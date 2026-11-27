"""G_POWER Main UNIVERSAL V2.8 - /chart 4h แสดง Wave Dow Theory
V2.8 แก้ในรถยนต์อย่างเดียว สมอง V9.3.1 ไม่ต้องแตะ:
- /chart gold 4h / /chart btc 4h มีเส้น ZigZag ขาว เชื่อม Swing 4h + ป้าย HH/HL/LH/LL
- HH = High ใหม่สูงกว่า High ก่อน, LH = High ใหม่ต่ำกว่า High ก่อน / HL = Low ใหม่สูงกว่า Low ก่อน, LL = Low ใหม่ต่ำกว่า Low ก่อน
- HH+HL = Dow UP, LH+LL = Dow DOWN ตรงกับ Dow4h ที่สมองตัดสินเลย เพราะใช้ swings ตัวเดียวกัน (detect_swings 4h)
- /chart 1h/15m เหมือน V2.7 ไม่ใส่ Dow เพราะ Dow ดูที่ 4h เท่านั้น
อัปโหลดเป็น main_G_POWER.py ทับตัวเก่า ต้องมี Pillow อย่างเดียวพอ
"""
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from datetime import datetime, timedelta
import os, ccxt, pandas as pd, json, requests, importlib, traceback
from pathlib import Path

app = FastAPI(title="G_POWER UNIVERSAL V2.8")

CAPITAL = 40.0
RISK_PCT = 0.02
LEVERAGE = 3
SYMBOLS = {"btc": "BTC/USDT:USDT", "gold": "PAXG/USDT:USDT"}
DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRADES_FILE = DATA_DIR / "g_power_trades.json"
AUTO_STATE_FILE = DATA_DIR / "auto_state.json"
LAST_TRADE_TIME_FILE = DATA_DIR / "last_trade_time.json"

def load_strategy(symbol_key):
    try:
        import strategy_G_POWER
        importlib.reload(strategy_G_POWER)
        StrategyCls = strategy_G_POWER.Strategy_G_Power
    except Exception as e:
        print(f"load_strategy import err {e}"); raise
    try: st = StrategyCls(symbol_key)
    except TypeError:
        st = StrategyCls(); st.symbol_key = symbol_key
    return st

def get_strategy_name(symbol_key="btc"):
    try:
        st = load_strategy(symbol_key); return getattr(st, "name", "UNKNOWN")
    except: return "UNKNOWN"

_STRAT_CACHE = {}
def get_strat(symbol_key):
    if symbol_key not in _STRAT_CACHE:
        _STRAT_CACHE[symbol_key] = load_strategy(symbol_key)
    return _STRAT_CACHE[symbol_key]

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

def get_data(symbol="BTC/USDT:USDT", timeframe="15m", limit=1000):
    # V2: 1000 แท่ง = 10 วัน (เดิม 250 แท่ง = 2.6 วัน Swing ไม่พอ)
    try:
        ex=ccxt.mexc({"options":{"defaultType":"swap"}})
        ohlcv=ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        if ohlcv and len(ohlcv)>50:
            df=pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['datetime']=pd.to_datetime(df['timestamp'], unit='ms')
            df['time']=df['datetime']
            return df
    except Exception as e: print(f"get_data err {e}")
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

def send_tele_photo(image_path, caption, chat_id=None):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    chat=chat_id or os.environ.get("TELEGRAM_CHAT_ID","").strip() or os.environ.get("CHAT_ID","").strip()
    if not token or not chat: return {"ok":False}
    try:
        with open(image_path,'rb') as f:
            r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id":chat,"caption":caption,"parse_mode":"HTML"}, files={"photo":f}, timeout=15)
        return {"ok": r.status_code==200, "resp": r.text[:300]}
    except Exception as e:
        print(f"send_tele_photo err {e}"); return {"ok":False}

