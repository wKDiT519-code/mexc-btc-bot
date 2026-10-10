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
SCAN_INTERVAL = 15
COOLDOWN = 300
DRY_RUN = True

def send_tele(msg):
    if not BOT_TOKEN or not CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
        print(f"TELE SENT: {msg[:80]}")
    except Exception as e:
        print(f"TELE ERR {e}")

def calc_rsi(s, p=14):
    d = s.diff()
    g = d.where(d>0,0).ewm(alpha=1/p, min_periods=p).mean()
    l = (-d.where(d<0,0)).ewm(alpha=1/p, min_periods=p).mean()
    rs = g/l
    return 100 - (100/(1+rs))

def calc_adx(df, p=14):
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
        return float(adx.iloc[-1]), float(pdi.iloc[-1]), float(mdi.iloc[-1])
    except:
        return 25.0, 20.0, 20.0

def bot_loop():
    ex=ccxt.mexc({'enableRateLimit': True})
    print(f"STARTING {SCAN_INTERVAL}s SCAN {SYMBOL}")
    send_tele(f"<b>BTC Bot v4 LIVE - 15s</b>\n{SYMBOL} {TIMEFRAME}\nRSI+ADX Fixed\nScan every {SCAN_INTERVAL}s")
    last=0
    while True:
        try:
            ohlcv=ex.fetch_ohlcv(SYMBOL,TIMEFRAME,limit=100)
            df=pd.DataFrame(ohlcv,columns=['ts','open','high','low','close','vol'])
            df['rsi']=calc_rsi(df['close'])
            adx,pdi,mdi=calc_adx(df)
            price=float(df['close'].iloc[-1]); rsi=float(df['rsi'].iloc[-1])
            trend="UP" if pdi>mdi else "DOWN"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] BTC {price:.2f} RSI {rsi:.1f} ADX {adx:.1f} {trend} {pdi:.1f}/{mdi:.1f}")
            if time.time()-last>COOLDOWN:
                sig=None
                if adx>20 and pdi>mdi and 35<rsi<60:
                    sig=f"🚀 <b>LONG</b> BTC ${price:,.2f}\nRSI {rsi:.1f} ADX {adx:.1f} {trend}\n+DI {pdi:.1f} -DI {mdi:.1f}\nTF {TIMEFRAME} {SCAN_INTERVAL}s"
                elif adx>20 and mdi>pdi and 40<rsi<65:
                    sig=f"🔻 <b>SHORT</b> BTC ${price:,.2f}\nRSI {rsi:.1f} ADX {adx:.1f} {trend}\n+DI {pdi:.1f} -DI {mdi:.1f}\nTF {TIMEFRAME} {SCAN_INTERVAL}s"
                if sig:
                    send_tele(sig+f"\n{datetime.now().strftime('%H:%M:%S')} {'DRY' if DRY_RUN else 'LIVE'}")
                    last=time.time()
        except Exception as e:
            print(f"ERR {e}")
        time.sleep(SCAN_INTERVAL)

threading.Thread(target=bot_loop, daemon=True).start()

@app.route('/')
def home(): return f"<h1>Bot v4 LIVE {SCAN_INTERVAL}s OK</h1><p>Logs every {SCAN_INTERVAL}s</p>"
@app.route('/health')
def health(): return "OK",200
@app.route('/test-telegram')
def test(): send_tele("v4 OK - ADX Fixed 0-100"); return "Sent!"

if __name__=="__main__":
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
