from flask import Flask
import threading, time, os, requests
import ccxt
import pandas as pd
from datetime import datetime

app = Flask(__name__)

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"  # ใช้ 1m เพื่อให้ไว เหมาะกับสแกน 15 วิ
SCAN_INTERVAL = 15  # สแกนทุก 15 วินาที
DRY_RUN = True  # True = แค่ส่งสัญญาณ ไม่ได้เทรดจริง
SIGNAL_COOLDOWN = 300  # กันสแปม ส่งห่างกัน 5 นาที

# ========== TELEGRAM ==========
def send_tele(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[TELEGRAM SKIP] No token/chat")
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
        print(f"[TELEGRAM SENT] {r.status_code} - {msg[:80]}")
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

# ========== INDICATORS ==========
def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_adx(df, period=14):
    try:
        high = df['high']
        low = df['low']
        close = df['close']
        plus_dm = high.diff()
        minus_dm = low.diff() * -1
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
        dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di))
        adx = dx.rolling(period).mean()
        return adx.iloc[-1], plus_di.iloc[-1], minus_di.iloc[-1]
    except Exception as e:
        print(f"ADX calc error: {e}")
        return 25, 20, 20

# ========== BOT LOOP ==========
def bot_loop():
    exchange = ccxt.mexc({'enableRateLimit': True})
    print(f"🚀 Bot Starting - Scanning every {SCAN_INTERVAL}s | TF {TIMEFRAME} | Symbol {SYMBOL}")
    send_tele(f"🤖 <b>MEXC BTC Bot Started LIVE!</b>\n\nSymbol: {SYMBOL}\nTF: {TIMEFRAME}\nScan: Every {SCAN_INTERVAL} sec\nStrategy: RSI + ADX\nMode: {'DRY RUN' if DRY_RUN else 'LIVE TRADING'}\n\nTime: {datetime.now().strftime('%H:%M:%S')}")

    last_signal_time = 0

    while True:
        try:
            # Fetch OHLCV
            ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
            df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])
            df['rsi'] = calc_rsi(df['close'], 14)
            adx, plus_di, minus_di = calc_adx(df, 14)

            price = float(df['close'].iloc[-1])
            rsi = float(df['rsi'].iloc[-1])
            trend = "UP 📈" if plus_di > minus_di else "DOWN 📉"

            # Log to Render Logs
            log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] BTC {price:.2f} RSI {rsi:.1f} ADX {adx:.1f} {trend} +DI {plus_di:.1f} -DI {minus_di:.1f}"
            print(log_msg)

            # Signal Logic with Cooldown
            if time.time() - last_signal_time > SIGNAL_COOLDOWN:
                signal = None
                
                # LONG: ADX > 20 + Uptrend + RSI 35-60
                if adx > 20 and plus_di > minus_di and 35 < rsi < 60:
                    signal = f"🚀 <b>SIGNAL LONG</b>\n\n💰 BTC: ${price:,.2f}\n📊 RSI: {rsi:.1f}\n📈 ADX: {adx:.1f}\n🔀 Trend: {trend}\n⏰ TF: {TIMEFRAME}\n⏱ Scan: {SCAN_INTERVAL}s\n🕐 {datetime.now().strftime('%d/%m %H:%M:%S')}\n\n{'🧪 DRY RUN - ไม่ได้เปิดออเดอร์จริง' if DRY_RUN else '⚠️ LIVE ORDER'}"

                # SHORT: ADX > 20 + Downtrend + RSI 40-65
                elif adx > 20 and minus_di > plus_di and 40 < rsi < 65:
                    signal = f"🔻 <b>SIGNAL SHORT</b>\n\n💰 BTC: ${price:,.2f}\n📊 RSI: {rsi:.1f}\n📈 ADX: {adx:.1f}\n🔀 Trend: {trend}\n⏰ TF: {TIMEFRAME}\n⏱ Scan: {SCAN_INTERVAL}s\n🕐 {datetime.now().strftime('%d/%m %H:%M:%S')}\n\n{'🧪 DRY RUN - ไม่ได้เปิดออเดอร์จริง' if DRY_RUN else '⚠️ LIVE ORDER'}"

                if signal:
                    send_tele(signal)
                    last_signal_time = time.time()
                    print(f">>> SIGNAL SENT: {signal[:50]}")

        except Exception as e:
            print(f"[LOOP ERROR] {e}")

        time.sleep(SCAN_INTERVAL)

# Start bot in background thread
threading.Thread(target=bot_loop, daemon=True).start()

# ========== FLASK ROUTES ==========
@app.route('/')
def home():
    return f"""
    <html>
    <head><title>BTC Bot LIVE</title><meta http-equiv="refresh" content="15"></head>
    <body style="font-family: sans-serif; padding: 20px;">
        <h1>🤖 MEXC BTC Bot LIVE ✅</h1>
        <p><b>Symbol:</b> {SYMBOL} | <b>TF:</b> {TIMEFRAME} | <b>Scan:</b> Every {SCAN_INTERVAL}s</p>
        <p><b>Mode:</b> {'DRY RUN (ทดสอบ - แค่ส่งสัญญาณ)' if DRY_RUN else 'LIVE TRADING (เทรดจริง)'}</p>
        <p><b>Strategy:</b> RSI + ADX > 20 + Trend</p>
        <p><b>Cooldown:</b> {SIGNAL_COOLDOWN//60} min per signal</p>
        <hr>
        <p><a href='/health'>/health</a> | <a href='/test-telegram'>/test-telegram</a></p>
        <p>Check <b>Render > Logs</b> to see live scan every {SCAN_INTERVAL}s</p>
        <p>Auto refresh every 15s - Last: {datetime.now().strftime('%H:%M:%S')}</p>
    </body>
    </html>
    """

@app.route('/health')
def health():
    return "OK", 200

@app.route('/test-telegram')
def test_telegram():
    if not BOT_TOKEN or not CHAT_ID:
        return "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in Environment"
    send_tele(f"🧪 <b>Telegram OK - {SCAN_INTERVAL}s Bot LIVE!</b>\n\nBTC Bot scanning every {SCAN_INTERVAL}s\nReady for signals!")
    return f"Sent! Scanning every {SCAN_INTERVAL}s - Check Telegram"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
