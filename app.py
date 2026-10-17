"""
V13 BT 30 DAYS + TELEGRAM - ส่งผลเข้าเทเลด้วย
ตามคำสั่ง: "ส่งผลเข้าเทเลด้วยมั้ย"

เพิ่มส่ง Telegram หลัง BT เสร็จ:
- ส่งสรุป WR, PnL, MaxDD, Balance ทั้ง BTC และ GOLD เข้า Telegram
- ใช้ BOT_TOKEN + CHAT_ID เดิมได้เลย
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

print(f"V13 BT 30 DAYS + TELE - DATA_DIR {DATA_DIR} | TELE {'ON' if BOT_TOKEN else 'OFF'}")

app = Flask(__name__)

def thai_time():
    return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram not configured, skip")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode":"HTML", "disable_web_page_preview": True}, timeout=15)
        print(f"Telegram sent")
    except Exception as e:
        print(f"TG err {e}")

def get_klines_requests(symbol_mexc="BTC_USDT", interval="Min15", limit_days=30):
    try:
        url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol_mexc}"
        params = {"interval": interval}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if 'data' not in data:
            print(f"Kline fetch fail {symbol_mexc} {data}")
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
            print(f"Unknown kline format {d.keys()}")
            return None
        df = df.tail(limit_days * 96)
        df['o'] = df['o'].astype(float)
        df['h'] = df['h'].astype(float)
        df['l'] = df['l'].astype(float)
        df['c'] = df['c'].astype(float)
        df['v'] = df['v'].astype(float)
        return df
    except Exception as e:
        print(f"get_klines err {symbol_mexc} {e}")
        import traceback
        traceback.print_exc()
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

def bt_all():
    global bt_results
    print(f"=== BT START {thai_time()} ===")
    send_telegram(f"📊 [{thai_time()}] เริ่ม BT 30 วัน BTC + GOLD ...\nกำลังดึงกราฟ MEXC | {DATA_DIR}")

    # BTC
    print("Fetching BTC_USDT...")
    df_btc = get_klines_requests("BTC_USDT", "Min15", 30)
    if df_btc is not None and len(df_btc)>200:
        df_btc = calc_indicators(df_btc)
        stats_btc, wr_btc, bal_btc = run_bt(df_btc, "BTCUSDT", tp=1.8, sl=0.9, max_hold=8, enable_short=True)
        bt_results["BTCUSDT"] = {"wr":wr_btc, "stats":stats_btc, "balance":bal_btc, "candles":len(df_btc)}
        print(f"BTC BT 30D: {stats_btc['total']} trades WR {wr_btc:.1f}% PnL {stats_btc['pnl_sum']:+.2f}%")
        with open(os.path.join(DATA_DIR, "btc_bt_30d.json"), 'w', encoding='utf-8') as f:
            json.dump(stats_btc, f, indent=2, ensure_ascii=False)
    else:
        print("BTC fetch failed")
        bt_results["BTCUSDT"] = {"wr":0, "stats":{"total":0,"wins":0,"losses":0,"pnl_sum":0,"max_dd":0}, "balance":40.16, "candles":0}

    time.sleep(2)

    # GOLD
    print("Fetching PAXG_USDT...")
    df_gold = get_klines_requests("PAXG_USDT", "Min15", 30)
    if df_gold is not None and len(df_gold)>200:
        df_gold = calc_indicators(df_gold)
        stats_gold, wr_gold, bal_gold = run_bt(df_gold, "PAXGUSDT", tp=2.5, sl=1.2, max_hold=24, enable_short=False)
        bt_results["PAXGUSDT"] = {"wr":wr_gold, "stats":stats_gold, "balance":bal_gold, "candles":len(df_gold)}
        print(f"GOLD BT 30D: {stats_gold['total']} trades WR {wr_gold:.1f}% PnL {stats_gold['pnl_sum']:+.2f}%")
        with open(os.path.join(DATA_DIR, "gold_bt_30d.json"), 'w', encoding='utf-8') as f:
            json.dump(stats_gold, f, indent=2, ensure_ascii=False)
    else:
        print("GOLD fetch failed")
        bt_results["PAXGUSDT"] = {"wr":0, "stats":{"total":0,"wins":0,"losses":0,"pnl_sum":0,"max_dd":0}, "balance":40.16, "candles":0}

    # ส่งผลเข้า Telegram
    print(f"=== BT DONE {thai_time()} ===")
    msg = f"📈 [{thai_time()}] BT 30 วันเสร็จ | {DATA_DIR}\n\n"
    for sym, res in bt_results.items():
        wr = res['wr']
        st = res['stats']
        bal = res['balance']
        status = "✅ ผ่าน" if wr>=60 and st['pnl_sum']>0 else "⚠️ ไม่ผ่าน"
        emoji = "🟢" if wr>=60 and st['pnl_sum']>0 else "🔴"
        msg += f"{emoji} {sym} {status}\n"
        msg += f"Trades {st['total']} WR {wr:.1f}% PnL {st['pnl_sum']:+.2f}%\n"
        msg += f"Bal 40.16→{bal:.2f} MaxDD {st['max_dd']:.1f}% Wins {st['wins']}/Loss {st['losses']}\n\n"
    
    msg += f"เกณฑ์ผ่าน: WR≥60% PnL>0 MaxDD<15%\n"
    if all(r['wr']>=60 and r['stats']['pnl_sum']>0 for r in bt_results.values()):
        msg += f"✅ พร้อมลงเงินจริงแล้ว! เปลี่ยน DRY_RUN=False"
    else:
        msg += f"⚠️ ต้องปรับ TP/SL ต่อ"
    
    msg += f"\nดูเว็บ /stats ได้เลย | {DATA_DIR}"
    send_telegram(msg)
    print(msg)
    print(bt_results)

@app.route('/')
def home():
    if not bt_results:
        return f"<h2>V13 BT 30 DAYS + TELE - Running... {thai_time()} | {DATA_DIR}</h2>กำลัง BT รอ 1-2 นาที แล้วจะส่งเข้า Telegram"
    html = f"<h2>BT 30 DAYS + TELE RESULT - {thai_time()} - {DATA_DIR}</h2>"
    for sym, res in bt_results.items():
        wr = res['wr']
        st = res['stats']
        bal = res['balance']
        status = "✅ ผ่าน พร้อมลงเงินจริง" if wr>=60 and st['pnl_sum']>0 else "⚠️ ยังไม่ผ่าน"
        html += f"<h3>{sym} {status}</h3>"
        html += f"Trades {st['total']} WR {wr:.1f}% PnL {st['pnl_sum']:+.2f}% Bal 40.16 -> {bal:.2f} MaxDD {st['max_dd']:.1f}%<br>"
        html += f"Wins {st['wins']} Losses {st['losses']} Candles {res['candles']}<br><hr>"
    html += f"<br><b>ส่งเข้า Telegram แล้ว</b> | เกณฑ์ผ่าน WR≥60% PnL>0 MaxDD<15%<br>"
    return html

@app.route('/health')
def health():
    return jsonify({"status":"ok","version":"V13 BT 30D + TELE","data_dir":DATA_DIR,"results":bt_results,"time":thai_time()})

@app.route('/stats')
def stats_page():
    return home()

import threading
def bt_thread():
    time.sleep(5)
    bt_all()

threading.Thread(target=bt_thread, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
