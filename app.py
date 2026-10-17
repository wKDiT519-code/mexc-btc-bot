"""
V13.1 COMMAND + STOP/START - มีคำสั่ง Telegram ปิด/เปิดเทรด
- /stats, /status, /health, /test_tele
- /stop, /pause, /ปิดบอท, /หยุดเทรด -> ปิดไม่ให้เปิดออเดอร์ใหม่
- /start, /resume, /เปิดบอท, /เริ่มเทรด -> เปิดเทรดต่อ
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

# รองรับทั้ง 2 ชื่อ
BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

TRADING_FLAG_FILE = os.path.join(DATA_DIR, "trading_enabled.json")
OFFSET_FILE = os.path.join(DATA_DIR, "telegram_offset.txt")

def load_trading_status():
    try:
        if os.path.exists(TRADING_FLAG_FILE):
            with open(TRADING_FLAG_FILE, 'r') as f:
                data = json.load(f)
                return data.get("enabled", True)
    except:
        pass
    return True

def save_trading_status(enabled):
    try:
        with open(TRADING_FLAG_FILE, 'w') as f:
            json.dump({"enabled": enabled, "updated": datetime.now().isoformat(), "by": "telegram"}, f)
    except Exception as e:
        print(f"save flag err {e}")

TRADING_ENABLED = load_trading_status()

print(f"=== V13.1 COMMAND START ===")
print(f"DATA_DIR: {DATA_DIR}")
print(f"BOT_TOKEN: {'SET '+BOT_TOKEN[:10] if BOT_TOKEN else 'MISSING ❌'}")
print(f"CHAT_ID: {CHAT_ID if CHAT_ID else 'MISSING ❌'}")
print(f"TRADING_ENABLED: {TRADING_ENABLED} ({TRADING_FLAG_FILE})")

app = Flask(__name__)

def thai_time():
    return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[TELE] Skip - token/chat missing")
        return False, "missing token/chat"
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode":"HTML", "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=15)
        print(f"[TELE] {r.status_code} {r.text[:150]}")
        return r.status_code == 200, r.text
    except Exception as e:
        print(f"[TELE] err {e}")
        return False, str(e)

# -------- BT LOGIC (เหมือนเดิม) --------
def get_klines_requests(symbol_mexc="BTC_USDT", interval="Min15", limit_days=30):
    try:
        url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol_mexc}"
        r = requests.get(url, params={"interval": interval}, timeout=15)
        data = r.json()
        if 'data' not in data: return None
        d = data['data']
        if 'time' in d:
            df = pd.DataFrame({'ot': d['time'],'o': d['open'],'h': d['high'],'l': d['low'],'c': d['close'],'v': d['vol']})
        elif isinstance(d, list):
            df = pd.DataFrame(d, columns=['ot','o','h','l','c','v'])
        else: return None
        df = df.tail(limit_days * 96)
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        return df
    except: return None

def calc_indicators(df):
    df['EMA12']=df['c'].ewm(span=12, adjust=False).mean()
    df['EMA26']=df['c'].ewm(span=26, adjust=False).mean()
    delta=df['c'].diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    tr1 = df['h']-df['l']; tr2 = (df['h']-df['c'].shift()).abs(); tr3 = (df['l']-df['c'].shift()).abs()
    df['TR']=pd.concat([tr1,tr2,tr3], axis=1).max(axis=1)
    df['+DM']=df.apply(lambda x: x['h']-x['h'].shift() if (x['h']-x['h'].shift())>(x['l'].shift()-x['l']) and (x['h']-x['h'].shift())>0 else 0, axis=1)
    df['-DM']=df.apply(lambda x: x['l'].shift()-x['l'] if (x['l'].shift()-x['l'])>(x['h']-x['h'].shift()) and (x['l'].shift()-x['l'])>0 else 0, axis=1)
    df['TR14']=df['TR'].rolling(14).sum(); df['+DM14']=df['+DM'].rolling(14).sum(); df['-DM14']=df['-DM'].rolling(14).sum()
    df['+DI']=100*df['+DM14']/df['TR14']; df['-DI']=100*df['-DM14']/df['TR14']
    df['DX']=100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI']); df['ADX']=df['DX'].rolling(14).mean()
    df['V_SMA20']=df['v'].rolling(20).mean(); df['VolSpike']=df['v']/df['V_SMA20']
    return df.dropna()

def run_bt(df, symbol="BTCUSDT", tp=1.8, sl=0.9, max_hold=8, enable_short=True):
    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"max_dd":0,"symbol":symbol}
    balance=40.16; highest=balance
    for i in range(200, len(df)):
        last=df.iloc[i]; price=float(last['c'])
        uptrend=last['+DI']>last['-DI'] and last['ADX']>22
        downtrend=last['-DI']>last['+DI'] and last['ADX']>22
        vol=last['VolSpike']>1.0
        if not vol: continue
        # simplified for BT
        buy=uptrend and last['RSI']>=45 and last['RSI']<=80
        sell=downtrend and last['RSI']>=20 and last['RSI']<=55 and enable_short
        # mock pnl - same as before logic approximated
        # For demo use random but we will reuse real exit logic
        pass
    # ใช้ logic เดิมแบบเต็ม
    positions=[]
    for i in range(200, len(df)):
        last = df.iloc[i]; price=float(last['c'])
        uptrend = last['+DI'] > last['-DI'] and last['ADX'] > 22
        downtrend = last['-DI'] > last['+DI'] and last['ADX'] > 22
        strong_bull = (last['c']-last['o']) > (last['h']-last['l'])*0.5
        strong_bear = (last['o']-last['c']) > (last['h']-last['l'])*0.5
        vol_spike = last['VolSpike'] > 1.0
        rsi_up = 45 <= last['RSI'] <= 80
        rsi_down = 20 <= last['RSI'] <= 55
        buy_signal = uptrend and strong_bull and vol_spike and rsi_up
        sell_signal = downtrend and strong_bear and vol_spike and rsi_down and enable_short
        if not positions and buy_signal:
            positions.append({"entry":price, "side":"long", "idx":i})
        elif not positions and sell_signal:
            positions.append({"entry":price, "side":"short", "idx":i})
        if positions:
            entry=positions[0]['entry']; side=positions[0]['side']; hold_hours=(i-positions[0]['idx'])*0.25
            pnl=(price-entry)/entry*100 if side=='long' else (entry-price)/entry*100
            exit_reason=None
            if pnl>=tp: exit_reason=f"TP {tp}%"
            elif pnl<=-sl: exit_reason=f"SL -{sl}%"
            elif hold_hours>=max_hold: exit_reason=f"MAX_HOLD {max_hold}H"
            if exit_reason:
                stats["total"]+=1
                if pnl>0: stats["wins"]+=1
                else: stats["losses"]+=1
                stats["pnl_sum"]+=pnl
                balance=balance*(1+pnl/100*0.1)
                highest=max(highest,balance)
                dd=(highest-balance)/highest*100 if highest>0 else 0
                stats["max_dd"]=max(stats["max_dd"],dd)
                positions=[]
    wr=(stats["wins"]/stats["total"]*100) if stats["total"]>0 else 0
    return stats, wr, balance

bt_results={}
bt_status="Starting..."

def bt_all():
    global bt_results, bt_status
    bt_status="Running BT..."
    print(f"=== BT START {thai_time()} ===")
    send_telegram(f"📊 [{thai_time()}] V13.1 BT เริ่มแล้ว\nTrading {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'} | BOT_TOKEN {'✅' if BOT_TOKEN else '❌'}\nกำลังดึงกราฟ MEXC 30 วัน...")

    df_btc=get_klines_requests("BTC_USDT","Min15",30)
    if df_btc is not None and len(df_btc)>200:
        df_btc=calc_indicators(df_btc)
        s,w,b=run_bt(df_btc,"BTCUSDT",tp=1.8,sl=0.9,max_hold=8,enable_short=True)
        bt_results["BTCUSDT"]={"wr":w,"stats":s,"balance":b,"candles":len(df_btc)}
    else:
        bt_results["BTCUSDT"]={"wr":0,"stats":{"total":0,"wins":0,"losses":0,"pnl_sum":0,"max_dd":0},"balance":40.16,"candles":0}

    df_gold=get_klines_requests("PAXG_USDT","Min15",30)
    if df_gold is not None and len(df_gold)>200:
        df_gold=calc_indicators(df_gold)
        s,w,b=run_bt(df_gold,"PAXGUSDT",tp=2.5,sl=1.2,max_hold=24,enable_short=False)
        bt_results["PAXGUSDT"]={"wr":w,"stats":s,"balance":b,"candles":len(df_gold)}
    else:
        bt_results["PAXGUSDT"]={"wr":0,"stats":{"total":0,"wins":0,"losses":0,"pnl_sum":0,"max_dd":0},"balance":40.16,"candles":0}

    bt_status="Done"
    msg=f"📈 [{thai_time()}] BT 30 วันเสร็จ | Trading {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\n\n"
    for sym,res in bt_results.items():
        wr=res['wr']; st=res['stats']; bal=res['balance']
        status="✅ ผ่าน" if wr>=60 and st['pnl_sum']>0 else "⚠️ ไม่ผ่าน"
        emoji="🟢" if wr>=60 and st['pnl_sum']>0 else "🔴"
        msg+=f"{emoji} {sym} {status}\nTrades {st['total']} WR {wr:.1f}% PnL {st['pnl_sum']:+.2f}%\nBal 40.16→{bal:.2f} MaxDD {st['max_dd']:.1f}%\n\n"
    msg+="พิมพ์ /status ดูสถานะเทรด\nพิมพ์ /stop เพื่อปิดเทรด\nพิมพ์ /stats ดูผล BT"
    send_telegram(msg)

# -------- TELEGRAM COMMAND HANDLER --------
def get_last_offset():
    try:
        if os.path.exists(OFFSET_FILE):
            with open(OFFSET_FILE,'r') as f:
                return int(f.read().strip())
    except: pass
    return 0

def save_offset(offset):
    try:
        with open(OFFSET_FILE,'w') as f:
            f.write(str(offset))
    except: pass

def handle_command(text, chat_id_from):
    global TRADING_ENABLED
    # security: only reply to configured CHAT_ID
    if CHAT_ID and str(chat_id_from) != str(CHAT_ID):
        print(f"[CMD] Ignored from {chat_id_from} != {CHAT_ID}")
        return

    txt = (text or "").strip().lower()
    print(f"[CMD] Received: {txt} from {chat_id_from}")

    if txt in ["/stats", "/bt", "stats", "/ผล"]:
        if not bt_results:
            send_telegram(f"⏳ [{thai_time()}] BT ยังไม่เสร็จ สถานะ: {bt_status}\nTrading: {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}")
        else:
            msg=f"📊 [{thai_time()}] ผล BT 30 วัน | Trading {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\n\n"
            for sym,res in bt_results.items():
                wr=res['wr']; st=res['stats']; bal=res['balance']
                status="✅ ผ่าน" if wr>=60 and st['pnl_sum']>0 else "⚠️ ไม่ผ่าน"
                emoji="🟢" if wr>=60 and st['pnl_sum']>0 else "🔴"
                msg+=f"{emoji} {sym} {status}\nTrades {st['total']} WR {wr:.1f}% PnL {st['pnl_sum']:+.2f}% Bal {bal:.2f}\n\n"
            send_telegram(msg)

    elif txt in ["/status", "/สถานะ", "status"]:
        msg=f"📍 [{thai_time()}] สถานะบอท\n\nTrading: {'✅ เปิดอยู่ - พร้อมเปิดออเดอร์ใหม่' if TRADING_ENABLED else '🛑 ปิดอยู่ - ไม่เปิดออเดอร์ใหม่ (ถือออเดอร์เดิมต่อได้)'}\nBT Status: {bt_status}\nDATA_DIR: {DATA_DIR}\n\n"
        if bt_results:
            for sym,res in bt_results.items():
                msg+=f"{sym}: WR {res['wr']:.1f}% PnL {res['stats']['pnl_sum']:+.2f}%\n"
        msg+="\nคำสั่ง:\n/stop = ปิดเทรด\n/start = เปิดเทรด\n/stats = ดูผล BT"
        send_telegram(msg)

    elif txt in ["/stop", "/pause", "/ปิดบอท", "/หยุดเทรด", "/stop_trading", "ปิด", "หยุด"]:
        TRADING_ENABLED=False
        save_trading_status(False)
        send_telegram(f"🛑 [{thai_time()}] ปิดเทรดบอทแล้ว\n\nบอทจะไม่เปิดออเดอร์ใหม่\nแต่ออเดอร์ที่ถืออยู่จะยังรันต่อจน TP/SL\n\nพิมพ์ /start เพื่อเปิดเทรดอีกครั้ง")

    elif txt in ["/start", "/resume", "/เปิดบอท", "/เริ่มเทรด", "/start_trading", "เปิด", "เริ่ม"]:
        TRADING_ENABLED=True
        save_trading_status(True)
        send_telegram(f"✅ [{thai_time()}] เปิดเทรดบอทแล้ว\n\nบอทพร้อมเปิดออเดอร์ใหม่ตามสัญญาณ\n\nพิมพ์ /stop เพื่อปิดเทรด\nพิมพ์ /stats ดูผล BT")

    elif txt in ["/health", "/test_tele", "/test"]:
        send_telegram(f"🧪 [{thai_time()}] Test OK\nBOT_TOKEN ✅\nCHAT_ID {chat_id_from}\nTrading {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\nBT {bt_status}\nWeb: / - /stats - /health")

    elif txt in ["/help", "/คำสั่ง", "help"]:
        send_telegram(f"📖 [{thai_time()}] คำสั่ง MEXC_BTC_bot\n\n/stats - ดูผล BT 30 วัน\n/status - ดูว่าเปิด/ปิดเทรด\n/stop - 🛑 ปิดเทรด (ไม่เปิดออเดอร์ใหม่)\n/start - ✅ เปิดเทรดต่อ\n/test_tele - เทส Telegram\n\nพิมพ์ภาษาไทยก็ได้: /ปิดบอท /เปิดบอท /หยุดเทรด")

def telegram_polling_loop():
    print("[POLL] Telegram polling started")
    offset = get_last_offset()
    while True:
        try:
            if not BOT_TOKEN:
                time.sleep(10)
                continue
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {"offset": offset+1, "timeout": 20, "allowed_updates": ["message"]}
            r = requests.get(url, params=params, timeout=25)
            if r.status_code != 200:
                print(f"[POLL] getUpdates fail {r.status_code} {r.text[:100]}")
                time.sleep(5)
                continue
            data = r.json()
            if not data.get("ok"):
                time.sleep(3)
                continue
            for upd in data.get("result", []):
                offset = max(offset, upd.get("update_id", 0))
                save_offset(offset)
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = msg.get("text", "")
                chat = msg.get("chat", {})
                chat_id_from = chat.get("id")
                if text:
                    handle_command(text, chat_id_from)
        except Exception as e:
            print(f"[POLL] exception {e}")
            import traceback; traceback.print_exc()
            time.sleep(5)

@app.route('/')
def home():
    status_trading = "✅ เปิดเทรด" if TRADING_ENABLED else "🛑 ปิดเทรด (ไม่เปิดออเดอร์ใหม่)"
    if not bt_results:
        return f"<h2>V13.1 COMMAND - {bt_status} {thai_time()}</h2>Trading: {status_trading}<br>BOT_TOKEN {'✅' if BOT_TOKEN else '❌'}<br>CHAT_ID {CHAT_ID}<br><br><a href='/test_tele'>test_tele</a> | <a href='/health'>health</a>"
    html=f"<h2>BT 30D V13.1 - {thai_time()} - {status_trading}</h2>"
    for sym,res in bt_results.items():
        wr=res['wr']; st=res['stats']; bal=res['balance']
        status="✅ ผ่าน" if wr>=60 and st['pnl_sum']>0 else "⚠️ ไม่ผ่าน"
        html+=f"<h3>{sym} {status}</h3>Trades {st['total']} WR {wr:.1f}% PnL {st['pnl_sum']:+.2f}% Bal {bal:.2f} MaxDD {st['max_dd']:.1f}%<hr>"
    html+=f"<p>Trading: {status_trading} | File: {TRADING_FLAG_FILE}</p>"
    html+=f"<p>Telegram: /stats /status /stop /start</p>"
    return html

@app.route('/test_tele')
def test_tele():
    ok,msg=send_telegram(f"🧪 [{thai_time()}] Test V13.1 OK\nTrading {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\nService Live On ✅")
    return jsonify({"telegram_sent":ok,"detail":msg,"trading_enabled":TRADING_ENABLED,"bot_token":bool(BOT_TOKEN),"chat_id":CHAT_ID})

@app.route('/health')
def health():
    return jsonify({"status":"ok","version":"V13.1 COMMAND + STOP/START","trading_enabled":TRADING_ENABLED,"bot_token":bool(BOT_TOKEN),"chat_id":bool(CHAT_ID),"results":bt_results,"time":thai_time()})

@app.route('/stats')
def stats_page(): return home()

# Start threads
print("Sending startup...")
send_telegram(f"🚀 [{thai_time()}] V13.1 COMMAND Live On\nTrading: {'✅ เปิด' if TRADING_ENABLED else '🛑 ปิด'}\nพิมพ์ /help ดูคำสั่ง\n/start = เปิดเทรด\n/stop = ปิดเทรด\n/stats = ดูผล BT")

def bt_thread():
    time.sleep(6)
    bt_all()
threading.Thread(target=bt_thread, daemon=True).start()
threading.Thread(target=telegram_polling_loop, daemon=True).start()

if __name__=="__main__":
    port=int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0",port=port)
