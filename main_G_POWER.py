"""G_POWER V5.6.1.1 - BTC+GOLD - Real MEXC data only"""
# 379 lines fixed - _m sets default config if old strategy has no ema_fast
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
try:
    from strategy_G_POWER import Strategy_G_Power as StrategyMulti
    USE_V5=True
except:
    from strategy_G_POWER import Strategy_G_Power as StrategyMulti
    USE_V5=False
from datetime import datetime, timedelta
import os, ccxt, pandas as pd, json, requests
from pathlib import Path
app = FastAPI(title="G_POWER V5.6.1.1 NO HEDGE + CLOSE")
def _m(k):
    try: s=StrategyMulti(k)
    except: s=StrategyMulti(); s.symbol_key=k
    if not getattr(s,'config',{}).get('ema_fast'): s.config={'ema_fast':12 if k=='btc' else 21 if k=='gold' else 9,'ema_slow':26 if k=='btc' else 55 if k=='gold' else 21,'ema_trend':50 if k=='btc' else 100 if k=='gold' else 34,'adx_min':10,'adx_sideway':10,'adx_turbo':28,'di_min':10,'di_turbo':20,'sl_pct':0.034 if k=='btc' else 0.028 if k=='gold' else 0.035,'tp_pct':0.18 if k=='btc' else 0.12 if k=='gold' else 0.10,'cdc_atr_fast':5,'cdc_mult_fast':0.5,'cdc_atr_slow':10,'cdc_mult_slow':2.0,'sideway_pct':1.2,'retest_pct':0.012,'be_trigger':0.01,'lock_trigger':0.02,'lock_pct':0.005}
    return s
STRATS = {"btc": _m("btc"), "gold": _m("gold")}
strat = STRATS["btc"]
MAX_POS_PER_SYMBOL=3; COOLDOWN_HOURS=0.5
CAPITAL=40; RISK_PCT=0.02; LEVERAGE=3
SYMBOLS = {"btc": "BTC/USDT", "gold": "PAXG/USDT:USDT"}
DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRADES_FILE = DATA_DIR / "g_power_trades.json"
AUTO_STATE_FILE = DATA_DIR / "auto_state.json"
LAST_TRADE_TIME_FILE = DATA_DIR / "last_trade_time.json"
def atomic_save(path: Path, data):
    try:
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w') as f:
            json.dump(data, f, default=str, indent=2)
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
                if isinstance(d,bool): return {"btc":d,"gold":d}
                if not isinstance(d, dict): return {"btc":True,"gold":True}
                if "enabled" in d:
                    val=bool(d.get("enabled",False))
                    return {"btc":val,"gold":val}
                if "btc" in d or "gold" in d:
                    return {"btc": bool(d.get("btc",False)), "gold": bool(d.get("gold",False))}
                return {"btc":True,"gold":True}
        except Exception as e:
            print(f"get_auto_state error {e}, reset to ON")
            try:
                AUTO_STATE_FILE.unlink(missing_ok=True)
            except: pass
            return {"btc":True,"gold":True}
    return {"btc":True,"gold":True}
def set_auto_state(k, en):
    s=get_auto_state()
    if k=='all':
        for kk in s: s[kk]=en
    else: s[k]=en
    atomic_save(AUTO_STATE_FILE, s)
    return s
def get_last_trade_times():
    if LAST_TRADE_TIME_FILE.exists():
        try:
            with open(LAST_TRADE_TIME_FILE,'r') as f: return json.load(f)
        except: pass
    return {}
def set_last_trade_time(symbol_key):
    times=get_last_trade_times()
    times[symbol_key]=datetime.now().isoformat()
    atomic_save(LAST_TRADE_TIME_FILE, times)
def can_open_new(symbol_key, cooldown_hours=1):
    times=get_last_trade_times()
    last_str=times.get(symbol_key)
    if not last_str: return True
    try:
        last=datetime.fromisoformat(last_str)
        if datetime.now() - last < timedelta(hours=cooldown_hours):
            return False
        return True
    except: return True
def calc_position(symbol_key="btc"):
    cfg=STRATS.get(symbol_key, STRATS['btc']).config
    sl=cfg['sl_pct']; tp=cfg['tp_pct']
    risk=CAPITAL*RISK_PCT
    pos=risk/sl if sl else risk/0.034
    return {"risk":risk,"pos":pos,"margin":pos/LEVERAGE,"sl":sl*100,"tp":tp*100,"rr":round(tp/sl,1)}
def get_data(symbol="BTC/USDT", timeframe="15m"):
    candidates=[symbol]
    if "PAXG" in symbol: candidates+= ["PAXG/USDT","XAUT/USDT:USDT"]
    for sym in candidates:
        try:
            ex=ccxt.mexc({"options":{"defaultType":"swap"}})
            ohlcv=ex.fetch_ohlcv(sym,timeframe,limit=250)
            if ohlcv and len(ohlcv)>50:
                df=pd.DataFrame(ohlcv,columns=['timestamp','open','high','low','close','volume'])
                df['datetime']=pd.to_datetime(df['timestamp'],unit='ms')
                if sym!=symbol:
                    print(f"[FALLBACK] {symbol}->{sym}")
                return df
        except: continue
    return (None, f"mexc no symbol {symbol}")
def get_mexc_balance():
    try:
        key=os.environ.get("MEXC_API_KEY","").strip(); sec=os.environ.get("MEXC_API_SECRET","").strip()
        if not key or not sec: return {"ok":False,"error":"No API"}
        ex=ccxt.mexc({'apiKey':key,'secret':sec,'options':{'defaultType':'swap'},'enableRateLimit':True})
        bal=ex.fetch_balance({'type':'swap'}); usdt=bal.get('USDT',{})
        poss=[]
        try:
            for p in ex.fetch_positions():
                if float(p.get('contracts',0) or 0)>0: poss.append(p)
        except: pass
        return {"ok":True,"free":usdt.get('free',0),"total":usdt.get('total',0),"positions":poss}
    except Exception as e: return {"ok":False,"error":str(e)[:150]}
def send_tele(msg, chat_id=None):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    chat=chat_id or os.environ.get("TELEGRAM_CHAT_ID","").strip() or os.environ.get("CHAT_ID","").strip()
    if not token or not chat: return {"ok":False}
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id":chat,"text":msg,"parse_mode":"HTML"}, timeout=10)
        return {"ok":r.status_code==200}
    except: return {"ok":False}
def send_tele_photo(img_bytes, caption, chat_id=None):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    chat=chat_id or os.environ.get("TELEGRAM_CHAT_ID","").strip() or os.environ.get("CHAT_ID","").strip()
    if not token or not chat: return {"ok":False}
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id":chat,"caption":caption,"parse_mode":"HTML"}, files={"photo":("portfolio.png", img_bytes, "image/png")}, timeout=20)
        return {"ok":r.status_code==200}
    except Exception as e: print(f"send_photo err {e}"); return {"ok":False}
