"""G_POWER V9 Backtest - EMA + Dow - ใช้ชื่อไฟล์มาตรฐาน
รัน: python backtest_G_POWER.py --days 30
- import จาก strategy_G_POWER (ชื่อมาตรฐาน) ไม่ใช่ V9
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
            if all_rows:
                since = all_rows[-1][0] + 1
        except:
            all_rows = []
    while len(all_rows) < need:
        ohlcv = ex.fetch_ohlcv(SYMBOLS[symbol], "15m", limit=limit, since=since)
        if not ohlcv:
            break
        if all_rows and ohlcv[0][0] <= all_rows[-1][0]:
            ohlcv = [r for r in ohlcv if r[0] > all_rows[-1][0]]
            if not ohlcv:
                break
        all_rows.extend(ohlcv)
        since = all_rows[-1][0] + 1
        if len(ohlcv) < limit:
            break
    all_rows = all_rows[-need:]
    cache.write_text(json.dumps(all_rows))
    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms")
    return df

def resample_1h(df_15m):
    df = df_15m.copy()
    df = df.set_index("time")
    df_1h = df.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    return df_1h

def run_bt(symbol, days=30, capital=40.0):
    st = Strategy_G_Power(symbol)
    c = st.config
    df15 = fetch_klines(symbol, days)
    df15 = st.add_indicators(df15)
    df1h = resample_1h(df15)
    df1h = st.add_indicators(df1h)
    bal = capital
    trades = []
    positions = []
    wave_counts = {}
    last_pullback_key = {}
    df1h_times = list(df1h["time"])
    for i in range(2, len(df15)):
        curr = df15.iloc[i]
        price = float(curr["close"])
        h1_idx = -1
        for j, t in enumerate(df1h_times):
            if t <= curr["time"]:
                h1_idx = j
            else:
                break
        if h1_idx < 5:
            continue
        df1h_up_to = df1h.iloc[:h1_idx+1]
        swings = st.detect_swings(df1h_up_to)
        wave_info = st.count_waves(swings)
        wave = wave_info["current_wave"]
        trend = wave_info["trend"]
        cycle_id = wave_info["cycle_id"]
        wave1_len = wave_info["wave1_len"]
        waveA_len = wave_info["waveA_len"]
        h1_row = df1h.iloc[h1_idx]
        ema36_1h = float(h1_row["ema_slow"])
        ema_fast_1h = float(h1_row["ema_fast"])
        adx_1h = float(h1_row["adx"])
        di_plus_1h = float(h1_row["di_plus"])
        di_minus_1h = float(h1_row["di_minus"])
        new_positions = []
        for pos in positions:
            hit_sl = (price <= pos["sl"] if pos["side"] == "LONG" else price >= pos["sl"])
            hit_tp = (price >= pos["tp"] if pos["side"] == "LONG" else price <= pos["tp"])
            if pos["side"] == "LONG" and price > pos["entry"]:
                tsl = max(pos["sl"], ema36_1h * 0.999)
                if price >= pos["entry"] + (pos["tp"] - pos["entry"]) * 0.5:
                    tsl = max(tsl, pos["entry"])
                pos["sl"] = tsl
            elif pos["side"] == "SHORT" and price < pos["entry"]:
                tsl = min(pos["sl"], ema36_1h * 1.001)
                if price <= pos["entry"] - (pos["entry"] - pos["tp"]) * 0.5:
                    tsl = min(tsl, pos["entry"])
                pos["sl"] = tsl
            exit_reason = None
            if hit_sl:
                exit_reason = "SL"
            elif hit_tp:
                exit_reason = "TP"
            if exit_reason:
                pnl_pct = (price - pos["entry"]) / pos["entry"] if pos["side"] == "LONG" else (pos["entry"] - price) / pos["entry"]
                risk_amt = bal * 0.02
                sl_pct = abs(pos["entry"] - pos["sl_orig"]) / pos["entry"] if pos["sl_orig"] != pos["entry"] else c["sl_pct_max"]
                sl_pct = max(sl_pct, 0.001)
                pnl = risk_amt * (pnl_pct / sl_pct)
                bal += pnl
                trades.append({"symbol": symbol, "side": pos["side"], "wave": pos["wave"], "entry": round(pos["entry"], 2), "exit": round(price, 2), "exit_reason": exit_reason, "pnl_pct": round(pnl_pct*100, 2), "pnl_usd": round(pnl, 2), "bal": round(bal, 2), "time": str(curr["time"])})
            else:
                new_positions.append(pos)
        positions = new_positions
        if wave is None or trend == "UNKNOWN":
            continue
        if adx_1h < c["adx_min"]:
            continue
        key = (cycle_id, wave)
        cnt = wave_counts.get(key, 0)
        quota = st.WAVE_QUOTA.get(wave, 1)
        if cnt >= quota:
            continue
        side = None
        if trend == "UP":
            if wave in ("1", "3", "5", "B"):
                side = "LONG"
            elif wave in ("2", "4", "A", "C"):
                side = "SHORT"
        else:
            if wave in ("1", "3", "5", "B"):
                side = "SHORT"
            elif wave in ("2", "4", "A", "C"):
                side = "LONG"
        if side is None:
            continue
        low15 = float(curr["low"])
        high15 = float(curr["high"])
        touched = st.is_touch_ema36(low15, high15, ema36_1h)
        if not touched:
            continue
        hl_key = round(ema36_1h, 2)
        if last_pullback_key.get(key) == hl_key:
            continue
        pat = st.check_pattern_15m(df15, i)
        if pat is None:
            continue
        if side == "LONG" and pat not in ("PIN_BULL", "ENG_BULL"):
            continue
        if side == "SHORT" and pat not in ("PIN_BEAR", "ENG_BEAR"):
            continue
        vol = float(curr["volume"])
        vol_avg = float(curr["vol_avg"]) if not pd.isna(curr["vol_avg"]) else vol
        if vol < vol_avg * 0.7:
            continue
        if side == "LONG" and di_plus_1h < c["di_min"]:
            continue
        if side == "SHORT" and di_minus_1h < c["di_min"]:
            continue
        if side == "LONG" and ema_fast_1h < ema36_1h:
            if wave != "B":
                continue
        if side == "SHORT" and ema_fast_1h > ema36_1h:
            if wave != "B":
                continue
        hl_price = float(curr["low"]) if side == "LONG" else float(curr["high"])
        sl = st.get_sl_by_structure(side, price, hl_price)
        tp = st.get_tp_by_wave(wave, side, price, wave1_len, waveA_len)
        risk = abs(price - sl)
        reward = abs(tp - price)
        if reward < risk * 0.9:
            continue
        positions.append({"side": side, "wave": wave, "entry": price, "sl": sl, "tp": tp, "sl_orig": sl, "entry_idx": i})
        wave_counts[key] = cnt + 1
        last_pullback_key[key] = hl_key
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    total_pnl = sum(t["pnl_usd"] for t in trades)
    winrate = len(wins) / len(trades) * 100 if trades else 0
    avg_win = sum(t["pnl_usd"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0
    return {"symbol": symbol, "days": days, "capital_start": capital, "capital_end": round(bal, 2), "total_pnl": round(total_pnl, 2), "trades": len(trades), "wins": len(wins), "losses": len(losses), "winrate_pct": round(winrate, 1), "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2), "profit_factor": round(abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 0, 2), "config": {"ema": "12/36", "adx_min": c["adx_min"], "di_min": c["di_min"]}, "trade_list": trades}

if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 30
    out = {}
    for sym in ["btc", "gold"]:
        print(f"BT V9 {sym} {days} วัน...")
        out[sym] = run_bt(sym, days)
        r = out[sym]
        print(f"  {sym}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} ทุน ${r['capital_start']} -> ${r['capital_end']} PF {r['profit_factor']}")
    (DATA_DIR / "bt_results_V9.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"บันทึกแล้วที่ {DATA_DIR}/bt_results_V9.json")
