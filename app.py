"""
V13.6 BTC FIXED - แก้ Error 'numpy.float64' object has no attribute 'shift'
สูตร ADX +DM/-DM แก้เป็น vector 100%
"""

import requests, pandas as pd, numpy as np, os, time, json
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
print(f"=== V13.6 BTC FIXED START ===")

app = Flask(__name__)
def thai_now(): return datetime.now(pytz.timezone('Asia/Bangkok'))
def thai_time(): return thai_now().strftime("%d/%m/%Y %H:%M ICT")
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return False
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r=requests.post(url, json={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=10)
        return r.status_code==200
    except: return False

def get_klines_fast(days=15):
    for sym in ["BTC_USDT","BTCUSDT"]:
        try:
            url=f"https://contract.mexc.com/api/v1/contract/kline/{sym}"
            r=requests.get(url, params={"interval":"Min15"}, timeout=5)
            j=r.json()
            if 'data' not in j: continue
            d=j['data']
            df=pd.DataFrame({'ot':d['time'],'o':d['open'],'h':d['high'],'l':d['low'],'c':d['close'],'v':d['vol']}) if 'time' in d else pd.DataFrame(d, columns=['ot','o','h','l','c','v'])
            df=df.tail(days*96)
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            if len(df)>200: return df, sym
        except: continue
    try:
        r=requests.get("https://api.mexc.com/api/v3/klines", params={"symbol":"BTCUSDT","interval":"15m","limit":500}, timeout=5)
        arr=r.json()
        if isinstance(arr, list) and len(arr)>200:
            df=pd.DataFrame(arr, columns=['ot','o','h','l','c','v','ct','qv','n','taker_v','taker_qv','ig'])
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            return df, "BTCUSDT-SPOT"
    except: pass
    try:
        import ccxt
        ex=ccxt.mexc({'enableRateLimit':True})
        ohlcv=ex.fetch_ohlcv('BTC/USDT','15m',limit=500)
        df=pd.DataFrame(ohlcv, columns=['ot','o','h','l','c','v'])
        for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
        if len(df)>200: return df, "BTC/USDT-CCXT"
    except: pass
    return None, None

def calc_indicators_fixed(df):
    """FIXED 100% - ไม่ใช้ apply shift ใน row อีก"""
    df['EMA12']=df['c'].ewm(span=12, adjust=False).mean()
    df['EMA26']=df['c'].ewm(span=26, adjust=False).mean()
    delta=df['c'].diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))

    # TR
    df['H-L'] = df['h']-df['l']
    df['H-pC'] = (df['h']-df['c'].shift(1)).abs()
    df['L-pC'] = (df['l']-df['c'].shift(1)).abs()
    df['TR'] = df[['H-L','H-pC','L-pC']].max(axis=1)

    # +DM / -DM แบบ vector ไม่ใช้ apply
    df['H-pH'] = df['h'] - df['h'].shift(1)
    df['pL-L'] = df['l'].shift(1) - df['l']
    df['+DM'] = np.where((df['H-pH'] > df['pL-L']) & (df['H-pH'] > 0), df['H-pH'], 0.0)
    df['-DM'] = np.where((df['pL-L'] > df['H-pH']) & (df['pL-L'] > 0), df['pL-L'], 0.0)

    df['TR14']=df['TR'].rolling(14).sum()
    df['+DM14']=pd.Series(df['+DM']).rolling(14).sum()
    df['-DM14']=pd.Series(df['-DM']).rolling(14).sum()
    df['+DI']=100*df['+DM14']/df['TR14']
    df['-DI']=100*df['-DM14']/df['TR14']
    df['DX']=100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI']).replace(0,0.001)
    df['ADX']=df['DX'].rolling(14).mean()

    df['TP']=(df['h']+df['l']+df['c'])/3
    df['TPV']=df['TP']*df['v']
    df['VWAP']=df['TPV'].rolling(20).sum()/df['v'].rolling(20).sum()
    df['V_SMA20']=df['v'].rolling(20).mean()
    df['VolSpike']=df['v']/df['V_SMA20']
    return df.dropna()

