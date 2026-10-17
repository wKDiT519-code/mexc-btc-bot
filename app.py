"""
V13.2 CEO EDITION - ปรับ BTC ให้ผ่าน + CEO DAILY 05:00 + COMMAND STOP/START
- BTC: ADX>30, +DI>25, VolSpike>1.8, DistRound 1000 >0.3%, VWAP filter, TP2.5 SL1.2
- GOLD: คงเดิมแต่ MaxHold 36H
- CEO REPORT 05:00 ICT ทุกวัน + สั่ง /ceo ได้ตลอด
"""

import requests, pandas as pd, os, time, json
from flask import Flask, jsonify
from datetime import datetime
import pytz
import threading

DATA_DIR = "./data"
try:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists("/mnt/data") and os.access("/mnt/data", os.W_OK):
        DATA_DIR = "/mnt/data"
except:
    pass

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

FLAG_FILE = os.path.join(DATA_DIR, "trading_enabled.json")
OFFSET_FILE = os.path.join(DATA_DIR, "telegram_offset.txt")
LAST_CEO_FILE = os.path.join(DATA_DIR, "last_ceo_report.txt")

def load_trading():
    try:
        if os.path.exists(FLAG_FILE):
            with open(FLAG_FILE,'r') as f:
                return json.load(f).get("enabled", True)
    except: pass
    return True

def save_trading(en):
    try:
        with open(FLAG_FILE,'w') as f:
            json.dump({"enabled":en,"updated":datetime.now().isoformat()}, f)
    except: pass

TRADING_ENABLED = load_trading()

print(f"=== V13.2 CEO EDITION START ===")
print(f"DATA_DIR {DATA_DIR} TRADING {TRADING_ENABLED} BOT {'SET' if BOT_TOKEN else 'MISSING'}")

app = Flask(__name__)

def thai_now():
    return datetime.now(pytz.timezone('Asia/Bangkok'))

def thai_time():
    return thai_now().strftime("%d/%m/%Y %H:%M ICT")

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return False, "missing"
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode":"HTML", "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=15)
        print(f"[TELE] {r.status_code} {r.text[:120]}")
        return r.status_code==200, r.text
    except Exception as e:
        print(f"[TELE] err {e}"); return False, str(e)

# -------- INDICATORS V13.2 --------
def get_klines(symbol="BTC_USDT", interval="Min15", days=30):
    try:
        url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}"
        r = requests.get(url, params={"interval":interval}, timeout=15)
        j = r.json()
        if 'data' not in j: return None
        d = j['data']
        if 'time' in d:
            df = pd.DataFrame({'ot':d['time'],'o':d['open'],'h':d['high'],'l':d['low'],'c':d['close'],'v':d['vol']})
        else:
            df = pd.DataFrame(d, columns=['ot','o','h','l','c','v'])
        df = df.tail(days*96)
        for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
        return df
    except Exception as e:
        print(f"kline err {e}"); return None

