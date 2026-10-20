"""
V14 BTC AUTO 2+3 - เพิ่ม Auto Signal + Grid สำหรับ BTC
ตามคำขอ: เพิ่ม 2/3 แต่เราเทรด btc นะ

2 = Auto Signal: EMA 9/21 + RSI Auto เปิด LONG/SHORT
3 = Grid Bot BTC: วางไม้ซื้อขายถี่ๆ กินกำไร Sideway

Features BTC:
- /auto on/off → เปิด Auto Signal EMA 9/21 + RSI 14
- /grid on/off → เปิด Grid Bot BTC ช่วง 80000-83000
- /auto ตั้งค่า: /ema 9 21 /rsi 30 70
- /grid ตั้งค่า: /gridrange 80000 83000 10
- Manual ยังได้: /open long 0.0005 sl 3.4 tp 18 REAL SL/TP บน MEXC
- ทุน $40 → 0.0005 BTC=5 CONT Margin $5 SL 3.4% TP 18%
- REAL SL/TP บน MEXC Exchange + Bot Monitor 10 วิ
"""

import requests, os, time, threading, json
from flask import Flask, jsonify
from datetime import datetime
import pytz
import math

DATA_DIR = "/mnt/data" if os.path.exists("/mnt/data") else "./data"
os.makedirs(DATA_DIR, exist_ok=True)

MEXC_API_KEY = os.environ.get("MEXC_API_KEY","").strip()
MEXC_API_SECRET = os.environ.get("MEXC_API_SECRET","").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()

SYMBOL_CCXT = "BTC/USDT:USDT"
DEFAULT_BTC = 0.0005
DEFAULT_CONT = 5
LEVERAGE = 8
DEFAULT_SL_PCT = 3.4
DEFAULT_TP_PCT = 18.0

# Auto Signal Config
auto_enabled = False
ema_short = 9
ema_long = 21
rsi_low = 30
rsi_high = 70
rsi_period = 14

# Grid Config
grid_enabled = False
grid_low = 80000
grid_high = 83000
grid_num = 10
grid_qty = 0.0005

POSITIONS_FILE = os.path.join(DATA_DIR, "positions_v14.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config_v14.json")
STATS_FILE = os.path.join(DATA_DIR, "stats_v14.json")

app = Flask(__name__)
@app.route('/')
def home(): return f"V14 BTC AUTO 2+3 | Auto {auto_enabled} Grid {grid_enabled} | BTC {DEFAULT_BTC} SL {DEFAULT_SL_PCT}% TP {DEFAULT_TP_PCT}%"
@app.route('/health')
def health(): return jsonify({"version":"V14","auto":auto_enabled,"grid":grid_enabled,"symbol":"BTCUSDT","btc":DEFAULT_BTC,"sl":DEFAULT_SL_PCT,"tp":DEFAULT_TP_PCT})

positions=[]; stats={"total_trades":0,"wins":0,"losses":0,"total_pnl_pct":0.0,"history":[],"auto_trades":0,"grid_trades":0}
mexc=None

try:
    import ccxt
    mexc = ccxt.mexc({'apiKey': MEXC_API_KEY, 'secret': MEXC_API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    print(f"✅ V14 BTC AUTO MEXC created KEY len {len(MEXC_API_KEY)}")
except Exception as e:
    print(f"CREATE FAIL {e}")
    mexc=None

def thai_time(): return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")

def save_positions():
    try:
        with open(POSITIONS_FILE,'w',encoding='utf-8') as f: json.dump({"positions":positions}, f)
    except: pass
def load_positions():
    global positions
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE,'r',encoding='utf-8') as f: positions=json.load(f).get("positions",[])
    except: pass
def save_stats():
    try:
        with open(STATS_FILE,'w',encoding='utf-8') as f: json.dump(stats,f)
    except: pass
def load_stats():
    global stats
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE,'r',encoding='utf-8') as f: stats.update(json.load(f))
    except: pass
def save_config():
    try:
        cfg={"auto_enabled":auto_enabled,"ema_short":ema_short,"ema_long":ema_long,"rsi_low":rsi_low,"rsi_high":rsi_high,"grid_enabled":grid_enabled,"grid_low":grid_low,"grid_high":grid_high,"grid_num":grid_num,"grid_qty":grid_qty}
        with open(CONFIG_FILE,'w',encoding='utf-8') as f: json.dump(cfg,f)
    except: pass
