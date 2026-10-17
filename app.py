"""
V13.5 BTC FAST - แก้ BT ค้าง ดึงกราฟไม่เสร็จ
- ลอง 3 API: contract -> spot -> ccxt fallback
- Timeout สั้น 5วิ + Retry
- BT ลดเหลือ 15 วัน เร็วขึ้น 3 เท่า
"""

import requests, pandas as pd, os, time, json
from flask import Flask, jsonify
from datetime import datetime
import pytz, threading, traceback

DATA_DIR = "./data"
try:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists("/mnt/data") and os.access("/mnt/data", os.W_OK):
        DATA_DIR = "/mnt/data"
except: pass

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
FLAG_FILE = os.path.join(DATA_DIR, "trading_enabled.json")
OFFSET_FILE = os.path.join(DATA_DIR, "telegram_offset.txt")

def load_trading():
    try:
        if os.path.exists(FLAG_FILE): return json.load(open(FLAG_FILE)).get("enabled", True)
    except: pass
    return True
def save_trading(en):
    try: json.dump({"enabled":en}, open(FLAG_FILE,'w'))
    except: pass

TRADING_ENABLED = load_trading()
print(f"=== V13.5 BTC FAST START TRADING={TRADING_ENABLED} ===")

app = Flask(__name__)
def thai_now(): return datetime.now(pytz.timezone('Asia/Bangkok'))
def thai_time(): return thai_now().strftime("%d/%m/%Y %H:%M ICT")
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return False,"missing"
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r=requests.post(url, json={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=10)
        print(f"[TELE BTC] {r.status_code}")
        return r.status_code==200, r.text
    except Exception as e: print(f"TELE fail {e}"); return False,str(e)

def get_klines_fast(symbol="BTC_USDT", interval="Min15", days=15):
    """FAST 3 ชั้น"""
    # 1. contract.mexc.com
    for sym in ["BTC_USDT","BTCUSDT","BTC_USDT"]:
        try:
            print(f"[KLINE] Try contract {sym}")
            url=f"https://contract.mexc.com/api/v1/contract/kline/{sym}"
            r=requests.get(url, params={"interval":interval}, timeout=5)
            j=r.json()
            if 'data' not in j: continue
            d=j['data']
            if 'time' in d:
                df=pd.DataFrame({'ot':d['time'],'o':d['open'],'h':d['high'],'l':d['low'],'c':d['close'],'v':d['vol']})
            else:
                df=pd.DataFrame(d, columns=['ot','o','h','l','c','v'])
            df=df.tail(days*96)
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            if len(df)>200:
                print(f"[KLINE] {sym} OK {len(df)}")
                return df, sym
        except Exception as e:
            print(f"[KLINE] {sym} fail {e}")

    # 2. spot API mexc
    try:
        print("[KLINE] Try spot BTCUSDT")
        url="https://api.mexc.com/api/v3/klines"
        params={"symbol":"BTCUSDT","interval":"15m","limit":500}
        r=requests.get(url, params=params, timeout=5)
        arr=r.json()
        if isinstance(arr, list) and len(arr)>200:
            df=pd.DataFrame(arr, columns=['ot','o','h','l','c','v','ct','qv','n','taker_v','taker_qv','ig'])
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            print(f"[KLINE] SPOT BTCUSDT OK {len(df)}")
            return df, "BTCUSDT-SPOT"
    except Exception as e:
        print(f"[KLINE SPOT] fail {e}")

    # 3. ccxt fallback ถ้ามี ccxt
    try:
        import ccxt
        print("[KLINE] Try ccxt BTC/USDT")
        ex=ccxt.mexc({'enableRateLimit':True})
        ohlcv=ex.fetch_ohlcv('BTC/USDT', '15m', limit=500)
        df=pd.DataFrame(ohlcv, columns=['ot','o','h','l','c','v'])
        for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
        if len(df)>200:
            print(f"[KLINE] CCXT OK {len(df)}")
            return df, "BTC/USDT-CCXT"
    except Exception as e:
        print(f"[KLINE CCXT] fail {e}")

    print("[KLINE] ALL FAILED")
    return None, None

def calc_indicators(df):
    df['EMA12']=df['c'].ewm(span=12, adjust=False).mean()
    df['EMA26']=df['c'].ewm(span=26, adjust=False).mean()
    delta=df['c'].diff(); gain=delta.where(delta>0,0).rolling(14).mean(); loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    tr1=df['h']-df['l']; tr2=(df['h']-df['c'].shift()).abs(); tr3=(df['l']-df['c'].shift()).abs()
    df['TR']=pd.concat([tr1,tr2,tr3], axis=1).max(axis=1)
    df['+DM']=df.apply(lambda x: x['h']-x['h'].shift() if (x['h']-x['h'].shift())>(x['l'].shift()-x['l']) and (x['h']-x['h'].shift())>0 else 0, axis=1)
    df['-DM']=df.apply(lambda x: x['l'].shift()-x['l'] if (x['l'].shift()-x['l'])>(x['h']-x['h'].shift()) and (x['l'].shift()-x['l'])>0 else 0, axis=1)
    df['TR14']=df['TR'].rolling(14).sum(); df['+DM14']=df['+DM'].rolling(14).sum(); df['-DM14']=df['-DM'].rolling(14).sum()
    df['+DI']=100*df['+DM14']/df['TR14']; df['-DI']=100*df['-DM14']/df['TR14']
    df['DX']=100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI']); df['ADX']=df['DX'].rolling(14).mean()
    df['TP']=(df['h']+df['l']+df['c'])/3; df['TPV']=df['TP']*df['v']; df['VWAP']=df['TPV'].rolling(20).sum()/df['v'].rolling(20).sum()
    df['V_SMA20']=df['v'].rolling(20).mean(); df['VolSpike']=df['v']/df['V_SMA20']
    return df.dropna()

def dist_pct(price, step): return abs(price-round(price/step)*step)/price*100

def run_bt(df):
    cfg={"tp":2.5,"sl":1.2,"max_hold":12,"adx":30,"di":25,"vol":1.8,"round_step":1000,"round_pct":0.3,"short":True}
    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"max_dd":0}
    bal=40.16; high=bal; pos=[]
    for i in range(200, len(df)):
        last=df.iloc[i]; price=float(last['c'])
        if last['ADX']<cfg["adx"]: continue
        if last['VolSpike']<cfg["vol"]: continue
        if dist_pct(price, cfg["round_step"])<cfg["round_pct"]: continue
        up=last['+DI']>last['-DI'] and last['+DI']>cfg["di"] and price>last['VWAP'] and last['EMA12']>last['EMA26']
        down=last['-DI']>last['+DI'] and last['-DI']>cfg["di"] and price<last['VWAP'] and last['EMA12']<last['EMA26']
        strong_bull=(last['c']-last['o'])>(last['h']-last['l'])*0.35
        strong_bear=(last['o']-last['c'])>(last['h']-last['l'])*0.35
        buy=up and strong_bull and 45<=last['RSI']<=78
        sell=down and strong_bear and 22<=last['RSI']<=58 and cfg["short"]
        if not pos and buy: pos.append({"entry":price,"side":"long","idx":i})
        elif not pos and sell: pos.append({"entry":price,"side":"short","idx":i})
        if pos:
            entry=pos[0]['entry']; side=pos[0]['side']; hold=(i-pos[0]['idx'])*0.25
            pnl=(price-entry)/entry*100 if side=='long' else (entry-price)/entry*100
            reason=None
            if pnl>=cfg["tp"]: reason="TP"
            elif pnl<=-cfg["sl"]: reason="SL"
            elif hold>=cfg["max_hold"]: reason="HOLD"
            if reason:
                stats["total"]+=1
                if pnl>0: stats["wins"]+=1
                else: stats["losses"]+=1
                stats["pnl_sum"]+=pnl
                bal=bal*(1+pnl/100*0.1); high=max(high,bal)
                stats["max_dd"]=max(stats["max_dd"], (high-bal)/high*100 if high>0 else 0)
                pos=[]
    wr=(stats["wins"]/stats["total"]*100) if stats["total"]>0 else 0
    return stats, wr, bal, cfg

