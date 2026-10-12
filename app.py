import requests, pandas as pd, os, time, threading, ccxt
from flask import Flask
from datetime import datetime, timezone
import pytz

# === ENV ===
MEXC_API_KEY = os.environ.get("MEXC_API_KEY", "").strip()
MEXC_API_SECRET = os.environ.get("MEXC_API_SECRET", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

# === CONFIG V2.4 BTC FINAL - ปรับจาก GOLD สำหรับ BTC ===
SYMBOL = "BTC_USDT"
SYMBOL_CCXT = "BTC_USDT"
RENDER_URL = "https://v6-cloud-bot-1.onrender.com"
INTERVAL = "15m"

ORDER_PERCENT = 5         # ลดจากทอง 6% -> 5% BTC สวิงแรงกว่า
LEVERAGE = 5
TP_PCT = 3.5              # BTC: TP กว้างกว่า TP 3.5% PnL = ราคาวิ่ง 0.7%
SL_PCT = 0.8              # BTC: SL กว้างกว่า SL 0.8% PnL = ราคาวิ่ง 0.16%
TRAIL_START_PCT = 0.6
TRAIL_PCT = 1.0
TRAIL_SUPER_PCT = 1.8
BE_PCT = 0.6

MAX_WOODS = 0
COOLDOWN_HOURS = 2
MAX_HOLD_HOURS = 72       # BTC ให้ถือได้นานกว่าทองหน่อย
MAX_DAILY_LOSS_PCT = 3.0

AVOID_FUNDING_MINUTES = 10
FUNDING_TIMES_UTC = [0, 8, 16]
ADX_THRESHOLD = 28        # BTC ต้อง >28 ถึงจะถือว่ามีเทรนด์ (ทอง >20)

app = Flask(__name__)
positions, highest, lowest = [], 0, 999999
stats = {"total_trades":0,"wins":0,"losses":0,"total_pnl_pct":0.0,"history":[],"daily_pnl":0.0,"last_reset_date":""}
cooldown_until = 0
trail_sl = 0
be_done = False
last_hourly = 0
last_hourly_report_minute = -1
hard_sl_price = 0
hard_tp_price = 0

mexc_public = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
mexc = ccxt.mexc({
    'apiKey': MEXC_API_KEY, 
    'secret': MEXC_API_SECRET, 
    'enableRateLimit': True, 
    'options': {'defaultType': 'swap'}
}) if MEXC_API_KEY and MEXC_API_SECRET else None

def thai_time():
    return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")
def thai_now():
    return datetime.now(pytz.timezone('Asia/Bangkok'))

def is_funding_time():
    try:
        now_utc = datetime.now(timezone.utc)
        for ft in FUNDING_TIMES_UTC:
            if now_utc.hour == ft and now_utc.minute < AVOID_FUNDING_MINUTES:
                return True
            if now_utc.hour == ft-1 and now_utc.minute >= (60-AVOID_FUNDING_MINUTES):
                return True
        return False
    except:
        return False

def check_max_hold():
    if not positions: return False
    try:
        ft = positions[0].get('time',0)
        return (time.time()-ft)/3600 >= MAX_HOLD_HOURS if ft else False
    except: return False

@app.route('/')
def home():
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    side = positions[0]['side'] if positions else "ว่าง"
    return f"V2.4 BTC FINAL WR:{wr:.1f}% PnL:{stats['total_pnl_pct']:+.2f}% Pos:{len(positions)} {side}"

@app.route('/stats')
def stats_page():
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    hist = "".join([f"{h['time']} {h['type']} {h['pnl']:+.2f}% {h.get('side','')}<br>" for h in stats["history"][-15:]])
    side = positions[0]['side'] if positions else "ว่าง"
    return f"<h2>V2.4 BTC FINAL 2WAY TP{TP_PCT}% SL{SL_PCT}% ADX>{ADX_THRESHOLD} {side}<br>HardSL:{hard_sl_price:.2f} Trail:{trail_sl:.2f}</h2>Trades:{stats['total_trades']} WR:{wr:.1f}% Total:{stats['total_pnl_pct']:+.2f}% Daily:{stats['daily_pnl']:+.2f}%<br><hr>{hist}"

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                          json={"chat_id": CHAT_ID, "text": msg, "parse_mode":"HTML", "disable_web_page_preview": True}, timeout=12)
        return r.status_code==200
    except Exception as e:
        print(f"Telegram err {e}")
        return False

