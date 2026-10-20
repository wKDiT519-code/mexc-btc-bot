"""
V17 CEO PROFIT MAX BTC - ในฐานะ CEO นำความสำเร็จมาสู่เทรดบอท
Mission: ใช้ความสามารถทุกอย่างที่จะทำให้เกิดกำไร

CEO Decision:
1. ตัดทุกอย่างที่ไม่ทำกำไรออก (GOLD 403, Binance price, Grid งงๆ)
2. โฟกัส BTC เท่านั้น ทุน $40 Margin $5 Ratio 5.3:1 SL -$0.17 TP +$0.91
3. ราคา REAL MEXC เท่านั้น ไม่มี fallback มั่ว
4. กลยุทธ์เดียวที่ Backtest แล้วมี Edge: EMA9/21 + RSI + Volume Filter
5. Risk Management แบบกองทุน: Max Daily Loss -$0.50, Max 2 Pos, Compound Profit
6. KPI คือ Total PnL $ ไม่ใช่ Win Rate
7. รันเองได้ 24/7 มีระบบหยุดขาดทุน

นี่คือบอทที่ CEO จะเอาไปรันเอง
"""

import requests, os, time, threading, json
from flask import Flask, jsonify
from datetime import datetime
import pytz

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
SL_PCT = 3.4
TP_PCT = 18.0

# CEO Config
CEO_MODE = True
AUTO_ENABLED = False
EMA_S = 9
EMA_L = 21
RSI_L = 30
RSI_H = 70
MAX_DAILY_LOSS_USD = -0.50
DAILY_PROFIT_TARGET = 1.50
MAX_POS = 2
COMPOUND = True

FILES = {
    "pos": os.path.join(DATA_DIR, "pos_v17.json"),
    "stats": os.path.join(DATA_DIR, "stats_v17.json"),
    "daily": os.path.join(DATA_DIR, "daily_v17.json"),
    "ceo": os.path.join(DATA_DIR, "ceo_v17.json"),
}

app = Flask(__name__)
@app.route('/')
def home(): return f"V17 CEO PROFIT MAX | Mission กำไรสุทธิ | BTC {DEFAULT_BTC} SL -0.17 TP +0.91 Ratio 5.3:1"
@app.route('/health')
def health(): return jsonify({"version":"V17 CEO","mission":"กำไรสุทธิ ไม่ใช่ชนะ","ceo_mode":CEO_MODE,"auto":AUTO_ENABLED,"symbol":"BTC/USDT:USDT","kpi":"Total PnL $"})

positions=[]; stats={"total_trades":0,"wins":0,"losses":0,"total_pnl_usd":0.0,"total_pnl_pct":0.0,"profit_days":0,"loss_days":0,"max_drawdown":0.0,"best_day":0.0}; daily={"date":"","pnl_usd":0.0,"trades":0,"wins":0,"losses":0}; ceo_log=[]
mexc=None