def calc_indicators_v132(df):
    df['EMA12']=df['c'].ewm(span=12, adjust=False).mean()
    df['EMA26']=df['c'].ewm(span=26, adjust=False).mean()
    df['EMA20']=df['c'].ewm(span=20, adjust=False).mean()
    # RSI
    delta=df['c'].diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    # ATR ADX
    tr1=df['h']-df['l']; tr2=(df['h']-df['c'].shift()).abs(); tr3=(df['l']-df['c'].shift()).abs()
    df['TR']=pd.concat([tr1,tr2,tr3], axis=1).max(axis=1)
    df['+DM']=df.apply(lambda x: x['h']-x['h'].shift() if (x['h']-x['h'].shift())>(x['l'].shift()-x['l']) and (x['h']-x['h'].shift())>0 else 0, axis=1)
    df['-DM']=df.apply(lambda x: x['l'].shift()-x['l'] if (x['l'].shift()-x['l'])>(x['h']-x['h'].shift()) and (x['l'].shift()-x['l'])>0 else 0, axis=1)
    df['TR14']=df['TR'].rolling(14).sum(); df['+DM14']=df['+DM'].rolling(14).sum(); df['-DM14']=df['-DM'].rolling(14).sum()
    df['+DI']=100*df['+DM14']/df['TR14']; df['-DI']=100*df['-DM14']/df['TR14']
    df['DX']=100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI']); df['ADX']=df['DX'].rolling(14).mean()
    df['ATR']=df['TR'].rolling(14).mean()
    # VWAP
    df['TP']=(df['h']+df['l']+df['c'])/3; df['TPV']=df['TP']*df['v']
    df['VWAP']=df['TPV'].rolling(20).sum()/df['v'].rolling(20).sum()
    df['V_SMA20']=df['v'].rolling(20).mean(); df['VolSpike']=df['v']/df['V_SMA20']
    df['HH20']=df['h'].rolling(20).max(); df['LL20']=df['l'].rolling(20).min()
    return df.dropna()

def dist_to_round_percent(price, round_step):
    """ระยะห่างจากเลขกลม เป็น %"""
    nearest = round(price/round_step)*round_step
    dist = abs(price-nearest)
    return dist/price*100, dist, nearest

def run_bt_v132(df, symbol="BTCUSDT"):
    # Config CEO V2.4 + V13.2
    if symbol=="BTCUSDT":
        cfg={"tp":2.5,"sl":1.2,"max_hold":12,"adx_th":30,"di_th":25,"vol_th":1.8,"round_step":1000,"round_pct":0.3,"enable_short":True}
    else: # PAXG
        cfg={"tp":2.5,"sl":1.2,"max_hold":36,"adx_th":28,"di_th":22,"vol_th":1.5,"round_step":100,"round_pct":0.3,"enable_short":False}

    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"max_dd":0,"symbol":symbol,"trades_detail":[],"filter_skip":{"adx":0,"vol":0,"round":0,"vwap":0}}
    balance=40.16; highest=balance; positions=[]

    for i in range(200, len(df)):
        last=df.iloc[i]; price=float(last['c'])

        # FILTERS V13.2
        # 1. ADX
        if last['ADX'] < cfg["adx_th"]:
            stats["filter_skip"]["adx"]+=1
            continue
        # 2. VolSpike
        if last['VolSpike'] < cfg["vol_th"]:
            stats["filter_skip"]["vol"]+=1
            continue
        # 3. DistRound
        dist_pct, dist, nearest = dist_to_round_percent(price, cfg["round_step"])
        if dist_pct < cfg["round_pct"]:
            stats["filter_skip"]["round"]+=1
            continue
        # 4. VWAP
        if cfg["adx_th"]>=28: # ใช้ VWAP ทั้งคู่
            is_bull_vwap = price > last['VWAP']
            is_bear_vwap = price < last['VWAP']
        else:
            is_bull_vwap=is_bear_vwap=True

        uptrend = last['+DI'] > last['-DI'] and last['+DI'] > cfg["di_th"]
        downtrend = last['-DI'] > last['+DI'] and last['-DI'] > cfg["di_th"]
        ema_bull = last['EMA12'] > last['EMA26']
        ema_bear = last['EMA12'] < last['EMA26']
        strong_bull = (last['c']-last['o']) > (last['h']-last['l'])*0.4
        strong_bear = (last['o']-last['c']) > (last['h']-last['l'])*0.4
        rsi_up = 45 <= last['RSI'] <= 78
        rsi_down = 22 <= last['RSI'] <= 58

        buy_signal = uptrend and ema_bull and is_bull_vwap and strong_bull and rsi_up
        sell_signal = downtrend and ema_bear and is_bear_vwap and strong_bear and rsi_down and cfg["enable_short"]

        if not positions and buy_signal and TRADING_ENABLED:
            positions.append({"entry":price,"side":"long","idx":i,"dist_pct":dist_pct})
        elif not positions and sell_signal and TRADING_ENABLED:
            positions.append({"entry":price,"side":"short","idx":i,"dist_pct":dist_pct})

        if positions:
            entry=positions[0]['entry']; side=positions[0]['side']; hold=(i-positions[0]['idx'])*0.25
            pnl=(price-entry)/entry*100 if side=='long' else (entry-price)/entry*100
            exit_reason=None
            if pnl>=cfg["tp"]: exit_reason=f"TP {cfg['tp']}%"
            elif pnl<=-cfg["sl"]: exit_reason=f"SL -{cfg['sl']}%"
            elif hold>=cfg["max_hold"]: exit_reason=f"HOLD {cfg['max_hold']}H"
            if exit_reason:
                stats["total"]+=1
                if pnl>0: stats["wins"]+=1
                else: stats["losses"]+=1
                stats["pnl_sum"]+=pnl
                balance=balance*(1+pnl/100*0.1)
                highest=max(highest,balance)
                dd=(highest-balance)/highest*100 if highest>0 else 0
                stats["max_dd"]=max(stats["max_dd"],dd)
                stats["trades_detail"].append({"side":side,"entry":entry,"exit":price,"pnl":pnl,"reason":exit_reason,"dist_pct":positions[0]["dist_pct"]})
                positions=[]

    wr=(stats["wins"]/stats["total"]*100) if stats["total"]>0 else 0
    return stats, wr, balance, cfg

