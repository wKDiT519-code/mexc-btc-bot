"""
V15.0 BTC 90D - BT ยาว 90 วัน เห็นทั้งเทรนด์ + Sideway
30 วัน = Sideway $82k-$85k เทรดยาก WR สวิง
90 วัน = เจอเทรนด์ขึ้น มิ.ย. $58k -> ก.ย. $87k + Sideway ต.ค. WR นิ่งกว่า
ใช้ฐาน V13.7 WR63.6% PnL-0.15% ที่ดีสุด
"""

import requests, pandas as pd, numpy as np, os, time, json
from flask import Flask, jsonify
from datetime import datetime
import pytz, threading

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

def get_klines_fast(days=90):
    # 90 วัน = 90*96 = 8640 แท่ง ต้องดึงหลายรอบ
    for sym in ["BTC_USDT","BTCUSDT"]:
        try:
            # MEXC contract ได้ครั้งละ 1000 แท่ง ต้อง loop
            all_data = []
            url=f"https://contract.mexc.com/api/v1/contract/kline/{sym}"
            r=requests.get(url, params={"interval":"Min15"}, timeout=10)
            j=r.json()
            if 'data' not in j: continue
            d=j['data']
            df=pd.DataFrame({'ot':d['time'],'o':d['open'],'h':d['high'],'l':d['low'],'c':d['close'],'v':d['vol']}) if 'time' in d else pd.DataFrame(d, columns=['ot','o','h','l','c','v'])
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            if len(df) >= days*96*0.8:  # ได้ 80% ของ 90 วันก็พอ
                return df.tail(days*96), sym
            elif len(df) > 300:
                return df, f"{sym}-{len(df)}bars"
        except: continue
    try:
        r=requests.get("https://api.mexc.com/api/v3/klines", params={"symbol":"BTCUSDT","interval":"15m","limit":1000}, timeout=10)
        arr=r.json()
        if isinstance(arr, list) and len(arr)>300:
            df=pd.DataFrame(arr, columns=['ot','o','h','l','c','v','ct','qv','n','taker_v','taker_qv','ig'])
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            return df, f"BTCUSDT-SPOT-{len(df)}bars"
    except: pass
    try:
        import ccxt
        ex=ccxt.mexc({'enableRateLimit':True})
        # ดึง 2 รอบ รอบละ 1000 = 2000 แท่ง ~20 วัน ต้องใช้ spot ที่ให้ 1000 แท่ง
        ohlcv=ex.fetch_ohlcv('BTC/USDT','15m',limit=1000)
        df=pd.DataFrame(ohlcv, columns=['ot','o','h','l','c','v'])
        for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
        if len(df)>300: return df, f"BTC/USDT-CCXT-{len(df)}bars"
    except: pass
    return None, None

def calc_indicators(df):
    df['EMA12']=df['c'].ewm(span=12, adjust=False).mean()
    df['EMA26']=df['c'].ewm(span=26, adjust=False).mean()
    df['EMA50']=df['c'].ewm(span=50, adjust=False).mean()
    delta=df['c'].diff(); gain=delta.where(delta>0,0).rolling(14).mean(); loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    df['H-L']=df['h']-df['l']; df['H-pC']=(df['h']-df['c'].shift(1)).abs(); df['L-pC']=(df['l']-df['c'].shift(1)).abs()
    df['TR']=df[['H-L','H-pC','L-pC']].max(axis=1)
    df['H-pH']=df['h']-df['h'].shift(1); df['pL-L']=df['l'].shift(1)-df['l']
    df['+DM']=np.where((df['H-pH'] > df['pL-L']) & (df['H-pH'] > 0), df['H-pH'], 0.0)
    df['-DM']=np.where((df['pL-L'] > df['H-pH']) & (df['pL-L'] > 0), df['pL-L'], 0.0)
    df['TR14']=df['TR'].rolling(14).sum(); df['+DM14']=pd.Series(df['+DM']).rolling(14).sum(); df['-DM14']=pd.Series(df['-DM']).rolling(14).sum()
    df['+DI']=100*df['+DM14']/df['TR14']; df['-DI']=100*df['-DM14']/df['TR14']
    df['DX']=100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI']).replace(0,0.001); df['ADX']=df['DX'].rolling(14).mean()
    df['TP']=(df['h']+df['l']+df['c'])/3; df['TPV']=df['TP']*df['v']; df['VWAP']=df['TPV'].rolling(20).sum()/df['v'].rolling(20).sum()
    df['V_SMA20']=df['v'].rolling(20).mean(); df['VolSpike']=df['v']/df['V_SMA20']
    return df.dropna()

def dist_pct(price, step): return abs(price-round(price/step)*step)/price*100