def load_config():
    global auto_enabled, ema_short, ema_long, rsi_low, rsi_high, grid_enabled, grid_low, grid_high, grid_num, grid_qty
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE,'r',encoding='utf-8') as f:
                c=json.load(f)
                auto_enabled=c.get("auto_enabled",False)
                ema_short=c.get("ema_short",9)
                ema_long=c.get("ema_long",21)
                rsi_low=c.get("rsi_low",30)
                rsi_high=c.get("rsi_high",70)
                grid_enabled=c.get("grid_enabled",False)
                grid_low=c.get("grid_low",80000)
                grid_high=c.get("grid_high",83000)
                grid_num=c.get("grid_num",10)
                grid_qty=c.get("grid_qty",0.0005)
    except: pass
load_stats(); load_positions(); load_config()

def send_telegram(msg, chat_id=None):
    target=str(chat_id) if chat_id else CHAT_ID
    if not BOT_TOKEN or not target: return False
    try:
        r=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id":target,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=10)
        return r.json().get('ok',False)
    except: return False

def get_price_fast(symbol="BTCUSDT"):
    try:
        r=requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol":symbol}, timeout=5)
        if r.status_code==200: return float(r.json().get('price',0))
    except: pass
    return 81500.0

def get_klines(symbol="BTCUSDT", interval="15m", limit=100):
    try:
        r=requests.get("https://api.binance.com/api/v3/klines", params={"symbol":symbol,"interval":interval,"limit":limit}, timeout=10)
        if r.status_code==200:
            data=r.json()
            closes=[float(k[4]) for k in data]
            return closes
    except: pass
    return []