def dist_pct(price, step): return abs(price-round(price/step)*step)/price*100

def run_bt(df):
    cfg={"tp":2.5,"sl":1.2,"max_hold":12,"adx":30,"di":25,"vol":1.8,"round_step":1000,"round_pct":0.3,"short":True}
    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"max_dd":0}
    bal=40.16; high=bal; pos=[]
    for i in range(200, len(df)):
        last=df.iloc[i]; price=float(last['c'])
        if last['ADX']<cfg["adx"] or last['VolSpike']<cfg["vol"]: continue
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
        send_telegram(f"📊 [{thai_time()}] V13.6 BTC FIXED เริ่ม BT 15D\nแก้ shift Error แล้ว...")
        df, sym = get_klines_fast(15)
        if df is None:
            bt_status="Fail"; send_telegram(f"🔴 BTC ดึงกราฟไม่ได้")
            return
        df=calc_indicators_fixed(df)
        LIVE_PRICE=float(df.iloc[-1]['c'])
        s,w,b,c=run_bt(df)
        bt_results["BTCUSDT"]={"wr":w,"stats":s,"balance":b,"cfg":c,"sym_used":sym,"live_price":LIVE_PRICE}
        bt_status="Done"
        send_telegram(f"✅ [{thai_time()}] V13.6 BTC BT เสร็จ\n{sym} ${LIVE_PRICE:.0f} WR {w:.1f}% PnL {s['pnl_sum']:+.2f}% Tr {s['total']} Bal {b:.2f}")
    except Exception as e:
        bt_status=f"Error {e}"
        traceback.print_exc()
        send_telegram(f"🔴 BT Error {e}\n{traceback.format_exc()[:300]}")

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
        if bt_status=="Running...": send_telegram("⏳ BTC BT กำลังรัน 10 วิ...")
        elif not bt_results:
            threading.Thread(target=bt_job, daemon=True).start()
            send_telegram("📊 เริ่ม BT V13.6 FIXED รอ 10 วิ...")
        else:
            b=bt_results["BTCUSDT"]; send_telegram(f"📊 BTC {b['sym_used']} ${b['live_price']:.0f} WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}%")
    elif t in ["/status"]:
        b=bt_results.get("BTCUSDT")
        if b: send_telegram(f"📍 BTC {b['sym_used']} ${b['live_price']:.0f} WR {b['wr']:.1f}% {'✅' if TRADING_ENABLED else '🛑'}")
        else: send_telegram(f"📍 BTC {bt_status} {'✅' if TRADING_ENABLED else '🛑'} /bt")
    elif t in ["/stop"]: TRADING_ENABLED=False; save_trading(False); send_telegram(f"🛑 ปิด BTC {thai_time()}")
    elif t in ["/start"]: TRADING_ENABLED=True; save_trading(True); send_telegram(f"✅ เปิด BTC {thai_time()}")

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
        except: time.sleep(5)

@app.route('/')
def home():
    b=bt_results.get("BTCUSDT")
    if not b: return f"<h2>V13.6 BTC FIXED {bt_status}</h2>"
    return f"<h2>BTC {b['sym_used']} WR {b['wr']:.1f}%</h2>"
@app.route('/health')
def health(): return jsonify({"status":"ok","version":"V13.6 FIXED","trading":TRADING_ENABLED,"bt":bt_results,"time":thai_time()})

send_telegram(f"🚀 [{thai_time()}] V13.6 BTC FIXED Live\nแก้ numpy.float64 shift Error แล้ว\nพิมพ์ /bt /status")

threading.Thread(target=lambda: (time.sleep(3), bt_job()), daemon=True).start()
threading.Thread(target=poll, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