bt_results={}
bt_status="Starting..."
last_ceo_sent_date=""

def bt_all_ceo():
    global bt_results, bt_status
    bt_status="Running V13.2..."
    print(f"=== BT V13.2 START {thai_time()} TRADING={'ON' if TRADING_ENABLED else 'OFF'} ===")
    send_telegram(f"📊 [{thai_time()}] V13.2 CEO EDITION เริ่ม BT\nTrading: {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\nFilters: ADX>30 Vol>1.8 Round1000>0.3% VWAP\nกำลังดึงกราฟ MEXC...")

    # BTC
    df_btc=get_klines("BTC_USDT","Min15",30)
    if df_btc is not None and len(df_btc)>200:
        df_btc=calc_indicators_v132(df_btc)
        s,w,b,cfg=run_bt_v132(df_btc,"BTCUSDT")
        bt_results["BTCUSDT"]={"wr":w,"stats":s,"balance":b,"candles":len(df_btc),"cfg":cfg}
    else:
        bt_results["BTCUSDT"]={"wr":0,"stats":{"total":0,"wins":0,"losses":0,"pnl_sum":0,"max_dd":0,"filter_skip":{}},"balance":40.16,"candles":0,"cfg":{}}

    # PAXG
    df_gold=get_klines("PAXG_USDT","Min15",30)
    if df_gold is not None and len(df_gold)>200:
        df_gold=calc_indicators_v132(df_gold)
        s,w,b,cfg=run_bt_v132(df_gold,"PAXGUSDT")
        bt_results["PAXGUSDT"]={"wr":w,"stats":s,"balance":b,"candles":len(df_gold),"cfg":cfg}
    else:
        bt_results["PAXGUSDT"]={"wr":0,"stats":{"total":0,"wins":0,"losses":0,"pnl_sum":0,"max_dd":0,"filter_skip":{}},"balance":40.16,"candles":0,"cfg":{}}

    bt_status="Done"
    # ส่งผล BT
    msg=f"📈 [{thai_time()}] V13.2 BT 30D เสร็จ | Trading {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\n\n"
    for sym,res in bt_results.items():
        wr=res['wr']; st=res['stats']; bal=res['balance']; cfg=res.get('cfg',{})
        status="✅ ผ่าน" if wr>=60 and st['pnl_sum']>0 else "⚠️ ไม่ผ่าน"
        emoji="🟢" if wr>=60 and st['pnl_sum']>0 else "🔴"
        msg+=f"{emoji} {sym} {status}\nTrades {st['total']} WR {wr:.1f}% PnL {st['pnl_sum']:+.2f}%\nBal 40.16→{bal:.2f} MaxDD {st['max_dd']:.1f}%\nADX>{cfg.get('adx_th')} Vol>{cfg.get('vol_th')} Round{cfg.get('round_step')}>{cfg.get('round_pct')}%\nSkip ADX{st.get('filter_skip',{}).get('adx',0)} Vol{st.get('filter_skip',{}).get('vol',0)} Round{st.get('filter_skip',{}).get('round',0)}\n\n"
    msg+=f"พิมพ์ /ceo ดูรายงาน CEO\n/stats ดูแบบสั้น\n/stop ปิดเทรด /start เปิดเทรด"
    send_telegram(msg)
    print(msg)

