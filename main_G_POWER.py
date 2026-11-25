"""G_POWER Main UNIVERSAL - Main ไม่ต้องแก้แล้ว เปลี่ยน Strategy อย่างเดียวจบ
หลักการ: Main เป็นแค่ "คนขับรถ" ไม่รู้เรื่องกลยุทธ์เลย
- ไม่ Hardcode EMA / ADX / DI / SL / TP / Wave / Quota ไว้ใน Main อีกต่อไป
- ทุกค่าอ่านจาก Strategy.config / Strategy.WAVE_QUOTA / Strategy.name
- ทุกการตัดสินใจเรียกผ่าน Strategy เท่านั้น: check_trend / check_pattern_15m / is_touch_ema36 / count_waves / detect_swings / get_dow_trend_4h / get_tp_by_wave / get_sl_by_structure
- ถ้า Strategy ตัวใหม่เพิ่ม Method ใหม่ Main จะใช้ทันที ถ้า Strategy เก่าไม่มี Method นั้น Main จะ Fallback เอง ไม่พัง
- เปลี่ยน Strategy V9.3 -> V9.4 -> V10 แค่ทับไฟล์ strategy_G_POWER.py แล้ว Deploy Main ไฟล์นี้ไม่ต้องแตะเลย
อัปโหลดเป็น main_G_POWER.py (ทับตัวเก่า V6.1)
"""
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from datetime import datetime, timedelta
import os, ccxt, pandas as pd, json, requests, importlib, traceback
from pathlib import Path

app = FastAPI(title="G_POWER UNIVERSAL")

# ===== Config ที่ไม่ใช่กลยุทธ์ (Main จัดการเอง) =====
CAPITAL = 40.0
RISK_PCT = 0.02
LEVERAGE = 3
SYMBOLS = {"btc": "BTC/USDT:USDT", "gold": "PAXG/USDT:USDT"}
DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRADES_FILE = DATA_DIR / "g_power_trades.json"
AUTO_STATE_FILE = DATA_DIR / "auto_state.json"
LAST_TRADE_TIME_FILE = DATA_DIR / "last_trade_time.json"

# ===== Load Strategy แบบ Dynamic - ไม่ Hardcode =====
def load_strategy(symbol_key):
    """โหลด Strategy ตาม symbol_key ทุกครั้งที่เรียก - เปลี่ยน Strategy แล้วไม่ต้องแก้ Main"""
    try:
        import strategy_G_POWER
        importlib.reload(strategy_G_POWER)
        StrategyCls = strategy_G_POWER.Strategy_G_Power
    except Exception as e:
        print(f"load_strategy import err {e}")
        raise
    try:
        st = StrategyCls(symbol_key)
    except TypeError:
        # Strategy เก่าที่ __init__ ไม่มี symbol_key
        st = StrategyCls()
        st.symbol_key = symbol_key
    return st

def get_strategy_name(symbol_key="btc"):
    try:
        st = load_strategy(symbol_key)
        return getattr(st, "name", "UNKNOWN")
    except:
        return "UNKNOWN"

# Cache Strategy ไว้ไม่ให้ reload บ่อยเกินไป (reload ทุกครั้งที่ /check จะช้า)
_STRAT_CACHE = {}
def get_strat(symbol_key):
    # ถ้ายังไม่มีใน Cache หรือ Strategy เปลี่ยนเวอร์ชั่น ให้โหลดใหม่
    # วิธีเช็ค: ถ้า Cache มีอยู่แล้วใช้ Cache ไปเลย Deploy ใหม่ Render จะ Restart เองอยู่แล้ว
    if symbol_key not in _STRAT_CACHE:
        _STRAT_CACHE[symbol_key] = load_strategy(symbol_key)
    return _STRAT_CACHE[symbol_key]

# ===== Helpers - Persistence =====
def atomic_save(path: Path, data):
    try:
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w') as f: json.dump(data, f, default=str, indent=2)
        tmp.replace(path)
    except Exception as e:
        print(f"atomic_save err {e}")
        try:
            with open(path, 'w') as f: json.dump(data, f, default=str, indent=2)
        except: pass

def load_trades():
    if TRADES_FILE.exists():
        try:
            with open(TRADES_FILE,'r') as f:
                d=json.load(f)
                return [t for t in d if not str(t.get('note','')).lower().startswith('sample')]
        except: return []
    return []
