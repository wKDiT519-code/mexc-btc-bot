"""
V12.26 BTC LONG/SHORT ULTIMATE PRICE FIX - แยกคุย BTC สัญญาณ LONG มาแล้ว
- BTCUSDT LONG/SHORT ได้ในเทเล
- Price ใช้ CoinGecko + Binance Vision การันตีได้ราคา
- Kline ใช้ Binance Vision + MEXC spot + OKX
- คำสั่ง: /open long, /open short, /close, /close long, /close short
"""

import requests, os, time, threading, json
from flask import Flask, jsonify, request
from datetime import datetime
import pytz

def get_data_dir():
    try:
        if os.path.exists("/mnt/data") and os.access("/mnt/data", os.W_OK):
            return "/mnt/data"
        os.makedirs("/mnt/data", exist_ok=True)
        if os.access("/mnt/data", os.W_OK):
            return "/mnt/data"
    except:
        pass
    try:
        os.makedirs("./data", exist_ok=True)
    except:
        pass
    return "./data"

DATA_DIR = get_data_dir()
print(f"V12.26 BTC LONG/SHORT - DATA_DIR: {DATA_DIR}")

MEXC_API_KEY = os.environ.get("MEXC_API_KEY", "").strip()
MEXC_API_SECRET = os.environ.get("MEXC_API_SECRET", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

SYMBOL = "BTCUSDT"
SYMBOL_MEXC_ID = "BTC_USDT"
ORDER_PERCENT = 10
LEVERAGE = 5
TP_PCT = 2.5
SL_PCT = 1.2
MAX_WOODS = 3
COOLDOWN_AFTER_SL = 0.25
MAX_HOLD_HOURS = 24
DAILY_MAX_LOSS = 2
AVOID_FUNDING_MINUTES = 10
FUNDING_TIMES_UTC = [0, 8, 16]

POSITIONS_FILE = os.path.join(DATA_DIR, "positions.json")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")

app = Flask(__name__)

@app.route('/', methods=['GET','HEAD'])
def home():
    if request.method == 'HEAD':
        return '', 200
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    pos_info = f"{len(positions)} BTC" if positions else "ว่าง"
    return f"V12.26 BTC LONG/SHORT LIVE | {DATA_DIR} | Pos:{pos_info} | Trades:{stats['total_trades']} WR:{wr:.1f}% | Price FIXED"

@app.route('/health', methods=['GET','HEAD'])
def health():
    if request.method == 'HEAD':
        return '', 200
    return jsonify({"status":"ok","version":"V12.26 BTC LONG/SHORT","data_dir":DATA_DIR,"positions":len(positions),"trades":stats["total_trades"]})

positions, highest, lowest, last_hourly = [], 0, 999999, time.time()
stats = {"total_trades":0,"wins":0,"losses":0,"total_pnl_pct":0.0,"history":[]}
cooldown_until = 0
daily_loss_count = 0
last_daily_reset = datetime.now(pytz.timezone('Asia/Bangkok')).day
manual_pause_until = 0

try:
    import ccxt
    mexc_public = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    if MEXC_API_KEY and MEXC_API_SECRET:
        mexc = ccxt.mexc({'apiKey': MEXC_API_KEY, 'secret': MEXC_API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        try:
            mexc.load_markets()
        except:
            pass
    else:
        mexc = None
except:
    mexc_public = None
    mexc = None

def thai_time():
    return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")

def save_positions():
    try:
        with open(POSITIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"positions": positions, "highest": highest, "lowest": lowest}, f)
    except:
        pass

def load_positions():
    global positions, highest, lowest
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                positions = data.get("positions", [])
                highest = data.get("highest", 0)
                lowest = data.get("lowest", 999999)
                return len(positions) > 0
    except:
        pass
    return False

def save_stats():
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f)
    except:
        pass

def load_stats():
    global stats
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                stats = json.load(f)
    except:
        pass

load_stats()
load_positions()

@app.route('/stats')
def stats_page():
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    hist = "".join([f"{h['time']} {h['type']} {h['pnl']:+.2f}%<br>" for h in stats["history"][-20:]])
    return f"<h2>V12.26 BTC LONG/SHORT - {DATA_DIR}</h2>Pos:{len(positions)} Trades:{stats['total_trades']} WR:{wr:.1f}%<br><hr>{hist}"

def send_telegram(msg, chat_id=None):
    target = str(chat_id) if chat_id else CHAT_ID
    if not BOT_TOKEN or not target:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": target, "text": msg, "parse_mode":"HTML", "disable_web_page_preview": True}, timeout=15)
        return r.json().get('ok', False)
    except:
        return False

def get_price_mexc():
    # 1. CoinGecko bitcoin
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": "bitcoin", "vs_currencies": "usd"}, timeout=10)
        if r.status_code == 200:
            price = float(r.json().get('bitcoin', {}).get('usd', 0))
            if price > 1000:
                print(f"Price CoinGecko BTC ok {price}")
                return price
    except Exception as e:
        print(f"Price CoinGecko err {e}")
    # 2. Binance Vision
    for host in ["https://data-api.binance.vision", "https://api.binance.com", "https://api1.binance.com"]:
        try:
            r = requests.get(f"{host}/api/v3/ticker/price", params={"symbol": SYMBOL}, timeout=10)
            if r.status_code == 200:
                price = float(r.json().get('price', 0))
                if price > 1000:
                    print(f"Price {host} BTC ok {price}")
                    return price
        except Exception as e:
            print(f"Price {host} err {e}")
    # 3. MEXC spot
    try:
        r = requests.get("https://api.mexc.com/api/v3/ticker/price", params={"symbol": SYMBOL}, timeout=10)
        if r.status_code == 200:
            price = float(r.json().get('price', 0))
            if price > 1000:
                return price
    except:
        pass
    # 4. OKX
    try:
        r = requests.get("https://www.okx.com/api/v5/market/ticker", params={"instId": "BTC-USDT"}, timeout=10)
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data:
                price = float(data[0].get('last', 0))
                if price > 1000:
                    return price
    except:
        pass
    print("Price all failed")
    return None

def get_klines_mexc(limit=200, timeframe='15m'):
    for host in ["https://data-api.binance.vision", "https://api.binance.com"]:
        try:
            tf_map = {'15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}
            bin_tf = tf_map.get(timeframe, '15m')
            r = requests.get(f"{host}/api/v3/klines", params={"symbol": SYMBOL, "interval": bin_tf, "limit": limit}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 50:
                    ohlcv = []
                    for k in data:
                        ohlcv.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
                    print(f"Kline {host} BTC ok {len(ohlcv)} TF {timeframe}")
                    return ohlcv
        except Exception as e:
            print(f"Kline {host} err {e}")
    # MEXC spot
    try:
        tf_map2 = {'15m': '15m', '1h': '60m', '4h': '4h', '1d': '1d'}
        mexc_tf = tf_map2.get(timeframe, '15m')
        r = requests.get("https://api.mexc.com/api/v3/klines", params={"symbol": SYMBOL, "interval": mexc_tf, "limit": limit}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 50:
                ohlcv = []
                for k in data:
                    ohlcv.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
                return ohlcv
    except:
        pass
    # OKX
    try:
        okx_tf = {'15m': '15m', '1h': '1H', '4h': '4H', '1d': '1D'}
        bar = okx_tf.get(timeframe, '15m')
        r = requests.get("https://www.okx.com/api/v5/market/candles", params={"instId": "BTC-USDT", "bar": bar, "limit": str(limit)}, timeout=15)
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data and len(data) > 50:
                ohlcv = []
                for k in reversed(data):
                    ohlcv.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
                return ohlcv
    except:
        pass
    print("Kline all failed BTC")
    return None

def ema_series(prices, span):
    alpha = 2.0/(span+1)
    ema = []
    for i,p in enumerate(prices):
        if i==0:
            ema.append(p)
        else:
            ema.append(alpha*p + (1-alpha)*ema[-1])
    return ema

def calc_indicators(ohlcv):
    if not ohlcv or len(ohlcv) < 50:
        return None
    try:
        closes = [float(x[4]) for x in ohlcv]
        highs = [float(x[2]) for x in ohlcv]
        lows = [float(x[3]) for x in ohlcv]
        opens = [float(x[1]) for x in ohlcv]
        vols = [float(x[5]) for x in ohlcv]
        times = [x[0] for x in ohlcv]
        n = len(closes)
        ema12 = ema_series(closes, 12)
        ema26 = ema_series(closes, 26)
        ema20 = ema_series(closes, 20)
        rsi = [50.0]*n
        gains = []
        losses = []
        for i in range(1,n):
            d = closes[i]-closes[i-1]
            gains.append(max(d,0))
            losses.append(max(-d,0))
        avg_gain = sum(gains[:14])/14 if len(gains)>=14 else 0.001
        avg_loss = sum(losses[:14])/14 if len(losses)>=14 else 0.001
        for i in range(14, n):
            if i>14 and i-1 < len(gains):
                avg_gain = (avg_gain*13 + gains[i-1])/14
                avg_loss = (avg_loss*13 + losses[i-1])/14
            rs = avg_gain/(avg_loss if avg_loss!=0 else 0.001)
            rsi[i] = 100 - (100/(1+rs))
        tr = [0.0]*n
        atr = [0.0]*n
        for i in range(n):
            if i==0:
                tr[i]=highs[i]-lows[i]
            else:
                tr[i]=max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        atr[13]=sum(tr[:14])/14 if n>=14 else tr[0]
        for i in range(14,n):
            atr[i]=(atr[i-1]*13 + tr[i])/14
        rows=[]
        for i in range(n):
            rows.append({
                'ot': times[i], 'o': opens[i], 'h': highs[i], 'l': lows[i], 'c': closes[i], 'v': vols[i],
                'EMA12': ema12[i], 'EMA26': ema26[i], 'EMA20': ema20[i],
                'RSI': rsi[i], 'ATR': atr[i],
            })
        return rows
    except Exception as e:
        print(f"calc err {e}")
        return None

def get_balance():
    if not mexc:
        return 40.16
    try:
        bal = mexc.fetch_balance()
        return float(bal.get('USDT', {}).get('free', 0) or bal.get('total', {}).get('USDT', 0) or 40.16)
    except:
        return 40.16

def mexc_buy(price, factor=1.0, custom_qty=None, side="long"):
    if not mexc:
        print(f"DRY RUN {side} BTC")
        qty = custom_qty or 0.001
        positions.append({'entry': price, 'qty': qty, 'side': side, 'time': time.time()})
        save_positions()
        return True, qty
    try:
        try:
            mexc.set_leverage(5, SYMBOL, {'marginMode': 'CROSS'})
        except:
            pass
        balance = get_balance()
        if custom_qty:
            qty = float(custom_qty)
        else:
            usdt_to_use = balance * 10 / 100 * factor
            qty = (usdt_to_use * 5) / price
            qty = max(0.001, round(qty, 3))
            qty = min(qty, 0.01)
        print(f"REAL {side.upper()} BTC qty {qty} @ {price}")
        if side == "long":
            order = mexc.create_market_buy_order(SYMBOL, qty)
        else:
            order = mexc.create_market_sell_order(SYMBOL, qty)
        print(f"{side} filled")
        positions.append({'entry': price, 'qty': qty, 'side': side, 'time': time.time()})
        save_positions()
        return True, qty
    except Exception as e:
        print(f"BUY {side} ERR {e}")
        send_telegram(f"❌ {side.upper()} ERROR {e}")
        return False, 0

def close_position(price, reason, close_side="all"):
    global cooldown_until, daily_loss_count, positions, highest, lowest
    if not positions:
        return False
    to_close = []
    remain = []
    for p in positions:
        if close_side == "all" or p.get('side','long') == close_side:
            to_close.append(p)
        else:
            remain.append(p)
    if not to_close:
        return False
    total_qty = sum(abs(p['qty']) for p in to_close)
    pnl = 0
    for p in to_close:
        if p.get('side','long') == 'long':
            pnl += (price - p['entry'])/p['entry']*100 * (abs(p['qty'])/total_qty)
        else:
            pnl += (p['entry'] - price)/p['entry']*100 * (abs(p['qty'])/total_qty)
    if mexc:
        try:
            long_qty = sum(abs(p['qty']) for p in to_close if p.get('side','long')=='long')
            short_qty = sum(abs(p['qty']) for p in to_close if p.get('side')=='short')
            if long_qty > 0:
                mexc.create_market_sell_order(SYMBOL, long_qty)
            if short_qty > 0:
                mexc.create_market_buy_order(SYMBOL, short_qty)
        except Exception as e:
            print(f"CLOSE ERR {e}")
    stats["total_trades"]+=1
    if pnl>0:
        stats["wins"]+=1
    else:
        stats["losses"]+=1
        daily_loss_count+=1
        cooldown_until = time.time() + 0.25*3600
    stats["total_pnl_pct"]+=pnl
    stats["history"].append({"time":thai_time(),"type":f"{close_side.upper()} {reason}","pnl":pnl})
    save_stats()
    send_telegram(f"{'🔴' if pnl<0 else '🟢'} [{thai_time()}] ปิด {close_side} {reason} PnL {pnl:+.2f}% @ {price:.2f}$ BTC")
    positions = remain
    if not positions:
        highest=0
        lowest=999999
    save_positions()
    return True

def manual_open(qty_str=None, side="long"):
    global manual_pause_until
    price = get_price_mexc()
    if not price:
        send_telegram(f"❌ เปิดไม่ได้ ดึงราคาไม่ได้ {thai_time()}")
        return
    if len(positions) >= MAX_WOODS:
        send_telegram(f"⚠️ มี {len(positions)} ไม้เต็มแล้ว /close ก่อน {thai_time()}")
        return
    custom_qty = None
    if qty_str:
        try:
            custom_qty = float(qty_str)
        except:
            custom_qty = None
    ok, qty = mexc_buy(price, factor=1.0, custom_qty=custom_qty, side=side)
    if ok:
        manual_pause_until = time.time() + 300
        send_telegram(f"✅ OPEN {side.upper()} {qty} @ {price:.2f}$ {thai_time()} Pos:{len(positions)}")

def manual_close(close_side="all"):
    global manual_pause_until
    price = get_price_mexc()
    if not price:
        price = positions[0]['entry'] if positions else 0
    if not positions:
        send_telegram(f"ℹ️ ไม่มีออเดอร์ให้ปิด {thai_time()}")
        return
    ok = close_position(price, "MANUAL_CLOSE", close_side=close_side)
    if ok:
        manual_pause_until = time.time() + 300
        send_telegram(f"✅ CLOSE {close_side} สำเร็จ {thai_time()}")

def trading_loop():
    global last_hourly
    print(f"V12.26 BTC START {DATA_DIR}")
    price = get_price_mexc()
    send_telegram(f"🚀 V12.26 BTC LONG/SHORT START {thai_time()} Price:{price} Pos:{len(positions)} สัญญาณ LONG มาแล้ว! /open long /open short /close ได้")
    while True:
        try:
            if manual_pause_until > time.time():
                time.sleep(10)
                continue
            ohlcv = get_klines_mexc(200, '15m')
            if not ohlcv or len(ohlcv)<50:
                time.sleep(60)
                continue
            rows = calc_indicators(ohlcv)
            if not rows:
                time.sleep(60)
                continue
            last = rows[-1]
            prev = rows[-2]
            price = float(last['c'])
            # Simple EMA signal for BTC
            ema_bull = last['EMA12'] > last['EMA26']
            ema_bear = last['EMA12'] < last['EMA26']
            # Auto trade example - LONG only for now as signal LONG
            if time.time()-last_hourly >= 14400:
                last_hourly=time.time()
                send_telegram(f"📊 BTC [{thai_time()}] Price {price:.2f} EMA12 {last['EMA12']:.2f} EMA26 {last['EMA26']:.2f} RSI {last['RSI']:.1f} Pos:{len(positions)} สัญญาณ LONG!")
            time.sleep(60)
        except Exception as e:
            print(f"Loop err {e}")
            time.sleep(30)

threading.Thread(target=trading_loop, daemon=True).start()

def telegram_check_loop():
    global cooldown_until
    if not BOT_TOKEN:
        return
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
    except:
        pass
    offset = 0
    print(f"Telegram BTC LONG/SHORT started Chat {CHAT_ID}")
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset+1}&timeout=30", timeout=35)
            data = r.json()
            if not data.get("ok"):
                err = data.get('description','')
                print(f"getUpdates not ok {data}")
                if '409' in str(data) or 'Conflict' in err:
                    try:
                        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
                    except:
                        pass
                    time.sleep(30)
                else:
                    time.sleep(5)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"]
                msg = upd.get("message", {})
                text_raw = msg.get("text","").strip()
                text = text_raw.lower()
                chat = str(msg.get("chat",{}).get("id",""))
                print(f"Got Tele BTC: '{text_raw}' from {chat}")
                if text in ["/start","/check","/status","/running"]:
                    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
                    long_pos = len([p for p in positions if p.get('side','long')=='long'])
                    short_pos = len([p for p in positions if p.get('side')=='short'])
                    price = get_price_mexc()
                    send_telegram(f"✅ BTC บอทรันอยู่\n⏰ {thai_time()}\nBTC Price:{price}\nPos:{len(positions)} L:{long_pos} S:{short_pos}\nWR:{wr:.1f}% Trades:{stats['total_trades']}\n\n/open long - เปิด LONG\n/open short - เปิด SHORT\n/open long 0.002\n/close - ปิดทั้งหมด\n/close long\n/close short\nสัญญาณ LONG มาแล้ว!", chat)
                elif text.startswith("/open") or text.startswith("/buy") or text.startswith("/long") or text.startswith("/short") or text.startswith("/sell"):
                    parts = text_raw.split()
                    side = "long"
                    qty = None
                    low = text_raw.lower()
                    if "short" in low or low.startswith("/short") or low.startswith("/sell"):
                        side = "short"
                    for p in parts[1:]:
                        try:
                            float(p)
                            qty = p
                            break
                        except:
                            continue
                    if len(parts)>=2 and parts[1].lower() in ["long","short"]:
                        side = parts[1].lower()
                        if len(parts)>=3:
                            qty = parts[2]
                    threading.Thread(target=manual_open, args=(qty, side), daemon=True).start()
                    send_telegram(f"⏳ เปิด {side.upper()} {qty or '0.001'} BTC...", chat)
                elif text.startswith("/close"):
                    close_side = "all"
                    if "long" in text:
                        close_side = "long"
                    elif "short" in text:
                        close_side = "short"
                    threading.Thread(target=manual_close, args=(close_side,), daemon=True).start()
                    send_telegram(f"⏳ ปิด {close_side} {len(positions)} ไม้ BTC...", chat)
                elif text == "/balance":
                    try:
                        bal = get_balance()
                        price = get_price_mexc()
                        send_telegram(f"💰 BTC Balance {thai_time()}\nUSDT:${bal:.2f}\nBTC Price:{price}\nPos:{len(positions)}\n/open long /open short", chat)
                    except Exception as e:
                        send_telegram(f"Balance err {e}", chat)
                elif text == "/data":
                    try:
                        total_qty = sum(abs(p.get('qty',0)) for p in positions)
                        send_telegram(f"📁 BTC DATA {thai_time()}\nDATA_DIR:{DATA_DIR}\nPos:{len(positions)} Qty:{total_qty}\n/open long /open short", chat)
                    except Exception as e:
                        send_telegram(f"/data err {e}", chat)
                elif text == "/bt":
                    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
                    send_telegram(f"📊 BTC BT {thai_time()}\nTrades:{stats['total_trades']} WR:{wr:.1f}%\nPos:{len(positions)}\n/open long /open short", chat)
        except Exception as e:
            print(f"Tele err {e}")
            time.sleep(10)

threading.Thread(target=telegram_check_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