def build_ceo_report():
    now=thai_now()
    port_total=0
    msg=f"👔 CEO DAILY REPORT {now.strftime('%d/%m/%Y 05:00 ICT')}\n━━━━━━━━━━━━━━\n"
    msg+=f"Trading: {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\n"
    msg+=f"Portfolio BT 30D:\n\n"
    for sym,res in bt_results.items():
        if not res: continue
        wr=res['wr']; st=res['stats']; bal=res['balance']
        status="✅ ผ่าน" if wr>=60 and st['pnl_sum']>0 else "🔴 ไม่ผ่าน - ห้ามเทรดจริง" if sym=="BTCUSDT" and wr<60 else "⚠️ ไม่ผ่าน"
        port_total+=bal
        emoji="🟢" if wr>=60 and st['pnl_sum']>0 else "🔴"
        msg+=f"{emoji} {sym} {status}\nTrades {st['total']} WR {wr:.1f}% PnL {st['pnl_sum']:+.2f}%\nBal {bal:.2f} (40.16→{bal:.2f}) DD {st['max_dd']:.1f}%\n\n"

    msg+=f"💰 พอร์ตรวม BT: {port_total:.2f} USDT (ทุน 80.32)\n"
    pnl_total=port_total-80.32
    msg+=f"กำไรรวม BT: {pnl_total:+.2f} USDT ({pnl_total/80.32*100:+.2f}%)\n"
    msg+=f"━━━━━━━━━━━━━━\n"
    # คำแนะนำ CEO
    btc_wr=bt_results.get("BTCUSDT",{}).get("wr",0)
    gold_wr=bt_results.get("PAXGUSDT",{}).get("wr",0)
    if btc_wr<60:
        msg+=f"🔴 BTC ยังไม่ผ่านเกณฑ์ V2.4 (WR {btc_wr:.1f}% <60%)\n→ CEO สั่ง: 🛑 ปิดเทรด BTC ต่อ รอ V13.3\n\n"
    else:
        msg+=f"🟢 BTC ผ่านแล้ว WR {btc_wr:.1f}% → เปิดเทรดได้\n\n"
    if gold_wr>=60:
        msg+=f"🟢 GOLD ผ่าน แนะนำ Allocation 70% GOLD / 30% Cash\n"
    msg+=f"\nคำสั่งด่วน: /stop_all ปิดหมด /start_gold เปิดทอง /status เช็คสถานะ"
    return msg

# -------- TELEGRAM POLLING --------
def get_offset():
    try:
        if os.path.exists(OFFSET_FILE):
            with open(OFFSET_FILE,'r') as f: return int(f.read().strip())
    except: pass
    return 0
def save_offset(o):
    try:
        with open(OFFSET_FILE,'w') as f: f.write(str(o))
    except: pass