def save_trades(t): atomic_save(TRADES_FILE, t)
def get_auto_state():
    if AUTO_STATE_FILE.exists():
        try:
            with open(AUTO_STATE_FILE,'r') as f:
                d=json.load(f)
                if isinstance(d, bool): return {"btc":d,"gold":d}
                if not isinstance(d, dict): return {"btc":True,"gold":True}
                if "enabled" in d:
                    v=bool(d.get("enabled",False)); return {"btc":v,"gold":v}
                return {"btc": bool(d.get("btc",False)), "gold": bool(d.get("gold",False))}
        except: return {"btc":True,"gold":True}
    return {"btc":True,"gold":True}
def set_auto_state(k, en):
    s=get_auto_state()
    if k=='all':
        for kk in s: s[kk]=en
    else: s[k]=en
    atomic_save(AUTO_STATE_FILE, s); return s
def get_last_trade_times():
    if LAST_TRADE_TIME_FILE.exists():
        try: return json.load(open(LAST_TRADE_TIME_FILE))
        except: pass
    return {}
def set_last_trade_time(symbol_key):
    times=get_last_trade_times(); times[symbol_key]=datetime.now().isoformat(); atomic_save(LAST_TRADE_TIME_FILE, times)

# ===== Data =====
def get_data(symbol="BTC/USDT:USDT", timeframe="15m", limit=250):
    try:
        ex=ccxt.mexc({"options":{"defaultType":"swap"}})
        ohlcv=ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        if ohlcv and len(ohlcv)>50:
            df=pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['datetime']=pd.to_datetime(df['timestamp'], unit='ms')
            df['time']=df['datetime']
            return df
    except Exception as e:
        print(f"get_data err {e}")
    return None

def resample_tf(df_15m, tf="1h"):
    df = df_15m.copy().set_index("time")
    rule = "1h" if tf=="1h" else "4h"
    ohlc = df.resample(rule).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()
    return ohlc

def send_tele(msg, chat_id=None):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    chat=chat_id or os.environ.get("TELEGRAM_CHAT_ID","").strip() or os.environ.get("CHAT_ID","").strip()
    if not token or not chat: return {"ok":False}
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id":chat,"text":msg,"parse_mode":"HTML"}, timeout=10)
        return {"ok": r.status_code==200}
    except Exception as e:
        print(f"send_tele err {e}"); return {"ok":False}

def calc_position(symbol_key, entry, sl):
    """คำนวณขนาดไม้จาก Risk - SL มาจาก Strategy ไม่ใช่ Hardcode"""
    risk = CAPITAL * RISK_PCT
    sl_pct = abs(entry-sl)/entry if entry and sl and entry!=0 else 0.01
    if sl_pct==0: sl_pct=0.01
    pos = risk / sl_pct  # Position size (USDT)
    return {"risk": risk, "pos": pos, "margin": pos/LEVERAGE, "sl_pct": sl_pct}