def make_portfolio_image(paper, unpnl, closed_pnl, win_rate, win_n, total_n, btc_pnl, gold_pnl, opens):
    # PIL infographic - English only (Thai font not on Render)
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        W,H=1080,1450
        img=Image.new("RGB",(W,H),"#0A0E1A"); d=ImageDraw.Draw(img)
        try:
            f_big=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",56)
            f_mid=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",36)
            f_small=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",28)
        except: f_big=ImageFont.load_default(); f_mid=f_big; f_small=f_big
        d.rounded_rectangle([30,30,W-30,170],radius=24,fill="#1E2A4A")
        d.text((60,55),"G_POWER  PORTFOLIO",font=f_big,fill="white")
        d.text((60,120),f"{datetime.now().strftime('%d/%m %H:%M')}  -  BTC + GOLD  -  PAPER",font=f_small,fill="#8FA3C8")
        def card(x,y,w,h,label,value,color):
            d.rounded_rectangle([x,y,x+w,y+h],radius=20,fill="#141D33")
            d.text((x+30,y+20),label,font=f_small,fill="#8FA3C8")
            d.text((x+30,y+60),value,font=f_mid,fill=color)
        card(30,200,500,170,"PAPER BALANCE",f"${paper:.2f}","white")
        card(550,200,500,170,"UNREALIZED PnL",f"{unpnl:+.2f}","#2ED573" if unpnl>=0 else "#FF4757")
        card(30,390,500,170,"TOTAL CLOSED",f"{closed_pnl:+.2f}","#2ED573" if closed_pnl>=0 else "#FF4757")
        card(550,390,500,170,"WIN RATE",f"{win_rate:.0f}%  ({win_n}/{total_n})","white")
        d.rounded_rectangle([30,580,W-30,880],radius=20,fill="#141D33")
        d.text((60,600),"PnL BY COIN",font=f_mid,fill="white")
        # BTC bar
        d.text((60,660),"BTC",font=f_mid,fill="white")
        bw=int(min(abs(btc_pnl)/max(1,abs(btc_pnl)+abs(gold_pnl))*650,650)) if (btc_pnl!=0 or gold_pnl!=0) else 0
        d.rounded_rectangle([200,660,200+max(bw,20),700],radius=10,fill="#2ED573" if btc_pnl>=0 else "#FF4757")
        d.text((870,660),f"{btc_pnl:+.2f}",font=f_mid,fill="#2ED573" if btc_pnl>=0 else "#FF4757")
        d.text((60,730),"GOLD",font=f_mid,fill="white")
        gw=int(min(abs(gold_pnl)/max(1,abs(btc_pnl)+abs(gold_pnl))*650,650)) if (btc_pnl!=0 or gold_pnl!=0) else 0
        d.rounded_rectangle([200,730,200+max(gw,20),770],radius=10,fill="#2ED573" if gold_pnl>=0 else "#FF4757")
        d.text((300 if gold_pnl>=0 else 300,730),f"{gold_pnl:+.2f}",font=f_mid,fill="#2ED573" if gold_pnl>=0 else "#FF4757")
        d.rounded_rectangle([30,900,W-30,1250],radius=20,fill="#141D33")
        d.text((60,920),f"OPEN  {len(opens)} TRADES",font=f_mid,fill="white")
        y=980
        for o in opens[:5]:
            col="#2ED573" if o['pnl']>=0 else "#FF4757"
            d.text((60,y),f"{o['key']} {o['sig']}",font=f_small,fill="white")
            d.text((360,y),o['txt'],font=f_small,fill="#8FA3C8")
            d.text((820,y),f"{o['pnl']:+.2f}",font=f_small,fill=col)
            y+=50
        d.text((60,1210),"MEXC Paper Only - Not Real Trade",font=f_small,fill="#8FA3C8")
        buf=io.BytesIO(); img.save(buf,format="PNG"); buf.seek(0); return buf.getvalue()
    except Exception as e:
        print(f"make_image err {e}"); return None