def get_price_mexc():
    for sym in [SYMBOL_CCXT, "BTC_USDT", "BTCUSDT"]:
        try:
            t = mexc_public.fetch_ticker(sym)
            price = float(t.get('last') or t.get('close') or 0)
            if price > 1000:
                return price
        except: continue
    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", params={"symbol": "BTC_USDT"}, timeout=8)
        price = float(r.json().get('data', {}).get('lastPrice') or 0)
        if price > 1000:
            return price
    except: pass
    return None

def get_klines_mexc(limit=150):
    for sym in [SYMBOL_CCXT, "BTC_USDT", "BTCUSDT"]:
        try:
            ohlcv = mexc_public.fetch_ohlcv(sym, timeframe='15m', limit=limit)
            df = pd.DataFrame(ohlcv, columns=['ot','o','h','l','c','v'])
            if len(df) > 80:
                return df
        except: continue
    return None

def calc_lite_btc(df):
    # BTC VERSION: ปรับให้เข้ากับ BTC
    df['hlc3'] = (df['h'] + df['l'] + df['c']) / 3
    df['VWAP'] = df['hlc3'].ewm(span=96).mean()
    df['EMA20'] = df['c'].ewm(span=20).mean()
    df['EMA50'] = df['c'].ewm(span=50).mean()
    
    df['H-pH'] = df['h'].diff()
    df['pL-L'] = df['l'].shift(1) - df['l']
    df['+DM'] = df['H-pH'].where((df['H-pH'] > df['pL-L']) & (df['H-pH'] > 0), 0.0)
    df['-DM'] = df['pL-L'].where((df['pL-L'] > df['H-pH']) & (df['pL-L'] > 0), 0.0)
    df['TR'] = pd.concat([df['h']-df['l'], (df['h']-df['c'].shift()).abs(), (df['l']-df['c'].shift()).abs()], axis=1).max(axis=1)
    df['ATR'] = df['TR'].rolling(14).mean()
    df['+DM14'] = df['+DM'].rolling(14).sum()
    df['-DM14'] = df['-DM'].rolling(14).sum()
    atr_sum = df['ATR'].rolling(14).sum().replace(0, 0.001)
    df['+DI'] = 100 * (df['+DM14'] / atr_sum)
    df['-DI'] = 100 * (df['-DM14'] / atr_sum)
    df['DX'] = 100 * (df['+DI'] - df['-DI']).abs() / (df['+DI'] + df['-DI']).replace(0, 0.001)
    df['ADX'] = df['DX'].rolling(14).mean()
    
    low_min=df['l'].rolling(14).min()
    high_max=df['h'].rolling(14).max()
    df['K']=100*(df['c']-low_min)/(high_max-low_min).replace(0,0.001)
    df['D']=df['K'].rolling(3).mean()
    delta=df['c'].diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    
    # BTC: VolSpike ต้อง x1.5 เพราะ BTC วอลุ่มหลอกเยอะ
    df['VolEMA'] = df['v'].ewm(span=20).mean()
    df['VolSpike'] = df['v'] > df['VolEMA'] * 1.5
    
    # BTC: เลขกลมๆ $100 ไม่ใช่ $10 แบบทอง
    df['Round100'] = (df['c'] / 100).round() * 100
    df['DistRound100'] = abs(df['c'] - df['Round100'])
    return df.dropna()