# ===== Core: Execute 1 Symbol - ทุกการตัดสินใจถาม Strategy =====
def execute_symbol(symbol_key):
    """Main ไม่รู้กลยุทธ์เลย ถาม Strategy ทุกขั้นตอน"""
    symbol = SYMBOLS[symbol_key]
    st = get_strat(symbol_key)
    cfg = getattr(st, "config", {})
    strat_name = getattr(st, "name", "UNKNOWN")
    # 1. ดึงข้อมูล 15m
    df = get_data(symbol, "15m", limit=250)
    if df is None or len(df)<50:
        return {"ok": False, "error": "no data", "strategy": strat_name}
    # 2. Indicators จาก Strategy (Main ไม่คำนวณ EMA/ADX เอง)
    try: df = st.add_indicators(df)
    except Exception as e: return {"ok": False, "error": f"add_indicators {e}", "strategy": strat_name}
    curr = df.iloc[-1]; prev = df.iloc[-2]
    price = float(curr["close"])
    # 3. Wave + Dow 4h จาก Strategy (ถ้า Strategy ไม่มี Method นี้ให้ Fallback)
    wave = None; cycle_id = 0; wave1_len=0; waveA_len=0; dow4h="UNKNOWN"; swings_1h=[]
    try:
        df_1h = resample_tf(df, "1h"); df_1h = st.add_indicators(df_1h)
        df_4h = resample_tf(df, "4h"); df_4h = st.add_indicators(df_4h)
        if hasattr(st, "detect_swings"):
            swings_1h = st.detect_swings(df_1h)
            swings_4h = st.detect_swings(df_4h)
            if hasattr(st, "count_waves") and len(swings_1h)>=6:
                winfo = st.count_waves(swings_1h)
                wave = winfo.get("current_wave"); cycle_id = winfo.get("cycle_id",0)
                wave1_len = winfo.get("wave1_len",0); waveA_len = winfo.get("waveA_len",0)
            if hasattr(st, "get_dow_trend_4h"):
                dow4h = st.get_dow_trend_4h(swings_4h)
    except Exception as e:
        print(f"wave/dow err {e}"); traceback.print_exc()
    # 4. เช็คไม้ที่ถืออยู่ - SL/TP
    trades = load_trades()
    opens = [t for t in trades if t.get("symbol_key")==symbol_key and str(t.get("status")).upper() in ("OPEN","PAPER_OPEN","PAPER")]
    closed_msg = ""
    for ot in opens:
        entry = float(ot["entry"]); sl = float(ot["sl"]); tp = float(ot["tp"]); sig = ot["signal"]; ps = float(ot.get("position_size",0))
        hit_sl = (price <= sl if sig=="LONG" else price >= sl)
        hit_tp = (price >= tp if sig=="LONG" else price <= tp)
        if hit_sl or hit_tp:
            pnl = (price-entry)/entry*ps if sig=="LONG" else (entry-price)/entry*ps
            ot["status"]="CLOSED"; ot["result"]="WIN" if pnl>0 else "LOSS"; ot["exit"]=price; ot["exit_time"]=datetime.now().isoformat(); ot["exit_reason"]="SL" if hit_sl else "TP"; ot["pnl_usd"]=pnl
            closed_msg += f"\n{'✅' if pnl>0 else '❌'} {sig} {symbol_key.upper()} {entry:.1f}->{price:.1f} {ot['exit_reason']} PnL ${pnl:+.2f} Wave {ot.get('wave','?')}"
            # บันทึก Last SL Wave ไว้กันเปิดซ้ำ - Main ไม่รู้ Wave เอง อ่านจากไม้ที่ปิด
            if hit_sl:
                ot["last_sl_wave"] = ot.get("wave"); ot["last_sl_cycle"] = ot.get("cycle")
    if closed_msg:
        save_trades(trades)
        send_tele(f"ปิดไม้ {symbol_key.upper()} {strat_name}{closed_msg}")
        # โหลดใหม่หลังปิด
        trades = load_trades()
        opens = [t for t in trades if t.get("symbol_key")==symbol_key and str(t.get("status")).upper() in ("OPEN","PAPER_OPEN","PAPER")]
    # ถ้ายังถืออยู่ ไม่เปิดไม้ใหม่ (1 ไม้ต่อเหรียญ - ถ้า Strategy ต้องการหลายไม้ ให้ Strategy บอกผ่าน MAX_POS ใน config)
    max_pos = cfg.get("max_pos_per_symbol", 1)
    if len(opens) >= max_pos:
        return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "holding": len(opens), "msg": "holding"}
    # 5. เช็ค Auto
    if not get_auto_state().get(symbol_key, True):
        return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": "auto off"}
    # 6. ถาม Strategy ว่าเข้าได้ไหม - Main ไม่ตัดสินใจเอง
    try:
        # ส่ง Dow 4h ไปให้ Strategy ล็อคทิศ (ถ้า Strategy เก่าไม่รับ param นี้ ให้ Fallback)
        try:
            trend = st.check_trend(curr, prev, dow_trend_4h=dow4h)
        except TypeError:
            try: trend = st.check_trend(curr, prev)
            except: trend = {"long": False, "short": False}
    except Exception as e:
        return {"ok": False, "error": f"check_trend {e}", "strategy": strat_name}
    side = "LONG" if trend.get("long") else "SHORT" if trend.get("short") else None
    if not side:
        return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": "no trend signal"}
    # 7. Quota + ห้ามซ้ำ Wave หลัง SL - อ่านจาก Strategy.WAVE_QUOTA + ประวัติเทรด
    if wave is not None:
        quota_map = getattr(st, "WAVE_QUOTA", {})
        quota = quota_map.get(wave, 1) if isinstance(quota_map, dict) else 1
        # นับไม้ที่เปิดแล้วใน Wave นี้ (Cycle เดียวกัน)
        count_in_wave = len([t for t in trades if t.get("symbol_key")==symbol_key and t.get("wave")==wave and t.get("cycle")==cycle_id and str(t.get("status")).upper() in ("OPEN","PAPER_OPEN","PAPER","CLOSED")])
        # ถ้าเทรดปิดแล้วนับด้วย? นับเฉพาะไม้ที่เปิดใน Cycle นี้ทั้งหมด (รวมที่ปิดไปแล้ว) เพื่อไม่ให้เปิดเกิน Quota
        if count_in_wave >= quota:
            return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": f"quota full Wave {wave} {count_in_wave}/{quota}"}
        # ห้ามซ้ำ Wave เดิมหลัง SL
        last_sl = None
        for t in reversed(trades):
            if t.get("symbol_key")==symbol_key and t.get("exit_reason")=="SL" and t.get("wave")==wave and t.get("cycle")==cycle_id and t.get("signal")==side:
                last_sl = t; break
        if last_sl:
            return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": f"skip Wave {wave} หลัง SL"}
    # 8. แตะ EMA + Pattern - ถาม Strategy
    try:
        ema_slow_val = float(curr["ema_slow"]) if "ema_slow" in curr else float(curr["ema_trend"]) if "ema_trend" in curr else 0
        if hasattr(st, "is_touch_ema36"):
            if not st.is_touch_ema36(float(curr["low"]), float(curr["high"]), ema_slow_val):
                return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": "not touch EMA"}
        if hasattr(st, "check_pattern_15m"):
            pat = st.check_pattern_15m(df, len(df)-1)
            if pat is None:
                return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": "no pattern"}
            if side=="LONG" and pat not in ("PIN_BULL","ENG_BULL"):
                return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": f"pattern {pat} ไม่ตรง LONG"}
            if side=="SHORT" and pat not in ("PIN_BEAR","ENG_BEAR"):
                return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": f"pattern {pat} ไม่ตรง SHORT"}
        else:
            pat = "N/A"
    except Exception as e:
        print(f"pattern/touch err {e}"); pat = "N/A"
    # 9. SL / TP - ถาม Strategy (ไม่ Hardcode %)
    try:
        atr_val = float(curr["atr"]) if "atr" in curr and pd.notna(curr["atr"]) else 0
        if hasattr(st, "get_sl_by_structure"):
            try: sl = float(st.get_sl_by_structure(side, price, swings_1h, atr_val))
            except TypeError: sl = float(st.get_sl_by_structure(side, price, price))
        else:
            sl_pct = cfg.get("sl_pct", 0.008); sl = price*(1-sl_pct) if side=="LONG" else price*(1+sl_pct)
        if hasattr(st, "get_tp_by_wave"):
            tp = float(st.get_tp_by_wave(wave, side, price, wave1_len, waveA_len))
        else:
            tp_pct = cfg.get("tp_pct", 0.016); tp = price*(1+tp_pct) if side=="LONG" else price*(1-tp_pct)
        if side=="LONG" and (sl>=price or tp<=price): return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "msg": "SL/TP ผิดทิศ"}
        if side=="SHORT" and (sl<=price or tp>=price): return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "msg": "SL/TP ผิดทิศ"}
    except Exception as e:
        return {"ok": False, "error": f"SL/TP {e}", "strategy": strat_name}
    # 10. เปิดไม้ Paper
    pos_info = calc_position(symbol_key, price, sl)
    new_trade = {
        "symbol_key": symbol_key, "symbol": symbol, "signal": side, "wave": wave, "cycle": cycle_id, "dow4h": dow4h,
        "entry": price, "sl": sl, "tp": tp, "position_size": pos_info["pos"], "margin": pos_info["margin"],
        "status": "PAPER_OPEN", "pattern": pat, "strategy": strat_name,
        "time": datetime.now().isoformat(), "entry_time": datetime.now().isoformat()
    }
    trades.append(new_trade); save_trades(trades); set_last_trade_time(symbol_key)
    send_tele(f"📈 เปิด {side} {symbol_key.upper()} {strat_name}\nWave {wave} Cycle {cycle_id} Dow4h {dow4h} Pattern {pat}\nเข้า {price:.1f} SL {sl:.1f} TP {tp:.1f} Risk ${pos_info['risk']:.2f}")
    return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "side": side, "entry": price, "sl": sl, "tp": tp, "msg": "opened"}