def generate_portfolio_image(trades, paper_balance, unrealized, total_closed_pnl, win_rate, win_count, total_count, pnl_btc, pnl_gold, opens):
    # V2.2: /port ต้องได้การ์ดแบบในรูปที่พี่ส่ง 13/11 20:16 ไม่ใช่ข้อความล้วน
    try:
        from PIL import Image, ImageDraw, ImageFont
        W, H = 800, 1050
        BG = (10, 14, 26); CARD = (18, 26, 48); CARD2 = (22, 32, 58)
        WHITE = (255,255,255); GRAY = (140,150,170); GREEN = (0, 210, 110); RED = (255, 80, 80)
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        def font(sz, bold=False):
            for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"]:
                try: return ImageFont.truetype(p, sz)
                except: pass
            return ImageFont.load_default()
        f_title = font(34, True); f_label = font(20, False); f_val = font(30, True); f_small = font(22, False); f_coin = font(24, True)
        # Header
        d.text((30, 20), "G_POWER  PORTFOLIO", fill=WHITE, font=f_title)
        d.text((30, 62), datetime.now().strftime("%d/%m %H:%M") + "  -  BTC + GOLD", fill=GRAY, font=f_small)
        # 4 boxes
        boxes = [
            ("PAPER BALANCE", f"${paper_balance:.2f}", WHITE, 30, 110, 360, 130),
            ("UNREALIZED PnL", f"{unrealized:+.2f}", GREEN if unrealized>=0 else RED, 430, 110, 360, 130),
            ("TOTAL CLOSED", f"{total_closed_pnl:+.2f}", GREEN if total_closed_pnl>=0 else RED, 30, 260, 360, 130),
            ("WIN RATE", f"{win_rate:.0f}%  ({win_count}/{total_count})", WHITE, 430, 260, 360, 130),
        ]
        for label, val, col, x, y, w, h in boxes:
            d.rounded_rectangle([x, y, x+w, y+h], radius=12, fill=CARD)
            d.text((x+18, y+14), label, fill=GRAY, font=f_label)
            d.text((x+18, y+48), val, fill=col, font=f_val)
        # PnL BY COIN
        y0 = 410
        d.rounded_rectangle([30, y0, 790, y0+190], radius=12, fill=CARD)
        d.text((50, y0+14), "PnL BY COIN", fill=WHITE, font=f_coin)
        # BTC bar
        max_abs = max(abs(pnl_btc), abs(pnl_gold), 0.01)
        d.text((50, y0+60), "BTC", fill=WHITE, font=f_coin)
        bw_btc = int(420 * abs(pnl_btc) / max_abs) if max_abs>0 else 0
        d.rectangle([150, y0+62, 150+bw_btc, y0+92], fill=GREEN if pnl_btc>=0 else RED)
        d.text((150+bw_btc+12, y0+60), f"{pnl_btc:+.2f}", fill=GREEN if pnl_btc>=0 else RED, font=f_coin)
        # GOLD bar
        d.text((50, y0+115), "GOLD", fill=WHITE, font=f_coin)
        bw_gold = int(420 * abs(pnl_gold) / max_abs) if max_abs>0 else 0
        d.rectangle([150, y0+117, 150+bw_gold, y0+147], fill=GREEN if pnl_gold>=0 else RED)
        d.text((150+bw_gold+12, y0+115), f"{pnl_gold:+.2f}", fill=GREEN if pnl_gold>=0 else RED, font=f_coin)
        # OPEN
        y1 = 620
        d.rounded_rectangle([30, y1, 790, y1+260], radius=12, fill=CARD)
        d.text((50, y1+14), f"OPEN  {len(opens)} TRADES", fill=WHITE, font=f_coin)
        if not opens:
            d.text((50, y1+90), "No open trades", fill=(170,180,200), font=f_val)
            d.text((50, y1+135), "Waiting for signal...", fill=GRAY, font=f_small)
        else:
            yy = y1+60
            for t in opens[:4]:
                d.text((50, yy), f"{t.get('signal')} {t.get('symbol_key','').upper()} Wave {t.get('wave','?')} {float(t.get('entry',0)):.1f} SL {float(t.get('sl',0)):.1f} TP {float(t.get('tp',0)):.1f}", fill=WHITE, font=f_small)
                yy += 38
        # Footer
        d.rounded_rectangle([30, 900, 790, 980], radius=12, fill=CARD2)
        d.text((50, 925), "MEXC Paper Only - Not Real Trade", fill=GRAY, font=f_small)
        out = "/tmp/g_power_portfolio.png"
        img.save(out)
        return out
    except Exception as e:
        print(f"generate_portfolio_image err {e}"); traceback.print_exc(); return None