def detect_candle_lite(df, i):
    if i < 2: return False, False, ""
    o, c, h, l = df.iloc[i]['o'], df.iloc[i]['c'], df.iloc[i]['h'], df.iloc[i]['l']
    prev_o, prev_c = df.iloc[i-1]['o'], df.iloc[i-1]['c']
    body = abs(c-o)
    lower_wick = min(o,c) - l
    upper_wick = h - max(o,c)
    total_range = h-l if (h-l)>0 else 0.01
    bull_pin = lower_wick > body*1.8 and lower_wick > total_range*0.5 and body < total_range*0.4
    bull_eng = prev_c < prev_o and c > o and c > prev_o and o <= prev_c and body > abs(prev_c-prev_o)
    bear_pin = upper_wick > body*1.8 and upper_wick > total_range*0.5 and body < total_range*0.4
    bear_eng = prev_c > prev_o and c < o and c < prev_o and o >= prev_c and body > abs(prev_c-prev_o)
    bull = bull_pin or bull_eng
    bear = bear_pin or bear_eng
    name = "HAMMER" if bull_pin else ("BULL_ENGULF" if bull_eng else ("SHOOTING" if bear_pin else ("BEAR_ENGULF" if bear_eng else "")))
    return bull, bear, name

def get_balance():
    if not mexc: return 0.0, 0.0, 0.0
    try:
        bal=mexc.fetch_balance()
        total = float(bal.get('USDT',{}).get('total') or bal.get('total',{}).get('USDT') or 0)
        free = float(bal.get('USDT',{}).get('free') or bal.get('USDT',{}).get('available') or 0)
        return total, free, 0.0
    except: return 0.0, 0.0, 0.0

def format_balance_msg():
    total, free, _ = get_balance()
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    return f"💰 {total:.2f}$ Free {free:.2f}$ | WR {wr:.1f}% PnL {stats['total_pnl_pct']:+.2f}% Daily {stats['daily_pnl']:+.2f}%", total, wr

def set_leverage_safe():
    if not mexc: return
    for sym in [SYMBOL_CCXT, "BTC_USDT"]:
        try: mexc.set_leverage(LEVERAGE, sym)
        except: pass

def place_hard_sl_tp(side, entry_price, qty):
    global hard_sl_price, hard_tp_price
    if not mexc:
        if side == 'long':
            hard_sl_price = entry_price * (1 - (SL_PCT/LEVERAGE)/100)
            hard_tp_price = entry_price * (1 + (TP_PCT/LEVERAGE)/100)
        else:
            hard_sl_price = entry_price * (1 + (SL_PCT/LEVERAGE)/100)
            hard_tp_price = entry_price * (1 - (TP_PCT/LEVERAGE)/100)
        return True
    price_move_pct = (SL_PCT / LEVERAGE) / 100
    tp_move_pct = (TP_PCT / LEVERAGE) / 100
    try:
        if side == 'long':
            sl_price = entry_price * (1 - price_move_pct)
            tp_price = entry_price * (1 + tp_move_pct)
            hard_sl_price = sl_price; hard_tp_price = tp_price
            try:
                mexc.create_order(SYMBOL_CCXT, 'STOP_MARKET', 'sell', qty, None, {'stopPrice': sl_price, 'reduceOnly': True})
            except: pass
            try:
                mexc.create_order(SYMBOL_CCXT, 'limit', 'sell', qty, tp_price, {'reduceOnly': True})
            except: pass
        else:
            sl_price = entry_price * (1 + price_move_pct)
            tp_price = entry_price * (1 - tp_move_pct)
            hard_sl_price = sl_price; hard_tp_price = tp_price
            try:
                mexc.create_order(SYMBOL_CCXT, 'STOP_MARKET', 'buy', qty, None, {'stopPrice': sl_price, 'reduceOnly': True})
            except: pass
            try:
                mexc.create_order(SYMBOL_CCXT, 'limit', 'buy', qty, tp_price, {'reduceOnly': True})
            except: pass
        return True
    except Exception as e:
        print(f"place SL err {e}")
        return False

def mexc_buy(price,factor):
    if not mexc: return True, 0.001
    try:
        total,free,_=get_balance()
        bal = total if total>0 else free
        if bal < 5: return False, 0
        qty = round(max((bal*(ORDER_PERCENT/100)*factor)/price, 0.0001), 4)
        set_leverage_safe()
        mexc.create_market_buy_order(SYMBOL_CCXT, qty)
        place_hard_sl_tp('long', price, qty)
        return True, qty
    except Exception as e:
        print(f"BUY err {e}")
        send_telegram(f"❌ BUY ล้มเหลว {e}")
        return False, 0