def parse_sym(s):
    s=(s or "").lower()
    if s in ("btc","bitcoin"): return ("btc","BTC")
    if s in ("gold","xau","paxg"): return ("gold","GOLD")
    if s in ("all",""): return ("all","ALL")
    return ("unknown", s)

# ===== API =====
@app.get("/ping")
def ping():
    return {"status": "ok UNIVERSAL", "strategy_btc": get_strategy_name("btc"), "strategy_gold": get_strategy_name("gold"), "auto": get_auto_state(), "trades": len(load_trades())}

@app.get("/", response_class=HTMLResponse)
def home():
    auto=get_auto_state()
    return f"<html><body style='background:#0a0e1a;color:#fff;font-family:Arial;padding:20px'><h1>G_POWER UNIVERSAL</h1><p>Strategy: {get_strategy_name('btc')}</p><p>BTC {'🟢' if auto.get('btc') else '🔴'} GOLD {'🟢' if auto.get('gold') else '🔴'}</p><p>Main ไม่ต้องแก้แล้ว เปลี่ยนแค่ strategy_G_POWER.py</p><a href='/ping'>Ping</a></body></html>"

@app.get("/check")
def check(sym: str = "all"):
    key,_ = parse_sym(sym)
    results={}
    if key=="all":
        for k in ["btc","gold"]:
            try: results[k]=execute_symbol(k)
            except Exception as e: results[k]={"ok":False,"error":str(e)[:200]}
    else:
        try: results[key]=execute_symbol(key)
        except Exception as e: results[key]={"ok":False,"error":str(e)[:200]}
    return results

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    try:
        body = await req.json()
        msg = body.get("message", {})
        text = (msg.get("text") or "").strip()
        chat_id = msg.get("chat", {}).get("id")
        tl = text.lower()
        if tl.startswith("/check"):
            parts = tl.split(); key = "all" if len(parts)<2 else parse_sym(parts[1])[0]
            if key=="unknown": send_tele("❓ มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            if key=="all":
                for k in ["btc","gold"]:
                    try:
                        r=execute_symbol(k)
                        send_tele(f"✅ {k.upper()} {r.get('strategy','')} ราคา {r.get('price','?')} Wave {r.get('wave','?')} Dow4h {r.get('dow4h','?')} {r.get('msg','')}", chat_id)
                    except Exception as e: send_tele(f"{k} Error {e}", chat_id)
            else:
                try:
                    r=execute_symbol(key)
                    send_tele(f"✅ {key.upper()} {r.get('strategy','')} ราคา {r.get('price','?')} Wave {r.get('wave','?')} Dow4h {r.get('dow4h','?')} {r.get('msg','')}", chat_id)
                except Exception as e: send_tele(f"{key} Error {e}", chat_id)
            return {"ok":True}
        elif tl.startswith("/bt"):
            try:
                f=DATA_DIR/"bt_results.json"
                if not f.exists():
                    send_tele("ยังไม่มีผล BT รันใน Shell ก่อน: python backtest_G_POWER.py --days 30", chat_id); return {"ok":True}
                out=json.loads(f.read_text())
                lines=["📊 BT ล่าสุด"]
                for sym in ["btc","gold"]:
                    if sym not in out: continue
                    r=out[sym]
                    lines.append(f"\n{'BTC' if sym=='btc' else 'GOLD'} {r['days']} วัน: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} PF {r['profit_factor']}")
                    for tr in r['trade_list'][-5:]:
                        lines.append(f"  {tr['side']} Wave {tr.get('wave','?')} {tr['entry']:.1f}->{tr['exit']:.1f} {tr['exit_reason']} ${tr['pnl_usd']:+.2f}")
                send_tele("\n".join(lines), chat_id); return {"ok":True}
            except Exception as e: send_tele(f"/bt Error {e}", chat_id); return {"ok":True}
        elif tl.startswith("/port") or tl.startswith("/info") or tl.startswith("/portfolio"):
            trades=load_trades(); opens=[t for t in trades if str(t.get("status")).upper() in ("OPEN","PAPER_OPEN","PAPER")]
            closed=[t for t in trades if str(t.get("status")).upper()=="CLOSED"]
            total_pnl=sum(float(t.get("pnl_usd",0)) for t in closed)
            lines=[f"📊 Portfolio {get_strategy_name('btc')}"]
            lines.append(f"ถืออยู่ {len(opens)} ไม้ | ปิดแล้ว {len(closed)} ไม้ PnL ${total_pnl:+.2f} ทุน ${CAPITAL}")
            for t in opens:
                lines.append(f"  {t.get('signal')} {t.get('symbol_key','').upper()} Wave {t.get('wave','?')} เข้า {float(t.get('entry',0)):.1f} SL {float(t.get('sl',0)):.1f} TP {float(t.get('tp',0)):.1f}")
            send_tele("\n".join(lines), chat_id); return {"ok":True}
        elif tl.startswith("/close"):
            parts=tl.split(); want=None if len(parts)<2 or parts[1]=="all" else parse_sym(parts[1])[0]
            trades=load_trades(); opens=[t for t in trades if str(t.get("status")).upper() in ("OPEN","PAPER_OPEN","PAPER")]
            if want and want!="all": opens=[t for t in opens if t.get("symbol_key")==want]
            if not opens: send_tele("ไม่มีไม้ที่ถืออยู่", chat_id); return {"ok":True}
            total=0; out=f"CLOSE {len(opens)} trades\n"
            for ot in opens:
                key=ot.get("symbol_key","btc")
                try: r=execute_symbol(key); curr_p=r.get("price", float(ot["entry"]))
                except: curr_p=float(ot["entry"])
                entry=float(ot["entry"]); sig=ot["signal"]; ps=float(ot.get("position_size",0))
                pnl=(curr_p-entry)/entry*ps if sig=="LONG" else (entry-curr_p)/entry*ps
                total+=pnl; ot["status"]="CLOSED"; ot["result"]="WIN" if pnl>0 else "LOSS"; ot["exit"]=curr_p; ot["exit_time"]=datetime.now().isoformat(); ot["exit_reason"]="MANUAL CLOSE"; ot["pnl_usd"]=pnl
                out+=f"{sig} {ot['symbol']} PnL ${pnl:+.2f}\n"
            save_trades(trades)
            if want is None or want=="all": set_auto_state("all", False); out+=f"รวม ${total:+.2f} Auto OFF"
            else: set_auto_state(want, False); out+=f"รวม ${total:+.2f} Auto {want.upper()} OFF"
            send_tele(out, chat_id); return {"ok":True}
        elif tl.startswith("/reset"):
            trades=load_trades(); opens=[t for t in trades if str(t.get("status")).upper() in ("OPEN","PAPER_OPEN","PAPER")]
            if opens: send_tele(f"ยังถือ {len(opens)} ไม้อยู่! พิมพ์ /close all ก่อน", chat_id); return {"ok":True}
            try:
                for f in [TRADES_FILE, AUTO_STATE_FILE]:
                    try:
                        if f.exists(): f.unlink(missing_ok=True)
                    except: pass
                save_trades([]); set_auto_state("all", False)
            except Exception as e: send_tele(f"RESET Error {e}", chat_id); return {"ok":True}
            send_tele("ล้างไพ่เรียบร้อย Paper $40.00 Auto OFF - พิมพ์ /on all เพื่อเริ่มใหม่", chat_id); return {"ok":True}
        elif tl.startswith("/on"):
            parts=tl.split(); key="all" if len(parts)<2 else parse_sym(parts[1])[0]
            if key=="unknown": send_tele("❓ มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            set_auto_state(key, True); send_tele(f"🟢 Auto ON {key.upper()} {get_strategy_name('btc')}", chat_id); return {"ok":True}
        elif tl.startswith("/off"):
            parts=tl.split(); key="all" if len(parts)<2 else parse_sym(parts[1])[0]
            if key=="unknown": send_tele("❓ มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            set_auto_state(key, False); send_tele(f"🔴 Auto OFF {key.upper()}", chat_id); return {"ok":True}
        else:
            send_tele(f"❓ {text}\n/check [btc|gold|all]\n/on [btc|gold|all]\n/off [btc|gold|all]\n/port\n/bt\n/close all", chat_id); return {"ok":True}
    except Exception as e:
        print(f"ERR {e}"); traceback.print_exc(); return {"ok":True}

@app.on_event("startup")
async def auto_set_webhook():
    token = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    if not token: return
    base = os.environ.get("RENDER_EXTERNAL_URL","").strip() or "https://mexc-btc-bot-1.onrender.com"
    url = base.rstrip("/") + "/telegram/webhook"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook?url={url}", timeout=10)
        print(f"STARTUP setWebhook {url} : {r.text[:200]}")
    except Exception as e: print(f"STARTUP fail {e}")

@app.get("/set_webhook")
def set_webhook():
    token = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    if not token: return {"ok":False,"error":"No BOT_TOKEN"}
    url = "https://mexc-btc-bot-1.onrender.com/telegram/webhook"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook?url={url}", timeout=10)
        return {"ok":r.status_code==200,"telegram":r.json(),"set_to":url}
    except Exception as e: return {"ok":False,"error":str(e)[:200]}

@app.get("/test_send")
def test_send():
    r = send_tele("TEST จาก Render UNIVERSAL - ถ้าเห็นข้อความนี้ = BOT_TOKEN + CHAT_ID ถูกแล้ว")
    return {"sent":r}