bt_results={}; bt_status="Idle"; LIVE_PRICE=0

def bt_job():
    global bt_results, bt_status, LIVE_PRICE
    bt_status="Running..."
    try:
        send_telegram(f"📊 [{thai_time()}] V13.5 BTC FAST เริ่ม BT 15D (เร็ว)\nกำลังดึงกราฟ 3 ชั้น...")
        df, sym = get_klines_fast("BTC_USDT","Min15",15)
        if df is None:
            bt_status="Fail - ดึงกราฟไม่ได้"; send_telegram(f"🔴 [{thai_time()}] BTC ดึงกราฟไม่ได้ทั้ง 3 ชั้น\nเช็คเน็ต Render หรือ MEXC API ล่ม\nลอง /bt ใหม่")
            return
        df=calc_indicators(df)
        LIVE_PRICE=float(df.iloc[-1]['c'])
        s,w,b,c=run_bt(df)
        bt_results["BTCUSDT"]={"wr":w,"stats":s,"balance":b,"cfg":c,"sym_used":sym,"live_price":LIVE_PRICE,"candles":len(df)}
        bt_status="Done"
        emoji="🟢" if w>=60 and s['pnl_sum']>0 else "🔴"
        send_telegram(f"📈 [{thai_time()}] V13.5 BTC FAST BT เสร็จ ✅\n\n{emoji} BTC {sym} WR {w:.1f}% PnL {s['pnl_sum']:+.2f}%\nTr {s['total']} Bal 40.16→{b:.2f} Price ${LIVE_PRICE:.0f}\n{ '✅ ผ่าน' if w>=60 else '🔴 ไม่ผ่าน - รอ V13.6'}")
    except Exception as e:
        bt_status=f"Error {e}"
        traceback.print_exc()
        send_telegram(f"🔴 BT Error {e}")

