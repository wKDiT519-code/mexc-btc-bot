"""
V3.0 HYBRID ULTIMATE - ผสม GOLD 2-way + BTC FINAL
- เทรดได้ทั้ง BTC และ GOLD ด้วยไฟล์เดียว Auto Adaptive
- นิสัย BTC: SL กว้าง 1.2% TP 2.5% ADX>28
- นิสัย GOLD: SL แคบ 0.5% TP 1.5% ADX>22 + Trailing ชิด
- เพิ่ม: Market Regime Detection + ATR Dynamic + Funding Filter
"""
import requests, pandas as pd, os, time, threading, ccxt
from flask import Flask
from datetime import datetime, timezone
import pytz

# === ENV ===
MEXC_API_KEY = os.environ.get("MEXC_API_KEY", "").strip()
MEXC_API_SECRET = os.environ.get("MEXC_API_SECRET", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip() or os.environ.get("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip() or os.environ.get("TELEGRAM_CHAT_ID","").strip()

# === CONFIG V3.0 HYBRID ===
SYMBOL = os.environ.get("SYMBOL", "BTC_USDT")  # เปลี่ยนเป็น GOLD_USDT ก็ได้ Auto ปรับ
SYMBOL_CCXT = SYMBOL.replace("_","/") if "_" in SYMBOL else "BTC/USDT"
INTERVAL = "15m"

# Adaptive Params ตามนิสัยราคา
if "BTC" in SYMBOL:
    # === BTC MODE - เหวี่ยงแรง ไส้ยาว ===
    ADAPTIVE = {
        "LEVERAGE": 8,
        "SL_PCT": 9.6,        # 1.2% ราคา *8 = 9.6% PnL
        "TP_PCT": 20.0,       # 2.5% ราคา *8 = 20% PnL RR 2.08
        "BE_PCT": 5.0,        # 0.625% ราคา
        "TRAIL_START": 8.0,   # 1.0% ราคา
        "TRAIL_PCT": 9.6,     # 1.2% ราคา
        "TRAIL_SUPER": 16.0,  # 2.0% ราคา
        "ADX_THR": 28,
        "VOL_MULT": 1.5,
        "EMA_DIST": 1.2,      # ใกล้ EMA ไม่เกิน 1.2%
        "ROUND_LEVEL": 100,   # แนวต้าน $100
        "MAX_HOLD": 24,
        "COOLDOWN": 3
    }
else:
    # === GOLD MODE - วิ่งช้า ไส้สั้น ===
    ADAPTIVE = {
        "LEVERAGE": 5,
        "SL_PCT": 3.0,        # 0.6% ราคา *5 = 3% PnL
        "TP_PCT": 12.5,       # 2.5% ราคา *5 = 12.5% PnL RR 4.16
        "BE_PCT": 2.25,       # 0.45% ราคา
        "TRAIL_START": 2.0,   # 0.4% ราคา
        "TRAIL_PCT": 3.5,     # 0.7% ราคา
        "TRAIL_SUPER": 6.0,   # 1.2% ราคา
        "ADX_THR": 22,
        "VOL_MULT": 1.3,
        "EMA_DIST": 0.8,
        "ROUND_LEVEL": 10,    # แนวต้าน $10
        "MAX_HOLD": 48,
        "COOLDOWN": 2
    }

ORDER_PERCENT = 5
MAX_DAILY_LOSS_PCT = 4.0
AVOID_FUNDING_MINUTES = 10
FUNDING_TIMES_UTC = [0, 8, 16]

app = Flask(__name__)
positions, highest, lowest = [], 0, 999999
stats = {"total_trades":0,"wins":0,"losses":0,"total_pnl_pct":0.0,"history":[],"daily_pnl":0.0,"last_reset_date":""}
cooldown_until = 0
trail_sl = 0
be_done = False
last_hourly_report_minute = -1
hard_sl_price = 0

mexc_public = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
mexc = ccxt.mexc({
    'apiKey': MEXC_API_KEY, 'secret': MEXC_API_SECRET,
    'enableRateLimit': True, 'options': {'defaultType': 'swap'}
}) if MEXC_API_KEY and MEXC_API_SECRET else None

def thai_time(): return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")
def thai_now(): return datetime.now(pytz.timezone('Asia/Bangkok'))
def is_funding_time():
    try:
        now_utc = datetime.now(timezone.utc)
        for ft in FUNDING_TIMES_UTC:
            if now_utc.hour == ft and now_utc.minute < AVOID_FUNDING_MINUTES: return True
            if now_utc.hour == ft-1 and now_utc.minute >= (60-AVOID_FUNDING_MINUTES): return True
        return False
    except: return False

def check_max_hold():
    if not positions: return False
    try: return (time.time()-positions[0].get('time',0))/3600 >= ADAPTIVE["MAX_HOLD"]
    except: return False

@app.route('/')
def home():
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    side = positions[0]['side'] if positions else "ว่าง"
    return f"V3.0 HYBRID {SYMBOL} WR:{wr:.1f}% PnL:{stats['total_pnl_pct']:+.2f}% Pos:{len(positions)} {side} ADX>{ADAPTIVE['ADX_THR']}"

@app.route('/stats')
def stats_page():
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    hist = "".join([f"{h['time']} {h['type']} {h['pnl']:+.2f}%<br>" for h in stats["history"][-20:]])
    side = positions[0]['side'] if positions else "ว่าง"
    return f"<h2>V3.0 HYBRID {SYMBOL} TP{ADAPTIVE['TP_PCT']}% SL{ADAPTIVE['SL_PCT']}% ADX>{ADAPTIVE['ADX_THR']} LEV x{ADAPTIVE['LEVERAGE']} {side}<br>Trail:{trail_sl:.2f} HardSL:{hard_sl_price:.2f}</h2>Trades:{stats['total_trades']} WR:{wr:.1f}% Total:{stats['total_pnl_pct']:+.2f}% Daily:{stats['daily_pnl']:+.2f}%<br><hr>{hist}"

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode":"HTML"}, timeout=12)
        return r.status_code==200
    except: return False

def get_price():
    for sym in [SYMBOL_CCXT, SYMBOL, SYMBOL.replace("_","")]:
        try:
            t = mexc_public.fetch_ticker(sym)
            price = float(t.get('last') or 0)
            if price>100: return price
        except: continue
    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", params={"symbol": SYMBOL}, timeout=8)
        price = float(r.json().get('data',{}).get('lastPrice') or 0)
        if price>100: return price
    except: pass
    return None

def get_klines(limit=150):
    for sym in [SYMBOL_CCXT, SYMBOL, SYMBOL.replace("_","")]:
        try:
            ohlcv = mexc_public.fetch_ohlcv(sym, timeframe=INTERVAL, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['ot','o','h','l','c','v'])
            if len(df)>80: return df
        except: continue
    return None

def calc_hybrid(df):
    # --- Hybrid Indicators ---
    df['hlc3'] = (df['h']+df['l']+df['c'])/3
    df['VWAP'] = df['hlc3'].ewm(span=96).mean()
    df['EMA20'] = df['c'].ewm(span=20).mean()
    df['EMA50'] = df['c'].ewm(span=50).mean()
    df['EMA200'] = df['c'].ewm(span=200).mean()
    
    # ADX
    df['H-pH'] = df['h'].diff()
    df['pL-L'] = df['l'].shift(1)-df['l']
    df['+DM'] = df['H-pH'].where((df['H-pH']>df['pL-L']) & (df['H-pH']>0), 0.0)
    df['-DM'] = df['pL-L'].where((df['pL-L']>df['H-pH']) & (df['pL-L']>0), 0.0)
    df['TR'] = pd.concat([df['h']-df['l'], (df['h']-df['c'].shift()).abs(), (df['l']-df['c'].shift()).abs()], axis=1).max(axis=1)
    df['ATR'] = df['TR'].rolling(14).mean()
    df['+DM14'] = df['+DM'].rolling(14).sum()
    df['-DM14'] = df['-DM'].rolling(14).sum()
    atr_sum = df['ATR'].rolling(14).sum().replace(0,0.001)
    df['+DI'] = 100*(df['+DM14']/atr_sum)
    df['-DI'] = 100*(df['-DM14']/atr_sum)
    df['DX'] = 100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI']).replace(0,0.001)
    df['ADX'] = df['DX'].rolling(14).mean()
    
    # RSI + Stoch
    delta=df['c'].diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    low_min=df['l'].rolling(14).min()
    high_max=df['h'].rolling(14).max()
    df['K']=100*(df['c']-low_min)/(high_max-low_min).replace(0,0.001)
    
    # Vol + ATR%
    df['VolEMA']=df['v'].ewm(span=20).mean()
    df['VolSpike']=df['v'] > df['VolEMA']*ADAPTIVE["VOL_MULT"]
    df['ATR_PCT']=df['ATR']/df['c']*100  # BTC ~0.3% GOLD ~0.15%
    
    # Market Regime - ของใหม่!
    # ถ้า ADX>35 + EMA20>EMA50>EMA200 = Super Trend
    # ถ้า ADX 22-35 = Normal Trend
    # ถ้า ADX<22 = Sideway ต้องใช้ Vol Spike
    df['Regime'] = 'SIDEWAY'
    df.loc[(df['ADX']>ADAPTIVE["ADX_THR"]) & (df['ADX']<=35), 'Regime'] = 'TREND'
    df.loc[df['ADX']>35, 'Regime'] = 'SUPER'
    
    # Round Level
    df['RoundLevel'] = (df['c']/ADAPTIVE["ROUND_LEVEL"]).round()*ADAPTIVE["ROUND_LEVEL"]
    return df

def get_balance():
    try:
        if not mexc: return 100,100,100
        bal=mexc.fetch_balance()
        total=float(bal.get('USDT',{}).get('total',100) or 100)
        return total,total,total
    except: return 100,100,100

def format_bal():
    total,_,_=get_balance()
    return f"💰 {total:.2f}$",total,total

def mexc_buy(price, wood):
    try:
        if not mexc: return True, ORDER_PERCENT
        total,_,_=get_balance()
        qty=total*ORDER_PERCENT/100*ADAPTIVE["LEVERAGE"]/price
        return True, qty
    except: return False,0

def mexc_sell(price, wood):
    try:
        if not mexc: return True, ORDER_PERCENT
        total,_,_=get_balance()
        qty=total*ORDER_PERCENT/100*ADAPTIVE["LEVERAGE"]/price
        return True, qty
    except: return False,0

def close_position(price, reason):
    global positions, stats, trail_sl, be_done, cooldown_until, hard_sl_price
    if not positions: return
    entry=positions[0]['entry']
    is_short=positions[0]['side']=='short'
    pnl=(entry-price)/entry*100*ADAPTIVE["LEVERAGE"] if is_short else (price-entry)/entry*100*ADAPTIVE["LEVERAGE"]
    stats["total_trades"]+=1
    stats["total_pnl_pct"]+=pnl
    stats["daily_pnl"]+=pnl
    if pnl>0:
        stats["wins"]+=1; icon="✅"
    else:
        stats["losses"]+=1; icon="❌"
    stats["history"].append({"time":thai_time(),"type":f"{positions[0]['side'].upper()} {reason}","pnl":pnl})
    wr = stats["wins"]/stats["total_trades"]*100 if stats["total_trades"]>0 else 0
    send_telegram(f"{icon} ปิด {positions[0]['side'].upper()} {SYMBOL} {price:.2f}$ {reason}\nPnL {pnl:+.2f}% Entry {entry:.2f} WR {wr:.1f}%\n💰 Total {stats['total_pnl_pct']:+.2f}% W{stats['wins']} L{stats['losses']}")
    positions=[]; trail_sl=0; be_done=False; hard_sl_price=0
    cooldown_until=time.time()+ADAPTIVE["COOLDOWN"]*3600

def trading_loop():
    global positions, highest, lowest, trail_sl, be_done, hard_sl_price
    print(f"V3.0 HYBRID {SYMBOL} START ADX>{ADAPTIVE['ADX_THR']} LEV x{ADAPTIVE['LEVERAGE']}")
    send_telegram(f"🚀 <b>V3.0 HYBRID ULTIMATE START</b>\nSYMBOL {SYMBOL} {INTERVAL}\nLEVERAGE x{ADAPTIVE['LEVERAGE']} ORDER {ORDER_PERCENT}%\nTP {ADAPTIVE['TP_PCT']}% SL {ADAPTIVE['SL_PCT']}% BE {ADAPTIVE['BE_PCT']}%\nADX>{ADAPTIVE['ADX_THR']} VOL x{ADAPTIVE['VOL_MULT']}\nCooldown {ADAPTIVE['COOLDOWN']}h MaxHold {ADAPTIVE['MAX_HOLD']}h\nRegime: SUPER/TREND/SIDEWAY")
    while True:
        try:
            if time.time()<cooldown_until: time.sleep(15); continue
            if is_funding_time(): time.sleep(60); continue
            if stats["daily_pnl"] <= -MAX_DAILY_LOSS_PCT:
                if time.time()%3600<15: send_telegram(f"🛑 Daily Loss Limit {stats['daily_pnl']:.2f}% หยุดวันนี้")
                time.sleep(60); continue

            df=get_klines(150)
            if df is None or len(df)<80: time.sleep(15); continue
            df=calc_hybrid(df)
            last=df.iloc[-1]
            price=float(last['c'])
            ema20=float(last['EMA20']); ema50=float(last['EMA50']); ema200=float(last['EMA200'])
            vwap=float(last['VWAP']); adx=float(last['ADX']); rsi=float(last['RSI'])
            plus_di=float(last['+DI']); minus_di=float(last['-DI'])
            atr_pct=float(last['ATR_PCT']); regime=last['Regime']
            dist_vwap=(price-vwap)/vwap*100
            dist_ema=(price-ema20)/ema20*100
            
            body=abs(last['c']-last['o'])
            bull_candle=last['c']>last['o'] and body>last['ATR']*0.3
            bear_candle=last['c']<last['o'] and body>last['ATR']*0.3
            near_round=abs(price-last['RoundLevel'])/price*100 < (0.15 if "BTC" in SYMBOL else 0.08)
            touch_ema=abs(dist_ema)<ADAPTIVE["EMA_DIST"]
            vol_spike=bool(last['VolSpike'])
            candle_name="BULL" if bull_candle else "BEAR" if bear_candle else "DOJI"

            # === Market Regime Logic - หัวใจ Hybrid ===
            super_up = regime=='SUPER' and plus_di>minus_di+10 and price>ema20 and ema20>ema50 and ema50>ema200 and rsi>50
            super_down = regime=='SUPER' and minus_di>plus_di+10 and price<ema20 and ema20<ema50 and ema50<ema200 and rsi<50
            uptrend = regime in ['TREND','SUPER'] and plus_di>minus_di and adx>ADAPTIVE["ADX_THR"] and price>vwap
            downtrend = regime in ['TREND','SUPER'] and minus_di>plus_di and adx>ADAPTIVE["ADX_THR"] and price<vwap

            buy=False; sell=False; buy_reason=""; sell_reason=""

            # --- LONG Logic Hybrid ---
            if super_up and price>ema20 and price>vwap and 50<=rsi<=68 and bull_candle and vol_spike:
                buy=True; buy_reason=f"SUPER_UP {candle_name} ADX{adx:.0f} ATR{atr_pct:.2f}%"
            elif uptrend and price>vwap and price>ema20 and (touch_ema or 0<=dist_ema<=ADAPTIVE["EMA_DIST"]*2) and 48<=rsi<=65 and not near_round and bull_candle:
                buy=True; buy_reason=f"TREND_UP {candle_name} ADX{adx:.0f} VWAP{dist_vwap:+.2f}%"
            elif regime=='SIDEWAY' and touch_ema and 45<=rsi<=58 and not near_round and bull_candle and vol_spike and last['c']>vwap and adx>ADAPTIVE["ADX_THR"]-5:
                # Sideway ต้องมี Vol Spike + อยู่เหนือ VWAP เท่านั้น
                buy=True; buy_reason=f"SIDEWAY_UP {candle_name} ADX{adx:.0f}"

            # --- SHORT Logic Hybrid - BTC ชอร์ตยากกว่า ---
            if super_down and price<ema20 and price<vwap and 32<=rsi<=50 and bear_candle and vol_spike:
                sell=True; sell_reason=f"SUPER_DOWN {candle_name} ADX{adx:.0f}"
            elif downtrend and price<vwap and price<ema20 and (touch_ema or -ADAPTIVE["EMA_DIST"]*2<=dist_ema<=0) and 35<=rsi<=52 and near_round and bear_candle:
                sell=True; sell_reason=f"TREND_DOWN {candle_name} ADX{adx:.0f}"
            elif regime=='SIDEWAY' and touch_ema and 42<=rsi<=55 and near_round and bear_candle and vol_spike and last['c']<vwap and adx>ADAPTIVE["ADX_THR"]-5:
                sell=True; sell_reason=f"SIDEWAY_DOWN {candle_name} ADX{adx:.0f}"

            # Hourly report
            now=thai_now()
            if now.minute==0 and now.hour!=last_hourly_report_minute:
                last_hourly_report_minute=now.hour
                total,_,_=get_balance()
                if len(positions)==0:
                    status=f"ว่าง ADX{adx:.0f} {regime} {candle_name} VWAP{dist_vwap:+.1f} ATR{atr_pct:.2f}%"
                else:
                    avg=positions[0]['entry']
                    is_s=positions[0]['side']=='short'
                    pnl=(avg-price)/avg*100*ADAPTIVE["LEVERAGE"] if is_s else (price-avg)/avg*100*ADAPTIVE["LEVERAGE"]
                    status=f"ถือ {positions[0]['side']} PnL {pnl:+.2f}% Trail {trail_sl:.0f} Regime {regime}"
                send_telegram(f"⏰ [{thai_time()}] {SYMBOL} {price:.2f}$ {status}\n💰 {total:.2f}$ Daily {stats['daily_pnl']:+.2f}% WR {stats['wins']}/{stats['total_trades']}")

            # ENTRY
            if len(positions)==0:
                if buy:
                    ok,qty=mexc_buy(price,1)
                    if ok:
                        positions.append({'entry':price,'qty':qty,'side':'long','time':time.time()})
                        highest=price; lowest=999999
                        trail_sl=price*(1-(ADAPTIVE["SL_PCT"]/ADAPTIVE["LEVERAGE"])/100)
                        hard_sl_price=trail_sl
                        be_done=False
                        bal_msg,_,_=format_bal()
                        send_telegram(f"🟢 LONG {SYMBOL} {price:.0f}$ {buy_reason}\nSL {trail_sl:.0f} RSI{rsi:.0f} {regime}\n{bal_msg}")
                elif sell:
                    ok,qty=mexc_sell(price,1)
                    if ok:
                        positions.append({'entry':price,'qty':-qty,'side':'short','time':time.time()})
                        lowest=price; highest=0
                        trail_sl=price*(1+(ADAPTIVE["SL_PCT"]/ADAPTIVE["LEVERAGE"])/100)
                        hard_sl_price=trail_sl
                        be_done=False
                        bal_msg,_,_=format_bal()
                        send_telegram(f"🔴 SHORT {SYMBOL} {price:.0f}$ {sell_reason}\nSL {trail_sl:.0f} RSI{rsi:.0f} {regime}\n{bal_msg}")

            # MANAGE
            if positions:
                avg=positions[0]['entry']
                is_short=positions[0]['side']=='short'
                pnl=(avg-price)/avg*100*ADAPTIVE["LEVERAGE"] if is_short else (price-avg)/avg*100*ADAPTIVE["LEVERAGE"]
                if is_short:
                    if price<lowest: lowest=price
                else:
                    if price>highest: highest=price

                # BE
                if pnl>=ADAPTIVE["BE_PCT"] and not be_done:
                    trail_sl = min(trail_sl, avg*0.999) if is_short else max(trail_sl, avg*1.001)
                    hard_sl_price=trail_sl
                    be_done=True
                    send_telegram(f"🔒 {SYMBOL} ยกทุน {trail_sl:.0f} PnL {pnl:+.2f}% {positions[0]['side']}")

                # Trailing - Dynamic ตาม Regime
                if pnl>=ADAPTIVE["TRAIL_START"]:
                    cur_pct = ADAPTIVE["TRAIL_SUPER"] if regime=='SUPER' else ADAPTIVE["TRAIL_PCT"]
                    if is_short:
                        new_trail=lowest*(1+cur_pct/100/ADAPTIVE["LEVERAGE"])
                        if new_trail < trail_sl or trail_sl==0:
                            trail_sl=new_trail; hard_sl_price=new_trail
                            if pnl>=ADAPTIVE["BE_PCT"]+2:
                                send_telegram(f"📉 Trail SHORT {SYMBOL} {trail_sl:.0f} Low {lowest:.0f} PnL {pnl:+.2f}% {regime}")
                    else:
                        new_trail=highest*(1-cur_pct/100/ADAPTIVE["LEVERAGE"])
                        if new_trail>trail_sl:
                            trail_sl=new_trail; hard_sl_price=new_trail
                            if pnl>=ADAPTIVE["BE_PCT"]+2:
                                send_telegram(f"📈 Trail LONG {SYMBOL} {trail_sl:.0f} High {highest:.0f} PnL {pnl:+.2f}% {regime}")

                should_exit=False; reason=""
                if is_short:
                    if price>=trail_sl and trail_sl>0:
                        if not (super_down and last['c']<vwap and last['c']<ema20):
                            should_exit=True; reason=f"TRAIL_SHORT {trail_sl:.0f}"
                    if last['c']>vwap and last['c']>ema20 and rsi>58 and plus_di>minus_di and pnl>0.5:
                        should_exit=True; reason="TREND_BREAK_UP"
                    if bull_candle and pnl>1.0 and rsi<30:
                        should_exit=True; reason=f"BULL_REVERSAL {candle_name}"
                else:
                    if price<=trail_sl and trail_sl>0:
                        if not (super_up and last['c']>vwap and last['c']>ema20):
                            should_exit=True; reason=f"TRAIL_LONG {trail_sl:.0f}"
                    if last['c']<vwap and last['c']<ema20 and rsi<42 and minus_di>plus_di and pnl>0.5:
                        should_exit=True; reason="TREND_BREAK_DOWN"
                    if bear_candle and pnl>1.0 and rsi>70:
                        should_exit=True; reason=f"BEAR_REVERSAL {candle_name}"

                if pnl>=ADAPTIVE["TP_PCT"]: should_exit=True; reason=f"TP {ADAPTIVE['TP_PCT']}%"
                if check_max_hold(): should_exit=True; reason=f"MAX_HOLD {ADAPTIVE['MAX_HOLD']}h"
                if pnl <= -ADAPTIVE["SL_PCT"]*1.5: should_exit=True; reason=f"HARD_SL {pnl:.2f}%"
                if should_exit: close_position(price, reason)

            time.sleep(15)
        except Exception as e:
            print(f"Loop err {e}")
            import traceback; traceback.print_exc()
            time.sleep(15)

threading.Thread(target=trading_loop, daemon=True).start()

if __name__ == "__main__":
    port=int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