def make_chart_image(df, st, symbol_label, price, signal, cond, open_trades, timeframe="15m"):
    # PIL chart - ไม่ใช้ matplotlib จะได้ไม่ต้องเพิ่ม lib บน Render
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        W,H=1080,1450
        img=Image.new("RGB",(W,H),"#0A0E1A"); d=ImageDraw.Draw(img)
        try:
            f_big=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",44)
            f_mid=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",30)
            f_small=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",24)
            f_tiny=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",20)
        except: f_big=ImageFont.load_default(); f_mid=f_big; f_small=f_big; f_tiny=f_big
        cfg=st.config
        # Header
        sig_color="#2ED573" if signal=="LONG" else "#FF4757" if signal=="SHORT" else "#8FA3C8"
        d.rounded_rectangle([30,30,W-30,150],radius=20,fill="#1E2A4A")
        d.text((60,50),f"{symbol_label}  {timeframe}  G_POWER",font=f_big,fill="white")
        d.text((60,105),f"${price:,.2f}  -  {signal}  -  {datetime.now().strftime('%d/%m %H:%M')}",font=f_small,fill=sig_color)
        # Legend
        d.text((60,170),"EMA Fast",font=f_tiny,fill="#2ED573")
        d.text((220,170),f"EMA Slow",font=f_tiny,fill="#FFD700")
        d.text((380,170),"EMA Trend",font=f_tiny,fill="#54A0FF")
        d.text((560,170),"CDC Stop",font=f_tiny,fill="#C56CF0")
        d.text((720,170),"EMA200",font=f_tiny,fill="#9B59B6")
        d.text((850,170),"B Buy  S Short",font=f_tiny,fill="white")
        # Chart area
        cx0,cy0,cx1,cy1=30,210,W-30,750
        d.rounded_rectangle([cx0,cy0,cx1,cy1],radius=16,fill="#141D33")
        # EMA200 สำหรับสไตล์ TradingView ในรูป (BTC 1D ใช้ 200)
        if 'ema200' not in df.columns:
            try: df['ema200']=df['close'].ewm(span=200, adjust=False).mean()
            except: df['ema200']=df['close']
        data=df.tail(80).reset_index(drop=True)
        if len(data)<5: return None
        # FIX: ไม่เอา cdc_stop มาคิดสเกล เพราะ CDC Stop เป็น Trailing ที่ค้างที่ High เก่า ($71k) จะบีบกราฟให้เล็ก
        lo=float(data[['low','ema_trend']].min().min())
        hi=float(data[['high','ema_trend']].max().max())
        # เผื่อเส้นtradesที่ถือ
        for ot in open_trades:
            try:
                lo=min(lo,float(ot.get('entry',lo)),float(ot.get('sl',lo)))
                hi=max(hi,float(ot.get('entry',hi)),float(ot.get('sl',hi)))
            except: pass
        pad=(hi-lo)*0.08 or 1
        lo-=pad; hi+=pad
        def py(p): return cy1 - (p-lo)/(hi-lo)*(cy1-cy0-40) - 10
        def px(i): return cx0+30 + i*(cx1-cx0-60)/max(1,len(data)-1)
        # Grid + ราคา
        for k in range(4):
            yv=cy0+20+k*(cy1-cy0-40)//3
            pv=hi-(hi-lo)*(yv-cy0)/(cy1-cy0)
            d.line([(cx0+10,yv),(cx1-10,yv)],fill="#1E2A4A",width=1)
            d.text((cx1-140,yv-10),f"{pv:,.0f}",font=f_tiny,fill="#8FA3C8")
        # Candles
        cw=(cx1-cx0-60)/max(1,len(data))*0.6
        for i,row in data.iterrows():
            x=px(i)
            o,h,l,c=float(row['open']),float(row['high']),float(row['low']),float(row['close'])
            col="#2ED573" if c>=o else "#FF4757"
            d.line([(x,py(h)),(x,py(l))],fill=col,width=2)
            top,bot=min(py(o),py(c)),max(py(o),py(c))
            if abs(top-bot)<2: bot=top+2
            d.rectangle([x-cw/2,top,x+cw/2,bot],fill=col)
        # EMA lines
        def draw_line(col_name,color,width=3):
            pts=[]
            for i,row in data.iterrows():
                try: pts.append((px(i),py(float(row[col_name]))))
                except: pass
            if len(pts)>1: d.line(pts,fill=color,width=width)
        draw_line('ema_fast',"#2ED573",3)
        draw_line('ema_slow',"#FFD700",3)
        draw_line('ema_trend',"#54A0FF",2)
        draw_line('ema200',"#9B59B6",2)
        # CDC stop dotted
        for i,row in data.iterrows():
            try:
                _cs=float(row['cdc_stop'])
                if lo <= _cs <= hi:
                    x=px(i); y=py(_cs)
                    d.ellipse([x-2,y-2,x+2,y+2],fill="#C56CF0")
            except: pass
        # B/S เฉพาะจุดที่เปิดไม้จริงเท่านั้น (ข้อมูลจริงจาก entry_time / entry)
        # ไม่วาด B/S จากสัญญาณพลิกอีกแล้ว - ที่เห็น S/B มั่วๆ ในรูปเก่ามาจากตรงนี้
        try:
            from datetime import datetime as _dt
            for _ot in open_trades:
                _sig=_ot.get('signal','')
                if _sig not in ('LONG','SHORT'): continue
                _et=str(_ot.get('entry_time','') or '')
                _idx=None
                # หาแท่งที่ตรงกับเวลาเปิดไม้จริงที่สุด (ใน data 80 แท่งที่วาด)
                if _et and 'datetime' in data.columns:
                    try:
                        _t=_dt.fromisoformat(_et.replace('Z',''))
                        _diffs=[abs((_d-_t).total_seconds()) if hasattr(_d,'to_pydatetime') else 1e18 for _d in data['datetime']]
                        # datetime ใน data อาจเป็น pandas Timestamp
                        _diffs=[]
                        for _d in data['datetime']:
                            try: _diffs.append(abs((_d.to_pydatetime()-_t).total_seconds()))
                            except: _diffs.append(abs((pd.to_datetime(_d).to_pydatetime()-_t).total_seconds()))
                        _idx=int(min(range(len(_diffs)), key=lambda k: _diffs[k]))
                        # ถ้าเวลาเปิดไม้ห่างจากหน้าต่างกราฟเกิน 80 แท่ง (>20 ชม. สำหรับ 15m) ให้ไม่วาด B/S บนกราฟ (ยังเห็นเส้น ENTRY อยู่)
                        if _diffs[_idx] > 80*900 and timeframe=='15m': _idx=None
                        if _diffs[_idx] > 80*86400 and timeframe=='1d': _idx=None
                    except: _idx=None
                if _idx is None:
                    # ไม่มีเวลาเปิดไม้ (ไม้เก่า) -> หาแท่งที่ close ใกล้ entry ที่สุด
                    try:
                        _e=float(_ot.get('entry',0))
                        _diffs2=[abs(float(c)-_e) for c in data['close']]
                        _idx=int(min(range(len(_diffs2)), key=lambda k: _diffs2[k]))
                    except: continue
                _x=px(_idx)
                # FIX: B/S ต้องอยู่ที่ราคา Entry เป๊ะๆ ไม่ใช่ High/Low ของแท่ง
                # ถ้า 2 ไม้เปิดในแท่งเดียวกัน ให้ขยับ X ไม่ให้ทับกัน
                if not hasattr(d, '_used_bs_x'): d._used_bs_x={}
                _key=int(_idx)
                _n_same=d._used_bs_x.get(_key, 0)
                d._used_bs_x[_key]=_n_same+1
                _x=_x + _n_same*44
                _e_price=float(_ot.get('entry',0))
                _y=py(_e_price)
                if _sig=='LONG':
                    d.ellipse([_x-16,_y-16,_x+16,_y+16],fill="#2ED573",outline="white",width=2)
                    d.text((_x-6,_y-10),"B",font=f_tiny,fill="white")
                    # Entry ข้างวงกลม S/B ที่ราคา Entry เป๊ะๆ - ถ้า S อยู่ขอบขวาให้ข้อความไปซ้าย จะได้ไม่ทับป้ายราคาขวา
                    _ex=_x-190 if _x > cx1-350 else _x+24
                    d.text((_ex,_y-12+_n_same*24),f"Entry {_e_price:,.0f}",font=f_small,fill="white")
                else:
                    d.ellipse([_x-16,_y-16,_x+16,_y+16],fill="#FF4757",outline="white",width=2)
                    d.text((_x-6,_y-10),"S",font=f_tiny,fill="white")
                    # Entry ข้างวงกลม S/B ที่ราคา Entry เป๊ะๆ - ถ้า S อยู่ขอบขวาให้ข้อความไปซ้าย จะได้ไม่ทับป้ายราคาขวา
                    _ex=_x-190 if _x > cx1-350 else _x+24
                    d.text((_ex,_y-12+_n_same*24),f"Entry {_e_price:,.0f}",font=f_small,fill="white")
        except Exception as _e: print(f"real B/S err {_e}")
        # เส้นtradesที่ถือ: Entry ขาว / SL แดง - ข้อความ ENTRY อยู่คู่กับวงกลม B/S (ตำแหน่งเปิดไม้จริง)
        for _oi, ot in enumerate(open_trades):
            try:
                e=float(ot['entry']); s=float(ot.get('sl',e))
                _tp=float(ot.get('tp',0)) or (e*(1+st.config['tp_pct']) if ot.get('signal')=='LONG' else e*(1-st.config['tp_pct']))
                ye=py(e); ys=py(s); yt=py(_tp)
                # เอาเส้นขาวยาวออกเลยตามที่ขอ - เหลือแค่ตัวเลข Entry ข้าง B/S + แผงล่างก็พอ
                d.line([(cx0+10,ys),(cx1-10,ys)],fill="#FF4757",width=1)
                # หา x ของวงกลม B/S จาก entry_time - ข้อความ ENTRY ต้องอยู่ตรงนั้น ไม่ใช่ขอบซ้าย
                _x_lab=cx0+14
                try:
                    from datetime import datetime as _dt3
                    _et3=str(ot.get('entry_time','') or '')
                    if _et3 and 'datetime' in data.columns:
                        _tt3=_dt3.fromisoformat(_et3.replace('Z',''))
                        _diffs3=[]
                        for _d in data['datetime']:
                            try: _diffs3.append(abs((_d.to_pydatetime()-_tt3).total_seconds()))
                            except: _diffs3.append(abs((pd.to_datetime(_d).to_pydatetime()-_tt3).total_seconds()))
                        _idx3=int(min(range(len(_diffs3)), key=lambda k: _diffs3[k]))
                        _x_lab=px(_idx3)
                except: pass
                # แบบที่ตกลงในรูป: ไม่ใส่ป้ายบนเส้น ENTRY แล้ว - ใส่คำว่า Entry ข้างวงกลม B/S แทน
                # (รายละเอียด ENTRY/SL/TP เต็มๆ อยู่ในแผงล่างแล้ว)
                d.text((cx0+14,ys+4),f"SL ${s:,.0f}",font=f_tiny,fill="#FF4757")
                # no TP label on chart
                # ป้ายราคาจริงด้านขวา - Entry / SL (กันทับกันถ้า 2 ไม้ราคาใกล้กัน)
                try:
                    if not hasattr(d, '_used_right_y'): d._used_right_y=[]
                    def _place_y(_y):
                        # ถ้าชนกับป้ายก่อนหน้า (<28px) ให้ขยับลง 30px
                        for _uy in d._used_right_y:
                            if abs(_y-_uy) < 28: _y=_uy+30
                        d._used_right_y.append(_y)
                        return _y
                    if cy0 <= ye <= cy1:
                        _yy=_place_y(ye)
                        d.rectangle([cx1-105,_yy-12,cx1-8,_yy+12],fill="white")
                        d.text((cx1-100,_yy-10),f"{e:,.0f}",font=f_tiny,fill="black")
                    if cy0 <= ys <= cy1:
                        _yy2=_place_y(ys)
                        d.rectangle([cx1-105,_yy2-12,cx1-8,_yy2+12],fill="#FF4757")
                        d.text((cx1-100,_yy2-10),f"{s:,.0f}",font=f_tiny,fill="white")
                except: pass
            except: pass
        # ป้ายราคาปัจจุบันจริงด้านขวา - สีตามทิศทาง (เขียว LONG / แดง SHORT / เทา WAIT)
        try:
            _yp=py(price)
            if cy0 <= _yp <= cy1:
                # กันชนกับป้าย Entry/SL ที่อยู่ใกล้กัน
                try:
                    for _uy in getattr(d, '_used_right_y', []):
                        if abs(_yp-_uy) < 28: _yp=_uy+30
                except: pass
                _pc="#2ED573" if signal=="LONG" else "#FF4757" if signal=="SHORT" else "#8FA3C8"
                d.rectangle([cx1-105,_yp-13,cx1-8,_yp+13],fill=_pc)
                d.text((cx1-100,_yp-11),f"{price:,.0f}",font=f_tiny,fill="white" if signal!="WAIT" else "black")
        except: pass
        # แผง ADX / +DI / -DI - ใช้ดูจุดเข้าไม้ถูก/ผิด TF 15m
        # กลยุทธ์ G_POWER ใช้ ADX+DI เป็นตัวตัดสินใจหลัก: ADX>min + DI ฝั่งที่เข้า > อีกฝั่ง + >di_min
        rx0,ry0,rx1,ry1=30,770,W-30,900
        d.rounded_rectangle([rx0,ry0,rx1,ry1],radius=16,fill="#141D33")
        try:
            # ADX/DI ต้องเป็นของจริง - ถ้าแบน/NaN คำนวณใหม่จาก high/low/close จริง (สูตรเดียวกับ strategy)
            try:
                import pandas as _pd, numpy as _np
                for _c in ['plus_di','minus_di','adx']:
                    if _c not in data.columns or data[_c].astype(float).isna().all() or float(data[_c].astype(float).std() or 0) < 0.1:
                        _up=data['high'].diff(); _dn=-data['low'].diff()
                        _pdm=_pd.Series([u if (u>d and u>0) else 0 for u,d in zip(_up,_dn)], index=data.index).ewm(alpha=1/14, adjust=False).mean()
                        _mdm=_pd.Series([d if (d>u and d>0) else 0 for u,d in zip(_up,_dn)], index=data.index).ewm(alpha=1/14, adjust=False).mean()
                        _tr=_pd.concat([data['high']-data['low'],(data['high']-data['close'].shift()).abs(),(data['low']-data['close'].shift()).abs()],axis=1).max(axis=1).ewm(alpha=1/14, adjust=False).mean()
                        data['plus_di']=100*_pdm/_tr; data['minus_di']=100*_mdm/_tr
                        _dx=100*(data['plus_di']-data['minus_di']).abs()/(data['plus_di']+data['minus_di']).replace(0,_np.nan)
                        data['adx']=_dx.ewm(alpha=1/14, adjust=False).mean().fillna(15)
                        break
            except Exception as _e: print(f"adx recompute err {_e}")
            _adx=float(data.iloc[-1]['adx']); _pdi=float(data.iloc[-1]['plus_di']); _mdi=float(data.iloc[-1]['minus_di'])
            _adx_min=cfg.get('adx_min',10); _di_min=cfg.get('di_min',10)
            d.text((60,778),f"ADX {_adx:.1f}  +DI {_pdi:.1f}  -DI {_mdi:.1f}  (min {_adx_min}/{_di_min})",font=f_tiny,fill="white")
            d.text((rx1-260,778),"ADX  +DI  -DI",font=f_tiny,fill="#8FA3C8")
            def apy(v): return ry1-8 - max(0,min(60,v))/60*(ry1-ry0-50)
            # เส้น ADX min (10/12) + เส้น 20
            for _lvl,_col in [(_adx_min,"#8FA3C8"),(20,"#8FA3C8")]:
                _y=apy(_lvl)
                for _x in range(rx0+10,rx1-10,14): d.line([(_x,_y),(_x+7,_y)],fill=_col,width=1)
                d.text((rx1-55,_y-10),str(_lvl),font=f_tiny,fill="#8FA3C8")
            _n=len(data)
            for _col_name,_col in [('adx',"#54A0FF"),('plus_di',"#2ED573"),('minus_di',"#FF4757")]:
                _vals=data[_col_name].astype(float).clip(0,60).tolist()
                _pts=[(cx0+30+i*(cx1-cx0-60)/max(1,_n-1), apy(v)) for i,v in enumerate(_vals)]
                if len(_pts)>1: d.line(_pts,fill=_col,width=2)
            # จุด B/S บนแผง ADX ด้วย - จะได้เห็นตอนเปิดไม้ ADX/DI เป็นยังไง (ถูก/ผิด)
            _used_adx_x={}
            for _ot in open_trades:
                _et=str(_ot.get('entry_time','') or '')
                try:
                    from datetime import datetime as _dt2
                    if _et and 'datetime' in data.columns:
                        _tt=_dt2.fromisoformat(_et.replace('Z',''))
                        _diffs=[]
                        for _d in data['datetime']:
                            try: _diffs.append(abs((_d.to_pydatetime()-_tt).total_seconds()))
                            except: _diffs.append(abs((pd.to_datetime(_d).to_pydatetime()-_tt).total_seconds()))
                        _idx=int(min(range(len(_diffs)), key=lambda k: _diffs[k]))
                        _x=cx0+30+_idx*(cx1-cx0-60)/max(1,_n-1)
                        # ถ้า 2 ไม้แท่งเดียวกัน ขยับไม่ให้ทับกัน
                        _c=_used_adx_x.get(int(_idx),0); _used_adx_x[int(_idx)]=_c+1; _x=_x+_c*32
                        _sig2=_ot.get('signal','')
                        _col2="#2ED573" if _sig2=='LONG' else "#FF4757"
                        _lab="B" if _sig2=='LONG' else "S"
                        d.ellipse([_x-12,apy(float(data.iloc[_idx]['adx']))-12,_x+12,apy(float(data.iloc[_idx]['adx']))+12],fill=_col2,outline="white",width=1)
                        d.text((_x-5,apy(float(data.iloc[_idx]['adx']))-9),_lab,font=f_tiny,fill="white")
                except: pass
        except Exception as e: print(f"adx panel err {e}")
        # แผง ENTRY / SL / TP - ตกลง: กราฟเดิม เปลี่ยนแค่ตรงนี้
        d.rounded_rectangle([30,920,W-30,1350],radius=20,fill="#141D33")
        d.text((60,940),"ENTRY / SL / TP",font=f_mid,fill="white")
        _sl_pct=st.config.get('sl_pct',0.034); _tp_pct=st.config.get('tp_pct',0.18)
        rows=[]
        if open_trades:
            for _i,_ot in enumerate(open_trades):
                _e=float(_ot.get('entry',price)); _s=float(_ot.get('sl',_e))
                _tp=float(_ot.get('tp',0)) or (_e*(1+_tp_pct) if _ot.get('signal')=='LONG' else _e*(1-_tp_pct))
                _sig=_ot.get('signal','')
                _pnl = (price-_e)/_e*100 if _sig=='LONG' else (_e-price)/_e*100
                _sl_d = (_s-_e)/_e*100 if _sig=='LONG' else (_e-_s)/_e*100  # ระยะ SL จาก Entry (ติดลบถ้า LONG, บวกถ้า SHORT - ใช้ abs ในแสดงผล)
                _sl_abs = abs(_s-_e)/_e*100; _tp_abs = abs(_tp-_e)/_e*100
                # 1 ไม้ = 1 บรรทัดหลักตามที่ตกลง: SHORT 63617 SL 64167 TP 52166 NOW 63367
                rows.append((f"{_sig}  {_e:,.0f}  SL {_s:,.0f}  TP {_tp:,.0f}  NOW {price:,.0f}", "#2ED573" if _sig=='LONG' else "#FF4757"))
                rows.append((f"PnL {_pnl:+.2f}%  |  SL {_sl_abs:.2f}%  |  TP {_tp_abs:.2f}%  |  RR {_tp_abs/max(_sl_abs,0.01):.1f}R", "#FFA502"))
        else:
            _l_sl=price*(1-_sl_pct); _l_tp=price*(1+_tp_pct)
            _s_sl=price*(1+_sl_pct); _s_tp=price*(1-_tp_pct)
            rows.append((f"No Open Trade - Plan at NOW {price:,.0f}", "white"))
            rows.append((f"LONG  {price:,.0f}  SL {_l_sl:,.0f}  TP {_l_tp:,.0f}  NOW {price:,.0f}", "#2ED573"))
            rows.append((f"SHORT  {price:,.0f}  SL {_s_sl:,.0f}  TP {_s_tp:,.0f}  NOW {price:,.0f}", "#FF4757"))
            rows.append((f"RR {_tp_pct/max(_sl_pct,0.001):.1f}R  -  SL {_sl_pct*100:.1f}% / TP {_tp_pct*100:.0f}%", "#FFA502"))
        y=990
        for txt,col in rows:
            d.text((60,y),txt,font=f_small,fill=col)
            y+=42
        d.text((60,1370),"MEXC Paper Only - Not Real Trade  |  /chart btc  /chart gold  /chart all",font=f_tiny,fill="#8FA3C8")
        buf=io.BytesIO(); img.save(buf,format="PNG"); buf.seek(0); return buf.getvalue()
    except Exception as e:
        print(f"make_chart err {e}")
        import traceback; traceback.print_exc()
        return None



