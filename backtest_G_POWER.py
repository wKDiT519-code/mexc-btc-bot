"""G_POWER Backtest V7.7 - SL ทอง = เส้น Slow / BTC Fixed 0.8% ล็อก 12/36
รัน: python backtest_G_POWER.py --days 30
- รันทีเดียว: BTC 12/36 (ล็อก) + ทอง 12/36,14/26,21/55,12/55 (SL Slow ทุกคู่)
- แถมวัดให้ว่า SL Slow ทองเฉลี่ยกี่ %
"""
import ccxt, pandas as pd, json, sys
from pathlib import Path
from strategy_G_POWER import Strategy_G_Power

DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")
DATA_DIR.mkdir(parents=True, exist_ok=True)
SYMBOLS = {"btc": "BTC/USDT:USDT", "gold": "PAXG/USDT:USDT"}

def fetch_klines(symbol, tf, days=30):
    cache = DATA_DIR / f"klines_{symbol}_{tf}.json"
    ex = ccxt.mexc({"enableRateLimit": True})
    per_day = 96 if tf == "15m" else 24
    need = days * per_day
    all_rows = []
    since = None
    if cache.exists():
        try:
            all_rows = json.loads(cache.read_text())
            if all_rows: since = all_rows[-1][0] + 1
        except: all_rows = []
    while len(all_rows) < need:
        ohlcv = ex.fetch_ohlcv(SYMBOLS[symbol], tf, limit=1000, since=since)
        if not ohlcv: break
        if all_rows and ohlcv[0][0] <= all_rows[-1][0]:
            ohlcv = [r for r in ohlcv if r[0] > all_rows[-1][0]]
            if not ohlcv: break
        all_rows.extend(ohlcv)
        since = all_rows[-1][0] + 1
        if len(ohlcv) < 1000: break
    all_rows = all_rows[-need:]
    cache.write_text(json.dumps(all_rows))
    df = pd.DataFrame(all_rows, columns=["ts","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms")
    return df

def run_bt(symbol, days=30, capital=40.0, ema_fast=None, ema_slow=None):
    st = Strategy_G_Power(symbol)
    if ema_fast is not None: st.config["ema_fast"] = ema_fast
    if ema_slow is not None: st.config["ema_slow"] = ema_slow
    c = st.config
    df = fetch_klines(symbol, "15m", days)
    df1h = fetch_klines(symbol, "1h", days)
    df = st.add_indicators(df, df1h)
    bal = capital
    trades = []
    sl_pcts = []
    pos = None
    for i in range(2, len(df)):
        price = float(df.iloc[i]["close"])
        slow = float(df.iloc[i]["ema_slow"])
        if pos:
            st.update_trailing_sl(pos, price, slow=slow)
            ex = st.check_exit(df, i, pos)
            if ex:
                pnl_pct = (price - pos["entry"]) / pos["entry"] if pos["side"] == "LONG" else (pos["entry"] - price) / pos["entry"]
                # PnL คิดตาม SL จริงของไม้นั้น (Dynamic สำหรับทอง)
                risk_pct = pos.get("sl_pct_init", c["sl_pct"])
                pnl = bal * 0.02 * (pnl_pct / risk_pct) if pnl_pct != 0 and risk_pct > 0 else 0
                bal += pnl
                trades.append({"symbol": symbol, "side": pos["side"], "entry": pos["entry"], "exit": price, "exit_reason": ex, "sl_pct_init": round(pos.get("sl_pct_init", 0)*100, 2), "pnl_pct": round(pnl_pct*100,2), "pnl_usd": round(pnl,2), "bal": round(bal,2), "time": str(df.iloc[i]["time"])})
                pos = None
        if not pos:
            side, reason = st.check_entry(df, i)
            if side:
                sl, tp, sl_pct_init = st.initial_sl_tp(price, side, slow=slow)
                sl_pcts.append(sl_pct_init)
                pos = {"side": side, "entry": price, "sl": sl, "tp": tp, "highest": price, "lowest": price, "be_done": False, "reason": reason, "sl_pct_init": sl_pct_init}
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    total_pnl = sum(t["pnl_usd"] for t in trades)
    winrate = len(wins)/len(trades)*100 if trades else 0
    avg_win = sum(t["pnl_usd"] for t in wins)/len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses)/len(losses) if losses else 0
    avg_sl_pct = sum(sl_pcts)/len(sl_pcts)*100 if sl_pcts else 0
    return {"symbol": symbol, "days": days, "capital_start": capital, "capital_end": round(bal,2), "total_pnl": round(total_pnl,2), "trades": len(trades), "wins": len(wins), "losses": len(losses), "winrate_pct": round(winrate,1), "avg_win": round(avg_win,2), "avg_loss": round(avg_loss,2), "avg_sl_pct": round(avg_sl_pct,2), "profit_factor": round(abs(sum(t["pnl_usd"] for t in wins)/sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses)!=0 else 0,2), "config": {"ema": f"{c['ema_fast']}/{c['ema_slow']}/{c['ema_trend']}", "sl_mode": c.get("sl_mode", "fixed")}, "trade_list": trades}

def send_tele_bt(msg):
    import os, requests
    tok = os.getenv("TELEGRAM_BOT_TOKEN",""); chat = os.getenv("TELEGRAM_CHAT_ID","")
    if not tok or not chat:
        print("ไม่มี TELEGRAM env เลยส่ง Telegram ไม่ได้ ดูผลใน Shell แทน"); return
    try: requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": msg}, timeout=15)
    except Exception as e: print("send tele err", e)

if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days")+1]) if "--days" in sys.argv else 30
    combos = {"btc": [(12,36)], "gold": [(12,36),(14,26),(21,55),(12,55)]}
    out = {}
    print(f"=== BT V7.7 SL ทอง = เส้น Slow {days} วัน ===")
    for sym in ["btc","gold"]:
        out[sym] = {}
        for (ef, es) in combos[sym]:
            print(f"BT {sym} EMA {ef}/{es} {days} วัน...")
            r = run_bt(sym, days, ema_fast=ef, ema_slow=es)
            out[sym][f"{ef}/{es}"] = r
            print(f"  {sym} EMA {ef}/{es}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} PF {r['profit_factor']} AvgSL {r['avg_sl_pct']}% AvgWin ${r['avg_win']:+.2f} AvgLoss ${r['avg_loss']:+.2f}")
    (DATA_DIR / "bt_compare.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    lines = ["📊 BT V7.7 SL ทอง = เส้น Slow"]
    for sym in ["btc","gold"]:
        lines.append(f"\n{'BTC (ล็อก 12/36)' if sym=='btc' else 'GOLD (SL Slow)'} {days} วัน:")
        ranked = sorted(out[sym].items(), key=lambda kv: kv[1]['total_pnl'], reverse=True)
        for k, r in ranked:
            flag = " ⭐ ดีสุด" if r is ranked[0][1] else ""
            lines.append(f"  EMA {k}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} PF {r['profit_factor']} AvgSL {r['avg_sl_pct']}%{flag}")
    msg = "\n".join(lines)
    print(msg)
    print(f"บันทึกแล้วที่ {DATA_DIR}/bt_compare.json")
    send_tele_bt(msg)
