"""
V12.34 QTY 5 CONT - ตามสั่ง
ทุน $40 เปิด 5 CONT = 0.0005 BTC ≈ $40 notional Margin $5
SL $0.17 (0.4% พอร์ต) TP $0.91 (2.2% พอร์ต) ปลอดภัย
"""
import requests, os, time, threading, json
from flask import Flask, jsonify, request
from datetime import datetime
import pytz

def get_data_dir():
    try:
        if os.path.exists("/mnt/data") and os.access("/mnt/data", os.W_OK): return "/mnt/data"
        os.makedirs("/mnt/data", exist_ok=True)
        if os.access("/mnt/data", os.W_OK): return "/mnt/data"
    except: pass
    try: os.makedirs("./data", exist_ok=True)
    except: pass
    return "./data"

DATA_DIR = get_data_dir()
MEXC_API_KEY = os.environ.get("MEXC_API_KEY","").strip()
MEXC_API_SECRET = os.environ.get("MEXC_API_SECRET","").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN","").strip() or os.environ.get("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip() or os.environ.get("TELEGRAM_CHAT_ID","").strip()

SYMBOL_CCXT = "BTC/USDT:USDT"
SYMBOL_BINANCE = "BTCUSDT"
LEVERAGE = 8
TP_PCT = 18.0
SL_PCT = 3.4
BE_PCT = 3.0
TRAIL_START = 7.0
TRAIL_PCT = 2.5
RSI_LONG_MIN = 57
RSI_LONG_MAX = 67
RSI_SHORT_MIN = 33
RSI_SHORT_MAX = 43
EMA_GAP_PCT = 0.22
ADX_MIN = 12
VOL_MULT = 0.9
DEFAULT_QTY = 5  # ตามสั่ง Qty=5 cont

POSITIONS_FILE = os.path.join(DATA_DIR, "positions.json")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")

app = Flask(__name__)
@app.route('/', methods=['GET','HEAD'])
def home():
    if request.method=='HEAD': return '',200
    return f"V12.34 QTY5 CONT"
@app.route('/health', methods=['GET','HEAD'])
def health():
    if request.method=='HEAD': return '',200
    return jsonify({"status":"ok","version":"V12.34 QTY5"})

positions, highest, lowest = [], 0, 999999
stats = {"total_trades":0,"wins":0,"losses":0,"total_pnl_pct":0.0,"history":[]}
is_real_mode=True; trail_sl=0; be_done=False; hard_sl_price=0; cooldown_until=0

try:
    import ccxt
    if MEXC_API_KEY and MEXC_API_SECRET:
        mexc=ccxt.mexc({'apiKey':MEXC_API_KEY,'secret':MEXC_API_SECRET,'enableRateLimit':True,'options':{'defaultType':'swap'}})
        try: mexc.load_markets()
        except: pass
    else:
        mexc=None; is_real_mode=False
except:
    mexc=None; is_real_mode=False

def thai_time(): return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")
def save_positions():
    try:
        with open(POSITIONS_FILE,'w',encoding='utf-8') as f: json.dump({"positions":positions,"highest":highest,"lowest":lowest,"trail_sl":trail_sl,"be_done":be_done}, f)
    except: pass
def load_positions():
    global positions, highest, lowest, trail_sl, be_done
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE,'r',encoding='utf-8') as f:
                d=json.load(f); positions=d.get("positions",[]); highest=d.get("highest",0); lowest=d.get("lowest",999999); trail_sl=d.get("trail_sl",0); be_done=d.get("be_done",False); return len(positions)>0
    except: pass
    return False
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
load_stats(); load_positions()

def send_telegram(msg, chat_id=None):
    target=str(chat_id) if chat_id else CHAT_ID
    if not BOT_TOKEN or not target: return False
    try:
        r=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id":target,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=15)
        return r.json().get('ok',False)
    except: return False