def send_chart_on_open(symbol, r, df=None):
    # ส่งกราฟทันทีเมื่อเปิดไม้ใหม่ - เรียกจาก /check /port /info /auto/run
    try:
        st=get_strat(symbol)
        if df is None:
            df=get_data(symbol)
            if isinstance(df,tuple): return
            df=st.add_indicators(df)
        trades=load_trades()
        kk=st.symbol_key
        opens=[x for x in trades if x.get("symbol_key")==kk and str(x.get("status")).upper() in ["OPEN","PAPER_OPEN","PAPER"]]
        o_list=[{"signal":o.get("signal",""),"entry":float(o.get("entry",0)),"sl":float(o.get("sl",o.get("entry",0))),"tp":float(o.get("tp",0)),"entry_time":o.get("entry_time","")} for o in opens]
        img=make_chart_image(df, st, symbol, float(r.get("price", df.iloc[-1]["close"])), r.get("signal","WAIT"), r, o_list)
        sig=r.get("signal","")
        cap=f"🚀 OPEN {sig} {symbol} ${r.get('price',0):,.2f} SL ${r.get('price',0)*(1-st.config['sl_pct']) if sig=='LONG' else r.get('price',0)*(1+st.config['sl_pct']):,.2f} ADX {r.get('adx',0):.1f} +DI {r.get('plus_di',0):.1f} -DI {r.get('minus_di',0):.1f} Retest {'✅' if r.get('retest') else '❌'}"
        if img: send_tele_photo(img, cap, None)
        else: send_tele(cap, None)
    except Exception as e: print(f"send_chart_on_open err {e}")

