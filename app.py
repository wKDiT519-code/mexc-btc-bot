from flask import Flask
import threading, time, os, requests
import ccxt
import pandas as pd
from datetime import datetime

app = Flask(__name__)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "BTC/USDT"
TIMEFRAME = "15m"
SCAN_INTERVAL = 60
COOLDOWN = 900
DRY_RUN = True

# ตั้งค่า ATR Multiplier - แก้ตรงนี้ได้
ATR_SL_MULT = 1.5
ATR_TP1_MULT = 1.0
ATR_TP2_MULT = 2.0
ATR_TP3_MULT = 3.0

def send_tele(msg):
    if not BOT_TOKEN or not CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
        print(f"SENT OK")
    except Exception as e:
        print(f"TELE ERR {e}")

def calc_rsi(s,p=14):
    d=s.diff(); g=d.where(d>0,0).ewm(alpha=1/p,min_periods=p).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p,min_periods=p).mean()
    return 100-(100/(1+g/l))

def calc_adx_atr(df,p=14):
    try:
        h=df['high']; l=df['low']; c=df['close']
        up=h.diff(); down=l.shift(1)-l
        pdm=pd.Series(0.0,index=df.index); mdm=pd.Series(0.0,index=df.index)
        pdm[(up>down)&(up>0)]=up; mdm[(down>up)&(down>0)]=down
        tr=pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
        atr=tr.ewm(alpha=1/p,min_periods=p).mean()
        pdi=100*(pdm.ewm(alpha=1/p,min_periods=p).mean()/atr)
        mdi=100*(mdm.ewm(alpha=1/p,min_periods=p).mean()/atr)
        dx=100*(((pdi-mdi).abs()/(pdi+mdi).replace(0,1)).fillna(0))
        adx=dx.ewm(alpha=1/p,min_periods=p).mean()
        return float(adx.iloc[-1]), float(pdi.iloc[-1]), float(mdi.iloc[-1]), float(atr.iloc[-1])
    except Exception as e:
        print(f"ADX ERR {e}")
        return 25.0,20.0,20.0,400.0

def calc_tp_sl_atr(price, side, atr):
    if side=="LONG":
        sl=price - atr*ATR_SL_MULT
        tp1=price + atr*ATR_TP1_MULT
        tp2=price + atr*ATR_TP2_MULT
        tp3=price + atr*ATR_TP3_MULT
    else:
        sl=price + atr*ATR_SL_MULT
        tp1=price - atr*ATR_TP1_MULT
        tp2=price - atr*ATR_TP2_MULT
        tp3=price - atr*ATR_TP3_MULT
    return tp1,tp2,tp3,sl

def format_signal(side, price, rsi, adx, trend, pdi, mdi, atr):
    icon = "🚀" if side=="LONG" else "🔻"
    trend_icon = "📈" if trend=="UP" else "📉"
    tp1,tp2,tp3,sl = calc_tp_sl_atr(price, side, atr)
    
    def pct(target): return ((target-price)/price*100)

    return (
        f"{icon} SIGNAL {side}\n\n"
        f"💰 BTC: ${price:,.2f}\n"
        f"📊 RSI: {rsi:.1f}\n"
        f"📈 ADX: {adx:.1f}\n"
        f"📏 ATR: {atr:.2f}\n"
        f"🔀 Trend: {trend} {trend_icon}\n"
        f"⏰ TF: {TIMEFRAME}\n"
        f"⏱ Scan: {SCAN_INTERVAL}s\n"
        f"🕐 {datetime.now().strftime('%d/%m %H:%M:%S')}\n\n"
        f"🎯 TP1: ${tp1:,.2f} ({pct(tp1):+.2f}% | x{ATR_TP1_MULT})\n"
        f"🎯 TP2: ${tp2:,.2f} ({pct(tp2):+.2f}% | x{ATR_TP2_MULT})\n"
        f"🎯 TP3: ${tp3:,.2f} ({pct(tp3):+.2f}% | x{ATR_TP3_MULT})\n"
        f"🛑 SL: ${sl:,.2f} ({pct(sl):+.2f}% | x{ATR_SL_MULT})\n"
        f"📐 RR: 1:{ATR_TP1_MULT/ATR_SL_MULT:.1f} / 1:{ATR_TP2_MULT/ATR_SL_MULT:.1f} / 1:{ATR_TP3_MULT/ATR_SL_MULT:.1f}\n\n"
        f"{'🧪 DRY RUN - ไม่ได้เปิดออเดอร์จริง' if DRY_RUN else '⚡ LIVE TRADING'}"
    )

def bot_loop():
    ex=ccxt.mexc({'enableRateLimit':True})
    send_tele(f"<b>Bot v8 ATR TP/SL LIVE!</b>\nTF {TIMEFRAME}\nATR SL x{ATR_SL_MULT} TP x{ATR_TP1_MULT}/{ATR_TP2_MULT}/{ATR_TP3_MULT}")
    last=0
    while True:
        try:
            ohlcv=ex.fetch_ohlcv(SYMBOL,TIMEFRAME,limit=100)
            df=pd.DataFrame(ohlcv,columns=['ts','open','high','low','close','vol'])
            df['rsi']=calc_rsi(df['close'])
            adx,pdi,mdi,atr=calc_adx_atr(df)
            price=float(df['close'].iloc[-1]); rsi=float(df['rsi'].iloc[-1])
            trend="DOWN" if mdi>pdi else "UP"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {price:.2f} RSI {rsi:.1f} ADX {adx:.1f} ATR {atr:.1f} {trend}")
            if time.time()-last>COOLDOWN:
                sig=None
                if adx>20 and pdi>mdi and 35<rsi<60:
                    sig=format_signal("LONG",price,rsi,adx,trend,pdi,mdi,atr)
                elif adx>20 and mdi>pdi and 40<rsi<65:
                    sig=format_signal("SHORT",price,rsi,adx,trend,pdi,mdi,atr)
                if sig:
                    send_tele(sig)
                    last=time.time()
        except Exception as e: print(f"ERR {e}")
        time.sleep(SCAN_INTERVAL)

threading.Thread(target=bot_loop,daemon=True).start()

@app.route('/')
def home(): return f"<h1>Bot v8 ATR TP/SL TF {TIMEFRAME} LIVE</h1>"
@app.route('/health')
def health(): return "OK",200
@app.route('/test-telegram')
def test():
    send_tele(format_signal("SHORT",82655.27,49.3,28.5,"DOWN",18.2,25.4,452.3))
    return "Sent ATR TP/SL format!"

if __name__=="__main__":
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