def get_price_mexc():
    try:
        r=requests.get("https://api.coingecko.com/api/v3/simple/price", params={"ids":"bitcoin","vs_currencies":"usd"}, timeout=10)
        if r.status_code==200:
            p=float(r.json().get('bitcoin',{}).get('usd',0))
            if p>1000: return p
    except: pass
    for host in ["https://data-api.binance.vision","https://api.binance.com"]:
        try:
            r=requests.get(f"{host}/api/v3/ticker/price", params={"symbol":SYMBOL_BINANCE}, timeout=10)
            if r.status_code==200:
                p=float(r.json().get('price',0))
                if p>1000: return p
        except: pass
    return None

def get_klines_mexc(limit=500, timeframe='15m'):
    for host in ["https://data-api.binance.vision","https://api.binance.com"]:
        try:
            r=requests.get(f"{host}/api/v3/klines", params={"symbol":SYMBOL_BINANCE,"interval":timeframe,"limit":limit}, timeout=15)
            if r.status_code==200:
                data=r.json()
                if isinstance(data,list) and len(data)>50:
                    return [[int(k[0]),float(k[1]),float(k[2]),float(k[3]),float(k[4]),float(k[5])] for k in data]
        except: pass
    return None

def ema_series(prices, span):
    alpha=2.0/(span+1); ema=[]
    for i,p in enumerate(prices): ema.append(p if i==0 else alpha*p + (1-alpha)*ema[-1])
    return ema