def get_strat(symbol):
    s=symbol.upper()
    if 'BTC' in s: return STRATS['btc']
    if 'XAU' in s or 'PAXG' in s or 'GOLD' in s or 'XAUT' in s: return STRATS['gold']
    return STRATS['btc']
def execute_symbol(symbol, manage_open=True):
    try:
        st=get_strat(symbol)
        symbol_key=st.symbol_key
        df=get_data(symbol)
        if isinstance(df,tuple): return {"ok":False,"symbol":symbol,"error":df[1]}
        df=st.add_indicators(df)
        for _c,_d in [('ema_fast',df['ema12'] if 'ema12' in df.columns else df['close']),('ema_slow',df['ema26'] if 'ema26' in df.columns else df['close']),('plus_di',0.0),('minus_di',0.0),('adx',15.0),('cdc_up',True),('cdc_stop',df['close'])]: df[_c]=_d if _c not in df.columns else df[_c]
        curr=df.iloc[-1]; prev=df.iloc[-2]
        price=float(curr['close'])
        trades=load_trades()
        open_trades=[t for t in trades if t.get('symbol')==symbol and str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
        actions=[]
        for ot in open_trades:
            entry=float(ot['entry']); sig=ot['signal']
            new_sl=st.get_trailing_sl(entry, price, float(curr['cdc_stop']), sig)
            old_sl=float(ot.get('sl', entry*(1-st.config['sl_pct']) if sig=='LONG' else entry*(1+st.config['sl_pct'])))
            if sig=='LONG' and new_sl>old_sl:
                ot['sl']=new_sl; ot['trailing']=f"Trail {old_sl:.0f}->{new_sl:.0f}"; actions.append(f"Trailing LONG {symbol} SL {old_sl:.0f}->{new_sl:.0f}")
            elif sig=='SHORT' and new_sl<old_sl:
                ot['sl']=new_sl; ot['trailing']=f"Trail {old_sl:.0f}->{new_sl:.0f}"; actions.append(f"Trailing SHORT {symbol} SL {old_sl:.0f}->{new_sl:.0f}")
            exit_info=st.check_exit_trend_change(curr, prev, sig)
            if exit_info['tp']:
                ot['status']='CLOSED'; ot['result']='WIN' if (price>entry and sig=='LONG') or (price<entry and sig=='SHORT') else 'LOSS'
                ot['exit']=price; ot['exit_time']=datetime.now().isoformat(); ot['exit_reason']='TREND CHANGE: '+','.join(exit_info['reasons'])
                pnl=(price-entry)/entry*ot.get('position_size',0) if sig=='LONG' else (entry-price)/entry*ot.get('position_size',0)
                ot['pnl_usd']=pnl
                actions.append(f"TP TREND CHANGE {symbol} {sig} {','.join(exit_info['reasons'])} PnL ${pnl:+.2f}")
        if actions:
            save_trades(trades)
        rev=st.check_reversal(prev,curr)
        trend=st.check_trend(curr)
        mom=st.check_momentum(curr)
        signal="WAIT"
        # V5.2.4 PYRAMID: เข้าเพิ่มได้ถ้ามีจังหวะดี จาก 1 เป็น 3 trades
        can_open=len(open_trades) < MAX_POS_PER_SYMBOL and can_open_new(symbol_key, cooldown_hours=COOLDOWN_HOURS)
        if len(open_trades)>0 and can_open:
            existing_sig=open_trades[0]['signal']
            if (trend['long'] and existing_sig!='LONG') or (trend['short'] and existing_sig!='SHORT'):
                can_open=False  # ไม่เพิ่มtradesสวนทาง
        if can_open and not trend['sideway']:
            # V5.2.2 PULLBACK ENTRY: ไม่ต้องWAIT cross ทุกครั้ง
            if trend['long'] and mom['long']:
                signal="LONG"
            elif trend['short'] and mom['short']:
                signal="SHORT"
        elif not can_open:
            if len(open_trades)>=MAX_POS_PER_SYMBOL:
                signal=f"MAX {len(open_trades)}/{MAX_POS_PER_SYMBOL} HOLD {open_trades[0]['signal']}"
            elif len(open_trades)>0:
                signal=f"HOLD {open_trades[0]['signal']} {len(open_trades)}/{MAX_POS_PER_SYMBOL}"
            else:
                signal="COOLDOWN"
        if signal in ['LONG','SHORT'] and can_open:
            pos_info=calc_position(symbol_key)
            new_trade={
                "id":len(trades)+1,
                "symbol":symbol,
                "symbol_key":symbol_key,
                "signal":signal,
                "entry":price,
                "entry_time":datetime.now().isoformat(),
                "position_size":pos_info['pos'],
                "sl":price*(1-st.config['sl_pct']) if signal=='LONG' else price*(1+st.config['sl_pct']),
                "tp":price*(1+st.config['tp_pct']) if signal=='LONG' else price*(1-st.config['tp_pct']),
                "status":"PAPER_OPEN",
                "real":False,
                "note":f"V5.2.2 pullback rev:{rev['long'] or rev['short']}"
            }
            trades.append(new_trade)
            save_trades(trades)
            set_last_trade_time(symbol_key)
            actions.append(f"OPEN {signal} {symbol} ${price:.2f} SL {new_trade['sl']:.2f}")
        _is_new = any(a.startswith("OPEN ") for a in actions)
        return {"ok":True,"symbol":symbol,"symbol_key":symbol_key,"signal":signal,"price":price,"new_trade":_is_new,
                "plus_di":float(curr['plus_di']),"minus_di":float(curr['minus_di']),"adx":float(curr['adx']),
                "cdc_up":bool(curr['cdc_up']),"cdc_stop":float(curr['cdc_stop']),
                "adx":float(curr['adx']), "plus_di":float(curr['plus_di']), "minus_di":float(curr['minus_di']),"ema_fast":float(curr['ema_fast']),"ema_slow":float(curr['ema_slow']),
                "retest":bool(trend.get('retest')),
                "sl_pct":st.config['sl_pct']*100,"tp_pct":st.config['tp_pct']*100,
                "actions":actions, "can_open":can_open, "open_count":len(open_trades),
                "sideway":bool(trend.get('sideway')), "long":bool(trend.get('long')), "short":bool(trend.get('short')),
                "rev_long":bool(rev.get('long')), "rev_short":bool(rev.get('short')),
                "mom_long":bool(mom.get('long')), "mom_short":bool(mom.get('short'))}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"ok":False,"symbol":symbol,"error":str(e)[:300]}