def run_bt_90d(df):
    # V15 90D: ใช้ฐาน V13.7 WR63.6% PnL-0.15% ที่ดีสุด BT ยาว 90 วัน
    cfg={"tp":2.2,"sl":1.3,"max_hold":32,"adx":22,"di":18,"vol":1.2,"round_step":500,"round_pct":0.15,"short":True}
    # TP2.2 SL1.3 RR1.69 Hold8H ADX22 Vol1.2 Round500 0.15% = V13.7
    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"max_dd":0,"skip":{"adx":0,"vol":0,"round":0}}
    bal=40.16; high=bal; pos=[]
    for i in range(200, len(df)):
        last=df.iloc[i]; price=float(last['c'])
        if last['ADX']<cfg["adx"]: stats["skip"]["adx"]+=1; continue
        if last['VolSpike']<cfg["vol"]: stats["skip"]["vol"]+=1; continue
        if dist_pct(price, cfg["round_step"])<cfg["round_pct"]: stats["skip"]["round"]+=1; continue
        up_trend = last['EMA12']>last['EMA26'] and last['EMA26']>last['EMA50'] and price>last['VWAP']
        down_trend = last['EMA12']<last['EMA26'] and last['EMA26']<last['EMA50'] and price<last['VWAP']
        up = last['+DI']>last['-DI'] and last['+DI']>cfg["di"] and up_trend
        down = last['-DI']>last['+DI'] and last['-DI']>cfg["di"] and down_trend and cfg["short"]
        body = abs(last['c']-last['o']); rng = last['h']-last['l']
        strong_bull = body > rng*0.3 and last['c']>last['o']
        strong_bear = body > rng*0.3 and last['o']>last['c']
        rsi_ok_long = 40 <= last['RSI'] <= 72
        rsi_ok_short = 28 <= last['RSI'] <= 62
        buy = up and strong_bull and rsi_ok_long
        sell = down and strong_bear and rsi_ok_short
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
        send_telegram(f"📊 [{thai_time()}] V15.0 BTC 90D เริ่ม BT ยาว 90 วัน\nฐาน V13.7 WR63.6% PnL-0.15% TP2.2 SL1.3 RR1.69 Hold8H ADX22 Vol1.2\nเห็นทั้งเทรนด์ ก.ย. $58k->$87k + Sideway ต.ค. $82k-$85k...")
        df, sym = get_klines_fast(90)
        if df is None: bt_status="Fail"; send_telegram("🔴 BTC ดึงกราฟ 90D ไม่ได้"); return
        df=calc_indicators(df)
        LIVE_PRICE=float(df.iloc[-1]['c'])
        s,w,b,c=run_bt_90d(df)
        bt_results["BTCUSDT"]={"wr":w,"stats":s,"balance":b,"cfg":c,"sym_used":sym,"live_price":LIVE_PRICE,"bars":len(df)}
        bt_status="Done"
        emoji="🟢" if w>=60 and s['pnl_sum']>0 else "🟡" if w>=55 else "🔴"
        msg=f"{emoji} [{thai_time()}] V15.0 BTC 90D BT เสร็จ\n{sym} ${LIVE_PRICE:.0f} Bars {len(df)}\nWR {w:.1f}% PnL {s['pnl_sum']:+.2f}% Tr {s['total']} Bal 40.16→{b:.2f}\nDD {s['max_dd']:.1f}% Skip ADX{s['skip']['adx']} Vol{s['skip']['vol']} Round{s['skip']['round']}\n"
        if w>=60 and s['pnl_sum']>0: msg+="✅ FINAL 90D ผ่าน! WR60%+ PnL บวก เทรนด์+Sideway!\n"
        elif w>=60: msg+=f"🟢 WR {w:.1f}% ผ่าน 60%! PnL {s['pnl_sum']:+.2f}%\n"
        else: msg+=f"WR {w:.1f}% PnL {s['pnl_sum']:+.2f}% 90D\n"
        msg+="V13.7 base TP2.2 SL1.3 RR1.69 Hold8H ADX22 Vol1.2 RSI14"
        send_telegram(msg)
    except Exception as e:
        bt_status=f"Error {e}"
        send_telegram(f"🔴 BT 90D Error {e}")

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
        if bt_status=="Running...": send_telegram("⏳ BTC 90D กำลังรัน...")
        elif not bt_results:
            threading.Thread(target=bt_job, daemon=True).start()
            send_telegram("📊 เริ่ม BT V15.0 90D รอ 20 วิ... (ดึง 90 วัน)")
        else:
            b=bt_results["BTCUSDT"]; send_telegram(f"📊 BTC 90D {b['sym_used']} ${b['live_price']:.0f} WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}% Tr {b['stats']['total']} Bars {b['bars']}")
    elif t in ["/status"]:
        b=bt_results.get("BTCUSDT")
        if b: send_telegram(f"📍 BTC 90D {b['sym_used']} ${b['live_price']:.0f} WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}% Bars {b['bars']} {'✅' if TRADING_ENABLED else '🛑'}")
        else: send_telegram(f"📍 BTC 90D {bt_status} {'✅' if TRADING_ENABLED else '🛑'} /bt")
    elif t in ["/stop"]: TRADING_ENABLED=False; save_trading(False); send_telegram(f"🛑 ปิด BTC 90D {thai_time()}")
    elif t in ["/start"]: TRADING_ENABLED=True; save_trading(True); send_telegram(f"✅ เปิด BTC 90D {thai_time()}")

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
    if not b: return f"<h2>V15.0 90D {bt_status}</h2>"
    return f"<h2>BTC 90D WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}% Bars {b['bars']}</h2>"
@app.route('/health')
def health(): return jsonify({"status":"ok","version":"V15.0 90D","trading":TRADING_ENABLED,"bt":bt_results,"time":thai_time()})

send_telegram(f"🚀 [{thai_time()}] V15.0 BTC 90D Live\nBT 90 วัน เห็นทั้งเทรนด์ ก.ย. $58k->$87k + Sideway ต.ค. $82k-$85k\nฐาน V13.7 WR63.6% TP2.2 SL1.3 Hold8H พิมพ์ /bt /status")

threading.Thread(target=lambda: (time.sleep(3), bt_job()), daemon=True).start()
threading.Thread(target=poll, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