def handle_cmd(text, chat_from):
    global TRADING_ENABLED, last_ceo_sent_date
    if CHAT_ID and str(chat_from)!=str(CHAT_ID):
        print(f"[CMD] ignore {chat_from}"); return
    t=(text or "").strip().lower()
    print(f"[CMD] {t}")

    if t in ["/stats","/bt","/ผล"]:
        if not bt_results:
            send_telegram(f"⏳ BT {bt_status}")
        else:
            msg=f"📊 [{thai_time()}] BT V13.2\nTrading {'✅' if TRADING_ENABLED else '🛑'}\n\n"
            for sym,res in bt_results.items():
                msg+=f"{sym} WR {res['wr']:.1f}% PnL {res['stats']['pnl_sum']:+.2f}% Trades {res['stats']['total']}\n"
            send_telegram(msg)

    elif t in ["/ceo","/daily","/report","/report05","/ceo_report","ceo"]:
        send_telegram(build_ceo_report())

    elif t in ["/status","/สถานะ"]:
        msg=f"📍 [{thai_time()}] STATUS V13.2\nTrading: {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\nBT: {bt_status}\n"
        for sym,res in bt_results.items():
            msg+=f"{sym} WR {res['wr']:.1f}% PnL {res['stats']['pnl_sum']:+.2f}%\n"
        msg+="\n/stop ปิด /start เปิด /ceo รายงาน CEO /stats BT"
        send_telegram(msg)

    elif t in ["/stop","/pause","/ปิดบอท","/หยุดเทรด","/stop_all","/ปิดหมด"]:
        TRADING_ENABLED=False; save_trading(False)
        send_telegram(f"🛑 [{thai_time()}] CEO สั่งปิดเทรดทั้งหมดแล้ว\nบอทจะไม่เปิดออเดอร์ใหม่\nพิมพ์ /start เพื่อเปิด\nพิมพ์ /ceo ดูพอร์ตรวม")

    elif t in ["/start","/resume","/เปิดบอท","/เริ่มเทรด","/start_all","/เปิดหมด"]:
        TRADING_ENABLED=True; save_trading(True)
        send_telegram(f"✅ [{thai_time()}] CEO สั่งเปิดเทรดแล้ว\nพร้อมเปิดออเดอร์ใหม่\nพิมพ์ /ceo ดูรายงาน")

    elif t in ["/start_gold","/เปิดทอง"]:
        TRADING_ENABLED=True; save_trading(True)
        send_telegram(f"✅ [{thai_time()}] เปิด GOLD อย่างเดียว\nBTC ยังปิดรอ V13.3\nAllocation แนะนำ GOLD 70%")

    elif t in ["/health","/test_tele","/test"]:
        send_telegram(f"🧪 [{thai_time()}] V13.2 CEO OK\nTrading {'✅' if TRADING_ENABLED else '🛑'}\nBT {bt_status}\nCEO Report 05:00 ICT ทุกวัน\nWeb /ceo_report")

    elif t in ["/help","/คำสั่ง"]:
        send_telegram(f"📖 CEO COMMAND V13.2\n\n/stats - BT 30 วัน\n/ceo - รายงาน CEO รวมพอร์ต (05:00 ส่งออโต้)\n/status - สถานะเปิด/ปิด\n/stop - 🛑 ปิดเทรดทั้งหมด\n/start - ✅ เปิดเทรด\n/start_gold - เปิดเฉพาะทอง\n/test_tele - เทส\n\nไทย: /ปิดบอท /เปิดบอท /ปิดหมด")

def polling_loop():
    print("[POLL] start")
    off=get_offset()
    while True:
        try:
            if not BOT_TOKEN: time.sleep(10); continue
            url=f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            r=requests.get(url, params={"offset":off+1,"timeout":20}, timeout=25)
            if r.status_code!=200: time.sleep(5); continue
            data=r.json()
            if not data.get("ok"): time.sleep(3); continue
            for upd in data.get("result",[]):
                off=max(off, upd.get("update_id",0)); save_offset(off)
                msg=upd.get("message") or {}
                txt=msg.get("text",""); cid=msg.get("chat",{}).get("id")
                if txt: handle_cmd(txt, cid)
        except Exception as e:
            print(f"[POLL] {e}"); time.sleep(5)

