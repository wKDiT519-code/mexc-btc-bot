"""
V13 BT 30 DAYS TELE FIX - แก้เทเลเงียบ
1. ส่งเทเลทันทีตอน Start ไม่รอ 5 วิ
2. เพิ่ม /test_tele ให้กดเทสได้เลย
3. Log ชัดเจนถ้า BOT_TOKEN ว่าง
"""

import requests, pandas as pd, os, time, json
from flask import Flask, jsonify
from datetime import datetime
import pytz

DATA_DIR = "./data"
try:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists("/mnt/data") and os.access("/mnt/data", os.W_OK):
        DATA_DIR = "/mnt/data"
except:
    pass

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

print(f"=== V13 BT TELE FIX START ===")
print(f"DATA_DIR: {DATA_DIR}")
print(f"BOT_TOKEN: {'SET '+BOT_TOKEN[:10]+'...' if BOT_TOKEN else 'MISSING ❌'}")
print(f"CHAT_ID: {CHAT_ID if CHAT_ID else 'MISSING ❌'}")
print(f"PORT: {os.environ.get('PORT')}")

app = Flask(__name__)

def thai_time():
    return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")

def send_telegram(msg):
    print(f"[TELE] Trying to send: {msg[:100]}")
    if not BOT_TOKEN:
        print("[TELE] ❌ BOT_TOKEN MISSING - ไปเพิ่มใน Render Environment!")
        return False, "BOT_TOKEN missing"
    if not CHAT_ID:
        print("[TELE] ❌ CHAT_ID MISSING - ไปเพิ่มใน Render Environment!")
        return False, "CHAT_ID missing"
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode":"HTML", "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=15)
        print(f"[TELE] Response {r.status_code}: {r.text[:200]}")
        if r.status_code == 200:
            print("[TELE] ✅ Sent OK")
            return True, "OK"
        else:
            print(f"[TELE] ❌ Failed {r.text}")
            return False, r.text
    except Exception as e:
        print(f"[TELE] ❌ Exception {e}")
        import traceback
        traceback.print_exc()
        return False, str(e)

def get_klines_requests(symbol_mexc="BTC_USDT", interval="Min15", limit_days=30):
    try:
        url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol_mexc}"
        params = {"interval": interval}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if 'data' not in data:
            print(f"Kline fail {symbol_mexc} {data}")
            return None
        d = data['data']
        if 'time' in d:
            df = pd.DataFrame({
                'ot': d['time'],
                'o': d['open'],
                'h': d['high'],
                'l': d['low'],
                'c': d['close'],
                'v': d['vol']
            })
        elif isinstance(d, list):
            df = pd.DataFrame(d, columns=['ot','o','h','l','c','v'])
        else:
            return None
        df = df.tail(limit_days * 96)
        for col in ['o','h','l','c','v']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"get_klines err {symbol_mexc} {e}")
        return None

def calc_indicators(df):
    df['EMA12']=df['c'].ewm(span=12, adjust=False).mean()
    df['EMA26']=df['c'].ewm(span=26, adjust=False).mean()
    df['EMA20']=df['c'].ewm(span=20, adjust=False).mean()
    delta=df['c'].diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    tr1 = df['h']-df['l']
    tr2 = (df['h']-df['c'].shift()).abs()
    tr3 = (df['l']-df['c'].shift()).abs()
    df['TR']=pd.concat([tr1,tr2,tr3], axis=1).max(axis=1)
    df['ATR']=df['TR'].rolling(14).mean()
    df['H-pH']=df['h']-df['h'].shift()
    df['pL-L']=df['l'].shift()-df['l']
    df['+DM']=df.apply(lambda x: x['H-pH'] if x['H-pH']>x['pL-L'] and x['H-pH']>0 else 0, axis=1)
    df['-DM']=df.apply(lambda x: x['pL-L'] if x['pL-L']>x['H-pH'] and x['pL-L']>0 else 0, axis=1)
    df['+DM14']=df['+DM'].rolling(14).sum()
    df['-DM14']=df['-DM'].rolling(14).sum()
    df['TR14']=df['TR'].rolling(14).sum()
    df['+DI']=100*df['+DM14']/df['TR14']
    df['-DI']=100*df['-DM14']/df['TR14']
    df['DX']=100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI'])
    df['ADX']=df['DX'].rolling(14).mean()
    df['TP']=(df['h']+df['l']+df['c'])/3
    df['TPV']=df['TP']*df['v']
    df['VWAP']=df['TPV'].rolling(20).sum()/df['v'].rolling(20).sum()
    df['V_SMA20']=df['v'].rolling(20).mean()
    df['VolSpike']=df['v']/df['V_SMA20']
    df['HH20']=df['h'].rolling(20).max()
    df['LL20']=df['l'].rolling(20).min()
    return df.dropna()