@app.post("/telegram/webhook")
async def webhook(request: Request):
    try:
        data=await request.json()
        msg=data.get('message',{}) or data.get('edited_message',{})
        chat_id=str(msg.get('chat',{}).get('id',''))
        text=msg.get('text','').strip(); tl=text.lower()
        allowed=os.environ.get("CHAT_ID","").strip() or os.environ.get("TELEGRAM_CHAT_ID","").strip()
        if allowed and chat_id!=str(allowed):
            try: send_tele("CHAT_ID ไม่ตรง คุณพิมพ์จาก ID: " + str(chat_id) + " แต่ใน Render = " + str(allowed), chat_id=chat_id)
            except: pass
            return {"ok":True}
        if not text: return {"ok":True}
        def parse_sym(a):
            a=a.lower()
            return {'btc':('btc',SYMBOLS['btc']),'gold':('gold',SYMBOLS['gold']),'all':('all',None)}.get(a,('unknown',None))
        if tl.startswith('/check'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            if key=="unknown": send_tele(f"❓ ไม่มีเหรียญ {parts[1]} แล้ว มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            results={}
            for k in ['btc','gold']:
                if key!='all' and k!=key: continue
                results[k]=execute_symbol(SYMBOLS[k])
            trades=load_trades(); auto=get_auto_state(); bal=get_mexc_balance()
            out=f"📊 <b>G_POWER V5.2.2 CHECK {key.upper()}</b> {datetime.now().strftime('%d/%m %H:%M')}\n"
            for k,r in results.items():
                if not r.get('ok'): out+=f"\n{k.upper()} ❌ {r.get('error')}\n"
                else:
                    cfg=STRATS[k].config
                    out+=f"\n<b>{k.upper()} {r['symbol']}</b> {'🟢 ON' if auto.get(k) else '🔴 OFF'} {r['signal']}\n${r['price']:,.2f} CDC {'🟢' if r['cdc_up'] else '🔴'} Stop ${r['cdc_stop']:,.2f}\nEMA{cfg['ema_fast']}/{cfg['ema_slow']} +DI {r['plus_di']:.1f} -DI {r['minus_di']:.1f} ADX {r['adx']:.1f}\nRetest {'✅' if r['retest'] else '❌'} Sideway {'❌' if not r.get('sideway') else '✅'} Trend Long {r.get('long')} Mom {r.get('mom_long') or r.get('mom_short')} Rev {r.get('rev_long') or r.get('rev_short')} CanOpen {'✅' if r['can_open'] else '❌'} Open {r['open_count']} SL {r['sl_pct']:.1f}% TP {r['tp_pct']:.0f}%\n"
                    if r['actions']: out+=f"⚡ {'; '.join(r['actions'])}\n"
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            if opens:
                out+=f"\n📌 ถือ {len(opens)} trades:\n"
                for ot in opens[-3:]:
                    entry=float(ot['entry']); curr_p=results.get(ot.get('symbol_key','btc'),{}).get('price',entry)
                    sig=ot['signal']; ps=ot.get('position_size',0)
                    if sig=='LONG': upnl=(curr_p-entry)/entry*ps if entry else 0; upp=(curr_p-entry)/entry*100 if entry else 0
                    else: upnl=(entry-curr_p)/entry*ps if entry else 0; upp=(entry-curr_p)/entry*100 if entry else 0
                    sl=ot.get('sl',0)
                    out+=f"{sig} {ot['symbol']} Entry ${entry:,.2f} Now ${curr_p:,.2f} UnPnL ${upnl:+.2f} ({upp:+.1f}%) SL ${sl:,.2f} {ot.get('trailing','')}\n"
            else: out+=f"\n📌 ไม่มีtradesถืออยู่ - WAIT\n"
            if bal.get('ok'): out+=f"\n🏦 MEXC {bal.get('total')} USDT | Pos {len(bal.get('positions',[]))}\n"
            out+=f"\n✅ V5.2.2 VOL 0.25 + PULLBACK + BTC+GOLD FIX\n💡 1.Retest 2.Trailing 3.TP Trend"
            send_tele(out, chat_id)
            # AUTO: เปิดไม้ใหม่ -> ส่งกราฟทันที
            for _k,_r in results.items():
                if _r.get('new_trade'): send_chart_on_open(_r.get('symbol'), _r)
            return {"ok":True}
        elif tl.startswith('/total') or tl.startswith('/portfolio') or tl.startswith('/port'):
            trades=load_trades(); bal=get_mexc_balance()
            results={}
            for k in ['btc','gold']:
                try: results[k]=execute_symbol(SYMBOLS[k])
                except: results[k]={'ok':False}
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            closeds=[t for t in trades if str(t.get('status')).upper()=='CLOSED']
            total_closed=sum([float(t.get('pnl_usd',0)) for t in closeds])
            out=f"PORTFOLIO {datetime.now().strftime('%d/%m %H:%M')} MEXC {bal.get('total',0) if bal.get('ok') else 0} USDT\n"
            if opens:
                total_upnl=0
                for ot in opens:
                    entry=float(ot['entry']); ps=float(ot.get('position_size',0)); key=ot.get('symbol_key','btc'); curr_p=results.get(key,{}).get('price',entry); sig=ot['signal']
                    upnl=(curr_p-entry)/entry*ps if sig=='LONG' else (entry-curr_p)/entry*ps
                    total_upnl+=upnl
                    out+=f"{sig} {ot['symbol']} ${entry:,.2f} -> ${curr_p:,.2f} PnL ${upnl:+.2f}\n"
                out+=f"UnPnL {total_upnl:+.2f} Paper ${40+total_closed+total_upnl:.2f}\n"
            else: out+=f"ไม่มีtradesถืออยู่ Paper ${40+total_closed:.2f}\n"
            # ส่งรูปอินโฟกราฟฟิกด้วย
            total_upnl_safe = total_upnl if opens else 0
            try:
                btc_p=sum([float(t.get('pnl_usd',0)) if t.get('symbol_key')=='btc' else 0 for t in closeds])
                gold_p=sum([float(t.get('pnl_usd',0)) if t.get('symbol_key')=='gold' else 0 for t in closeds])
                # รวม UnPnL เข้าไปด้วย
                for ot in opens:
                    entry=float(ot['entry']); ps=float(ot.get('position_size',0)); key2=ot.get('symbol_key','btc'); curr_p=results.get(key2,{}).get('price',entry); sig2=ot['signal']
                    up2=(curr_p-entry)/entry*ps if sig2=='LONG' else (entry-curr_p)/entry*ps
                    if key2=='btc': btc_p+=up2
                    else: gold_p+=up2
                wins=len([t for t in closeds if float(t.get('pnl_usd',0))>0])
                tot_c=len(closeds) if closeds else len(opens)
                wr=(wins/len(closeds)*100) if closeds else (100 if total_upnl_safe>0 else 0)
                opens_info=[]
                for ot in opens:
                    entry=float(ot['entry']); ps=float(ot.get('position_size',0)); key2=ot.get('symbol_key','btc'); curr_p=results.get(key2,{}).get('price',entry); sig2=ot['signal']
                    up2=(curr_p-entry)/entry*ps if sig2=='LONG' else (entry-curr_p)/entry*ps
                    opens_info.append({"key":key2.upper(),"sig":sig2,"txt":f"${entry:,.0f} -> ${curr_p:,.0f}","pnl":up2})
                paper_val=40+total_closed+total_upnl_safe
                img_bytes=make_portfolio_image(paper_val, total_upnl_safe, total_closed, wr, wins, len(closeds) if closeds else len(opens), btc_p, gold_p, opens_info)
                if img_bytes: send_tele_photo(img_bytes, out, chat_id)
                else: send_tele(out, chat_id)
                for _k,_r in results.items():
                    if isinstance(_r, dict) and _r.get('new_trade'): send_chart_on_open(_r.get('symbol'), _r)
            except Exception as e: print(f"portfolio img err {e}"); send_tele(out, chat_id)
            return {'ok':True}
        elif tl.startswith('/info') or tl.startswith('/infographic'):
            trades=load_trades(); bal=get_mexc_balance(); results={}
            for k in ['btc','gold']:
                try: results[k]=execute_symbol(SYMBOLS[k])
                except: results[k]={'ok':False}
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            closeds=[t for t in trades if str(t.get('status')).upper()=='CLOSED']
            total_closed=sum([float(t.get('pnl_usd',0)) for t in closeds])
            total_upnl=0; opens_info=[]
            btc_p=sum([float(t.get('pnl_usd',0)) if t.get('symbol_key')=='btc' else 0 for t in closeds]); gold_p=sum([float(t.get('pnl_usd',0)) if t.get('symbol_key')=='gold' else 0 for t in closeds])
            for ot in opens:
                entry=float(ot['entry']); ps=float(ot.get('position_size',0)); key2=ot.get('symbol_key','btc'); curr_p=results.get(key2,{}).get('price',entry); sig2=ot['signal']; up2=(curr_p-entry)/entry*ps if sig2=='LONG' else (entry-curr_p)/entry*ps; total_upnl+=up2
                opens_info.append({'key':key2.upper(),'sig':sig2,'txt':f"${entry:,.0f} -> ${curr_p:,.0f}",'pnl':up2})
                btc_p+=up2 if key2=='btc' else 0; gold_p+=up2 if key2=='gold' else 0
            wins=len([t for t in closeds if float(t.get('pnl_usd',0))>0]); wr=(wins/len(closeds)*100) if closeds else (100 if total_upnl>0 else 0)
            paper_val=40+total_closed+total_upnl
            img_bytes=make_portfolio_image(paper_val,total_upnl,total_closed,wr,wins,len(closeds) if closeds else len(opens),btc_p,gold_p,opens_info)
            cap=f"G_POWER PORTFOLIO {datetime.now().strftime('%d/%m %H:%M')} Paper ${paper_val:.2f} UnPnL {total_upnl:+.2f}"
            
            send_tele_photo(img_bytes,cap,chat_id) if img_bytes else send_tele('สร้างรูปไม่ได้',chat_id)
            for _k,_r in results.items():
                if isinstance(_r, dict) and _r.get('new_trade'): send_chart_on_open(_r.get('symbol'), _r)
            return {'ok':True}
        elif tl.startswith('/chart'):
            parts=tl.split(); key='btc' if len(parts)<2 else parse_sym(parts[1])[0]
            tf='15m'
            if len(parts)>=3 and parts[2].lower() in ['15m','1h','4h','1d','1w']: tf=parts[2].lower()
            elif len(parts)>=3 and parts[2].lower() in ['15','60','240']: tf={'15':'15m','60':'1h','240':'4h'}[parts[2].lower()]
            if key=="unknown": send_tele(f"❓ ไม่มีเหรียญ {parts[1]} แล้ว มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            keys=['btc','gold'] if key=='all' else [key]
            for kk in keys:
                try:
                    sym=SYMBOLS[kk]; st=STRATS[kk]
                    df=get_data(sym, tf)
                    if isinstance(df,tuple): send_tele(f"{kk.upper()} ❌ {df[1]}", chat_id); continue
                    df2=st.add_indicators(df)
                    r=execute_symbol(sym)
                    trades=load_trades()
                    opens=[t for t in trades if t.get('symbol_key')==kk and str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
                    # ดึง open trades ให้เป็น entry/sl สำหรับวาดเส้น
                    o_list=[]
                    for ot in opens:
                        o_list.append({'signal':ot.get('signal',''),'entry':float(ot.get('entry',0)),'sl':float(ot.get('sl',ot.get('entry',0))),'tp':float(ot.get('tp',0)),'entry_time':ot.get('entry_time','')})
                    img_bytes=make_chart_image(df2, st, sym, float(r.get('price', df2.iloc[-1]['close'])), r.get('signal','WAIT'), r, o_list, tf)
                    cap=f"📈 {sym} {tf} ${r.get('price',0):,.2f} {r.get('signal','WAIT')} ADX {r.get('adx',0):.1f} +DI {r.get('plus_di',0):.1f} -DI {r.get('minus_di',0):.1f} CDC {'UP' if r.get('cdc_up') else 'DOWN'} Retest {'✅' if r.get('retest') else '❌'} Open {r.get('open_count',0)}"
                    if img_bytes: send_tele_photo(img_bytes, cap, chat_id)
                    else: send_tele(cap+"\n(สร้างรูปกราฟไม่ได้)", chat_id)
                except Exception as e: send_tele(f"{kk.upper()} CHART Error: {e}", chat_id)
            return {"ok":True}
        elif tl.startswith('/close'):
            trades=load_trades(); opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            if not opens: send_tele('ไม่มีtradesถืออยู่', chat_id); return {'ok':True}
            results={}
            for k in ['btc','gold']:
                try: results[k]=execute_symbol(SYMBOLS[k])
                except: results[k]={'ok':False}
            total=0; out=f"CLOSE ALL {len(opens)} trades\n"
            for ot in opens:
                key=ot.get('symbol_key','btc'); curr_p=results.get(key,{}).get('price', ot.get('entry')); entry=float(ot['entry']); sig=ot['signal']; ps=float(ot.get('position_size',0))
                pnl=(curr_p-entry)/entry*ps if sig=='LONG' else (entry-curr_p)/entry*ps
                total+=pnl; ot['status']='CLOSED'; ot['result']='WIN' if pnl>0 else 'LOSS'; ot['exit']=curr_p; ot['exit_time']=datetime.now().isoformat(); ot['exit_reason']='MANUAL CLOSE'; ot['pnl_usd']=pnl
                out+=f"{sig} {ot['symbol']} PnL ${pnl:+.2f}\n"
            save_trades(trades); set_auto_state('all', False)
            out+=f"รวม PnL ${total:+.2f} Auto OFF แล้ว"
            send_tele(out, chat_id); return {'ok':True}
        elif tl.startswith('/reset'):
            trades=load_trades(); opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            if opens: send_tele(f"ยังถือ {len(opens)} tradesอยู่! พิมพ์ /close all ก่อน", chat_id); return {'ok':True}
            try:
                for f in ['/data/g_power_trades.json','/data/auto_state.json']:
                    try:
                        if os.path.exists(f): os.remove(f)
                    except: pass
                save_trades([]); set_auto_state('all', False)
            except Exception as e: send_tele(f"RESET Error: {e}", chat_id); return {'ok':True}
            send_tele('ล้างไพ่เรียบร้อย Paper $40.00 Auto OFF - พิมพ์ /on all เพื่อเริ่มใหม่', chat_id); return {'ok':True}
        elif tl.startswith('/on'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            if key=="unknown": send_tele(f"❓ ไม่มีเหรียญ {parts[1]} แล้ว มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            set_auto_state(key, True)
            send_tele(f"🟢 Auto ON {key.upper()} {datetime.now().strftime('%d/%m %H:%M')} V5.2.2 PULLBACK", chat_id)
            return {"ok":True}
        elif tl.startswith('/off'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            if key=="unknown": send_tele(f"❓ ไม่มีเหรียญ {parts[1]} แล้ว มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            set_auto_state(key, False)
            send_tele(f"🔴 Auto OFF {key.upper()}", chat_id)
            return {"ok":True}
        else:
            send_tele(f"❓ {text}\n/check [btc|gold|all]\n/chart [btc|gold|all] [15m|1h|4h|1d] = กราฟ TradingView + EMA200 + ADX/DI\n/on [btc|gold|all]\n/off [btc|gold|all]\n/portfolio = รูปสรุปพอร์ต\n/info = รูปอย่างเดียว\n/live [btc|gold]", chat_id)
            return {"ok":True}
    except Exception as e:
        print(f"ERR {e}"); return {"ok":True}
@app.on_event("startup")
async def auto_set_webhook():
    import requests, os
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
    import requests, os
    token = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    if not token: return {"ok":False,"error":"No BOT_TOKEN"}
    url = "https://mexc-btc-bot-1.onrender.com/telegram/webhook"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook?url={url}", timeout=10)
        return {"ok":r.status_code==200,"telegram":r.json(),"set_to":url}
    except Exception as e: return {"ok":False,"error":str(e)[:200]}
@app.get("/webhook_info")
def webhook_info():
    import requests, os
    token = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    if not token: return {"ok":False,"error":"No BOT_TOKEN"}
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10)
        return r.json()
    except Exception as e: return {"ok":False,"error":str(e)[:200]}
@app.get("/test_send")
def test_send():
    r = send_tele("TEST จาก Render - ถ้าเห็นข้อความนี้ = BOT_TOKEN + CHAT_ID ถูกแล้ว")
    return {"sent":r}
@app.api_route("/ping", methods=["GET","HEAD"])
def ping():
    return {"status":"ok V5.6.1.1 NO HEDGE + CLOSE CIRCLE","auto":get_auto_state(),"dir":str(DATA_DIR),"trades":len(load_trades())}
@app.get("/", response_class=HTMLResponse)
def home():
    auto=get_auto_state()
    return f"<html><body style='background:#0a0e1a;color:#fff;font-family:Arial;padding:20px'><h1>G_POWER V5.2.3 BTC+GOLD 2COINS</h1><p>BTC {'🟢' if auto.get('btc') else '🔴'} GOLD {'🟢' if auto.get('gold') else '🔴'}</p><p>✅ VOL 0.25 | PULLBACK ENTRY | BTC+GOLD FIX</p><a href='/ping'>Ping</a></body></html>"
