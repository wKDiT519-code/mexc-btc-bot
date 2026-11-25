"""G_POWER Backtest V9.3 - Dow Trend Lock + ห้ามซ้ำ Wave หลัง SL + SL โครงสร้าง
รันใน Render Shell: python backtest_G_POWER.py --days 30
ต้องใช้คู่กับ strategy_G_POWER.py V9.3
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
    limit = 1000; need = days * 96
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
        all_rows.extend(ohlcv); since = all_rows[-1][0] + 1
        if len(ohlcv) < limit: break
    all_rows = all_rows[-need:]
    cache.write_text(json.dumps(all_rows))
    df = pd.DataFrame(all_rows, columns=["ts","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms")
    return df

def resample_tf(df_15m, tf="1h"):
    df = df_15m.copy().set_index("time")
    rule = "1h" if tf=="1h" else "4h"
    ohlc = df.resample(rule).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()
    return ohlc

def run_bt(symbol, days=30, capital=40.0):
    st = Strategy_G_Power(symbol); c = st.config
    df = fetch_klines(symbol, days)
    df = st.add_indicators(df)
    # Precompute 1h / 4h swings -> wave per 1h bar
    df_1h = resample_tf(df, "1h"); df_1h = st.add_indicators(df_1h)
    df_4h = resample_tf(df, "4h"); df_4h = st.add_indicators(df_4h)
    swings_1h_full = st.detect_swings(df_1h)
    swings_4h_full = st.detect_swings(df_4h)
    # Wave ต่อ 1h bar: ค่อยๆ เพิ่ม Swing ไปเรื่อยๆ แล้วนับแบบ Sequential
    wave_by_1h_idx = {}
    for idx_1h in range(len(df_1h)):
        # Swing ที่ idx <= idx_1h
        swings_up_to = [s for s in swings_1h_full if s["idx"] <= idx_1h]
        if len(swings_up_to) >= 6:
            w = st.count_waves(swings_up_to)
            wave_by_1h_idx[idx_1h] = w
        else:
            wave_by_1h_idx[idx_1h] = {"current_wave": None, "cycle_id": 0, "wave1_len": 0, "waveA_len": 0, "trend": "UNKNOWN"}
    # Dow Trend 4h ต่อ 4h bar
    trend4h_by_idx = {}
    for idx_4h in range(len(df_4h)):
        swings_up_to = [s for s in swings_4h_full if s["idx"] <= idx_4h]
        trend4h_by_idx[idx_4h] = st.get_dow_trend_4h(swings_up_to) if len(swings_up_to)>=4 else "UNKNOWN"

    bal = capital; trades = []; pos = None
    wave_counts = {}  # (cycle_id, wave) -> จำนวนไม้ที่เปิดแล้วใน Wave นี้
    last_sl_key = None  # (cycle_id, wave, side) ที่เพิ่งโดน SL ไป -> ห้ามเปิดซ้ำ
    # Map 15m -> 1h / 4h index โดยใช้เวลา
    df_1h_times = list(df_1h["time"]); df_4h_times = list(df_4h["time"])
    for i in range(2, len(df)):
        curr = df.iloc[i]; prev = df.iloc[i-1]
        price = float(curr["close"]); t = curr["time"]
        # หา 1h / 4h bar ล่าสุดที่ปิดแล้ว (time <= t)
        idx_1h = max([k for k, tt in enumerate(df_1h_times) if tt <= t], default=0)
        idx_4h = max([k for k, tt in enumerate(df_4h_times) if tt <= t], default=0)
        winfo = wave_by_1h_idx.get(idx_1h, {"current_wave": None, "cycle_id": 0, "wave1_len": 0, "waveA_len": 0})
        wave = winfo.get("current_wave"); cycle_id = winfo.get("cycle_id", 0)
        dow4h = trend4h_by_idx.get(idx_4h, "UNKNOWN")
        atr_val = float(curr["atr"]) if "atr" in curr and pd.notna(curr["atr"]) else 0
        # --- ถืออยู่: เช็คออก ---
        if pos:
            hit_sl = (price <= pos["sl"] if pos["side"]=="LONG" else price >= pos["sl"])
            hit_tp = (price >= pos["tp"] if pos["side"]=="LONG" else price <= pos["tp"])
            exit_reason = None
            if hit_sl: exit_reason = "SL"
            elif hit_tp: exit_reason = "TP"
            if exit_reason:
                pnl_pct = (price-pos["entry"])/pos["entry"] if pos["side"]=="LONG" else (pos["entry"]-price)/pos["entry"]
                # Risk 2% ต่อไม้: PnL = bal * 0.02 * (pnl_pct / sl_pct)
                sl_pct_used = abs(pos["entry"]-pos["sl"])/pos["entry"] if pos["entry"]!=0 else c["sl_pct"]
                if sl_pct_used==0: sl_pct_used = c["sl_pct"]
                pnl = bal * 0.02 * (pnl_pct / sl_pct_used) if pnl_pct!=0 else 0
                bal += pnl
                trades.append({"symbol": symbol, "side": pos["side"], "wave": pos["wave"], "cycle": pos["cycle"], "dow4h": pos["dow4h"], "entry": pos["entry"], "exit": price, "exit_reason": exit_reason, "pnl_pct": round(pnl_pct*100,2), "pnl_usd": round(pnl,2), "bal": round(bal,2), "time": str(t), "sl": pos["sl"], "tp": pos["tp"]})
                if exit_reason=="SL":
                    last_sl_key = (pos["cycle"], pos["wave"], pos["side"])
                pos = None
        # --- ว่าง: เช็คเข้า ---
        if not pos:
            if wave is None: continue
            # V9.3 Rule 1: Dow Trend Lock 4h
            trend = st.check_trend(curr, prev, dow_trend_4h=dow4h)
            side = "LONG" if trend["long"] else "SHORT" if trend["short"] else None
            if not side: continue
            # V9.3 Rule 2: ห้ามเปิดซ้ำ Wave เดิมหลัง SL
            if last_sl_key == (cycle_id, wave, side):
                continue
            # Quota: Wave 1=3, 2=1, 3=3, 4=1, 5=3, A=1, B=3, C=1
            key = (cycle_id, wave)
            if wave_counts.get(key, 0) >= st.WAVE_QUOTA.get(wave, 1):
                continue
            # ต้องแตะ EMA36 + มี Pattern 15m
            ema36 = float(curr["ema_slow"])
            if not st.is_touch_ema36(float(curr["low"]), float(curr["high"]), ema36):
                continue
            pat = st.check_pattern_15m(df, i)
            if pat is None: continue
            # Pattern ต้องตรงทิศ: LONG ต้อง PIN_BULL/ENG_BULL, SHORT ต้อง PIN_BEAR/ENG_BEAR
            if side=="LONG" and pat not in ("PIN_BULL","ENG_BULL"): continue
            if side=="SHORT" and pat not in ("PIN_BEAR","ENG_BEAR"): continue
            # SL ตามโครงสร้าง (ใช้ Swing 1h ล่าสุด)
            swings_up_to = [s for s in swings_1h_full if s["idx"] <= idx_1h]
            sl = st.get_sl_by_structure(side, price, swings_up_to, atr_val)
            tp = st.get_tp_by_wave(wave, side, price, winfo.get("wave1_len",0), winfo.get("waveA_len",0))
            # กัน SL/TP ผิดทิศ
            if side=="LONG" and (sl>=price or tp<=price): continue
            if side=="SHORT" and (sl<=price or tp>=price): continue
            wave_counts[key] = wave_counts.get(key,0)+1
            pos = {"side": side, "wave": wave, "cycle": cycle_id, "dow4h": dow4h, "entry": price, "sl": sl, "tp": tp, "pattern": pat}
    wins = [t for t in trades if t["pnl_usd"]>0]; losses = [t for t in trades if t["pnl_usd"]<=0]
    total_pnl = sum(t["pnl_usd"] for t in trades)
    winrate = len(wins)/len(trades)*100 if trades else 0
    avg_win = sum(t["pnl_usd"] for t in wins)/len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses)/len(losses) if losses else 0
    return {"symbol": symbol, "days": days, "capital_start": capital, "capital_end": round(bal,2), "total_pnl": round(total_pnl,2), "trades": len(trades), "wins": len(wins), "losses": len(losses), "winrate_pct": round(winrate,1), "avg_win": round(avg_win,2), "avg_loss": round(avg_loss,2), "profit_factor": round(abs(sum(t["pnl_usd"] for t in wins)/sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses)!=0 else 0,2), "config": {"ema": f"{c['ema_fast']}/{c['ema_slow']}", "adx_min": c["adx_min"], "version": "V9.3 DOW-LOCK"}, "trade_list": trades}

def format_bt_msg(out):
    lines=["📊 BT V9.3 Dow Trend Lock (15m MEXC Perp)"]
    for sym in ["btc","gold"]:
        r=out[sym]
        lines.append(f"\n{'BTC' if sym=='btc' else 'GOLD'} {r['days']} วัน: {r['trades']} ไม้ Win {r['winrate_pct']}%")
        lines.append(f"PnL ${r['total_pnl']:+.2f} ทุน ${r['capital_start']} -> ${r['capital_end']} PF {r['profit_factor']}")
        lines.append(f"Avg Win ${r['avg_win']:+.2f} / Avg Loss ${r['avg_loss']:+.2f} | EMA {r['config']['ema']} ADX {r['config']['adx_min']}")
        for idx,tr in enumerate(r['trade_list'],1):
            lines.append(f"{idx:2d}. {tr['side']:5s} Wave {tr['wave']} เข้า {tr['entry']:.1f} -> ออก {tr['exit']:.1f} {tr['exit_reason']} PnL ${tr['pnl_usd']:+.2f} {tr['time']}")
    lines.append("\nดูรายละเอียดทุกไม้ใน /data/bt_results.json")
    return "\n".join(lines)

if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days")+1]) if "--days" in sys.argv else 30
    out = {}
    for sym in ["btc","gold"]:
        print(f"BT {sym} {days} วัน V9.3...")
        out[sym] = run_bt(sym, days)
        r = out[sym]
        print(f"  {sym}: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} ทุน ${r['capital_start']} -> ${r['capital_end']} PF {r['profit_factor']}")
    (DATA_DIR / "bt_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    msg=format_bt_msg(out)
    print(msg)
    print(f"บันทึกแล้วที่ {DATA_DIR}/bt_results.json")
    try:
        import os, requests
        tok=os.getenv("TELEGRAM_BOT_TOKEN",""); chat=os.getenv("TELEGRAM_CHAT_ID","")
        if tok and chat: requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": msg}, timeout=15)
    except Exception as e: print("send tele err", e)