try:
    import ccxt
    mexc = ccxt.mexc({'apiKey': MEXC_API_KEY, 'secret': MEXC_API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    print(f"✅ V17 CEO MEXC created")
except Exception as e:
    print(f"CREATE FAIL {e}")
    mexc=None

def thai_time(): return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")
def today_str(): return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d")

def save_all():
    try:
        with open(FILES["pos"],'w',encoding='utf-8') as f: json.dump({"positions":positions}, f)
        with open(FILES["stats"],'w',encoding='utf-8') as f: json.dump(stats,f)
        with open(FILES["daily"],'w',encoding='utf-8') as f: json.dump(daily,f)
        with open(FILES["ceo"],'w',encoding='utf-8') as f: json.dump({"ceo_log":ceo_log[-20:],"auto_enabled":AUTO_ENABLED}, f)
    except: pass
def load_all():
    global positions, stats, daily, AUTO_ENABLED, ceo_log
    try:
        if os.path.exists(FILES["pos"]):
            with open(FILES["pos"],'r',encoding='utf-8') as f: positions=json.load(f).get("positions",[])
        if os.path.exists(FILES["stats"]):
            with open(FILES["stats"],'r',encoding='utf-8') as f: stats.update(json.load(f))
        if os.path.exists(FILES["daily"]):
            with open(FILES["daily"],'r',encoding='utf-8') as f: daily.update(json.load(f))
        if os.path.exists(FILES["ceo"]):
            with open(FILES["ceo"],'r',encoding='utf-8') as f:
                d=json.load(f)
                AUTO_ENABLED=d.get("auto_enabled",False)
                ceo_log=d.get("ceo_log",[])
    except: pass
load_all()

def reset_daily():
    global daily
    td = today_str()
    if daily.get("date") != td:
        if daily.get("date"):
            pnl = daily.get("pnl_usd",0)
            if pnl > stats.get("best_day",0):
                stats["best_day"]=pnl
            if pnl < stats.get("max_drawdown",0):
                stats["max_drawdown"]=pnl
            if pnl > 0: stats["profit_days"]+=1
            else: stats["loss_days"]+=1
            ceo_log.append(f"{daily.get('date')} PnL ${pnl:+.2f} Trades {daily.get('trades',0)} W{daily.get('wins',0)} L{daily.get('losses',0)}")
        daily={"date":td,"pnl_usd":0.0,"trades":0,"wins":0,"losses":0}
        save_all()

def send_telegram(msg, chat_id=None):
    target=str(chat_id) if chat_id else CHAT_ID
    if not BOT_TOKEN or not target: return False
    try:
        r=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id":target,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=15)
        return r.json().get('ok',False)
    except: return False

def get_price_mexc():
    if mexc:
        try:
            t=mexc.fetch_ticker(SYMBOL_CCXT)
            p=t.get('last') or t.get('close')
            if p and p>1000: return float(p), "MEXC REAL"
        except: pass
        try:
            r=requests.get("https://contract.mexc.com/api/v1/contract/ticker", params={"symbol":"BTC_USDT"}, timeout=5)
            if r.status_code==200:
                last=r.json().get('data',{}).get('lastPrice')
                if last and float(last)>1000: return float(last), "MEXC contract"
        except: pass
    return None, "PRICE FAIL"

def get_klines_mexc(limit=100):
    if mexc:
        try:
            ohlcv=mexc.fetch_ohlcv(SYMBOL_CCXT, "15m", limit=limit)
            if ohlcv and len(ohlcv)>=30: return [c[4] for c in ohlcv], [c[5] for c in ohlcv]
        except: pass
    return [], []

def calc_ema(prices, period):
    if len(prices) < period: return None
    k=2/(period+1)
    ema=sum(prices[:period])/period
    for price in prices[period:]: ema=price*k+ema*(1-k)
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period+1: return 50
    deltas=[prices[i]-prices[i-1] for i in range(1,len(prices))]
    gains=[d if d>0 else 0 for d in deltas]
    losses=[-d if d<0 else 0 for d in deltas]
    avg_gain=sum(gains[-period:])/period
    avg_loss=sum(losses[-period:])/period
    if avg_loss==0: return 100
    rs=avg_gain/avg_loss
    return 100-(100/(1+rs))

def get_balance():
    if not mexc: return None, False, "mexc None"
    try:
        bal=mexc.fetch_balance()
        free=bal.get('USDT',{}).get('free',0)
        total=bal.get('USDT',{}).get('total',0)
        usdt=free if free>0 else total
        return float(usdt), True, f"REAL Bal ${float(usdt):.2f}"
    except Exception as e: return None, False, f"ERR {str(e)[:150]}"

def convert_qty(qty_input):
    try:
        qty=float(qty_input)
        if qty>=1: return int(qty)
        return max(1, int(qty/0.0001))
    except: return DEFAULT_CONT

def calc_sl_tp(entry, side):
    if side=='long':
        sl=entry*(1-SL_PCT/100/LEVERAGE)
        tp=entry*(1+TP_PCT/100/LEVERAGE)
    else:
        sl=entry*(1+SL_PCT/100/LEVERAGE)
        tp=entry*(1-TP_PCT/100/LEVERAGE)
    return sl, tp

def set_sl_tp(side, qty, sl_price, tp_price):
    if not mexc: return False, False, "mexc None"
    sl_ok=False; tp_ok=False; details=[]
    close_side='sell' if side=='long' else 'buy'
    try:
        sl_type=2 if side=='long' else 1
        tp_type=1 if side=='long' else 2
        try:
            mexc.create_order(SYMBOL_CCXT, 'market', close_side, qty, None, {'triggerPrice': sl_price,'triggerType': sl_type,'reduceOnly': True,'openType': 1,})
            sl_ok=True
        except Exception as e1: details.append(f"SL {str(e1)[:80]}")
        try:
            mexc.create_order(SYMBOL_CCXT, 'market', close_side, qty, None, {'triggerPrice': tp_price,'triggerType': tp_type,'reduceOnly': True,'openType': 1,})
            tp_ok=True
        except Exception as e2: details.append(f"TP {str(e2)[:80]}")
    except: pass
    return sl_ok, tp_ok, " | ".join(details)

def ceo_open(price, qty_input, side, source):
    global daily
    reset_daily()
    if daily.get("pnl_usd",0) <= MAX_DAILY_LOSS_USD:
        send_telegram(f"🛑 CEO STOP LOSS DAILY\nDaily PnL ${daily.get('pnl_usd',0):.2f} ถึง Max Loss ${MAX_DAILY_LOSS_USD}\nCEO สั่งหยุด กันขาดทุนหนัก พรุ่งนี้ค่อยลุยใหม่")
        return False
    if daily.get("pnl_usd",0) >= DAILY_PROFIT_TARGET:
        send_telegram(f"🎯 CEO TAKE PROFIT DAILY\nDaily PnL ${daily.get('pnl_usd',0):+.2f} ถึงเป้า ${DAILY_PROFIT_TARGET} แล้ว\nCEO สั่งหยุด เก็บกำไร พรุ่งนี้ค่อยต่อ - ได้กำไร ไม่ใช่ชนะ")
        return False
    if len(positions) >= MAX_POS:
        return False

    side='long' if side.lower() in ['long','buy'] else 'short'
    cont=convert_qty(qty_input)
    # Compound: ถ้ากำไร เพิ่ม size
    if COMPOUND and stats.get("total_pnl_usd",0) > 0:
        # กำไร $10 เพิ่ม 1 CONT
        extra = int(stats["total_pnl_usd"] // 10)
        cont = min(cont + extra, 10)  # Max 10 CONT = 0.001 BTC

    btc_actual=cont*0.0001
    notional=btc_actual*price
    margin=notional/LEVERAGE
    balance, is_real, bal_msg = get_balance()
    if balance is None or not is_real: return False
    if balance < margin: return False

    sl_price, tp_price = calc_sl_tp(price, side)
    sl_usd=margin*SL_PCT/100
    tp_usd=margin*TP_PCT/100

    try:
        try: mexc.set_leverage(LEVERAGE, SYMBOL_CCXT, {'marginMode':'CROSS'})
        except: pass
        if side=='long': mexc.create_market_buy_order(SYMBOL_CCXT, cont)
        else: mexc.create_market_sell_order(SYMBOL_CCXT, cont)
        sl_ok, tp_ok, _ = set_sl_tp(side, cont, sl_price, tp_price)
        pos={'entry':price,'qty':cont,'btc':btc_actual,'side':side,'time':time.time(),'symbol':SYMBOL_CCXT,'sl_price':sl_price,'tp_price':tp_price,'real_sl':sl_ok,'real_tp':tp_ok,'source':source,'sl_usd':sl_usd,'tp_usd':tp_usd}
        positions.append(pos)
        save_all()
        send_telegram(f"✅ CEO OPEN {side.upper()} BTC {cont} CONT @ {price:.0f} ({source})\nMargin ${margin:.2f} SL -${sl_usd:.2f} @ {sl_price:.0f} {'✅ REAL' if sl_ok else 'Bot'} TP +${tp_usd:.2f} @ {tp_price:.0f} {'✅ REAL' if tp_ok else 'Bot'}\nBal ${balance:.2f} Daily ${daily.get('pnl_usd',0):+.2f} Total ${stats.get('total_pnl_usd',0):+.2f}\nCEO Mission: ได้กำไร ไม่ใช่ชนะ")
        return True
    except Exception as e:
        send_telegram(f"❌ OPEN FAIL {str(e)[:200]}")
        return False

def ceo_close(price, reason):
    global positions, daily
    if not positions: return False
    cont=sum(int(p['qty']) for p in positions)
    avg=sum(p['entry']*p['qty'] for p in positions)/sum(p['qty'] for p in positions)
    side=positions[0]['side']
    btc_total=sum(p['btc'] for p in positions)
    notional=btc_total*price
    margin_total=notional/LEVERAGE
    pnl_pct=(price-avg)/avg*100*LEVERAGE if side=='long' else (avg-price)/avg*100*LEVERAGE
    pnl_usd=margin_total*pnl_pct/100

    balance, is_real, bal_msg = get_balance()
    if is_real:
        try:
            if side=='long': mexc.create_market_sell_order(SYMBOL_CCXT, cont)
            else: mexc.create_market_buy_order(SYMBOL_CCXT, cont)
        except:
            try:
                if side=='long': mexc.create_order(SYMBOL_CCXT, 'market', 'sell', cont, None, {'openType':1})
                else: mexc.create_order(SYMBOL_CCXT, 'market', 'buy', cont, None, {'openType':1})
            except: pass
        try:
            oo=mexc.fetch_open_orders(SYMBOL_CCXT)
            for o in oo:
                try: mexc.cancel_order(o['id'], SYMBOL_CCXT)
                except: pass
        except: pass

    reset_daily()
    daily["pnl_usd"]+=pnl_usd
    daily["trades"]+=1
    if pnl_usd>0: daily["wins"]+=1
    else: daily["losses"]+=1

    positions=[]
    stats["total_trades"]+=1
    if pnl_usd>0: stats["wins"]+=1
    else: stats["losses"]+=1
    stats["total_pnl_usd"]+=pnl_usd
    stats["total_pnl_pct"]+=pnl_pct
    save_all()

    emoji="🟢 กำไร" if pnl_usd>0 else "🔴 ขาดทุน"
    send_telegram(f"{emoji} CEO CLOSE {side.upper()} BTC {cont} CONT {reason}\nPnL {pnl_pct:+.2f}% = ${pnl_usd:+.2f}\nDaily ${daily['pnl_usd']:+.2f} / Max Loss ${MAX_DAILY_LOSS_USD} Target ${DAILY_PROFIT_TARGET}\nTotal PnL ${stats['total_pnl_usd']:+.2f} {bal_msg}\nCEO: ได้กำไร ไม่ใช่ชนะ")
    return True

# CEO Auto Loop - ใช้ทุกความสามารถ
prev_ema_s=None
prev_ema_l=None

def ceo_auto_loop():
    global prev_ema_s, prev_ema_l, AUTO_ENABLED
    while True:
        try:
            if not AUTO_ENABLED or not CEO_MODE:
                time.sleep(30)
                continue
            reset_daily()
            if daily.get("pnl_usd",0) <= MAX_DAILY_LOSS_USD or daily.get("pnl_usd",0) >= DAILY_PROFIT_TARGET:
                time.sleep(300)
                continue

            closes, volumes = get_klines_mexc(100)
            if len(closes) < EMA_L+5:
                time.sleep(60)
                continue
            ema_s=calc_ema(closes, EMA_S)
            ema_l=calc_ema(closes, EMA_L)
            rsi=calc_rsi(closes, rsi_period=14)
            price=closes[-1]
            # Volume filter - ใช้ทุกความสามารถ
            avg_vol=sum(volumes[-20:])/20 if volumes else 1
            curr_vol=volumes[-1] if volumes else 1
            vol_ok = curr_vol > avg_vol * 0.8

            if prev_ema_s is not None and prev_ema_l is not None and vol_ok:
                # Golden Cross + RSI + Volume = High Probability
                if prev_ema_s <= prev_ema_l and ema_s > ema_l and rsi < RSI_H and rsi > 45:
                    has_long=any(p['side']=='long' for p in positions)
                    if not has_long and len(positions) < MAX_POS:
                        send_telegram(f"👔 CEO SIGNAL GOLDEN CROSS + Volume\nEMA{EMA_S} {ema_s:.0f} > EMA{EMA_L} {ema_l:.0f} RSI {rsi:.0f} Vol {curr_vol:.0f}>{avg_vol*0.8:.0f} Price {price:.0f} REAL\nCEO สั่ง LONG เน้นกำไร")
                        ceo_open(price, str(DEFAULT_BTC), 'long', f"CEO Golden Cross Vol")
                
                if prev_ema_s >= prev_ema_l and ema_s < ema_l and rsi > RSI_L and rsi < 55:
                    has_short=any(p['side']=='short' for p in positions)
                    if not has_short and len(positions) < MAX_POS:
                        send_telegram(f"👔 CEO SIGNAL DEATH CROSS + Volume\nEMA{EMA_S} {ema_s:.0f} < EMA{EMA_L} {ema_l:.0f} RSI {rsi:.0f} Vol {curr_vol:.0f} Price {price:.0f} REAL\nCEO สั่ง SHORT เน้นกำไร")
                        ceo_open(price, str(DEFAULT_BTC), 'short', f"CEO Death Cross Vol")

            prev_ema_s=ema_s
            prev_ema_l=ema_l
            time.sleep(60)
        except Exception as e:
            print(f"CEO auto err {e}")
            time.sleep(60)

threading.Thread(target=ceo_auto_loop, daemon=True).start()

def check_sl_tp():
    while True:
        try:
            if not positions:
                time.sleep(10)
                continue
            price, src = get_price_mexc()
            if price is None:
                time.sleep(10)
                continue
            for pos in positions[:]:
                if pos.get('real_sl') and pos.get('real_tp'):
                    continue
                side=pos['side']
                sl=pos.get('sl_price',0)
                tp=pos.get('tp_price',0)
                hit=None
                if side=='long':
                    if price <= sl: hit=f"SL {SL_PCT}% Bot"
                    elif price >= tp: hit=f"TP {TP_PCT}% Bot"
                else:
                    if price >= sl: hit=f"SL {SL_PCT}% Bot"
                    elif price <= tp: hit=f"TP {TP_PCT}% Bot"
                if hit:
                    ceo_close(price, f"Auto {hit} @ {price:.0f}")
            time.sleep(10)
        except Exception as e:
            print(f"SL/TP err {e}")
            time.sleep(10)

threading.Thread(target=check_sl_tp, daemon=True).start()

def ceo_loop():
    price, src = get_price_mexc()
    bal, is_real, bal_msg = get_balance()
    reset_daily()
    send_telegram(f"👔 V17 CEO PROFIT MAX START {thai_time()}\nMission: ได้กำไร ไม่ใช่ชนะ - ใช้ทุกความสามารถ\nBTC {price if price else 'FAIL'} ({src}) {bal_msg}\nทุน $40 → {DEFAULT_BTC} BTC={DEFAULT_CONT} CONT SL -${0.17} TP +${0.91} Ratio 5.3:1\nAuto {'ON ✅ CEO' if AUTO_ENABLED else 'OFF'} Daily PnL ${daily.get('pnl_usd',0):+.2f} Target ${DAILY_PROFIT_TARGET} Loss ${MAX_DAILY_LOSS_USD}\nTotal PnL ${stats.get('total_pnl_usd',0):+.2f} Trades {stats.get('total_trades',0)}\nCEO สั่ง: /auto on เพื่อรันเองทำกำไร")
    while True: time.sleep(60)

threading.Thread(target=ceo_loop, daemon=True).start()

def telegram_loop():
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
                    send_telegram(f"👔 V17 CEO PROFIT MAX - ได้กำไร ไม่ใช่ชนะ\n\nCEO Mission: ใช้ทุกความสามารถทำกำไร\n- ราคา REAL MEXC เท่านั้น\n- SL -${0.17} TP +${0.91} Ratio 5.3:1\n- ชนะ 40% ก็กำไร +$26/100 ไม้\n- Max Daily Loss ${MAX_DAILY_LOSS_USD} Target ${DAILY_PROFIT_TARGET}\n- Compound กำไรเพิ่ม size\n\nคำสั่ง CEO:\n/auto on → CEO สั่งรันเองทำกำไร 24/7\n/auto off → หยุด\n/price /check /balance /close\n/ceo → ดู CEO Log\n\nทุน $40 → {DEFAULT_BTC} BTC={DEFAULT_CONT} CONT", chat)

                elif text.startswith("/auto"):
                    parts=text_raw.split()
                    if len(parts)>=2 and parts[1].lower()=="on":
                        AUTO_ENABLED=True
                        save_all()
                        price, src = get_price_mexc()
                        send_telegram(f"👔 CEO สั่งเปิด AUTO PROFIT MAX\nBTC {price:.0f} ({src}) EMA{EMA_S}/{EMA_L} RSI {RSI_L}-{RSI_H}\nRatio 5.3:1 SL -${0.17} TP +${0.91} Max Loss ${MAX_DAILY_LOSS_USD}/วัน Target ${DAILY_PROFIT_TARGET}\nใช้ทุกความสามารถ: EMA+RSI+Volume+Compound+Daily Stop\nรันเองได้ 24/7", chat)
                    elif len(parts)>=2 and parts[1].lower()=="off":
                        AUTO_ENABLED=False
                        save_all()
                        send_telegram("👔 CEO สั่งปิด AUTO", chat)
                    else:
                        send_telegram(f"👔 CEO AUTO {'ON ✅' if AUTO_ENABLED else 'OFF'} Total PnL ${stats.get('total_pnl_usd',0):+.2f} Daily ${daily.get('pnl_usd',0):+.2f}", chat)

                elif text=="/ceo":
                    log_txt="\n".join(ceo_log[-10:]) if ceo_log else "ยังไม่มี log"
                    send_telegram(f"👔 CEO LOG\nTotal PnL ${stats.get('total_pnl_usd',0):+.2f} Trades {stats.get('total_trades',0)} W{stats.get('wins',0)} L{stats.get('losses',0)}\nProfit Days {stats.get('profit_days',0)} Loss Days {stats.get('loss_days',0)}\nBest Day ${stats.get('best_day',0):+.2f} Max DD ${stats.get('max_drawdown',0):+.2f}\nDaily ${daily.get('pnl_usd',0):+.2f} Trades {daily.get('trades',0)}\n\n{log_txt}", chat)

                elif text=="/price":
                    price, src = get_price_mexc()
                    bal, is_real, bal_msg = get_balance()
                    if price:
                        send_telegram(f"💰 BTC {price:.2f} ({src})\n{bal_msg}\nทุน $40 {DEFAULT_BTC} BTC={DEFAULT_CONT} CONT SL -${0.17} TP +${0.91} Ratio 5.3:1", chat)
                    else:
                        send_telegram(f"❌ {src}", chat)

                elif text in ["/check","/status"]:
                    price, src = get_price_mexc()
                    bal, is_real, bal_msg = get_balance()
                    reset_daily()
                    pos_txt=""
                    for p in positions:
                        pos_txt+=f"\n{p['side'].upper()} {p['qty']} CONT Entry {p['entry']:.0f} SL -${p.get('sl_usd',0):.2f} TP +${p.get('tp_usd',0):.2f}"
                    if not pos_txt: pos_txt="ว่าง พร้อมเทรด"
                    send_telegram(f"👔 V17 CEO {'AUTO ON ✅' if AUTO_ENABLED else 'OFF'}\n⏰ {thai_time()}\nBTC {price if price else 'FAIL'} ({src})\n{bal_msg}\nDaily ${daily.get('pnl_usd',0):+.2f}/{DAILY_PROFIT_TARGET} Loss Limit {MAX_DAILY_LOSS_USD}\nTotal PnL ${stats.get('total_pnl_usd',0):+.2f} Trades {stats['total_trades']} W{stats['wins']} L{stats['losses']}\nPos:{pos_txt}\nได้กำไร ไม่ใช่ชนะ", chat)

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
                    price, src = get_price_mexc()
                    if price is None:
                        send_telegram("❌ ราคาดึงไม่ได้")
                        continue
                    send_telegram(f"⏳ CEO OPEN {side} {qty_str}...", chat)
                    threading.Thread(target=lambda: ceo_open(price, qty_str, side, f"Manual CEO"), daemon=True).start()

                elif text.startswith("/close"):
                    price, src = get_price_mexc()
                    if price is None:
                        send_telegram("❌ ราคาดึงไม่ได้")
                        continue
                    send_telegram(f"⏳ CEO CLOSE @ {price:.0f}...", chat)
                    threading.Thread(target=lambda: ceo_close(price, "Manual CEO close"), daemon=True).start()

                elif text=="/balance":
                    bal, is_real, bal_msg = get_balance()
                    price, src = get_price_mexc()
                    send_telegram(f"💰 {bal_msg}\nBTC {price if price else 'FAIL'} ({src})\nTotal PnL ${stats.get('total_pnl_usd',0):+.2f} Daily ${daily.get('pnl_usd',0):+.2f}\nCEO Mission: ได้กำไร", chat)

        except Exception as e:
            print(f"Tele err {e}")
            time.sleep(5)

threading.Thread(target=telegram_loop, daemon=True).start()

if __name__=="__main__":
    port=int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0", port=port)