def mexc_sell(price,factor):
    if not mexc: return True, 0.001
    try:
        total,free,_=get_balance()
        bal = total if total>0 else free
        if bal < 5: return False, 0
        qty = round(max((bal*(ORDER_PERCENT/100)*factor)/price, 0.0001), 4)
        set_leverage_safe()
        mexc.create_market_sell_order(SYMBOL_CCXT, qty)
        place_hard_sl_tp('short', price, qty)
        return True, qty
    except Exception as e:
        print(f"SELL err {e}")
        send_telegram(f"❌ SELL ล้มเหลว {e}")
        return False, 0

def mexc_close_all():
    if not mexc: return True
    try:
        try: mexc.cancel_all_orders(SYMBOL_CCXT)
        except: pass
        mexc.create_order(SYMBOL_CCXT, 'market', 'sell', 0, None, {'reduceOnly': True, 'closePosition': True})
        time.sleep(0.5)
        mexc.create_order(SYMBOL_CCXT, 'market', 'buy', 0, None, {'reduceOnly': True, 'closePosition': True})
        return True
    except:
        return False

def close_position(price,typ):
    global positions,stats,trail_sl,be_done,cooldown_until,hard_sl_price,hard_tp_price
    if not positions: return
    avg = sum(p['entry']*abs(p['qty']) for p in positions)/sum(abs(p['qty']) for p in positions) if positions else price
    is_short = positions[0].get('side') == 'short'
    pnl = (avg - price)/avg*100*LEVERAGE if is_short else (price-avg)/avg*100*LEVERAGE
    today_str = thai_now().strftime("%Y-%m-%d")
    if stats["last_reset_date"] != today_str:
        stats["daily_pnl"] = 0
        stats["last_reset_date"] = today_str
    stats["daily_pnl"] += pnl
    stats["total_trades"]+=1
    stats["total_pnl_pct"]+=pnl
    if pnl>0: stats["wins"]+=1
    else: stats["losses"]+=1
    stats["history"].append({"time":thai_time(),"type":typ,"pnl":pnl,"side":positions[0]['side']})
    mexc_close_all()
    bal_msg,_,wr=format_balance_msg()
    side_emoji = "🔴" if is_short else "🟢"
    send_telegram(f"✅ [{thai_time()}] {side_emoji} {typ} ปิด {pnl:+.2f}% {positions[0]['side']} WR {wr:.1f}%\nHardSL {hard_sl_price:.1f} Trail {trail_sl:.1f}\n{bal_msg}")
    positions.clear()
    global highest, lowest
    highest=0; lowest=999999; trail_sl=0; hard_sl_price=0; hard_tp_price=0; be_done=False
    cooldown_until = time.time() + COOLDOWN_HOURS*3600

def should_send_hourly():
    global last_hourly, last_hourly_report_minute
    now = thai_now()
    time_ok = (time.time() - last_hourly) >= 3600
    hour_top = (now.minute == 0 and now.second < 20 and last_hourly_report_minute != now.hour)
    return time_ok or hour_top

