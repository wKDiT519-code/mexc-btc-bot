from flask import Flask
import threading, time, os, requests
import ccxt
import pandas as pd
from datetime import datetime

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"
SCAN_INTERVAL = 15
DRY_RUN = True
SIGNAL_COOLDOWN = 300

def send_tele(msg):
    if not BOT_TOKEN or not CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except: pass

def calc_rsi(s, p=14):
    d = s.diff()
    gain = d.where(d>0,0).ewm(alpha=1/p, min_periods=p).mean()
    loss = (-d.where(d<0,0)).ewm(alpha=1/p, min_periods=p).mean()
    rs = gain/loss
    return 100 - (100/(1+rs))

def calc_adx(df, p=14):
    try:
        h = df['high']; l = df['low']; c = df['close']
        up = h.diff()
        down = l.shift(1) - l
        # +DM and -DM
        plus_dm = pd.Series(0.0, index=df.index)
        minus_dm = pd.Series(0.0, index=df.index)
        plus_dm[(up > down) & (up > 0)] = up
        minus_dm[(down > up) & (down > 0)] = down
        
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        atr = tr.ewm(alpha=1/p, min_periods=p).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1/p, min_periods=p).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1/p, min_periods=p).mean() / atr)
        
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)).fillna(0)
        adx = dx.ewm(alpha=1/p, min_periods=p).mean()
        return adx.iloc[-1], plus_di.iloc[-1], minus_di.iloc[-1]
    except:
        return 25.0, 20.0, 20.0

def bot_loop():
    ex = ccxt.mexc({'enableRateLimit': True})
    send_tele(f"🤖 <b>BTC Bot v2 FIXED - 15s LIVE!</b>\n{SYMBOL} {TIMEFRAME} ADX Fixed")
    last = 0
    while True:
        try:
            ohlcv = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
            df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])
            df['rsi'] = calc_rsi(df['close'])
            adx, plus_di, minus_di = calc_adx(df)
            price = float(df['close'].iloc[-1])
            rsi = float(df['rsi'].iloc[-1])
            trend = "UP 📈" if plus_di > minus_di else "DOWN 📉"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] BTC {price:.2f} RSI {rsi:.1f} ADX {adx:.1f} {trend}")
            
            if time.time() - last > SIGNAL_COOLDOWN:
                sig = None
                if adx > 20 and plus_di > minus_di and 35 < rsi < 60:
                    sig = f"🚀 <b>LONG</b> BTC ${price:,.2f}\nRSI {rsi:.1f} ADX {adx:.1f} {trend}\n+DI {plus_di:.1f} > -DI {minus_di:.1f}\nTF {TIMEFRAME} {SCAN_INTERVAL}s"
                elif adx > 20 and minus_di > plus_di and 40 < rsi < 65:
                    sig = f"🔻 <b>SHORT</b> BTC ${price:,.2f}\nRSI {rsi:.1f} ADX {adx:.1f} {trend}\n+DI {plus_di:.1f} < -DI {minus_di:.1f}\nTF {TIMEFRAME} {SCAN_INTERVAL}s"
                if sig:
                    send_tele(sig + f"\n🕐 {datetime.now().strftime('%H:%M:%S')}\n{'🧪 DRY RUN' if DRY_RUN else 'LIVE'}")
                    last = time.time()
        except Exception as e:
            print(f"Error {e}")
        time.sleep(SCAN_INTERVAL)

threading.Thread(target=bot_loop, daemon=True).start()

@app.route('/')
def home(): return f"<h1>🤖 BTC Bot FIXED v2 - {SCAN_INTERVAL}s ✅</h1>"
@app.route('/health')
def health(): return "OK",200
@app.route('/test-telegram')
def test_telegram():
    send_tele(f"🧪 FIXED v2 OK - ADX now 0-100")
    return "Sent!"