def get_off():
    try:
        if os.path.exists(OFFSET_FILE): return int(open(OFFSET_FILE).read().strip())
    except: pass
    return 0
def save_off(o):
    try: open(OFFSET_FILE,'w').write(str(o))
    except: pass

def handle(text, cid):
    global TRADING_ENABLED
    if CHAT_ID and str(cid)!=str(CHAT_ID): return
    t=(text or "").lower().strip()
    if t in ["/stats","/bt"]:
        if bt_status=="Running...": send_telegram(f"⏳ BT กำลังรัน {bt_status} รอ 10 วิ")
        elif not bt_results: 
            threading.Thread(target=bt_job, daemon=True).start()
            send_telegram("📊 เริ่ม BT FAST ใหม่ 15D รอ 10 วิ...")
        else:
            b=bt_results["BTCUSDT"]; send_telegram(f"📊 [{thai_time()}] BTC {b['sym_used']} WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}% Price ${b['live_price']:.0f}")
    elif t in ["/status"]:
        b=bt_results.get("BTCUSDT")
        if b: send_telegram(f"📍 BTC {b['sym_used']} ${b['live_price']:.0f} WR {b['wr']:.1f}% {'✅' if TRADING_ENABLED else '🛑'}")
        else: send_telegram(f"📍 BTC {bt_status} {'✅' if TRADING_ENABLED else '🛑'} พิมพ์ /bt")
    elif t in ["/stop"]: TRADING_ENABLED=False; save_trading(False); send_telegram(f"🛑 ปิด BTC {thai_time()}")
    elif t in ["/start"]: TRADING_ENABLED=True; save_trading(True); send_telegram(f"✅ เปิด BTC {thai_time()}")
    elif t in ["/test_tele","/health"]: send_telegram(f"🧪 V13.5 FAST OK {bt_status} {'✅' if TRADING_ENABLED else '🛑'}")
    elif t in ["/help"]: send_telegram("/stats /bt - BT FAST 15D\n/status - ราคาสด\n/start /stop\n/test_tele")

def poll():
    off=get_off()
    while True:
        try:
            if not BOT_TOKEN: time.sleep(10); continue
            r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset":off+1,"timeout":20}, timeout=25)
            if r.status_code!=200: time.sleep(5); continue
            data=r.json()
            if not data.get("ok"): time.sleep(3); continue
            for upd in data.get("result",[]):
                off=max(off, upd.get("update_id",0)); save_off(off)
                msg=upd.get("message") or {}; txt=msg.get("text",""); cid=msg.get("chat",{}).get("id")
                if txt: handle(txt, cid)
        except Exception as e: print(e); time.sleep(5)

@app.route('/')
def home():
    b=bt_results.get("BTCUSDT")
    if not b: return f"<h2>V13.5 BTC FAST {bt_status}</h2>"
    return f"<h2>BTC {b['sym_used']} ${b['live_price']:.0f} WR {b['wr']:.1f}% {bt_status}</h2>"
@app.route('/health')
def health(): return jsonify({"status":"ok","version":"V13.5 BTC FAST","trading":TRADING_ENABLED,"bt":bt_results,"time":thai_time()})
@app.route('/test_tele')
def test(): ok,_=send_telegram(f"🧪 V13.5 FAST Test {thai_time()}"); return jsonify({"ok":ok})

send_telegram(f"🚀 [{thai_time()}] V13.5 BTC FAST Live\nแก้ BT ค้าง - ดึง 3 ชั้น\nพิมพ์ /bt /status")

threading.Thread(target=lambda: (time.sleep(3), bt_job()), daemon=True).start()
threading.Thread(target=poll, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