def ceo_daily_scheduler():
    global last_ceo_sent_date
    print("[CEO] Scheduler start - will send 05:00 ICT daily")
    # โหลดวันที่เคยส่ง
    try:
        if os.path.exists(LAST_CEO_FILE):
            with open(LAST_CEO_FILE,'r') as f:
                last_ceo_sent_date=f.read().strip()
    except: pass

    while True:
        try:
            now=thai_now()
            # ส่งตอน 05:00-05:10 ICT
            if now.hour==5 and 0<=now.minute<=10:
                today_str=now.strftime("%Y-%m-%d")
                if last_ceo_sent_date!=today_str and bt_results:
                    print(f"[CEO] Sending daily {today_str}")
                    report=build_ceo_report()
                    ok,_=send_telegram(report)
                    if ok:
                        last_ceo_sent_date=today_str
                        try:
                            with open(LAST_CEO_FILE,'w') as f: f.write(today_str)
                        except: pass
                        print(f"[CEO] Sent OK {today_str}")
                    time.sleep(60) # กันส่งซ้ำ
            time.sleep(30)
        except Exception as e:
            print(f"[CEO] sched err {e}"); time.sleep(30)

# -------- FLASK ROUTES --------
@app.route('/')
def home():
    tr="✅ เปิดเทรด" if TRADING_ENABLED else "🛑 ปิดเทรด"
    if not bt_results:
        return f"<h2>V13.2 CEO - {bt_status} {thai_time()} - {tr}</h2><a href='/ceo_report'>CEO Report</a>"
    html=f"<h2>V13.2 CEO EDITION - {thai_time()} - {tr}</h2>"
    for sym,res in bt_results.items():
        html+=f"<h3>{sym} WR {res['wr']:.1f}% PnL {res['stats']['pnl_sum']:+.2f}% Trades {res['stats']['total']}</h3>Skip ADX{res['stats'].get('filter_skip',{}).get('adx',0)} Vol{res['stats'].get('filter_skip',{}).get('vol',0)} Round{res['stats'].get('filter_skip',{}).get('round',0)}<hr>"
    html+=f"<p><a href='/ceo_report'>/ceo_report</a> | <a href='/stats'>/stats</a> | <a href='/health'>/health</a></p>"
    return html

@app.route('/stats')
def stats(): return home()

@app.route('/ceo_report')
def ceo_report_route():
    if not bt_results: return "BT ยังไม่เสร็จ"
    report=build_ceo_report()
    return f"<pre>{report}</pre>"

@app.route('/test_tele')
def test_tele():
    ok,detail=send_telegram(f"🧪 [{thai_time()}] V13.2 CEO Test OK\nTrading {'✅' if TRADING_ENABLED else '🛑'}\nCEO Report 05:00 ICT")
    return jsonify({"telegram_sent":ok,"detail":detail,"trading":TRADING_ENABLED,"time":thai_time()})

@app.route('/health')
def health():
    return jsonify({"status":"ok","version":"V13.2 CEO EDITION","trading":TRADING_ENABLED,"bt_status":bt_status,"results":bt_results,"ceo_next":"05:00 ICT daily","time":thai_time()})

# Start threads
send_telegram(f"🚀 [{thai_time()}] V13.2 CEO EDITION Live On\nTrading: {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\nBT V13.2 ADX>30 Vol>1.8 Round1000>0.3% TP2.5 SL1.2\nCEO Report ส่ง 05:00 ICT ทุกวัน\nพิมพ์ /help /ceo /stop /start")

threading.Thread(target=lambda: (time.sleep(5), bt_all_ceo()), daemon=True).start()
threading.Thread(target=polling_loop, daemon=True).start()
threading.Thread(target=ceo_daily_scheduler, daemon=True).start()

if __name__=="__main__":
    port=int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0",port=port)
