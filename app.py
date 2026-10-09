"""
MEXC BTC Bot - FINAL FIX for Render Free
แก้ปัญหา Deploy failed status 2
"""
import ccxt
import pandas as pd
import time
from datetime import datetime
import os
import threading
from flask import Flask
import requests

app = Flask(__name__)
latest_log = []
signals = []

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        return True
    except:
        return False

@app.route('/')
def home():
    logs_html = "<br>".join(latest_log[-30:]) or "กำลังเริ่ม..."
    sig_html = "<br>".join(signals[-10:]) if signals else "ยังไม่มีสัญญาณ - บอทกำลังสแกน"
    tg = "✅ ต่อแล้ว" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "❌ ยังไม่ได้ใส่ Token/Chat ID (ยังรันได้ แต่ไม่ส่ง Telegram)"
    return f"""
    <h1>🤖 MEXC BTC Bot Running ✅</h1>
    <p><b>Config:</b> Long Only Risk 2% TP 3.5 ATR SL 2.2 ATR</p>
    <p><b>Backtest:</b> +4.73% / 3M | PF 2.02</p>
    <p><b>Telegram:</b> {tg}</p>
    <p><b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} GMT+7</p>
    <hr><h3>📈 สัญญาณ</h3><div style="background:#fef3c7;padding:10px">{sig_html}</div>
    <hr><h3>📋 Log</h3><div style="background:#f3f4f6;padding:10px;font-size:12px">{logs_html}</div>
    <hr><p>Endpoints: <a href="/health">/health</a> | <a href="/test-telegram">/test-telegram</a></p>
    """

@app.route('/health')
def health():
    return "OK", 200

@app.route('/test-telegram')
def test_telegram():
    ok = send_telegram("🧪 ทดสอบ Telegram จาก MEXC BTC Bot - สำเร็จ!")
    return f"Telegram test: {'Sent ✅' if ok else 'Failed ❌ - Check Token/Chat ID'}"

def add_log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    latest_log.append(line)
    if len(latest_log) > 100:
        latest_log.pop(0)

def get_bot():
    return ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

def get_df(exchange, tf):
    ohlcv = exchange.fetch_ohlcv('BTC/USDT:USDT', tf, limit=300)
    df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','vol'])
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    delta = df['close'].diff()
    gain = delta.where(delta>0,0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta<0,0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100/(1+gain/loss.replace(0,0.00001)))
    tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.ewm(alpha=1/14, adjust=False).mean()
    df['vol_ema'] = df['vol'].ewm(span=20, adjust=False).mean()
    up = df['high'].diff(); down = -df['low'].diff()
    plus_dm = pd.Series([u if (u>d and u>0) else 0 for u,d in zip(up,down)]).ewm(alpha=1/14, adjust=False).mean()
    minus_dm = pd.Series([d if (d>u and d>0) else 0 for u,d in zip(up,down)]).ewm(alpha=1/14, adjust=False).mean()
    tr14 = tr.ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100*plus_dm/tr14; minus_di = 100*minus_dm/tr14
    dx = 100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,float('nan'))
    df['adx'] = dx.ewm(alpha=1/14, adjust=False).mean().fillna(20)
    return df.dropna()

def run_bot():
    add_log("Bot Starting - DRY RUN - No API Key needed for scanning")
    if TELEGRAM_BOT_TOKEN:
        send_telegram("🤖 *MEXC BTC Bot Started*\nConfig: Long Only Risk 2% TP 3.5 ATR\nMode: DRY RUN - Scanning BTC...")
    exchange = get_bot()
    position = None
    while True:
        try:
            df_4h = get_df(exchange, '4h')
            df_15m = get_df(exchange, '15m')
            last = df_15m.iloc[-1]; prev = df_15m.iloc[-2]
            price = float(last['close'])
            big_up = df_4h.iloc[-1]['ema50'] > df_4h.iloc[-1]['ema200']

            if position:
                if price > position['highest']: position['highest'] = price
                sl_hit = price <= position['sl']
                tp_hit = price >= position['entry'] + position['atr']*3.5
                trail = position['highest'] - position['entry'] > position['atr']*1.5 and price < position['highest'] - position['atr']*1.2
                if sl_hit or tp_hit or trail:
                    pnl = (price-position['entry'])/position['entry']*100
                    reason = 'SL' if sl_hit else ('TP 3.5 ATR' if tp_hit else 'Trailing')
                    msg = f"CLOSE {reason} @ {price:.1f} PnL {pnl:+.2f}%"
                    add_log(msg); signals.append(msg)
                    send_telegram(f"{'🔴' if pnl<0 else '🟢'} *{reason}* Exit ${price:.1f} PnL {pnl:+.2f}%")
                    position = None
                else:
                    add_log(f"HOLD Entry {position['entry']:.1f} Now {price:.1f} PnL {(price-position['entry'])/position['entry']*100:+.2f}%")
                    time.sleep(30); continue

            if not big_up:
                add_log(f"Trend DOWN BTC {price:.0f} - Skip"); time.sleep(120); continue
            if last['adx'] < 23:
                add_log(f"ADX {last['adx']:.1f} weak BTC {price:.0f} RSI {last['rsi']:.1f}"); time.sleep(60); continue
            if last['vol'] < last['vol_ema']*0.7:
                add_log(f"Vol low BTC {price:.0f}"); time.sleep(60); continue

            if 40 <= last['rsi'] <= 54 and last['rsi'] > prev['rsi']:
                sl = price - float(last['atr'])*2.2
                tp = price + float(last['atr'])*3.5
                msg = f"SIGNAL LONG @ {price:.1f} RSI {last['rsi']:.1f} ADX {last['adx']:.1f} SL {sl:.1f} TP {tp:.1f}"
                add_log(f">>> {msg}"); signals.append(msg)
                send_telegram(f"🚀 *SIGNAL LONG*\nPrice ${price:.1f}\nRSI {last['rsi']:.1f} ADX {last['adx']:.1f}\nSL ${sl:.1f} TP ${tp:.1f}\nRisk 2%")
                position = {'entry':price,'sl':sl,'highest':price,'atr':float(last['atr'])}
            else:
                add_log(f"Wait BTC {price:.0f} RSI {last['rsi']:.1f} ADX {last['adx']:.1f} Trend UP")
            time.sleep(60)
        except Exception as e:
            add_log(f"Error {e}"); time.sleep(10)

def start():
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    add_log(f"Web server starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == "__main__":
    start()
