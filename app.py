from flask import Flask
import threading, time, os, requests
import ccxt
import pandas as pd
from datetime import datetime

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_tele(msg):
    try:
        if not BOT_TOKEN or not CHAT_ID:
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except:
        pass

def bot_loop():
    print("Bot v3 Starting - 15s scan")
    ex = ccxt.mexc({'enableRateLimit': True})
    try:
        send_tele("Bot v3 FIXED Starting - 15s scan")
    except:
        pass
    while True:
        try:
            ohlcv = ex.fetch_ohlcv("BTC/USDT", "1m", limit=50)
            df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])
            price = df['close'].iloc[-1]
            print(f"[{datetime.now().strftime('%H:%M:%S')}] BTC {price:.2f}")
        except Exception as e:
            print(f"error {e}")
        time.sleep(15)

threading.Thread(target=bot_loop, daemon=True).start()

@app.route('/')
def home():
    return "<h1>Bot v3 LIVE 15s</h1><p><a href='/test-telegram'>test-telegram</a></p>"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/test-telegram')
def test_telegram():
    send_tele("v3 OK - 15s")
    return "Sent!"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
