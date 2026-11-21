"""G_POWER Backtest V6.8 HTF 1h + 15m - ใช้ Disk /data เก็บแท่งเทียน + ผล BT ไม่หายตอน Deploy
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

def fetch_klines(symbol, days=30, timeframe="15m"):
    # ดึงแท่ง 15m จาก MEXC Perp ตัวเดียวกับที่เทรดจริง + Cache ลง Disk
    cache = DATA_DIR / f"klines_{symbol}_{timeframe}.json"
    ex = ccxt.mexc({"enableRateLimit": True})
    limit = 1000
    need = days * 96 if timeframe=="15m" else days * 24  # 15m วันละ 96 / 1h วันละ 24
    all_rows = []
    since = None
    # ถ้ามี Cache เก่า โหลดมาก่อน แล้วดึงต่อจากแท่งสุดท้าย (ประหยัด API)
    if cache.exists():
        try:
            all_rows = json.loads(cache.read_text())
            if all_rows: since = all_rows[-1][0] + 1
        except: all_rows = []
    while len(all_rows) < need:
        ohlcv = ex.fetch_ohlcv(SYMBOLS[symbol], timeframe, limit=limit, since=since)
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

def run_bt(symbol, days=30, capital=40.0, ema_fast=None, ema_slow=None):
    try:
        st = Strategy_G_Power(symbol)
    except TypeError:
        # strategy บน Render ยังเป็นตัวเก่า ( __init__(self) ไม่มี symbol_key )
        # สร้างแบบไม่มี arg แล้วตั้ง config ตาม symbol เอง
        st = Strategy_G_Power()
        st.symbol_key = symbol
        if symbol == "gold":
            st.config = {"ema_fast": 21, "ema_slow": 55, "ema_trend": 100, "ema50": 50, "ema100": 100, "ema200": 200, "smc_min_score": 3, "adx_min": 12, "adx_sideway": 12, "adx_turbo": 26, "di_min": 10, "di_turbo": 20, "sl_pct": 0.028, "tp_pct": 0.12, "cdc_atr_fast": 10, "cdc_mult_fast": 1.0, "cdc_atr_slow": 20, "cdc_mult_slow": 2.5, "sideway_pct": 1.2, "retest_pct": 0.006, "max_extension_pct": 2.0, "be_trigger": 0.008, "lock_trigger": 0.015, "lock_pct": 0.004}
        else:
            st.config = {"ema_fast": 15, "ema_slow": 40, "ema_trend": 80, "ema50": 50, "ema100": 100, "ema200": 200, "smc_min_score": 3, "adx_min": 15, "adx_sideway": 15, "adx_turbo": 30, "di_min": 12, "di_turbo": 22, "sl_pct": 0.034, "tp_pct": 0.18, "cdc_atr_fast": 7, "cdc_mult_fast": 0.8, "cdc_atr_slow": 14, "cdc_mult_slow": 2.0, "sideway_pct": 1.5, "retest_pct": 0.009, "max_extension_pct": 3.0, "be_trigger": 0.01, "lock_trigger": 0.02, "lock_pct": 0.005}
    c = st.config
    if ema_fast is not None: c['ema_fast']=ema_fast
    if ema_slow is not None: c['ema_slow']=ema_slow
    df = fetch_klines(symbol, days, "15m")
    df = st.add_indicators(df)
    # V6.8 HTF: ดึง 1h มาหาเทรนหลัก - แท่ง 15m แต่ละแท่งใช้ 1h แท่งล่าสุดที่ปิดไปแล้ว
    try:
        df_1h = fetch_klines(symbol, days, "1h")
        df_1h["ema_trend_1h"] = df_1h["close"].ewm(span=int(c["ema_trend"]), adjust=False).mean()
        _times_1h = df_1h["ts"].values; _trend_1h = df_1h["ema_trend_1h"].values; _close_1h = df_1h["close"].values
        import bisect
        def _htf_at(ts):
            j = bisect.bisect_right(_times_1h, ts) - 1
            if j < 0: return None
            return 'long' if float(_close_1h[j]) > float(_trend_1h[j]) else 'short'
    except Exception as _e:
        print(f"HTF 1h fail {symbol}: {_e}"); _htf_at = lambda ts: None
    # V7.5: 4h เทรนใหญ่สุด - LONG ต้อง 4h ขึ้น / SHORT ต้อง 4h ลง
    try:
        df_4h = fetch_klines(symbol, days, "4h")
        df_4h["ema_trend_4h"] = df_4h["close"].ewm(span=int(c["ema_trend"]), adjust=False).mean()
        _times_4h = df_4h["ts"].values; _trend_4h = df_4h["ema_trend_4h"].values; _close_4h = df_4h["close"].values
        import bisect as _bis4
        def _htf4h_at(ts):
            j = _bis4.bisect_right(_times_4h, ts) - 1
            if j < 0: return None
            return 'long' if float(_close_4h[j]) > float(_trend_4h[j]) else 'short'
    except Exception as _e:
        print(f"HTF 4h fail {symbol}: {_e}"); _htf4h_at = lambda ts: None
    # V6.9: แพทเทิร์น 1h - คำนวณจากแท่ง 1h ที่ปิดแล้ว 2 แท่งล่าสุด
    try:
        _pat_map = {}
        for _j in range(1, len(df_1h)):
            _p = df_1h.iloc[_j-1]; _c = df_1h.iloc[_j]
            _pat_map[int(_c["ts"])] = (st.check_pattern_1h(_p, _c, True), st.check_pattern_1h(_p, _c, False))
        import bisect as _bis
        _ts1h_sorted = sorted(_pat_map.keys())
        def _htf_pat_at(ts):
            # V7.0 WINDOW: แพทเทิร์น 1h มีอายุ 4 ชม.
            _k = _bis.bisect_right(_ts1h_sorted, ts) - 1
            if _k < 0: return (None, None)
            _pl=_ps=False
            for _j in range(max(0,_k-3), _k+1):  # V7.3: แพทเทิร์นอายุ 4 ชม.
                _a,_b=_pat_map[_ts1h_sorted[_j]]; _pl=_pl or _a; _ps=_ps or _b
            return (_pl, _ps)
    except Exception as _e:
        print(f"1h pattern fail: {_e}"); _htf_pat_at = lambda ts: (None, None)
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
            smc = None  # V7.1: SMC ไม่กรองตอนเข้า
            # รองรับทั้ง strategy ใหม่ (รับ smc) และเก่า (ไม่รับ smc) - ถ้าเก่าจะได้ไม่พัง
            try:
                _pl,_ps = _htf_pat_at(int(curr["ts"]))
                _win = df.iloc[max(0,i-5):i+1]  # V7.3: แตะ Trend ใน 1.5 ชม.ล่าสุด
                _touch_l = bool((_win["low"] <= _win["ema_trend"]).any())
                _touch_s = bool((_win["high"] >= _win["ema_trend"]).any())
                trend = st.check_trend(curr, prev, smc=smc, htf_trend=_htf_at(int(curr["ts"])), htf_pattern_long=_pl, htf_pattern_short=_ps, touch_long=_touch_l, touch_short=_touch_s, htf4h_trend=_htf4h_at(int(curr["ts"])))
            except TypeError:
                try: trend = st.check_trend(curr, prev, smc=smc)
                except TypeError: trend = st.check_trend(curr, prev)
            # V6.8 live ต้องผ่าน momentum ด้วย - BT ต้องเช็คเหมือนกันไม่งั้นไม้เกินจริง
            pass  # V7.1: momentum = ADX+DI อยู่ใน check_trend แล้ว ไม่เช็คซ้ำ
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

def send_tele_bt(msg):
    import os, requests
    tok=os.getenv("TELEGRAM_BOT_TOKEN",""); chat=os.getenv("TELEGRAM_CHAT_ID","")
    if not tok or not chat: print("ไม่มี TELEGRAM env เลยส่ง Telegram ไม่ได้ ดูผลใน Shell แทน"); return
    try: requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": msg}, timeout=15)
    except Exception as e: print("send tele err", e)

def format_bt_msg(out):
    lines=["📊 BT V7.5 4H FILTER 1H Pattern + 15m EMA Fast/Slow (MEXC Perp)"]
    for sym in ["btc","gold"]:
        r=out[sym]
        lines.append(f"\n{'BTC' if sym=='btc' else 'GOLD'} {r['days']} วัน: {r['trades']} ไม้ Win {r['winrate_pct']}%")
        lines.append(f"PnL ${r['total_pnl']:+.2f} ทุน ${r['capital_start']} -> ${r['capital_end']} PF {r['profit_factor']}")
        lines.append(f"Avg Win ${r['avg_win']:+.2f} / Avg Loss ${r['avg_loss']:+.2f} | EMA {r['config']['ema']} Retest {r['config']['retest_pct']*100:.1f}% MaxExt {r['config']['max_ext']}%")
        # 5 ไม้ล่าสุด
        for tr in r['trade_list'][-5:]:
            lines.append(f"  {tr['side']} เข้า {tr['entry']:.1f} ออก {tr['exit']:.1f} {tr['exit_reason']} PnL ${tr['pnl_usd']:+.2f}")
    lines.append("\nดูรายละเอียดทุกไม้ใน /data/bt_results.json (บน Disk)")
    return "\n".join(lines)

if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days")+1]) if "--days" in sys.argv else 30
    combos = {"btc": [(15,40),(14,26),(12,36)], "gold": [(12,36),(14,26),(21,55),(12,55)]}
    out = {}
    print(f"=== BT เทียบ Fast/Slow {days} วัน รันทีเดียวรู้เลย ===")
    for sym in ["btc","gold"]:
        out[sym] = {}
        for (ef, es) in combos[sym]:
            print(f"BT {sym} EMA {ef}/{es} {days} วัน...")
            r = run_bt(sym, days, ema_fast=ef, ema_slow=es)
            out[sym][f"{ef}/{es}"] = r
            print(f"  {sym} EMA {ef}/{es}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} PF {r['profit_factor']} AvgWin ${r['avg_win']:+.2f} AvgLoss ${r['avg_loss']:+.2f}")
    (DATA_DIR / "bt_compare.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    # สรุปหาคู่ดีสุดตาม Win Rate (ต้องมีไม้ >=5 ถึงนับ)
    lines=["📊 BT เทียบ Fast/Slow (รันทีเดียว)"]
    for sym in ["btc","gold"]:
        lines.append(f"\n{'BTC' if sym=='btc' else 'GOLD'} {days} วัน:")
        ranked=sorted(out[sym].items(), key=lambda kv: kv[1]['winrate_pct'] if kv[1]['trades']>=3 else -1, reverse=True)
        for k,r in ranked:
            flag=" ⭐ ดีสุด" if r is ranked[0][1] else ""
            lines.append(f"  EMA {k}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} PF {r['profit_factor']}{flag}")
    msg="\n".join(lines)
    print(msg)
    print(f"บันทึกแล้วที่ {DATA_DIR}/bt_compare.json")
    send_tele_bt(msg)