def run_bt(df, symbol="BTCUSDT", tp=1.8, sl=0.9, max_hold=8, enable_short=True):
    positions=[]
    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"trades":[],"max_dd":0,"symbol":symbol}
    balance=40.16
    highest_equity=balance
    for i in range(200, len(df)):
        last = df.iloc[i]
        price=float(last['c'])
        ema_bull = last['EMA12'] > last['EMA26']
        ema_bear = last['EMA12'] < last['EMA26']
        uptrend = last['+DI'] > last['-DI'] and last['ADX'] > 22
        downtrend = last['-DI'] > last['+DI'] and last['ADX'] > 22
        strong_bull = (last['c']-last['o']) > (last['h']-last['l'])*0.5
        strong_bear = (last['o']-last['c']) > (last['h']-last['l'])*0.5
        vol_spike = last['VolSpike'] > 1.0
        rsi_up = 45 <= last['RSI'] <= 80
        rsi_down = 20 <= last['RSI'] <= 55
        buy_signal = uptrend and strong_bull and vol_spike and rsi_up and ema_bull
        sell_signal = downtrend and strong_bear and vol_spike and rsi_down and ema_bear
        if not positions and buy_signal:
            positions.append({"entry":price, "side":"long", "idx":i})
        elif not positions and sell_signal and enable_short:
            positions.append({"entry":price, "side":"short", "idx":i})
        if positions:
            entry=positions[0]['entry']
            side=positions[0]['side']
            hold_hours = (i-positions[0]['idx'])*0.25
            pnl = (price-entry)/entry*100 if side=='long' else (entry-price)/entry*100
            exit_reason=None
            if pnl >= tp:
                exit_reason=f"TP {tp}%"
            elif pnl <= -sl:
                exit_reason=f"SL -{sl}%"
            elif hold_hours >= max_hold:
                exit_reason=f"MAX_HOLD {max_hold}H"
            if exit_reason:
                stats["total"]+=1
                if pnl>0:
                    stats["wins"]+=1
                else:
                    stats["losses"]+=1
                stats["pnl_sum"]+=pnl
                balance = balance * (1 + pnl/100 * 0.1)
                highest_equity = max(highest_equity, balance)
                dd = (highest_equity-balance)/highest_equity*100 if highest_equity>0 else 0
                stats["max_dd"]=max(stats["max_dd"], dd)
                stats["trades"].append({"entry":entry,"exit":price,"side":side,"pnl":pnl,"reason":exit_reason})
                positions=[]
    wr = (stats["wins"]/stats["total"]*100) if stats["total"]>0 else 0
    return stats, wr, balance

bt_results = {}
bt_status = "Starting..."