def trading_loop():
    global positions,highest,lowest,last_hourly,cooldown_until,last_hourly_report_minute,trail_sl,be_done,hard_sl_price
    time.sleep(3)
    bal_msg,_,_=format_balance_msg()
    last_hourly = time.time()
    last_hourly_report_minute = thai_now().hour
    send_telegram(f"🚀 V2.4 BTC FINAL LIVE {SYMBOL_CCXT} TP{TP_PCT}% SL{SL_PCT}% ADX>{ADX_THRESHOLD} 2WAY HardSL ON")

    while True:
        try:
            if time.time() < cooldown_until: time.sleep(30); continue
            if is_funding_time(): time.sleep(60); continue
            if stats["daily_pnl"] <= -MAX_DAILY_LOSS_PCT:
                send_telegram(f"🛑 ตัดขาดทุนรายวัน {stats['daily_pnl']:.2f}% หยุด 6 ชม.")
                time.sleep(3600*6); continue

            price=get_price_mexc()
            df=get_klines_mexc()
            if not price or df is None or len(df)<100: time.sleep(15); continue
            df=calc_lite_btc(df)
            last=df.iloc[-1]
            adx = last['ADX']
            plus_di = last['+DI']
            minus_di = last['-DI']
            has_trend = adx > ADX_THRESHOLD
            uptrend = plus_di > minus_di and has_trend
            downtrend = minus_di > plus_di and has_trend
            super_up = adx > 28 and (plus_di-minus_di) > 12
            super_down = adx > 28 and (minus_di-plus_di) > 12
            vwap = last['VWAP']
            ema20 = last['EMA20']
            rsi = last['RSI']
            dist_vwap = last['c']-vwap
            dist_ema = last['c']-ema20
            
            # BTC: แนวรับต้าน $100
            near_support = (abs(last['DistRound100'])<50) or (0<=dist_vwap<=100) or (0<=dist_ema<=100)
            near_resistance = (abs(last['DistRound100'])<50) or (-100<=dist_vwap<=0) or (-100<=dist_ema<=0)
            touch_ema_buy = last['l'] <= ema20 and last['c'] > ema20
            touch_ema_sell = last['h'] >= ema20 and last['c'] < ema20
            bull_candle, bear_candle, candle_name = detect_candle_lite(df, len(df)-1)
            vol_spike = last['VolSpike']

            buy=False; sell=False; buy_reason=""; sell_reason=""

            # LONG BTC - เข้มกว่า GOLD
            if super_up and last['c']>ema20 and last['c']>vwap and 55<=rsi<=80 and bull_candle and vol_spike:
                buy=True; buy_reason=f"SUPER_UP {candle_name} ADX{adx:.0f}"
            elif uptrend and last['c']>vwap and last['c']>ema20 and (touch_ema_buy or 0<=dist_ema<=120) and 50<=rsi<=78 and near_support and bull_candle:
                buy=True; buy_reason=f"TREND_UP {candle_name} ADX{adx:.0f}"
            elif not has_trend and touch_ema_buy and 50<=rsi<=70 and near_support and bull_candle and vol_spike and last['c']>vwap:
                buy=True; buy_reason=f"SIDEWAY_UP {candle_name} ADX{adx:.0f}"

            # SHORT BTC
            if super_down and last['c']<ema20 and last['c']<vwap and 20<=rsi<=45 and bear_candle and vol_spike:
                sell=True; sell_reason=f"SUPER_DOWN {candle_name} ADX{adx:.0f}"
            elif downtrend and last['c']<vwap and last['c']<ema20 and (touch_ema_sell or -120<=dist_ema<=0) and 22<=rsi<=50 and near_resistance and bear_candle:
                sell=True; sell_reason=f"TREND_DOWN {candle_name} ADX{adx:.0f}"
            elif not has_trend and touch_ema_sell and 30<=rsi<=50 and near_resistance and bear_candle and vol_spike and last['c']<vwap:
                sell=True; sell_reason=f"SIDEWAY_DOWN {candle_name} ADX{adx:.0f}"

            if should_send_hourly():
                last_hourly=time.time()
                last_hourly_report_minute = thai_now().hour
                total,_,_=get_balance()
                if len(positions)==0:
                    status = f"ว่าง ADX{adx:.0f} {candle_name} VWAP{dist_vwap:+.0f} RSI{rsi:.0f}"
                else:
                    avg = positions[0]['entry']
                    is_s = positions[0]['side']=='short'
                    pnl = (avg-price)/avg*100*LEVERAGE if is_s else (price-avg)/avg*100*LEVERAGE
                    status = f"ถือ {positions[0]['side']} PnL {pnl:+.2f}% HardSL {hard_sl_price:.0f} Trail {trail_sl:.0f}"
                send_telegram(f"⏰ [{thai_time()}] {SYMBOL_CCXT} {price:.2f}$ {status}\n💰 {total:.2f}$ Daily {stats['daily_pnl']:+.2f}%")

            if len(positions)==0:
                if buy:
                    ok,qty=mexc_buy(price,1)
                    if ok:
                        positions.append({'entry':price,'qty':qty,'side':'long','time':time.time()})
                        highest=price; lowest=999999
                        trail_sl=price*(1-(SL_PCT/LEVERAGE)/100)
                        be_done=False
                        bal_msg,_,_=format_balance_msg()
                        send_telegram(f"🟢 LONG BTC {price:.0f}$ {buy_reason}\nHard SL {hard_sl_price:.0f} TP {hard_tp_price:.0f} RSI{rsi:.0f}\n{bal_msg}")
                elif sell:
                    ok,qty=mexc_sell(price,1)
                    if ok:
                        positions.append({'entry':price,'qty':-qty,'side':'short','time':time.time()})
                        lowest=price; highest=0
                        trail_sl=price*(1+(SL_PCT/LEVERAGE)/100)
                        be_done=False
                        bal_msg,_,_=format_balance_msg()
                        send_telegram(f"🔴 SHORT BTC {price:.0f}$ {sell_reason}\nHard SL {hard_sl_price:.0f} TP {hard_tp_price:.0f} RSI{rsi:.0f}\n{bal_msg}")

            if positions:
                avg=positions[0]['entry']
                is_short = positions[0]['side']=='short'
                pnl=(avg-price)/avg*100*LEVERAGE if is_short else (price-avg)/avg*100*LEVERAGE
                if is_short:
                    if price<lowest: lowest=price
                else:
                    if price>highest: highest=price

                if pnl>=BE_PCT and not be_done:
                    trail_sl = min(trail_sl, avg*0.999) if is_short else max(trail_sl, avg*1.001)
                    hard_sl_price = trail_sl
                    be_done=True
                    send_telegram(f"🔒 BTC ยกทุน {trail_sl:.0f} PnL {pnl:+.2f}% {positions[0]['side']}")

                if pnl>=TRAIL_START_PCT:
                    if is_short:
                        cur_pct = TRAIL_SUPER_PCT if super_down else TRAIL_PCT
                        new_trail=lowest*(1+cur_pct/100)
                        if new_trail < trail_sl or trail_sl==0:
                            trail_sl=new_trail; hard_sl_price = new_trail
                            if pnl>=1.0:
                                send_telegram(f"📉 Trail SHORT BTC {trail_sl:.0f} Low {lowest:.0f} PnL {pnl:+.2f}% ADX{adx:.0f}")
                    else:
                        cur_pct = TRAIL_SUPER_PCT if super_up else TRAIL_PCT
                        new_trail=highest*(1-cur_pct/100)
                        if new_trail>trail_sl:
                            trail_sl=new_trail; hard_sl_price = new_trail
                            if pnl>=1.0:
                                send_telegram(f"📈 Trail LONG BTC {trail_sl:.0f} High {highest:.0f} PnL {pnl:+.2f}% ADX{adx:.0f}")

                should_exit=False; reason=""
                if is_short:
                    if price>=trail_sl and trail_sl>0:
                        if not (super_down and last['c']<vwap and last['c']<ema20):
                            should_exit=True; reason=f"TRAIL_SHORT {trail_sl:.0f}"
                    if (last['c']>vwap and last['c']>ema20 and rsi>55 and plus_di>minus_di and pnl>0.2):
                        should_exit=True; reason="TREND_BREAK_UP"
                    if bull_candle and pnl>0.5 and rsi<30:
                        should_exit=True; reason=f"BULL_CANDLE {candle_name}"
                else:
                    if price<=trail_sl and trail_sl>0:
                        if not (super_up and last['c']>vwap and last['c']>ema20):
                            should_exit=True; reason=f"TRAIL_LONG {trail_sl:.0f}"
                    if (last['c']<vwap and last['c']<ema20 and rsi<45 and minus_di>plus_di and pnl>0.2):
                        should_exit=True; reason="TREND_BREAK_DOWN"
                    if bear_candle and pnl>0.5 and rsi>70:
                        should_exit=True; reason=f"BEAR_CANDLE {candle_name}"

                if pnl>=TP_PCT: should_exit=True; reason=f"TP {TP_PCT}%"
                if check_max_hold(): should_exit=True; reason=f"MAX_HOLD {MAX_HOLD_HOURS}h"
                if pnl <= -SL_PCT*1.5: should_exit=True; reason=f"HARD_SL {pnl:.2f}%"
                if should_exit: close_position(price, reason)

            time.sleep(15)
        except Exception as e:
            print(f"Loop err {e}")
            import traceback; traceback.print_exc()
            time.sleep(15)

threading.Thread(target=trading_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
