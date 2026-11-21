"""Backtest COMPARE Exit - FAST_FLIP vs ไม่ใช้ FAST_FLIP
Cross Window ล็อกที่ 5 แท่ง (ดีสุดจากรอบก่อน)
- โหมด A: ออกด้วย FAST_FLIP (แบบปัจจุบัน) + SL/TP
- โหมด B: ออกด้วย SL/TP อย่างเดียว ไม่สน FAST_FLIP
รันทีเดียวรู้เลยว่า FAST_FLIP มันตัดกำไรทิ้งไหม
วิธีอัป: เปลี่ยนชื่อเป็น backtest_G_POWER.py, import เป็น from strategy_G_POWER import Strategy_G_Power
รัน: python backtest_G_POWER.py --days 30
"""
import ccxt, pandas as pd, json, sys
from pathlib import Path
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

def run_bt(symbol, days, capital, cross_window, use_fast_flip):
    st = Strategy_G_Power(symbol)
    st.config["cross_window"] = cross_window
    c = st.config
    df = fetch_klines(symbol, days)
    df = st.add_indicators(df)
    bal = capital
    trades = []
    pos = None
    flip_count = 0
    for i in range(2, len(df)):
        curr = df.iloc[i]
        price = float(curr["close"])
        if pos:
            hit_sl = (price <= pos["sl"] if pos["side"]=="LONG" else price >= pos["sl"])
            hit_tp = (price >= pos["tp"] if pos["side"]=="LONG" else price <= pos["tp"])
            st.update_trailing_sl(pos, price, float(curr["ema_slow"]))
            ex = st.check_exit(df, i, pos)
            exit_reason = None
            if hit_sl: exit_reason = "SL"
            elif hit_tp: exit_reason = "TP"
            elif ex == "FAST_FLIP":
                if use_fast_flip:
                    exit_reason = "FAST_FLIP"
                    flip_count += 1
                else:
                    exit_reason = None  # โหมด B: ไม่สน FAST_FLIP ถือต่อ
            elif ex:
                exit_reason = ex
            if exit_reason:
                pnl_pct = (price-pos["entry"])/pos["entry"] if pos["side"]=="LONG" else (pos["entry"]-price)/pos["entry"]
                pnl = bal * 0.02 * (pnl_pct / c["sl_pct"]) if pnl_pct!=0 else 0
                bal += pnl
                trades.append({"symbol": symbol, "side": pos["side"], "entry": pos["entry"], "exit": price, "exit_reason": exit_reason, "pnl_pct": round(pnl_pct*100,2), "pnl_usd": round(pnl,2), "bal": round(bal,2), "time": str(curr["time"])})
                pos = None
        if not pos:
            side, reason = st.check_entry(df, i)
            if side:
                sl, tp, sl_pct = st.initial_sl_tp(price, side, slow=float(curr["ema_slow"]))
                pos = {"side": side, "entry": price, "sl": sl, "tp": tp, "sl_pct_init": sl_pct, "highest": price, "lowest": price}
    wins = [t for t in trades if t["pnl_usd"]>0]
    losses = [t for t in trades if t["pnl_usd"]<=0]
    total_pnl = sum(t["pnl_usd"] for t in trades)
    winrate = len(wins)/len(trades)*100 if trades else 0
    pf = abs(sum(t["pnl_usd"] for t in wins)/sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses)!=0 else 0
    flip_trades = [t for t in trades if t["exit_reason"]=="FAST_FLIP"]
    flip_pnl = sum(t["pnl_usd"] for t in flip_trades)
    return {"mode": "WITH_FLIP" if use_fast_flip else "NO_FLIP", "symbol": symbol, "trades": len(trades), "wins": len(wins), "winrate_pct": round(winrate,1), "total_pnl": round(total_pnl,2), "capital_end": round(bal,2), "profit_factor": round(pf,2), "flip_trades": len(flip_trades), "flip_pnl": round(flip_pnl,2), "trade_list": trades}

if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days")+1]) if "--days" in sys.argv else 30
    print(f"COMPARE Exit FAST_FLIP vs NO_FLIP - Cross 5 แท่ง - {days} วัน")
    for use_flip, label in [(True, "A: มี FAST_FLIP (ปัจจุบัน)"), (False, "B: ไม่มี FAST_FLIP (ถือจน SL/TP)")]:
        print(f"\n=== {label} ===")
        for sym in ["btc", "gold"]:
            r = run_bt(sym, days, 40.0, 5, use_flip)
            print(f"  {sym.upper()}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} PF {r['profit_factor']} | ออกด้วย FLIP {r['flip_trades']} ไม้ PnL ${r['flip_pnl']:+.2f}")
    print("\nเสร็จแล้ว - ดูว่า FLIP มันช่วยหรือมันตัดกำไรทิ้ง")
