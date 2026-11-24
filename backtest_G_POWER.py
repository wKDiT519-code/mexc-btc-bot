"""G_POWER V9 Backtest - EMA + Dow
รัน: python backtest_G_POWER_V9.py --days 30
- ดึง 15m จาก MEXC Perp + Cache /data
- Resample 15m -> 1h สำหรับนับคลื่น Dow + แตะ EMA36
- เข้า 15m: แตะ EMA36 (1h) + Pin/Engulfing ปิดแท่ง + ADX/DI + โควต้า Wave
- โควต้า: W1=3, W2=1, W3=3, W4=1, W5=3, A=1, B=3, C=1
- TP วัดตามคลื่น, SL ตามโครงสร้าง
- 1 การย่อ = 1 ไม้ (กันเปิดซ้ำที่ HL เดิม) + นับโควต้าตาม Wave+Cycle
"""
import ccxt, pandas as pd, json, sys
from pathlib import Path
from datetime import datetime
from strategy_G_POWER_V9 import Strategy_G_Power

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
    # เตรียม Swing + Wave บน 1h ทั้งเส้นก่อน (สำหรับ backtest จะอัปเดตตามเวลา)
    bal = capital
    trades = []
    positions = []  # หลายไม้ได้ตามโควต้า Wave
    wave_counts = {}  # (cycle_id, wave) -> count
    last_pullback_key = {}  # (cycle_id, wave) -> hl_price กันเปิดซ้ำย่อเดิม
    # Map เวลา 1h -> index ใน df1h
    # สำหรับแต่ละแท่ง 15m หา 1h bar ล่าสุดที่ปิดแล้ว
    df1h_times = list(df1h["time"])
    for i in range(2, len(df15)):
        curr = df15.iloc[i]
        prev = df15.iloc[i-1]
        price = float(curr["close"])
        # หา 1h bar ล่าสุดที่ time <= curr time
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
        # --- เช็คออกทุกไม้ที่ถืออยู่ ---
        new_positions = []
        for pos in positions:
            hit_sl = (price <= pos["sl"] if pos["side"] == "LONG" else price >= pos["sl"])
            hit_tp = (price >= pos["tp"] if pos["side"] == "LONG" else price <= pos["tp"])
            # Trailing ตาม HL ใหม่: ถ้า LONG ให้ขยับ SL ขึ้นตาม EMA36 1h ถ้าราคาเหนือ entry
            if pos["side"] == "LONG" and price > pos["entry"]:
                # Trailing: SL = max(SL เดิม, EMA36 1h - 0.05% หรือ entry ถ้าถึง TP1)
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
            # Dow กลับตัวชัด: ถ้า LONG แล้วราคาปิดต่ำกว่า HL เดิม (SL) ก็คือ SL ไปแล้ว ไม่ต้องเช็คแยก
            if exit_reason:
                pnl_pct = (price - pos["entry"]) / pos["entry"] if pos["side"] == "LONG" else (pos["entry"] - price) / pos["entry"]
                # Risk 2% ต่อไม้
                risk_amt = bal * 0.02
                # PnL เทียบกับ SL: pnl = risk * (pnl_pct / sl_pct)
                sl_pct = abs(pos["entry"] - pos["sl_orig"]) / pos["entry"] if pos["sl_orig"] != pos["entry"] else c["sl_pct_max"]
                sl_pct = max(sl_pct, 0.001)
                pnl = risk_amt * (pnl_pct / sl_pct)
                bal += pnl
                trades.append({"symbol": symbol, "side": pos["side"], "wave": pos["wave"], "entry": round(pos["entry"], 2), "exit": round(price, 2), "exit_reason": exit_reason, "pnl_pct": round(pnl_pct*100, 2), "pnl_usd": round(pnl, 2), "bal": round(bal, 2), "time": str(curr["time"]), "ema36_touch": pos.get("ema36_touch", False)})
            else:
                new_positions.append(pos)
        positions = new_positions
        # --- เช็คเข้า ---
        if wave is None or trend == "UNKNOWN":
            continue
        # ADX / DI filter
        if adx_1h < c["adx_min"]:
            continue
        # Wave quota
        key = (cycle_id, wave)
        cnt = wave_counts.get(key, 0)
        quota = st.WAVE_QUOTA.get(wave, 1)
        if cnt >= quota:
            continue
        # ตัดสิน Side จาก Wave + Trend
        # UP trend: Wave 1,3,5,B = LONG, Wave 2,4,A,C = SHORT
        # DOWN trend: กลับด้าน
        side = None
        if trend == "UP":
            if wave in ("1", "3", "5", "B"):
                side = "LONG"
            elif wave in ("2", "4", "A", "C"):
                side = "SHORT"
        else:  # DOWN
            if wave in ("1", "3", "5", "B"):
                side = "SHORT"
            elif wave in ("2", "4", "A", "C"):
                side = "LONG"
        if side is None:
            continue
        # EMA trend filter: LONG ต้องราคาอยู่เหนือ EMA36 1h หรือแตะแล้วเด้ง (สำหรับ LONG Wave 1,3,5,B ราคาต้องไม่หลุด EMA36 ลงไปเยอะ)
        # SHORT ต้องราคาอยู่ใต้ EMA36 หรือแตะแล้วร่วง
        # สำหรับ V9 เงื่อนไขหลักคือ "แตะ EMA36" บน 1h
        low15 = float(curr["low"])
        high15 = float(curr["high"])
        touched = st.is_touch_ema36(low15, high15, ema36_1h)
        # ถ้าไม่แตะ EMA36 บน 1h ให้ข้าม - กันดอย
        if not touched:
            continue
        # กันเปิดซ้ำย่อเดิม: ถ้า HL ราคาเดิมกับไม้ก่อนหน้าใน Wave เดียวกัน ให้ข้าม
        hl_key = round(ema36_1h, 2)
        if last_pullback_key.get(key) == hl_key:
            continue
        # Pattern 15m ที่ปิดแท่งแล้ว
        pat = st.check_pattern_15m(df15, i)
        if pat is None:
            continue
        # Pattern ต้องตรงทิศ: LONG ต้อง PIN_BULL/ENG_BULL, SHORT ต้อง PIN_BEAR/ENG_BEAR
        if side == "LONG" and pat not in ("PIN_BULL", "ENG_BULL"):
            continue
        if side == "SHORT" and pat not in ("PIN_BEAR", "ENG_BEAR"):
            continue
        # Volume ยืนยัน: วอลุ่มแท่งเข้า > vol_avg * 0.8 (ไม่แห้งเกินไป)
        vol = float(curr["volume"])
        vol_avg = float(curr["vol_avg"]) if not pd.isna(curr["vol_avg"]) else vol
        if vol < vol_avg * 0.7:
            continue
        # DI ยืนยันทิศ
        if side == "LONG" and di_plus_1h < c["di_min"]:
            continue
        if side == "SHORT" and di_minus_1h < c["di_min"]:
            continue
        # EMA Fast/Slow ยืนยันทิศบน 1h
        if side == "LONG" and ema_fast_1h < ema36_1h:
            # ยกเว้น Wave B ที่เป็นเด้ง ABC อาจจะยังใต้ EMA ได้ - ให้ผ่านถ้า Wave B
            if wave != "B":
                continue
        if side == "SHORT" and ema_fast_1h > ema36_1h:
            if wave != "B":
                continue
        # คำนวณ SL/TP
        hl_price = float(curr["low"]) if side == "LONG" else float(curr["high"])
        sl = st.get_sl_by_structure(side, price, hl_price)
        tp = st.get_tp_by_wave(wave, side, price, wave1_len, waveA_len)
        # TP ต้องมากกว่า Risk อย่างน้อย 1:1
        risk = abs(price - sl)
        reward = abs(tp - price)
        if reward < risk * 0.9:
            continue
        positions.append({"side": side, "wave": wave, "entry": price, "sl": sl, "tp": tp, "sl_orig": sl, "ema36_touch": True, "entry_idx": i})
        wave_counts[key] = cnt + 1
        last_pullback_key[key] = hl_key
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    total_pnl = sum(t["pnl_usd"] for t in trades)
    winrate = len(wins) / len(trades) * 100 if trades else 0
    avg_win = sum(t["pnl_usd"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0
    return {"symbol": symbol, "days": days, "capital_start": capital, "capital_end": round(bal, 2), "total_pnl": round(total_pnl, 2), "trades": len(trades), "wins": len(wins), "losses": len(losses), "winrate_pct": round(winrate, 1), "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2), "profit_factor": round(abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 0, 2), "config": {"ema": "12/36", "adx_min": c["adx_min"], "di_min": c["di_min"]}, "trade_list": trades}

def format_bt_msg(out):
    lines = ["📊 BT V9 EMA+DOW (1h นับคลื่น / 15m เข้า / แตะ EMA36)"]
    for sym in ["btc", "gold"]:
        r = out[sym]
        lines.append(f"\n{'BTC' if sym == 'btc' else 'GOLD'} {r['days']} วัน: {r['trades']} ไม้ Win {r['winrate_pct']}%")
        lines.append(f"PnL ${r['total_pnl']:+.2f} ทุน ${r['capital_start']} -> ${r['capital_end']} PF {r['profit_factor']}")
        lines.append(f"Avg Win ${r['avg_win']:+.2f} / Avg Loss ${r['avg_loss']:+.2f} | EMA {r['config']['ema']} ADX>{r['config']['adx_min']} DI>{r['config']['di_min']}")
        for tr in r['trade_list'][-5:]:
            lines.append(f"  {tr['side']} W{tr['wave']} เข้า {tr['entry']:.1f} ออก {tr['exit']:.1f} {tr['exit_reason']} PnL ${tr['pnl_usd']:+.2f}")
    return "\n".join(lines)

if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 30
    out = {}
    for sym in ["btc", "gold"]:
        print(f"BT V9 {sym} {days} วัน...")
        out[sym] = run_bt(sym, days)
        r = out[sym]
        print(f"  {sym}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} ทุน ${r['capital_start']} -> ${r['capital_end']} PF {r['profit_factor']}")
    (DATA_DIR / "bt_results_V9.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(format_bt_msg(out))
    print(f"บันทึกแล้วที่ {DATA_DIR}/bt_results_V9.json")