def bt_all():
    global bt_results, bt_status
    bt_status = "Running BT..."
    print(f"=== BT START {thai_time()} ===")
    send_telegram(f"📊 [{thai_time()}] V13 BT FIX เริ่มแล้ว\nDATA_DIR {DATA_DIR}\nBOT_TOKEN {'✅' if BOT_TOKEN else '❌ MISSING'}\nCHAT_ID {CHAT_ID if CHAT_ID else '❌ MISSING'}\nกำลังดึงกราฟ MEXC 30 วัน...")

    # BTC
    print("Fetching BTC...")
    df_btc = get_klines_requests("BTC_USDT", "Min15", 30)
    if df_btc is not None and len(df_btc)>200:
        df_btc = calc_indicators(df_btc)
        stats_btc, wr_btc, bal_btc = run_bt(df_btc, "BTCUSDT", tp=1.8, sl=0.9, max_hold=8, enable_short=True)
        bt_results["BTCUSDT"] = {"wr":wr_btc, "stats":stats_btc, "balance":bal_btc, "candles":len(df_btc)}
        with open(os.path.join(DATA_DIR, "btc_bt_30d.json"), 'w', encoding='utf-8') as f:
            json.dump(stats_btc, f, indent=2, ensure_ascii=False)
    else:
        bt_results["BTCUSDT"] = {"wr":0, "stats":{"total":0,"wins":0,"losses":0,"pnl_sum":0,"max_dd":0}, "balance":40.16, "candles":0}

    time.sleep(1)
    print("Fetching GOLD...")
    df_gold = get_klines_requests("PAXG_USDT", "Min15", 30)
    if df_gold is not None and len(df_gold)>200:
        df_gold = calc_indicators(df_gold)
        stats_gold, wr_gold, bal_gold = run_bt(df_gold, "PAXGUSDT", tp=2.5, sl=1.2, max_hold=24, enable_short=False)
        bt_results["PAXGUSDT"] = {"wr":wr_gold, "stats":stats_gold, "balance":bal_gold, "candles":len(df_gold)}
        with open(os.path.join(DATA_DIR, "gold_bt_30d.json"), 'w', encoding='utf-8') as f:
            json.dump(stats_gold, f, indent=2, ensure_ascii=False)
    else:
        bt_results["PAXGUSDT"] = {"wr":0, "stats":{"total":0,"wins":0,"losses":0,"pnl_sum":0,"max_dd":0}, "balance":40.16, "candles":0}

    bt_status = "Done"
    msg = f"📈 [{thai_time()}] BT 30 วันเสร็จ | {DATA_DIR}\n\n"
    for sym, res in bt_results.items():
        wr = res['wr']
        st = res['stats']
        bal = res['balance']
        status = "✅ ผ่าน" if wr>=60 and st['pnl_sum']>0 else "⚠️ ไม่ผ่าน"
        emoji = "🟢" if wr>=60 and st['pnl_sum']>0 else "🔴"
        msg += f"{emoji} {sym} {status}\nTrades {st['total']} WR {wr:.1f}% PnL {st['pnl_sum']:+.2f}%\nBal 40.16→{bal:.2f} MaxDD {st['max_dd']:.1f}%\n\n"
    msg += f"ดูเว็บ /stats ได้เลย"
    send_telegram(msg)
    print(msg)

@app.route('/')
def home():
    if not bt_results:
        return f"<h2>V13 BT FIX - {bt_status} {thai_time()} | {DATA_DIR}</h2>BOT_TOKEN {'✅' if BOT_TOKEN else '❌ ไปเพิ่มใน Environment'}<br>CHAT_ID {CHAT_ID if CHAT_ID else '❌'}<br>รอ 1-2 นาที แล้วจะส่งเข้า Telegram<br><br><a href='/test_tele'>กด /test_tele เพื่อเทส Telegram</a>"
    html = f"<h2>BT 30D FIX RESULT - {thai_time()} - {DATA_DIR}</h2>"
    for sym, res in bt_results.items():
        wr = res['wr']
        st = res['stats']
        bal = res['balance']
        status = "✅ ผ่าน" if wr>=60 and st['pnl_sum']>0 else "⚠️ ไม่ผ่าน"
        html += f"<h3>{sym} {status}</h3>Trades {st['total']} WR {wr:.1f}% PnL {st['pnl_sum']:+.2f}% Bal {bal:.2f} MaxDD {st['max_dd']:.1f}%<br><hr>"
    return html

@app.route('/test_tele')
def test_tele():
    ok, msg = send_telegram(f"🧪 [{thai_time()}] Test Telegram จาก V13 BT FIX\nDATA_DIR {DATA_DIR}\nService Live On ✅\nBOT_TOKEN {'✅ SET' if BOT_TOKEN else '❌ MISSING'}\nCHAT_ID {CHAT_ID}")
    return jsonify({"telegram_sent": ok, "detail": msg, "bot_token_set": bool(BOT_TOKEN), "chat_id": CHAT_ID, "data_dir": DATA_DIR})

@app.route('/health')
def health():
    return jsonify({"status":"ok","version":"V13 BT FIX + TELE","data_dir":DATA_DIR,"bot_token": bool(BOT_TOKEN), "chat_id": bool(CHAT_ID), "results":bt_results, "time":thai_time()})

@app.route('/stats')
def stats_page():
    return home()

# ส่งเทเลทันทีตอน Start (ไม่ใช่รอใน Thread)
print("Sending startup telegram...")
send_telegram(f"🚀 [{thai_time()}] V13 BT FIX Live On\nDATA_DIR {DATA_DIR}\nBOT_TOKEN {'✅' if BOT_TOKEN else '❌ MISSING - ไปเพิ่มใน Render Env Vars'}\nCHAT_ID {CHAT_ID if CHAT_ID else '❌ MISSING'}\nกำลังเริ่ม BT 30 วัน...")

import threading
def bt_thread():
    time.sleep(8)
    bt_all()

threading.Thread(target=bt_thread, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