def calc_indicators(ohlcv):
    if not ohlcv or len(ohlcv)<300: return None
    try:
        closes=[float(x[4]) for x in ohlcv]; highs=[float(x[2]) for x in ohlcv]; lows=[float(x[3]) for x in ohlcv]; vols=[float(x[5]) for x in ohlcv]; times=[x[0] for x in ohlcv]; n=len(closes)
        ema12=ema_series(closes,12); ema26=ema_series(closes,26); ema50=ema_series(closes,50); ema200=ema_series(closes,200); vol_ma=ema_series(vols,20)
        rsi=[50.0]*n; gains=[]; losses=[]
        for i in range(1,n):
            d=closes[i]-closes[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
        avg_gain=sum(gains[:14])/14 if len(gains)>=14 else 0.001; avg_loss=sum(losses[:14])/14 if len(losses)>=14 else 0.001
        for i in range(14,n):
            if i>14 and i-1<len(gains):
                avg_gain=(avg_gain*13+gains[i-1])/14; avg_loss=(avg_loss*13+losses[i-1])/14
            rs=avg_gain/(avg_loss if avg_loss!=0 else 0.001); rsi[i]=100-(100/(1+rs))
        adx=[abs(ema12[i]-ema26[i])/closes[i]*100*10 for i in range(n)]
        rows=[]
        for i in range(n):
            rows.append({'ot':times[i],'c':closes[i],'EMA12':ema12[i],'EMA26':ema26[i],'EMA50':ema50[i],'EMA200':ema200[i],'RSI':rsi[i],'VOL':vols[i],'VOLMA':vol_ma[i],'ADX':adx[i]})
        return rows
    except: return None

def get_balance():
    if not mexc: return 40.0
    try:
        bal=mexc.fetch_balance(); return float(bal.get('USDT',{}).get('free',0) or bal.get('total',{}).get('USDT',0) or 40.0)
    except: return 40.0

def mexc_open_futures(price, qty_contracts, side):
    global is_real_mode
    try:
        qty_contracts = int(float(qty_contracts))
        if qty_contracts < 1: qty_contracts = 1
        if qty_contracts > 20: qty_contracts = 20
    except:
        qty_contracts = DEFAULT_QTY
    if mexc and is_real_mode:
        try:
            try: mexc.set_leverage(LEVERAGE, SYMBOL_CCXT, {'marginMode':'CROSS'})
            except: pass
            if side=="long":
                try: mexc.create_order(SYMBOL_CCXT, 'market', 'buy', qty_contracts, None, {'positionSide':'LONG'})
                except: mexc.create_market_buy_order(SYMBOL_CCXT, qty_contracts)
            else:
                try: mexc.create_order(SYMBOL_CCXT, 'market', 'sell', qty_contracts, None, {'positionSide':'SHORT'})
                except: mexc.create_market_sell_order(SYMBOL_CCXT, qty_contracts)
            return True
        except Exception as e:
            err=str(e)
            if "700007" in err or "permission" in err.lower():
                is_real_mode=False
                send_telegram(f"⚠️ 700007 → PAPER {side.upper()} {qty_contracts} CONT @ {price:.0f}")
                return "PAPER"
            if "precision" in err.lower() or "amount" in err.lower():
                try:
                    if side=="long":
                        mexc.create_order(SYMBOL_CCXT, 'market', 'buy', 1, None, {'positionSide':'LONG'})
                    else:
                        mexc.create_order(SYMBOL_CCXT, 'market', 'sell', 1, None, {'positionSide':'SHORT'})
                    send_telegram(f"✅ แก้ precision สำเร็จ เปิด {side.upper()} 1 CONT @ {price:.0f}")
                    return True
                except Exception as e2:
                    send_telegram(f"❌ {side.upper()} ERR {str(e2)[:250]}")
                    return False
            send_telegram(f"❌ {side.upper()} ERR {err[:250]}")
            return False
    else:
        return "PAPER"

def mexc_buy(price, custom_qty=None, side="long"):
    global highest, lowest, trail_sl, be_done, hard_sl_price
    if positions:
        cur=positions[0].get('side','long')
        if cur!=side:
            send_telegram(f"⚠️ มี {cur.upper()} อยู่แล้ว ต้อง /close ก่อนเปิด {side.upper()}")
            return False,0
        else:
            send_telegram(f"⚠️ มี {cur.upper()} อยู่แล้ว 1 ไม้ SINGLE SIDE")
            return False,0
    if custom_qty:
        try: qty_contracts=int(float(custom_qty))
        except: qty_contracts=DEFAULT_QTY
    else:
        qty_contracts=DEFAULT_QTY  # ตามสั่ง 5 CONT
    result=mexc_open_futures(price, qty_contracts, side)
    if result==False: return False,0
    positions.append({'entry':price,'qty':qty_contracts,'side':side,'time':time.time()})
    if side=="long": highest=price; lowest=999999; trail_sl=price*(1-(SL_PCT/LEVERAGE)/100)
    else: lowest=price; highest=0; trail_sl=price*(1+(SL_PCT/LEVERAGE)/100)
    hard_sl_price=trail_sl; be_done=False
    save_positions()
    btc_size = qty_contracts * 0.0001
    send_telegram(f"✅ เปิด {side.upper()} BTCUSDT {price:.0f} {qty_contracts} CONT ({btc_size:.4f} BTC) SL {trail_sl:.0f} Ratio 5.3:1 QTY5")
    return True, qty_contracts

def close_position(price, reason):
    global positions, highest, lowest, trail_sl, be_done, hard_sl_price, cooldown_until
    if not positions: return False
    p=positions[0]; qty_contracts=abs(int(p['qty'])); entry=p['entry']; side=p['side']
    pnl=(entry-price)/entry*100*LEVERAGE if side=='short' else (price-entry)/entry*100*LEVERAGE
    if mexc and is_real_mode:
        try:
            if side=='long':
                try: mexc.create_order(SYMBOL_CCXT, 'market', 'sell', qty_contracts, None, {'positionSide':'LONG'})
                except: mexc.create_market_sell_order(SYMBOL_CCXT, qty_contracts)
            else:
                try: mexc.create_order(SYMBOL_CCXT, 'market', 'buy', qty_contracts, None, {'positionSide':'SHORT'})
                except: mexc.create_market_buy_order(SYMBOL_CCXT, qty_contracts)
        except: pass
    stats["total_trades"]+=1; stats["total_pnl_pct"]+=pnl
    if pnl>0: stats["wins"]+=1; icon="✅"
    else: stats["losses"]+=1; icon="❌"; cooldown_until=time.time()+1*3600
    stats["history"].append({"time":thai_time(),"type":f"{side.upper()} {reason}","pnl":pnl})
    save_stats(); wr=stats["wins"]/stats["total_trades"]*100 if stats["total_trades"]>0 else 0
    send_telegram(f"{icon} ปิด {side.upper()} BTCUSDT {reason} {price:.0f} PnL {pnl:+.2f}% WR {wr:.1f}% QTY{qty_contracts}")
    positions.clear(); highest=0; lowest=999999; trail_sl=0; be_done=False; hard_sl_price=0
    save_positions()
    return True

def trading_loop():
    global highest, lowest, trail_sl, be_done, hard_sl_price, cooldown_until
    price=get_price_mexc()
    send_telegram(f"🚀 <b>V12.34 QTY5 CONT START</b>\nทุน $40 เปิด {DEFAULT_QTY} CONT = {DEFAULT_QTY*0.0001:.4f} BTC\nTP {TP_PCT}% SL {SL_PCT}% Ratio 5.3:1\nPrice:{price}")
    while True:
        try:
            ohlcv=get_klines_mexc(500, '15m')
            if not ohlcv or len(ohlcv)<300: time.sleep(30); continue
            rows=calc_indicators(ohlcv)
            if not rows: time.sleep(30); continue
            last=rows[-1]; price=float(last['c']); ema12=float(last['EMA12']); ema26=float(last['EMA26']); ema50=float(last['EMA50']); ema200=float(last['EMA200']); rsi=float(last['RSI']); vol=float(last['VOL']); volma=float(last['VOLMA']); adx=float(last['ADX'])
            ema_gap = abs(ema12-ema26)/price*100
            if positions:
                avg=positions[0]['entry']; is_short=positions[0]['side']=='short'; pnl=(avg-price)/avg*100*LEVERAGE if is_short else (price-avg)/avg*100*LEVERAGE
                if is_short:
                    if price<lowest: lowest=price
                else:
                    if price>highest: highest=price
                if pnl>=BE_PCT and not be_done:
                    trail_sl=avg*0.9995 if is_short else avg*1.0005; hard_sl_price=trail_sl; be_done=True; send_telegram(f"🔒 ยกทุน {trail_sl:.0f} PnL {pnl:.1f}%"); save_positions()
                if pnl>=TRAIL_START:
                    if is_short:
                        new_trail=lowest*(1+TRAIL_PCT/100/LEVERAGE)
                        if new_trail < trail_sl: trail_sl=new_trail; hard_sl_price=new_trail; save_positions()
                    else:
                        new_trail=highest*(1-TRAIL_PCT/100/LEVERAGE)
                        if new_trail>trail_sl: trail_sl=new_trail; hard_sl_price=new_trail; save_positions()
                should_exit=False; reason=""
                if is_short:
                    if price>=trail_sl and trail_sl>0: should_exit=True; reason="TRAIL"
                else:
                    if price<=trail_sl and trail_sl>0: should_exit=True; reason="TRAIL"
                if pnl>=TP_PCT: should_exit=True; reason=f"TP {TP_PCT}%"
                if pnl<=-SL_PCT: should_exit=True; reason=f"SL {SL_PCT}%"
                if (time.time()-positions[0].get('time',0))/3600>=20: should_exit=True; reason="TIME"
                if should_exit: close_position(price, reason)
            else:
                if time.time()<cooldown_until: time.sleep(15); continue
                if adx < ADX_MIN: time.sleep(15); continue
                if vol < volma*VOL_MULT: time.sleep(15); continue
                if ema_gap < EMA_GAP_PCT: time.sleep(15); continue
                bull = price>ema50 and price>ema200 and ema12>ema26>ema50 and RSI_LONG_MIN<rsi<RSI_LONG_MAX
                bear = price<ema50 and price<ema200 and ema12<ema26<ema50 and RSI_SHORT_MIN<rsi<RSI_SHORT_MAX
                if bull:
                    mexc_buy(price, side="long")
                elif bear:
                    mexc_buy(price, side="short")
            time.sleep(15)
        except Exception as e:
            print(f"Loop err {e}"); time.sleep(15)

threading.Thread(target=trading_loop, daemon=True).start()

def telegram_check_loop():
    if not BOT_TOKEN: return
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
    except: pass
    offset=0
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset+1}&timeout=30", timeout=35)
            data=r.json()
            if not data.get("ok"): time.sleep(5); continue
            for upd in data.get("result",[]):
                offset=upd["update_id"]; msg=upd.get("message",{}); text_raw=msg.get("text","").strip(); text=text_raw.lower(); chat=str(msg.get("chat",{}).get("id",""))
                if text in ["/start","/check","/status"]:
                    wr=(stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
                    side=positions[0]['side'].upper() if positions else "ว่าง"
                    price=get_price_mexc()
                    bal=get_balance()
                    send_telegram(f"✅ BTCUSDT V12.34 QTY5\n⏰ {thai_time()}\nPrice:{price:.0f} Bal:{bal:.2f}\nถือ:{side} {positions[0]['qty'] if positions else ''} CONT\nWR:{wr:.1f}% Trades:{stats['total_trades']} PnL {stats['total_pnl_pct']:+.1f}%\nTP {TP_PCT}% SL {SL_PCT}% Ratio 5.3:1\nDefault {DEFAULT_QTY} CONT", chat)
                elif text.startswith("/open"):
                    parts=text_raw.split()
                    side="long"
                    qty=DEFAULT_QTY
                    if len(parts)>=2:
                        if "short" in parts[1].lower(): side="short"
                        elif "long" in parts[1].lower(): side="long"
                        else:
                            try: qty=int(float(parts[1])); side="long"
                            except: pass
                    if len(parts)>=3:
                        try: qty=int(float(parts[2]))
                        except: pass
                        if "short" in parts[1].lower(): side="short"
                    price=get_price_mexc()
                    if not price: price=81500
                    threading.Thread(target=lambda s=side,q=qty,p=price: mexc_buy(p, custom_qty=q, side=s), daemon=True).start()
                    send_telegram(f"⏳ เปิด {side.upper()} {qty} CONT...", chat)
                elif text=="/long":
                    price=get_price_mexc() or 81500
                    threading.Thread(target=lambda: mexc_buy(price, custom_qty=DEFAULT_QTY, side="long"), daemon=True).start()
                    send_telegram(f"⏳ เปิด LONG {DEFAULT_QTY} CONT...", chat)
                elif text=="/short":
                    price=get_price_mexc() or 81500
                    threading.Thread(target=lambda: mexc_buy(price, custom_qty=DEFAULT_QTY, side="short"), daemon=True).start()
                    send_telegram(f"⏳ เปิด SHORT {DEFAULT_QTY} CONT...", chat)
                elif text.startswith("/close"):
                    price=get_price_mexc() or (positions[0]['entry'] if positions else 0)
                    if positions: close_position(price, "MANUAL_CLOSE")
                    send_telegram(f"⏳ ปิด {len(positions)} ไม้...", chat)
                elif text.startswith("/balance"):
                    bal=get_balance()
                    send_telegram(f"💰 Balance: {bal:.2f} USDT\n{DEFAULT_QTY} CONT = {DEFAULT_QTY*0.0001:.4f} BTC ≈ ${ (get_price_mexc() or 81500)*0.0001*DEFAULT_QTY :.2f}", chat)
        except Exception as e:
            print(f"Tele err {e}"); time.sleep(10)

threading.Thread(target=telegram_check_loop, daemon=True).start()

if __name__=="__main__":
    port=int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0", port=port)