def generate_chart_image(symbol_key, df, trades, wave, dow4h, ema36, tf="15m", candle_minutes=15, dow_swings=None):
    # V2.8: + กราฟ 4h แสดง Wave Dow Theory: เส้น ZigZag เชื่อม Swing 4h + ป้าย HH/HL/LH/LL
    try:
        from PIL import Image, ImageDraw, ImageFont
        orig_len = len(df)
        d = df.tail(120).copy().reset_index(drop=True)
        offset = orig_len - len(d)
        W, H = 960, 700
        BG = (10, 14, 26); GREEN = (0, 210, 110); RED = (255, 82, 82); YELLOW = (255, 213, 74); WHITE = (255,255,255); GRAY = (140,150,170)
        img = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)
        def font(sz, bold=False):
            for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
                try: return ImageFont.truetype(p, sz)
                except: pass
            return ImageFont.load_default()
        f_title = font(26, True); f_small = font(20, False); f_leg = font(18, False); f_price = font(17, False); f_tag = font(17, True)
        draw.text((20, 12), f"{symbol_key.upper()} {tf}  Wave {wave}  Dow4h {dow4h}", fill=WHITE, font=f_title)
        last_price = float(d["close"].iloc[-1])
        draw.text((20, 48), f"Price {last_price:.2f}  EMA36 {ema36:.2f}", fill=YELLOW, font=f_small)
        # พื้นที่กราฟ: เว้นขอบขวา 110px ไว้เป็นสเกลราคา
        left, top, right, bottom = 20, 90, 830, 560
        price_x = right + 6
        draw.rectangle([left, top, right, bottom], outline=(50,60,80))
        # สเกลราคา
        lo = float(d["low"].min()); hi = float(d["high"].max())
        sym_trades = [t for t in trades if t.get("symbol_key")==symbol_key]
        for t in sym_trades:
            try:
                lo = min(lo, float(t.get("sl", lo)), float(t.get("tp", lo)), float(t.get("entry", lo)))
                hi = max(hi, float(t.get("sl", hi)), float(t.get("tp", hi)), float(t.get("entry", hi)))
            except: pass
        if hi<=lo: hi = lo+1
        pad = (hi-lo)*0.08; lo -= pad; hi += pad
        def y_of(price): return bottom - (price-lo)/(hi-lo)*(bottom-top)
        def x_of(i): return left + 8 + i*(right-left-16)/max(len(d)-1,1)
        # เส้นกริด + ระดับราคาขอบขวา (5 ระดับ)
        for gy in range(5):
            y = top + (bottom-top)*gy/4
            draw.line([(left, y), (right, y)], fill=(30,40,60), width=1)
            lvl_price = hi - (hi-lo)*gy/4
            draw.text((price_x, y-9), f"{lvl_price:.1f}", fill=GRAY, font=f_price)
        # แท่งเทียน 120 แท่ง
        for i in range(len(d)):
            o=float(d["open"].iloc[i]); h=float(d["high"].iloc[i]); l=float(d["low"].iloc[i]); c=float(d["close"].iloc[i])
            x = x_of(i); col = GREEN if c>=o else RED
            draw.line([(x, y_of(h)), (x, y_of(l))], fill=col, width=2)
            bw = max(2, (right-left)//len(d)//2)
            draw.rectangle([x-bw//2, y_of(max(o,c)), x+bw//2, y_of(min(o,c))], fill=col)
        # เส้น EMA36 เหลือง
        if "ema_slow" in d.columns:
            pts=[]
            for i in range(len(d)):
                try: pts.append((x_of(i), y_of(float(d["ema_slow"].iloc[i]))))
                except: pass
            if len(pts)>=2: draw.line(pts, fill=YELLOW, width=2)
        # ===== V2.8: กราฟ 4h แสดง Wave Dow Theory =====
        # ใช้ swings ที่สมองนับไว้แล้ว (detect_swings 4h) มาวาดซ้ำ ไม่ได้นับใหม่ในรถยนต์
        # เส้น ZigZag ขาว เชื่อม High/Low + ป้าย HH/HL (ขาขึ้น) / LH/LL (ขาลง) เทียบกับ Swing ประเภทเดียวกันก่อนหน้า
        if tf=="4h" and dow_swings:
            try:
                pts=[]; labels=[]
                last_high=None; last_low=None
                for s in dow_swings:
                    try:
                        # รองรับ swings หลายรูปแบบ: dict / tuple / list
                        if isinstance(s, dict):
                            idx=s.get("index", s.get("idx", s.get("i", s.get("pos", s.get("bar", None)))))
                            pr=s.get("price", s.get("value", s.get("close", None)))
                            typ=str(s.get("type", s.get("kind", s.get("side", s.get("label",""))))).lower()
                            if idx is None and "time" in s: idx=None
                            if pr is None: continue
                            idx=int(idx) if idx is not None else None
                        elif isinstance(s, (list, tuple)) and len(s)>=2:
                            idx=int(s[0]); pr=float(s[1]); typ=str(s[2]).lower() if len(s)>=3 else ""
                        else: continue
                        if idx is None: continue
                        # ถ้าไม่มี type ให้เดาจากราคา vs High/Low ของแท่งนั้น
                        if not typ or typ not in ("high","low","h","l","hh","hl","lh","ll"):
                            try:
                                row=df.iloc[idx]
                                typ="high" if abs(float(pr)-float(row["high"]))<=abs(float(pr)-float(row["low"])) else "low"
                            except: typ="high" if pr>=float(d["close"].iloc[-1]) else "low"
                        is_high = typ in ("high","h","hh","lh")
                        # ป้าย Dow: High ใหม่สูงกว่า High ก่อน = HH, ต่ำกว่า = LH / Low ใหม่สูงกว่า Low ก่อน = HL, ต่ำกว่า = LL
                        if is_high:
                            lbl="HH" if (last_high is None or float(pr)>last_high) else "LH"
                            last_high=float(pr)
                        else:
                            lbl="HL" if (last_low is None or float(pr)>last_low) else "LL"
                            last_low=float(pr)
                        # แปลง index ของ df เต็ม -> index ในรูป tail 120
                        xi = idx - offset
                        if xi<0 or xi>=len(d): continue
                        pts.append((x_of(xi), y_of(float(pr))))
                        labels.append((x_of(xi), y_of(float(pr)), lbl, is_high))
                    except: continue
                if len(pts)>=2: draw.line(pts, fill=WHITE, width=2)
                for x,y,lbl,is_high in labels:
                    col = GREEN if lbl in ("HH","HL") else RED
                    draw.ellipse([(x-4,y-4),(x+4,y+4)], fill=col, outline=WHITE)
                    ty = y-26 if is_high else y+10
                    draw.text((x-12, ty), lbl, fill=col, font=f_tag)
                # ข้อความบอก Dow ใต้หัวข้อ
                draw.text((20, 72), f"Dow 4h: {dow4h}  HH/HL = ขาขึ้น  LH/LL = ขาลง  เส้นขาว = ZigZag Swing 4h", fill=GRAY, font=f_leg)
            except Exception as e: print(f"dow overlay err {e}")
        # เส้นราคาปัจจุบัน - เก็บเป็นป้ายไว้ก่อน วาดทีเดียวแบบกันซ้อน
        right_tags = []
        y_cur = y_of(last_price)
        for xx in range(left, right, 12): draw.line([(xx, y_cur), (xx+6, y_cur)], fill=YELLOW, width=1)
        right_tags.append([y_cur, f"{last_price:.1f}", YELLOW, (10,14,26)])
        # จุดเข้า/ออก + SL/TP
        out_text = ""
        try: times_list = list(pd.to_datetime(d["time"] if "time" in d.columns else d["datetime"]))
        except: times_list = []
        for t in sym_trades[-3:]:
            try:
                entry=float(t.get("entry",0)); sl=float(t.get("sl",0)); tp=float(t.get("tp",0))
                xi = len(d)-1
                try:
                    et=pd.to_datetime(t.get("entry_time") or t.get("time"))
                    found = None
                    for j, ct in enumerate(times_list):
                        if ct <= et < ct + pd.Timedelta(minutes=candle_minutes):
                            found = j; break
                    if found is not None: xi = found
                    else: xi = min(range(len(times_list)), key=lambda j: abs((times_list[j]-et).total_seconds()))
                except: xi=len(d)-1
                x=x_of(xi); y=y_of(entry)
                sig=t.get("signal","")
                tri_col = GREEN if sig=="LONG" else RED
                for yy in range(top, bottom, 16): draw.line([(x, yy), (x, yy+8)], fill=(80,90,110), width=1)
                # สามเหลี่ยมอย่างเดียว ไม่แสดงข้อความใดๆ - ข้อความไปอยู่ที่ป้ายราคาขอบขวาแทน
                if sig=="LONG":
                    draw.polygon([(x, y-14), (x-10, y+10), (x+10, y+10)], fill=GREEN, outline=WHITE)
                else:
                    draw.polygon([(x, y+14), (x-10, y-10), (x+10, y-10)], fill=RED, outline=WHITE)
                # เส้นโยงจากสามเหลี่ยมไปป้ายราคาขอบขวา
                for xx in range(int(x), right, 14): draw.line([(xx, y), (xx+7, y)], fill=tri_col, width=2)
                right_tags.append([y, f"{'BUY' if sig=='LONG' else 'SELL'} {entry:.1f}", tri_col, WHITE])
                for val, cc, lbl in [(sl, RED, "SL"), (tp, GREEN, "TP")]:
                    yy = y_of(val)
                    for xx in range(left, right, 14): draw.line([(xx, yy), (xx+7, yy)], fill=cc, width=1)
                    right_tags.append([yy, f"{lbl} {val:.1f}", cc, WHITE])
                if str(t.get("status")).upper()=="CLOSED" and t.get("exit") is not None:
                    ex=float(t.get("exit")); yex=y_of(ex)
                    try:
                        xt=pd.to_datetime(t.get("exit_time") or t.get("time"))
                        x_idx=None
                        for j, ct in enumerate(times_list):
                            if ct <= xt < ct + pd.Timedelta(minutes=candle_minutes): x_idx=j; break
                        if x_idx is None: x_idx=len(d)-1
                    except: x_idx=len(d)-1
                    xex=min(x_of(x_idx), right-15)
                    draw.line([(xex-10, yex-10), (xex+10, yex+10)], fill=WHITE, width=3)
                    draw.line([(xex-10, yex+10), (xex+10, yex-10)], fill=WHITE, width=3)
                    right_tags.append([yex, f"OUT {ex:.1f}", WHITE, (10,14,26)])
                    out_text = f"OUT {ex:.1f} {t.get('exit_reason','')} ${float(t.get('pnl_usd',0)):+.2f}"
            except Exception as e: print(f"chart trade err {e}")
        # วาดป้ายขอบขวาแบบกันซ้อน
        right_tags.sort(key=lambda r: r[0])
        prev_y = -100
        for tag in right_tags:
            yy = tag[0]
            if yy - prev_y < 24: yy = prev_y + 24
            yy = max(top, min(bottom-12, yy))
            tag[0] = yy; prev_y = yy
        for yy, txt, bg, fg in right_tags:
            draw.rectangle([price_x-2, yy-11, W-8, yy+11], fill=bg)
            draw.text((price_x+2, yy-10), txt, fill=fg, font=f_tag)
        # Legend แยก 2 บรรทัด กันโดนตัด
        leg1 = "Green=UP Red=DOWN Yellow=EMA36 Triangle=Entry X=Exit"
        leg2 = "Dashed Red=SL Green=TP  Right=Price Levels"
        if out_text:
            draw.text((20, bottom+8), out_text, fill=WHITE, font=f_small)
            draw.text((20, bottom+36), leg1, fill=GRAY, font=f_leg)
            draw.text((20, bottom+60), leg2, fill=GRAY, font=f_leg)
        else:
            draw.text((20, bottom+8), leg1, fill=GRAY, font=f_leg)
            draw.text((20, bottom+32), leg2, fill=GRAY, font=f_leg)
        out=f"/tmp/g_power_chart_{symbol_key}.png"
        img.save(out)
        return out
    except Exception as e:
        print(f"generate_chart_image err {e}"); traceback.print_exc(); return None

def calc_position(symbol_key, entry, sl):
    risk = CAPITAL * RISK_PCT
    sl_pct = abs(entry-sl)/entry if entry and sl and entry!=0 else 0.01
    if sl_pct==0: sl_pct=0.01
    pos = risk / sl_pct
    return {"risk": risk, "pos": pos, "margin": pos/LEVERAGE, "sl_pct": sl_pct}

def execute_symbol(symbol_key):
    symbol = SYMBOLS[symbol_key]
    st = get_strat(symbol_key)
    cfg = getattr(st, "config", {})
    strat_name = getattr(st, "name", "UNKNOWN")
    df = get_data(symbol, "15m", limit=1000)
    if df is None or len(df)<50:
        return {"ok": False, "error": "no data", "strategy": strat_name}
    try: df = st.add_indicators(df)
    except Exception as e: return {"ok": False, "error": f"add_indicators {e}", "strategy": strat_name}
    curr = df.iloc[-1]; prev = df.iloc[-2]
    price = float(curr["close"])
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
    # เช็คไม้ถืออยู่ - SL/TP (ถือต่อได้แม้ Wave None / Dow UNKNOWN)
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
            if hit_sl:
                ot["last_sl_wave"] = ot.get("wave"); ot["last_sl_cycle"] = ot.get("cycle")
    if closed_msg:
        save_trades(trades)
        send_tele(f"ปิดไม้ {symbol_key.upper()} {strat_name}{closed_msg}")
        trades = load_trades()
        opens = [t for t in trades if t.get("symbol_key")==symbol_key and str(t.get("status")).upper() in ("OPEN","PAPER_OPEN","PAPER")]
    max_pos = cfg.get("max_pos_per_symbol", 1)
    if len(opens) >= max_pos:
        return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "holding": len(opens), "msg": "holding"}
    if not get_auto_state().get(symbol_key, True):
        return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": "auto off"}
    # ===== V2 FIX: ห้ามเปิดถ้า Wave None หรือ Dow UNKNOWN =====
    if wave is None:
        return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": "Wave None - รอ Wave ก่อน ไม่เปิด"}
    if dow4h == "UNKNOWN":
        return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": "Dow4h UNKNOWN - รอ Dow ก่อน ไม่เปิด"}
    try:
        try: trend = st.check_trend(curr, prev, dow_trend_4h=dow4h)
        except TypeError:
            try: trend = st.check_trend(curr, prev)
            except: trend = {"long": False, "short": False}
    except Exception as e:
        return {"ok": False, "error": f"check_trend {e}", "strategy": strat_name}
    side = "LONG" if trend.get("long") else "SHORT" if trend.get("short") else None
    if not side:
        return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": "no trend signal"}
    if wave is not None:
        quota_map = getattr(st, "WAVE_QUOTA", {})
        quota = quota_map.get(wave, 1) if isinstance(quota_map, dict) else 1
        count_in_wave = len([t for t in trades if t.get("symbol_key")==symbol_key and t.get("wave")==wave and t.get("cycle")==cycle_id and str(t.get("status")).upper() in ("OPEN","PAPER_OPEN","PAPER","CLOSED")])
        if count_in_wave >= quota:
            return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": f"quota full Wave {wave} {count_in_wave}/{quota}"}
        last_sl = None
        for t in reversed(trades):
            if t.get("symbol_key")==symbol_key and t.get("exit_reason")=="SL" and t.get("wave")==wave and t.get("cycle")==cycle_id and t.get("signal")==side:
                last_sl = t; break
        if last_sl:
            return {"ok": True, "strategy": strat_name, "price": price, "wave": wave, "dow4h": dow4h, "msg": f"skip Wave {wave} หลัง SL"}
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
        else: pat = "N/A"
    except Exception as e:
        print(f"pattern/touch err {e}"); pat = "N/A"
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

@app.get("/ping")
def ping():
    return {"status": "ok UNIVERSAL V2.8", "strategy_btc": get_strategy_name("btc"), "strategy_gold": get_strategy_name("gold"), "auto": get_auto_state(), "trades": len(load_trades())}

@app.get("/", response_class=HTMLResponse)
def home():
    auto=get_auto_state()
    return f"<html><body style='background:#0a0e1a;color:#fff;font-family:Arial;padding:20px'><h1>G_POWER UNIVERSAL V2.8</h1><p>Strategy: {get_strategy_name('btc')}</p><p>BTC {'🟢' if auto.get('btc') else '🔴'} GOLD {'🟢' if auto.get('gold') else '🔴'}</p><p>Main ไม่ต้องแก้แล้ว เปลี่ยนแค่ strategy_G_POWER.py | Wave None / Dow UNKNOWN ห้ามเปิด</p><a href='/ping'>Ping</a></body></html>"

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
        elif tl.startswith("/port") or tl.startswith("/portfolio"):
            # V2.2: /port ต้องได้การ์ดแบบรูป 13/11 ที่พี่ส่ง ไม่ใช่ข้อความล้วน
            trades=load_trades()
            opens=[t for t in trades if str(t.get("status")).upper() in ("OPEN","PAPER_OPEN","PAPER")]
            closed=[t for t in trades if str(t.get("status")).upper()=="CLOSED"]
            pnl_btc=sum(float(t.get("pnl_usd",0)) for t in closed if t.get("symbol_key")=="btc")
            pnl_gold=sum(float(t.get("pnl_usd",0)) for t in closed if t.get("symbol_key")=="gold")
            total_closed_pnl=pnl_btc+pnl_gold
            # Paper Balance = ทุน $40 + กำไรปิดแล้ว + Unrealized (ตอนนี้ไม่มีไม้ถือ Unrealized=0)
            # ถ้ามีไม้ถืออยู่ คำนวณ Unrealized จากราคาปัจจุบันไม่ได้ตรงนี้ ให้ใส่ 0 แล้วข้อความด้านล่างบอก
            unrealized=0.0
            paper_balance=CAPITAL+total_closed_pnl+unrealized
            wins=len([t for t in closed if float(t.get("pnl_usd",0))>0])
            total_count=len(closed)
            win_rate=(wins/total_count*100) if total_count>0 else 0
            img_path=generate_portfolio_image(trades, paper_balance, unrealized, total_closed_pnl, win_rate, wins, total_count, pnl_btc, pnl_gold, opens)
            caption=f"PORTFOLIO {datetime.now().strftime('%d/%m %H:%M')} MEXC {paper_balance:.2f} USDT\n{'ไม่มีไม้ถืออยู่' if not opens else f'ถืออยู่ {len(opens)} ไม้'} Paper ${paper_balance:.2f}"
            if img_path:
                r=send_tele_photo(img_path, caption, chat_id)
                if not r.get("ok"):
                    # ถ้าส่งรูปไม่ได้ ส่งข้อความแทน
                    send_tele(caption, chat_id)
            else:
                send_tele(caption, chat_id)
            return {"ok":True}
        elif tl.startswith("/info"):
            # V2.1 FIX: /info เดิมเรียกโค้ดเดียวกับ /port เลยได้ Portfolio ซ้ำกัน แก้ให้แสดงข้อมูลสมองแทน
            try:
                st_btc=get_strat("btc"); st_gold=get_strat("gold")
                cfg_btc=getattr(st_btc,"config",{}); cfg_gold=getattr(st_gold,"config",{})
                raw_name=get_strategy_name('btc')
                base_name=raw_name.replace(' BTC','').replace(' btc','').strip()
                auto=get_auto_state()
                lines=[f"ℹ️ Info {base_name}"]
                lines.append(f"รถยนต์ Main UNIVERSAL V2.8 | สมอง Strategy V9.3.1")
                lines.append(f"Auto BTC {'🟢 ON' if auto.get('btc') else '🔴 OFF'} | GOLD {'🟢 ON' if auto.get('gold') else '🔴 OFF'}")
                lines.append(f"\nBTC: EMA {cfg_btc.get('ema_fast')}/{cfg_btc.get('ema_slow')} ADX>{cfg_btc.get('adx_min')} DI>={cfg_btc.get('di_min')} SL cap {cfg_btc.get('sl_pct_max')} TP cap {cfg_btc.get('tp_cap')}")
                lines.append(f"GOLD: EMA {cfg_gold.get('ema_fast')}/{cfg_gold.get('ema_slow')} ADX>{cfg_gold.get('adx_min')} DI>={cfg_gold.get('di_min')} SL cap {cfg_gold.get('sl_pct_max')} TP cap {cfg_gold.get('tp_cap')}")
                lines.append(f"\nTF: 1h นับ Wave | 15m เข้า | 4h ยืนยัน Dow")
                lines.append(f"เข้า: แตะ EMA36 1h + Pin Bar / Engulfing 15m + Volume")
                lines.append(f"TP: Wave3=1.618x Wave1 | Wave5=1.0x Wave1 | ABC=1.0x WaveA")
                lines.append(f"SL: ตามโครงสร้าง HL/LH Cap BTC 0.8% / GOLD 0.6%")
                lines.append(f"Quota: Wave 1=3, 2=1, 3=3, 4=1, 5=3, A=1, B=3, C=1")
                lines.append(f"ห้าม: Wave None / Dow UNKNOWN ห้ามเปิด")
                send_tele("\n".join(lines), chat_id)
            except Exception as e: send_tele(f"/info Error {e}", chat_id)
            return {"ok":True}
        elif tl.startswith("/chart"):
            # V2.7: /chart [btc|gold|all] [15m|1h|4h] - ตัวอย่าง /chart gold /chart gold 1h /chart btc 4h /chart all 1h /chart 1h
            parts=tl.split()
            tf="15m"; candle_minutes=15; key="all"
            for p in parts[1:]:
                pl=p.lower()
                if pl in ("15m","15","m15"): tf="15m"; candle_minutes=15
                elif pl in ("1h","h1","60m","60"): tf="1h"; candle_minutes=60
                elif pl in ("4h","h4","240m","240"): tf="4h"; candle_minutes=240
                else:
                    pk=parse_sym(p)[0]
                    if pk!="unknown": key=pk
            if key=="unknown": send_tele("❓ /chart [btc|gold|all] [15m|1h|4h]\nตัวอย่าง: /chart gold 1h /chart btc 4h", chat_id); return {"ok":True}
            keys=["btc","gold"] if key=="all" else [key]
            trades_all=load_trades()
            for k in keys:
                try:
                    sym=SYMBOLS[k]; st=get_strat(k)
                    df15=get_data(sym,"15m",limit=1000)
                    if df15 is None: send_tele(f"{k.upper()} ไม่มีข้อมูล", chat_id); continue
                    # สร้าง df ตาม TF ที่ขอ: 15m ใช้ตรงๆ 1h/4h resample จาก 15m เหมือนตอนนับ Wave
                    if tf=="15m": df_chart=df15
                    else: df_chart=resample_tf(df15, tf)
                    df_chart=st.add_indicators(df_chart); curr=df_chart.iloc[-1]
                    price=float(curr["close"]); ema36=float(curr["ema_slow"]) if "ema_slow" in curr else 0
                    adx=float(curr["adx"]) if "adx" in curr else 0
                    pdi=float(curr["plus_di"]) if "plus_di" in curr else 0
                    mdi=float(curr["minus_di"]) if "minus_di" in curr else 0
                    wave="?" ; dow4h="?" ; dow_swings=None
                    try:
                        df_1h=resample_tf(df15,"1h"); df_1h=st.add_indicators(df_1h)
                        df_4h=resample_tf(df15,"4h"); df_4h=st.add_indicators(df_4h)
                        sw1=st.detect_swings(df_1h); sw4=st.detect_swings(df_4h)
                        if len(sw1)>=6: wave=str(st.count_waves(sw1).get("current_wave"))
                        dow4h=st.get_dow_trend_4h(sw4)
                        # กราฟ 4h ใช้ swings 4h ตัวเดียวกับที่สมองใช้ตัดสิน Dow (ไม่นับใหม่)
                        if tf=="4h": dow_swings=sw4
                    except: pass
                    touch="แตะ EMA36" if hasattr(st,"is_touch_ema36") and st.is_touch_ema36(float(curr["low"]),float(curr["high"]),ema36) else "ไม่แตะ EMA36"
                    pat="?"
                    # Pattern มีแค่ 15m เท่านั้น 1h/4h ไม่เช็ค Pattern
                    if tf=="15m":
                        try: pat=str(st.check_pattern_15m(df_chart,len(df_chart)-1))
                        except: pass
                    else: pat="- (Pattern ดูที่ 15m)"
                    img_path=generate_chart_image(k, df_chart, trades_all, wave, dow4h, ema36, tf=tf, candle_minutes=candle_minutes, dow_swings=dow_swings)
                    caption=f"📈 Chart {k.upper()} {tf} ราคา {price:.2f} Wave {wave} Dow4h {dow4h} EMA36 {ema36:.2f} | {touch} ADX {adx:.1f} DI+ {pdi:.1f} DI- {mdi:.1f} Pattern {pat}\n🔺 เขียว = BUY / 🔻 แดง = SELL / X ขาว = จุดออก / เส้นประแดง = SL / เส้นประเขียว = TP" + (f"\n⚪ เส้นขาว = ZigZag Dow 4h | HH/HL = ขาขึ้น | LH/LL = ขาลง" if tf=="4h" else "")
                    if img_path:
                        r=send_tele_photo(img_path, caption, chat_id)
                        if not r.get("ok"): send_tele(caption, chat_id)
                    else:
                        send_tele(caption, chat_id)
                except Exception as e: send_tele(f"/chart {k} {tf} Error {e}", chat_id)
            return {"ok":True}
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
            send_tele(f"❓ {text}\n/check [btc|gold|all]\n/on [btc|gold|all]\n/off [btc|gold|all]\n/port\n/info\n/chart [btc|gold|all]\n/bt\n/close all", chat_id); return {"ok":True}
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
    r = send_tele("TEST จาก Render UNIVERSAL V2.8 - ถ้าเห็นข้อความนี้ = BOT_TOKEN + CHAT_ID ถูกแล้ว")
    return {"sent":r}
