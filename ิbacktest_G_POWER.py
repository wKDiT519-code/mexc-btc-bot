"""G_POWER Backtest - ใช้ Disk /data เก็บแท่งเทียน + ผล BT ไม่หายตอน Deploy
รันใน Render Shell: python backtest_G_POWER.py
หรือรันในเครื่อง: python backtest_G_POWER.py --days 30
"""
import ccxt, pandas as pd, json, sys
from pathlib import Path
from datetime import datetime
from strategy_G_POWER import Strategy_G_Power

DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")
DATA_DIR.mkdir(parents=True, exist_ok=True)
SYMBOLS = {"btc": "BTC/USDT:USDT", "gold": "PAXG/USDT:USDT"}

def fetch_klines(symbol, days=30):
    # ดึงแท่ง 15m จาก MEXC Perp ตัวเดียวกับที่เทรดจริง + Cache ลง Disk
    cache = DATA_DIR / f"klines_{symbol}_15m.json"
    ex = ccxt.mexc({"enableRateLimit": True})
    limit = 1000
    need = days * 96  # 15m วันละ 96 แท่ง
    all_rows = []
    since = None
    # ถ้ามี Cache เก่า โหลดมาก่อน แล้วดึงต่อจากแท่งสุดท้าย (ประหยัด API)
    if cache.exists():
        try:
            all_rows = json.loads(cache.read_text())
            if all_rows: since = all_rows[-1][0] + 1
        except: all_rows = []
    while len(all_rows) < need:
        ohlcv = ex.fetch_ohlcv(SYMBOLS[symbol], "15m", limit=limit, since=since)
        if not ohlcv: break
        # กันวนลูปซ้ำแท่งเดิม
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
    pos = None  # {side, entry, sl, tp, entry_idx}
    for i in range(2, len(df)):
        curr = df.iloc[i]; prev = df.iloc[i-1]
        price = float(curr["close"])
        # --- ถืออยู่: เช็คออก ---
        if pos:
            # SL/TP
            hit_sl = (price <= pos["sl"] if pos["side"]=="LONG" else price >= pos["sl"])
            hit_tp = (price >= pos["tp"] if pos["side"]=="LONG" else price <= pos["tp"])
            ex = st.check_exit_trend_change(curr, prev, pos["side"])
            # Trailing BE/Lock จาก strategy
            tsl = st.get_trailing_sl(pos["entry"], price, float(curr["cdc_stop"]), pos["side"])
            if pos["side"]=="LONG": pos["sl"] = max(pos["sl"], tsl) if price > pos["entry"] else pos["sl"]
            else: pos["sl"] = min(pos["sl"], tsl) if price < pos["entry"] else pos["sl"]
            exit_reason = None
            if hit_sl: exit_reason = "SL"
            elif hit_tp: exit_reason = "TP"
            elif ex["tp"]: exit_reason = "TREND:" + ",".join(ex["reasons"])
            if exit_reason:
                pnl_pct = (price-pos["entry"])/pos["entry"] if pos["side"]=="LONG" else (pos["entry"]-price)/pos["entry"]
                # Paper: เสี่ยง 2% ของทุน * Leverage 3 = Position ~ 2.4x ทุน (ตามบอทจริง)
                size = bal * 0.02 * 3 / 0.02  # เทียบเท่า risk 2% ต่อไม้แบบง่าย: ใช้ fixed risk
                pnl = bal * 0.02 * (pnl_pct / c["sl_pct"]) if pnl_pct!=0 else 0
                # คิดแบบ Risk:Reward ตรงๆ: กำไร/ขาดทุน เทียบกับ SL
                pnl = bal * 0.02 * (pnl_pct / c["sl_pct"])
                bal += pnl
                trades.append({"symbol": symbol, "side": pos["side"], "entry": pos["entry"], "exit": price, "exit_reason": exit_reason, "pnl_pct": round(pnl_pct*100,2), "pnl_usd": round(pnl,2), "bal": round(bal,2), "time": str(curr["time"])})
                pos = None
        # --- ว่าง: เช็คเข้า Pullback ---
        if not pos:
            trend = st.check_trend(curr, prev)
            side = "LONG" if trend["long"] else "SHORT" if trend["short"] else None
            if side:
                sl = price*(1-c["sl_pct"]) if side=="LONG" else price*(1+c["sl_pct"])
                tp = price*(1+c["tp_pct"]) if side=="LONG" else price*(1-c["tp_pct"])
                pos = {"side": side, "entry": price, "sl": sl, "tp": tp}
    wins = [t for t in trades if t["pnl_usd"]>0]
    losses = [t for t in trades if t["pnl_usd"]<=0]
    total_pnl = sum(t["pnl_usd"] for t in trades)
    winrate = len(wins)/len(trades)*100 if trades else 0
    avg_win = sum(t["pnl_usd"] for t in wins)/len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses)/len(losses) if losses else 0
    return {"symbol": symbol, "days": days, "capital_start": capital, "capital_end": round(bal,2), "total_pnl": round(total_pnl,2), "trades": len(trades), "wins": len(wins), "losses": len(losses), "winrate_pct": round(winrate,1), "avg_win": round(avg_win,2), "avg_loss": round(avg_loss,2), "profit_factor": round(abs(sum(t["pnl_usd"] for t in wins)/sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses)!=0 else 0,2), "config": {"ema": f"{c['ema_fast']}/{c['ema_slow']}/{c['ema_trend']}", "adx_min": c["adx_min"], "retest_pct": c["retest_pct"], "max_ext": c["max_extension_pct"]}, "trade_list": trades}

if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days")+1]) if "--days" in sys.argv else 30
    out = {}
    for sym in ["btc","gold"]:
        print(f"BT {sym} {days} วัน...")
        out[sym] = run_bt(sym, days)
        r = out[sym]
        print(f"  {sym}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} ทุน ${r['capital_start']} -> ${r['capital_end']} PF {r['profit_factor']}")
    (DATA_DIR / "bt_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"บันทึกแล้วที่ {DATA_DIR}/bt_results.json (อยู่บน Disk ไม่หายตอน Deploy)")