def calc_ema(prices, period):
    if len(prices) < period: return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period+1: return 50
    deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    gains = [d if d>0 else 0 for d in deltas]
    losses = [-d if d<0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss==0: return 100
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def get_balance_real():
    if not mexc:
        return 40.0, False, f"mexc None KEY len {len(MEXC_API_KEY)}"
    try:
        bal=mexc.fetch_balance()
        free = bal.get('USDT',{}).get('free',0)
        total = bal.get('USDT',{}).get('total',0)
        usdt = free if free>0 else total
        return float(usdt), True, f"REAL Bal ${usdt:.2f}"
    except Exception as e:
        err=str(e)
        if "403" in err: return 40.0, False, f"403 - BTC ok PAXG ok GOLD blocked"
        return 40.0, False, f"Bal ERR {err[:150]}"

def convert_qty(qty_input):
    try:
        qty=float(qty_input)
        if qty >= 1: return int(qty)
        return max(1, int(qty / 0.0001))
    except: return DEFAULT_CONT

def calc_sl_tp(entry, side, sl_pct, tp_pct):
    if side=='long':
        sl_price = entry * (1 - sl_pct/100/LEVERAGE)
        tp_price = entry * (1 + tp_pct/100/LEVERAGE)
    else:
        sl_price = entry * (1 + sl_pct/100/LEVERAGE)
        tp_price = entry * (1 - tp_pct/100/LEVERAGE)
    return sl_price, tp_price

def set_real_sl_tp_on_mexc(symbol_ccxt, side, qty, sl_price, tp_price):
    if not mexc:
        return False, False, "mexc None"
    sl_ok=False; tp_ok=False; details=[]
    close_side = 'sell' if side=='long' else 'buy'
    try:
        sl_trigger_type = 2 if side=='long' else 1
        tp_trigger_type = 1 if side=='long' else 2
        try:
            sl_order = mexc.create_order(symbol_ccxt, 'market', close_side, qty, None, {'triggerPrice': sl_price,'triggerType': sl_trigger_type,'reduceOnly': True,'openType': 1,})
            sl_ok=True
            details.append(f"SL REAL @ {sl_price:.0f}")
        except Exception as e1:
            details.append(f"SL fail {str(e1)[:100]}")
        try:
            tp_order = mexc.create_order(symbol_ccxt, 'market', close_side, qty, None, {'triggerPrice': tp_price,'triggerType': tp_trigger_type,'reduceOnly': True,'openType': 1,})
            tp_ok=True
            details.append(f"TP REAL @ {tp_price:.0f}")
        except Exception as e2:
            details.append(f"TP fail {str(e2)[:100]}")
    except Exception as e:
        details.append(f"general fail {str(e)[:100]}")
    return sl_ok, tp_ok, " | ".join(details)

def mexc_open_with_real_sl_tp(price, qty_input, side, sl_pct=None, tp_pct=None, source="Manual"):
    global SYMBOL_CCXT
    side='long' if side.lower() in ['long','buy'] else 'short'
    sl_pct = float(sl_pct) if sl_pct is not None else DEFAULT_SL_PCT
    tp_pct = float(tp_pct) if tp_pct is not None else DEFAULT_TP_PCT
    cont = convert_qty(qty_input)
    btc_actual = cont * 0.0001
    notional = btc_actual * price
    margin = notional / LEVERAGE
    balance, is_real, bal_msg = get_balance_real()
    mode = "REAL" if is_real and mexc else "DRY RUN"
    sl_price, tp_price = calc_sl_tp(price, side, sl_pct, tp_pct)

    if source.startswith("Auto"):
        send_telegram(f"🤖 V14 AUTO SIGNAL {mode} {side.upper()} BTC {btc_actual:.4f}={cont} CONT\nPrice {price:.0f} EMA{ema_short} {ema_long} RSI {calc_rsi(get_klines()):.0f}\nSL {sl_pct}% @ {sl_price:.0f} TP {tp_pct}% @ {tp_price:.0f} {bal_msg}")
    elif source.startswith("Grid"):
        send_telegram(f"🔲 V14 GRID {mode} {side.upper()} BTC {btc_actual:.4f}={cont} CONT\nPrice {price:.0f} Grid {grid_low}-{grid_high} {bal_msg}")
    else:
        sl_loss = margin * sl_pct / 100
        tp_profit = margin * tp_pct / 100
        send_telegram(f"🔄 V14 {mode} OPEN {side.upper()} BTC {btc_actual:.4f}={cont} CONT\nPrice {price:.0f} Notional ${notional:.2f} Margin ${margin:.2f}\nSL {sl_pct}% @ {sl_price:.0f} Loss ${sl_loss:.2f}\nTP {tp_pct}% @ {tp_price:.0f} Profit ${tp_profit:.2f} {bal_msg}")

    if not mexc or not is_real:
        pos={'entry':price,'qty':cont,'btc':btc_actual,'side':side,'time':time.time(),'symbol':SYMBOL_CCXT,'sl_pct':sl_pct,'tp_pct':tp_pct,'sl_price':sl_price,'tp_price':tp_price,'real_sl':False,'real_tp':False,'source':source}
        positions.append(pos)
        save_positions()
        return True

    try:
        try: mexc.set_leverage(LEVERAGE, SYMBOL_CCXT, {'marginMode':'CROSS'})
        except: pass
        if side=='long': order=mexc.create_market_buy_order(SYMBOL_CCXT, cont)
        else: order=mexc.create_market_sell_order(SYMBOL_CCXT, cont)
        sl_ok, tp_ok, details = set_real_sl_tp_on_mexc(SYMBOL_CCXT, side, cont, sl_price, tp_price)
        pos={'entry':price,'qty':cont,'btc':btc_actual,'side':side,'time':time.time(),'symbol':SYMBOL_CCXT,'sl_pct':sl_pct,'tp_pct':tp_pct,'sl_price':sl_price,'tp_price':tp_price,'real_sl':sl_ok,'real_tp':tp_ok,'source':source}
        positions.append(pos)
        save_positions()
        if source.startswith("Auto"): stats["auto_trades"]+=1
        if source.startswith("Grid"): stats["grid_trades"]+=1
        save_stats()
        if sl_ok and tp_ok:
            send_telegram(f"✅ {source} REAL SL/TP สำเร็จ\n{side.upper()} BTC {cont} CONT @ {price:.0f} SL ✅ REAL @ {sl_price:.0f} TP ✅ REAL @ {tp_price:.0f} Bal ${balance:.2f}")
        else:
            send_telegram(f"⚠️ {source} OPEN แต่ SL/TP Bot Monitor\nSL {'✅ REAL' if sl_ok else '❌ Bot'} @ {sl_price:.0f} TP {'✅ REAL' if tp_ok else '❌ Bot'} @ {tp_price:.0f}\n{details[:200]}")
        return True
    except Exception as e:
        send_telegram(f"❌ OPEN FAILED BTC {cont} CONT {str(e)[:200]}")
        return False

def mexc_close_fast(price, side_filter=None, reason="Manual"):
    global positions
    if not positions:
        return False
    to_close = [p for p in positions if p['side']==side_filter] if side_filter in ['long','short'] else positions
    if not to_close: return False
    cont=sum(int(p['qty']) for p in to_close)
    sym = to_close[0].get('symbol', SYMBOL_CCXT)
    balance, is_real, bal_msg = get_balance_real()
    if mexc and is_real:
        try:
            if to_close[0]['side']=='long': mexc.create_market_sell_order(sym, cont)
            else: mexc.create_market_buy_order(sym, cont)
        except:
            try:
                if to_close[0]['side']=='long': mexc.create_order(sym, 'market', 'sell', cont, None, {'openType':1})
                else: mexc.create_order(sym, 'market', 'buy', cont, None, {'openType':1})
            except: pass
        try:
            open_orders = mexc.fetch_open_orders(sym)
            for o in open_orders:
                try: mexc.cancel_order(o['id'], sym)
                except: pass
        except: pass
    avg=sum(p['entry']*p['qty'] for p in to_close)/sum(p['qty'] for p in to_close)
    pnl=(price-avg)/avg*100*LEVERAGE if to_close[0]['side']=='long' else (avg-price)/avg*100*LEVERAGE
    positions=[p for p in positions if p not in to_close]
    save_positions()
    stats["total_trades"]+=1
    if pnl>0: stats["wins"]+=1
    else: stats["losses"]+=1
    stats["total_pnl_pct"]+=pnl
    save_stats()
    mode="REAL" if is_real else "DRY RUN"
    emoji="🟢 TP" if pnl>0 else "🔴 SL"
    send_telegram(f"{emoji} {mode} CLOSE {to_close[0]['side'].upper()} BTC {cont} CONT {reason}\nPnL {pnl:+.2f}% @ {price:.0f} {bal_msg} Src {to_close[0].get('source','')}")
    return True

def manual_open(side='long', qty_str=None, sl_str=None, tp_str=None, source="Manual"):
    try:
        price=get_price_fast("BTCUSDT")
        qty_input = qty_str if qty_str else str(DEFAULT_BTC)
        sl_pct = float(sl_str) if sl_str else DEFAULT_SL_PCT
        tp_pct = float(tp_str) if tp_str else DEFAULT_TP_PCT
        mexc_open_with_real_sl_tp(price, qty_input, side=side, sl_pct=sl_pct, tp_pct=tp_pct, source=source)
    except Exception as e:
        send_telegram(f"❌ open crash {e}")

# Auto Signal Loop
prev_ema_short = None
prev_ema_long = None

def auto_signal_loop():
    global prev_ema_short, prev_ema_long, auto_enabled, ema_short, ema_long
    while True:
        try:
            if not auto_enabled:
                time.sleep(30)
                continue
            closes = get_klines("BTCUSDT", "15m", 100)
            if len(closes) < ema_long+5:
                time.sleep(60)
                continue
            ema_s = calc_ema(closes, ema_short)
            ema_l = calc_ema(closes, ema_long)
            rsi = calc_rsi(closes, rsi_period)
            price = closes[-1]
            
            # Check cross
            if prev_ema_short is not None and prev_ema_long is not None:
                # Golden Cross: ema short crosses above long
                if prev_ema_short <= prev_ema_long and ema_s > ema_l and rsi < rsi_high:
                    # Check no long position already
                    has_long = any(p['side']=='long' for p in positions)
                    if not has_long and len(positions) < 2:
                        send_telegram(f"🤖 AUTO SIGNAL GOLDEN CROSS BTC\nEMA{ema_short} {ema_s:.0f} > EMA{ema_long} {ema_l:.0f} RSI {rsi:.0f} Price {price:.0f}\nAuto LONG {DEFAULT_BTC} BTC")
                        manual_open('long', str(DEFAULT_BTC), str(DEFAULT_SL_PCT), str(DEFAULT_TP_PCT), f"Auto EMA Cross LONG")
                
                # Death Cross: ema short crosses below long
                if prev_ema_short >= prev_ema_long and ema_s < ema_l and rsi > rsi_low:
                    has_short = any(p['side']=='short' for p in positions)
                    if not has_short and len(positions) < 2:
                        send_telegram(f"🤖 AUTO SIGNAL DEATH CROSS BTC\nEMA{ema_short} {ema_s:.0f} < EMA{ema_long} {ema_l:.0f} RSI {rsi:.0f} Price {price:.0f}\nAuto SHORT {DEFAULT_BTC} BTC")
                        manual_open('short', str(DEFAULT_BTC), str(DEFAULT_SL_PCT), str(DEFAULT_TP_PCT), f"Auto EMA Cross SHORT")

            prev_ema_short = ema_s
            prev_ema_long = ema_l
            time.sleep(60)
        except Exception as e:
            print(f"Auto loop err {e}")
            time.sleep(60)

threading.Thread(target=auto_signal_loop, daemon=True).start()

# Grid Bot Loop
grid_orders = []

def grid_loop():
    global grid_enabled, grid_low, grid_high, grid_num, grid_qty
    while True:
        try:
            if not grid_enabled:
                time.sleep(30)
                continue
            price = get_price_fast("BTCUSDT")
            if price < grid_low or price > grid_high:
                # Price out of grid range
                time.sleep(30)
                continue
            
            # Grid logic: if price drops, buy; if rises, sell
            # Simplified: maintain 1 long and 1 short grid
            spacing = (grid_high - grid_low) / grid_num
            
            # Count grid positions
            grid_positions = [p for p in positions if p.get('source','').startswith('Grid')]
            if len(grid_positions) >= 4:
                time.sleep(30)
                continue

            # If price near lower grid -> buy
            # If price near upper grid -> sell
            # For BTC $40 capital, grid 10 levels 80000-83000 spacing $300
            # Buy when price % spacing < 0.3 * spacing
            lower_grid = math.floor((price - grid_low) / spacing) * spacing + grid_low
            upper_grid = lower_grid + spacing
            dist_to_lower = price - lower_grid
            
            if dist_to_lower < spacing * 0.4:
                # Near lower -> buy (expect bounce)
                has_long = any(p['side']=='long' and p.get('source','').startswith('Grid') for p in positions)
                if not has_long:
                    send_telegram(f"🔲 GRID BUY SIGNAL BTC Price {price:.0f} Near Lower {lower_grid:.0f} Spacing ${spacing:.0f}")
                    manual_open('long', str(grid_qty), str(DEFAULT_SL_PCT), str(DEFAULT_TP_PCT/2), f"Grid BUY {lower_grid:.0f}")
            
            if dist_to_lower > spacing * 0.6:
                has_short = any(p['side']=='short' and p.get('source','').startswith('Grid') for p in positions)
                if not has_short:
                    send_telegram(f"🔲 GRID SELL SIGNAL BTC Price {price:.0f} Near Upper {upper_grid:.0f} Spacing ${spacing:.0f}")
                    manual_open('short', str(grid_qty), str(DEFAULT_SL_PCT), str(DEFAULT_TP_PCT/2), f"Grid SELL {upper_grid:.0f}")

            time.sleep(60)
        except Exception as e:
            print(f"Grid loop err {e}")
            time.sleep(60)

threading.Thread(target=grid_loop, daemon=True).start()

def check_sl_tp_loop():
    while True:
        try:
            if not positions:
                time.sleep(10)
                continue
            price = get_price_fast("BTCUSDT")
            for pos in positions[:]:
                side = pos['side']
                sl_price = pos.get('sl_price', 0)
                tp_price = pos.get('tp_price', 0)
                hit = None
                if side=='long':
                    if price <= sl_price: hit = f"SL {pos.get('sl_pct',0)}% Bot"
                    elif price >= tp_price: hit = f"TP {pos.get('tp_pct',0)}% Bot"
                else:
                    if price >= sl_price: hit = f"SL {pos.get('sl_pct',0)}% Bot"
                    elif price <= tp_price: hit = f"TP {pos.get('tp_pct',0)}% Bot"
                if hit:
                    mexc_close_fast(price, side_filter=None, reason=f"Auto {hit} @ {price:.0f}")
            time.sleep(10)
        except Exception as e:
            print(f"SL/TP check err {e}")
            time.sleep(10)

threading.Thread(target=check_sl_tp_loop, daemon=True).start()

def trading_loop():
    price=get_price_fast()
    bal, is_real, bal_msg = get_balance_real()
    mode="REAL" if is_real else "DRY RUN"
    send_telegram(f"🚀 V14 BTC AUTO 2+3 START {thai_time()}\n{mode} | {bal_msg}\nBTC Price {price:.0f} ทุน $40 → {DEFAULT_BTC} BTC={DEFAULT_CONT} CONT Margin $5\n\nAuto Signal: {'ON ✅' if auto_enabled else 'OFF'} EMA{ema_short}/{ema_long} RSI {rsi_low}-{rsi_high}\nGrid: {'ON ✅' if grid_enabled else 'OFF'} {grid_low}-{grid_high} {grid_num} grids\n\n/open long {DEFAULT_BTC} sl {DEFAULT_SL_PCT} tp {DEFAULT_TP_PCT}\n/auto on /grid on /check")
    while True: time.sleep(60)

threading.Thread(target=trading_loop, daemon=True).start()

def telegram_check_loop():
    if not BOT_TOKEN: return
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
    except: pass
    offset=0
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset+1}&timeout=25", timeout=30)
            data=r.json()
            if not data.get("ok"): time.sleep(5); continue
            for upd in data.get("result",[]):
                offset=upd["update_id"]
                msg=upd.get("message",{})
                text_raw=msg.get("text","").strip()
                if not text_raw: continue
                text=text_raw.lower()
                chat=str(msg.get("chat",{}).get("id",""))

                if text in ["/start","/help"]:
                    send_telegram(f"📖 V14 BTC AUTO 2+3 คำสั่ง\n\n🤖 Auto Signal EMA+RSI:\n/auto on → เปิด Auto Signal\n/auto off → ปิด\n/ema 9 21 → ตั้ง EMA short long\n/rsi 30 70 → ตั้ง RSI low high\n\n🔲 Grid Bot BTC:\n/grid on → เปิด Grid {grid_low}-{grid_high}\n/grid off → ปิด Grid\n/gridrange 80000 83000 10 → ตั้งช่วงและจำนวนกริด\n\n📈 Manual BTC (ทุน $40):\n/open long {DEFAULT_BTC} → SL {DEFAULT_SL_PCT}% TP {DEFAULT_TP_PCT}% REAL\n/open long {DEFAULT_BTC} sl 5 tp 20\n/open short {DEFAULT_BTC}\n/sl 5 /tp 20 /close\n\n/check /balance /btc\nV14 Auto + Grid + REAL SL/TP", chat)

                elif text.startswith("/auto"):
                    parts=text_raw.split()
                    if len(parts)>=2:
                        if parts[1].lower()=="on":
                            globals()["auto_enabled"]=True
                            save_config()
                            send_telegram(f"✅ เปิด Auto Signal EMA{ema_short}/{ema_long} RSI {rsi_low}-{rsi_high}\nบอทจะดูกราฟ 15m ทุก 1 นาที Golden/Death Cross Auto เปิด LONG/SHORT\nทุน $40 {DEFAULT_BTC} BTC=5 CONT SL {DEFAULT_SL_PCT}% TP {DEFAULT_TP_PCT}%", chat)
                        elif parts[1].lower()=="off":
                            globals()["auto_enabled"]=False
                            save_config()
                            send_telegram("❌ ปิด Auto Signal", chat)
                    else:
                        send_telegram(f"🤖 Auto Signal {'ON ✅' if auto_enabled else 'OFF ❌'}\nEMA{ema_short}/{ema_long} RSI {rsi_low}-{rsi_high} 15m\n/auto on /auto off", chat)

                elif text.startswith("/grid"):
                    parts=text_raw.split()
                    if len(parts)>=2 and parts[1].lower()=="on":
                        globals()["grid_enabled"]=True
                        save_config()
                        send_telegram(f"✅ เปิด Grid Bot BTC\nช่วง {grid_low}-{grid_high} {grid_num} กริด Spacing ${(grid_high-grid_low)/grid_num:.0f}\nQty {grid_qty} BTC={convert_qty(grid_qty)} CONT\nบอทจะซื้อต่ำขายสูงอัตโนมัติ", chat)
                    elif len(parts)>=2 and parts[1].lower()=="off":
                        globals()["grid_enabled"]=False
                        save_config()
                        send_telegram("❌ ปิด Grid Bot", chat)
                    elif parts[1].lower().startswith("range") or len(parts)>=4:
                        # /gridrange 80000 83000 10
                        try:
                            if parts[0]=="/gridrange":
                                low=int(parts[1]); high=int(parts[2]); num=int(parts[3]) if len(parts)>=4 else grid_num
                            else:
                                low=int(parts[1]); high=int(parts[2]); num=int(parts[3]) if len(parts)>=4 else grid_num
                            globals()["grid_low"]=low; globals()["grid_high"]=high; globals()["grid_num"]=num
                            save_config()
                            send_telegram(f"✅ ตั้ง Grid Range {low}-{high} {num} กริด Spacing ${(high-low)/num:.0f}", chat)
                        except:
                            send_telegram("❌ ใช้ /gridrange 80000 83000 10", chat)
                    else:
                        send_telegram(f"🔲 Grid {'ON ✅' if grid_enabled else 'OFF ❌'} {grid_low}-{grid_high} {grid_num} grids Qty {grid_qty}\n/grid on /grid off /gridrange 80000 83000 10", chat)

                elif text.startswith("/ema"):
                    parts=text_raw.split()
                    try:
                        if len(parts)>=3:
                            globals()["ema_short"]=int(parts[1]); globals()["ema_long"]=int(parts[2]); save_config()
                            send_telegram(f"✅ ตั้ง EMA {ema_short}/{ema_long}", chat)
                    except:
                        send_telegram("❌ ใช้ /ema 9 21", chat)

                elif text.startswith("/rsi"):
                    parts=text_raw.split()
                    try:
                        if len(parts)>=3:
                            globals()["rsi_low"]=int(parts[1]); globals()["rsi_high"]=int(parts[2]); save_config()
                            send_telegram(f"✅ ตั้ง RSI {rsi_low}-{rsi_high}", chat)
                    except:
                        send_telegram("❌ ใช้ /rsi 30 70", chat)

                elif text.startswith("/gridrange"):
                    parts=text_raw.split()
                    try:
                        low=int(parts[1]); high=int(parts[2]); num=int(parts[3]) if len(parts)>=4 else grid_num
                        globals()["grid_low"]=low; globals()["grid_high"]=high; globals()["grid_num"]=num; save_config()
                        send_telegram(f"✅ Grid {low}-{high} {num} grids", chat)
                    except:
                        send_telegram("❌ /gridrange 80000 83000 10", chat)

                elif text in ["/check","/status","/env"]:
                    bal, is_real, bal_msg = get_balance_real()
                    price=get_price_fast("BTCUSDT")
                    closes=get_klines("BTCUSDT","15m",100)
                    ema_s=calc_ema(closes,ema_short) if closes else 0
                    ema_l=calc_ema(closes,ema_long) if closes else 0
                    rsi=calc_rsi(closes) if closes else 50
                    wr=(stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
                    mode="✅ REAL" if is_real and mexc else "⚠️ DRY RUN"
                    pos_txt=""
                    for p in positions:
                        real_txt=f"SL {'✅ REAL' if p.get('real_sl') else 'Bot'} TP {'✅ REAL' if p.get('real_tp') else 'Bot'}"
                        pos_txt+=f"\n{p['side'].upper()} {p['qty']} CONT Entry {p['entry']:.0f} SL {p.get('sl_pct',0)}% @ {p.get('sl_price',0):.0f} TP {p.get('tp_pct',0)}% @ {p.get('tp_price',0):.0f} {real_txt} {p.get('source','')}"
                    if not pos_txt: pos_txt="ว่าง"
                    send_telegram(f"{mode} V14 BTC AUTO 2+3\n⏰ {thai_time()}\nBTC Price {price:.0f} EMA{ema_short} {ema_s:.0f} EMA{ema_long} {ema_l:.0f} RSI {rsi:.0f}\n{bal_msg}\nAuto {'ON ✅' if auto_enabled else 'OFF'} Grid {'ON ✅' if grid_enabled else 'OFF'} {grid_low}-{grid_high}\nPos:{pos_txt}\nWR {wr:.1f}% Trades {stats['total_trades']} Auto {stats['auto_trades']} Grid {stats['grid_trades']}\n/open long {DEFAULT_BTC} /auto on /grid on", chat)

                elif text.startswith("/open"):
                    parts=text_raw.split()
                    side='long'; qty_str=None; sl_str=None; tp_str=None
                    i=1
                    while i < len(parts):
                        p=parts[i].lower()
                        if p in ['long','short','buy','sell']:
                            side='long' if p in ['long','buy'] else 'short'
                        elif p=='sl' and i+1 < len(parts):
                            sl_str=parts[i+1]; i+=1
                        elif p=='tp' and i+1 < len(parts):
                            tp_str=parts[i+1]; i+=1
                        else:
                            if qty_str is None:
                                try: float(p); qty_str=p
                                except: pass
                        i+=1
                    if not qty_str: qty_str=str(DEFAULT_BTC)
                    send_telegram(f"⏳ รับคำสั่ง /open {side} {qty_str} SL {sl_str or DEFAULT_SL_PCT}% TP {tp_str or DEFAULT_TP_PCT}% REAL...", chat)
                    threading.Thread(target=manual_open, args=(side, qty_str, sl_str, tp_str, "Manual"), daemon=True).start()

                elif text.startswith("/sl"):
                    parts=text_raw.split()
                    if len(parts)>=2:
                        try:
                            new_sl=float(parts[1])
                            for p in positions:
                                p['sl_pct']=new_sl
                                sl_price, _ = calc_sl_tp(p['entry'], p['side'], new_sl, p.get('tp_pct',DEFAULT_TP_PCT))
                                p['sl_price']=sl_price
                            save_positions()
                            send_telegram(f"✅ ตั้ง SL ใหม่ {new_sl}%", chat)
                        except:
                            send_telegram("❌ /sl 3.4", chat)

                elif text.startswith("/tp"):
                    parts=text_raw.split()
                    if len(parts)>=2:
                        try:
                            new_tp=float(parts[1])
                            for p in positions:
                                p['tp_pct']=new_tp
                                _, tp_price = calc_sl_tp(p['entry'], p['side'], p.get('sl_pct',DEFAULT_SL_PCT), new_tp)
                                p['tp_price']=tp_price
                            save_positions()
                            send_telegram(f"✅ ตั้ง TP ใหม่ {new_tp}%", chat)
                        except:
                            send_telegram("❌ /tp 18", chat)

                elif text in ["/long","/short"]:
                    side='long' if text=="/long" else 'short'
                    send_telegram(f"⏳ รับคำสั่ง {side} {DEFAULT_BTC} SL {DEFAULT_SL_PCT}% TP {DEFAULT_TP_PCT}% REAL...", chat)
                    threading.Thread(target=manual_open, args=(side, str(DEFAULT_BTC), str(DEFAULT_SL_PCT), str(DEFAULT_TP_PCT), "Manual"), daemon=True).start()

                elif text.startswith("/close"):
                    parts=text_raw.split()
                    f=None
                    if len(parts)>=2 and parts[1].lower() in ['long','short']: f=parts[1].lower()
                    send_telegram(f"⏳ รับคำสั่ง /close {f or 'ALL'}...", chat)
                    threading.Thread(target=lambda: mexc_close_fast(get_price_fast("BTCUSDT"), f, "Manual close"), daemon=True).start()

                elif text=="/btc":
                    send_telegram(f"✅ BTC Futures ทุน $40 {DEFAULT_BTC} BTC={DEFAULT_CONT} CONT Margin $5\nAuto EMA{ema_short}/{ema_long} Grid {grid_low}-{grid_high}", chat)

                elif text=="/balance":
                    bal, is_real, bal_msg = get_balance_real()
                    price=get_price_fast("BTCUSDT")
                    mode="REAL" if is_real else "DRY RUN"
                    send_telegram(f"💰 {mode} {bal_msg}\nBTC Price {price:.0f}\nAuto {'ON' if auto_enabled else 'OFF'} Grid {'ON' if grid_enabled else 'OFF'} Pos {len(positions)}", chat)

        except Exception as e:
            print(f"Tele err {e}")
            import traceback; traceback.print_exc()
            time.sleep(5)

threading.Thread(target=telegram_check_loop, daemon=True).start()

if __name__=="__main__":
    port=int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0", port=port)
