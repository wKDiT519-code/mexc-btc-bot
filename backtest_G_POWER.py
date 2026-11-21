"""Backtest V8.1 - จบแท่ง ตรวจทันที ไม่ใช้ 10 แท่ง
รัน: python backtest_G_POWER_V81.py --days 30
"""
import ccxt, pandas as pd, json, sys
from pathlib import Path
from datetime import datetime
from strategy_G_POWER import Strategy_G_Power

DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")
DATA_DIR.mkdir(parents=True, exist_ok=True)
SYMBOLS = {"btc": "BTC/USDT:USDT", "gold": "PAXG/USDT:USDT"}

def fetch_klines(symbol, days=30):
    cache = DATA_DIR / f"klines_{symbol}_15m.json"
    ex = ccxt.mexc({"enableRateLimit": True})
    limit = 1000
    need = days * 96
    all_rows = []
    since = None
    if cache.exists():
        try:
            all_rows = json.loads(cache.read_text())
            if all_rows: since = all_rows[-1][0] + 1
        except: all_rows = []
    while len(all_rows) < need:
        ohlcv = ex.fetch_ohlcv(SYMBOLS[symbol], "15m", limit=limit, since=since)
        if not ohlcv: break
        if all_rows and ohlcv[0][0] <= all_rows[-1][0]:
            ohlcv = [r for r in ohlcv if r[0] > all_rows[-1][0]]
            if not ohlcv: break
        all_rows.extend(ohlcv)
        since = all_rows[-1][0] + 1
        if len(ohlcv) < limit: break
    all_rows = all_rows[-need:]
    cache.write_text(json.dumps(all_rows))
    df = pd.DataFrame(all_rows, columns=["ts","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms")
    return df

def run_bt(symbol, days=30, capital=40.0):
    st = Strategy_G_Power(symbol)
    c = st.config
    df = fetch_klines(symbol, days)
    df = st.add_indicators(df)
    bal = capital
    trades = []
    pos = None
    for i in range(2, len(df)):
        curr = df.iloc[i]
        price = float(curr["close"])
        # ถืออยู่: เช็คออก - ใช้ค่า EMA แท่งปิดแล้ว
        if pos:
            hit_sl = (price <= pos["sl"] if pos["side"]=="LONG" else price >= pos["sl"])
            hit_tp = (price >= pos["tp"] if pos["side"]=="LONG" else price <= pos["tp"])
            # Trailing ตาม Slow / BE
            if pos["side"]=="LONG":
                # update trailing
                st.update_trailing_sl(pos, price, float(curr["ema_slow"]))
            else:
                st.update_trailing_sl(pos, price, float(curr["ema_slow"]))
            ex = st.check_exit(df, i, pos)
            exit_reason = None
            if hit_sl: exit_reason = "SL"
            elif hit_tp: exit_reason = "TP"
            elif ex: exit_reason = ex
            if exit_reason:
                pnl_pct = (price-pos["entry"])/pos["entry"] if pos["side"]=="LONG" else (pos["entry"]-price)/pos["entry"]
                pnl = bal * 0.02 * (pnl_pct / c["sl_pct"]) if pnl_pct!=0 else 0
                bal += pnl
                trades.append({"symbol": symbol, "side": pos["side"], "entry": pos["entry"], "exit": price, "exit_reason": exit_reason, "pnl_pct": round(pnl_pct*100,2), "pnl_usd": round(pnl,2), "bal": round(bal,2), "time": str(curr["time"])})
                pos = None
        # ว่าง: เช็คเข้า - จบแท่ง ตรวจทันที
        if not pos:
            side, reason = st.check_entry(df, i)
            if side:
                sl, tp, sl_pct = st.initial_sl_tp(price, side, slow=float(curr["ema_slow"]))
                pos = {"side": side, "entry": price, "sl": sl, "tp": tp, "sl_pct_init": sl_pct, "highest": price, "lowest": price}
    wins = [t for t in trades if t["pnl_usd"]>0]
    losses = [t for t in trades if t["pnl_usd"]<=0]
    total_pnl = sum(t["pnl_usd"] for t in trades)
    winrate = len(wins)/len(trades)*100 if trades else 0
    avg_win = sum(t["pnl_usd"] for t in wins)/len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses)/len(losses) if losses else 0
    return {"symbol": symbol, "days": days, "capital_start": capital, "capital_end": round(bal,2), "total_pnl": round(total_pnl,2), "trades": len(trades), "wins": len(wins), "losses": len(losses), "winrate_pct": round(winrate,1), "avg_win": round(avg_win,2), "avg_loss": round(avg_loss,2), "profit_factor": round(abs(sum(t["pnl_usd"] for t in wins)/sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses)!=0 else 0,2), "config": {"ema": f"{c['ema_fast']}/{c['ema_slow']}", "adx_min": c["adx_min"], "note": "V8.1 CrossNow - จบแท่งตรวจทันที"}, "trade_list": trades}

if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days")+1]) if "--days" in sys.argv else 30
    out = {}
    for sym in ["btc","gold"]:
        print(f"BT V8.1 {sym} {days} วัน...")
        out[sym] = run_bt(sym, days)
        r = out[sym]
        print(f"  {sym}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} ทุน ${r['capital_start']} -> ${r['capital_end']} PF {r['profit_factor']}")
    (DATA_DIR / "bt_results_V81.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"บันทึกแล้วที่ {DATA_DIR}/bt_results_V81.json")
