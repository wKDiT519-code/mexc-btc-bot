"""
MEXC BTC Bot - DRY RUN + Telegram Notification
ส่งผลงานเข้า Telegram ทุกครั้งที่เจอสัญญาณ
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

# Telegram Config - จะใส่ใน Render Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=10)
        print(f"[Telegram] Sent: {msg[:50]}")
    except Exception as e:
        print(f"[Telegram Error] {e}")

@app.route('/')
def home():
    logs_html = "<br>".join(latest_log[-30:])
    sig_html = "<br>".join(signals[-15:]) if signals else "ยังไม่มีสัญญาณ - รอตลาด"
    tg_status = "✅ เชื่อมต่อแล้ว" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "❌ ยังไม่ได้ตั้งค่า TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
    return f"""
    <html><head><meta http-equiv="refresh" content="30"></head><body style="font-family: monospace; padding: 20px; max-width: 900px;">
    <h1>🤖 MEXC BTC Bot - DRY RUN + Telegram</h1>
    <p><b>Config:</b> Long Only + Risk 2% + TP 3.5 ATR + SL 2.2 ATR</p>
    <p><b>Backtest:</b> +4.73% / 3M | PF 2.02 | WR 63.6%</p>
    <p><b>Telegram:</b> {tg_status}</p>
    <p><b>Last update:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <hr>
    <h3>📈 สัญญาณล่าสุด (ส่งเข้า Telegram แล้ว):</h3>
    <div style="background: #fef3c7; padding: 15px; border-radius: 8px; white-space: pre-wrap;">{sig_html}</div>
    <hr>
    <h3>📋 Log ล่าสุด:</h3>
    <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; font-size: 12px; max-height: 400px; overflow-y: auto;">{logs_html}</div>
    <hr>
    <p>💡 วิธีตั้งค่า Telegram ดูใน README ด้านล่าง</p>
    </body></html>
    """

@app.route('/health')
def health():
    return "OK", 200

@app.route('/test-telegram')
def test_telegram():
    send_telegram("🧪 ทดสอบ Telegram จาก MEXC BTC Bot - ถ้าเห็นข้อความนี้แปลว่าเชื่อมต่อสำเร็จ!")
    return "Test message sent to Telegram! Check your Telegram."

def add_log(msg):
    global latest_log
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    latest_log.append(line)
    if len(latest_log) > 150:
        latest_log = latest_log[-150:]

class MexcBtcDryRunBot:
    def __init__(self):
        self.exchange = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        self.symbol = 'BTC/USDT:USDT'
        self.RISK_PCT = 0.02
        self.SL_ATR = 2.2
        self.TP_ATR = 3.5
        add_log(f"Bot Started - DRY RUN + Telegram Mode")
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            add_log(f"Telegram Connected - Chat ID {TELEGRAM_CHAT_ID}")
            send_telegram(f"🤖 *MEXC BTC Bot Started*\n\nConfig: Long Only | Risk 2% | TP 3.5 ATR\nMode: DRY RUN\n\nบอทเริ่มสแกน BTC แล้ว จะแจ้งเตือนเมื่อเจอสัญญาณ")
        else:
            add_log(f"Telegram NOT set - ใส่ TELEGRAM_BOT_TOKEN และ TELEGRAM_CHAT_ID ใน Render Env")

    def get_df(self, tf, limit=300):
        ohlcv = self.exchange.fetch_ohlcv(self.symbol, tf, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','vol'])
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        delta = df['close'].diff()
        gain = delta.where(delta>0,0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta<0,0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss.replace(0, 0.00001)
        df['rsi'] = 100 - (100/(1+rs))
        tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
        df['atr'] = tr.ewm(alpha=1/14, adjust=False).mean()
        df['vol_ema'] = df['vol'].ewm(span=20, adjust=False).mean()
        up = df['high'].diff()
        down = -df['low'].diff()
        plus_dm = pd.Series([u if (u>d and u>0) else 0 for u,d in zip(up,down)]).ewm(alpha=1/14, adjust=False).mean()
        minus_dm = pd.Series([d if (d>u and d>0) else 0 for u,d in zip(up,down)]).ewm(alpha=1/14, adjust=False).mean()
        tr14 = tr.ewm(alpha=1/14, adjust=False).mean()
        plus_di = 100*plus_dm/tr14
        minus_di = 100*minus_dm/tr14
        dx = 100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,float('nan'))
        df['adx'] = dx.ewm(alpha=1/14, adjust=False).mean().fillna(20)
        return df.dropna()

    def run_loop(self):
        position = None
        while True:
            try:
                df_4h = self.get_df('4h')
                df_15m = self.get_df('15m')
                big_up = df_4h.iloc[-1]['ema50'] > df_4h.iloc[-1]['ema200']
                last = df_15m.iloc[-1]
                prev = df_15m.iloc[-2]
                price = float(last['close'])

                if position:
                    if price > position['highest']:
                        position['highest'] = price
                    sl_hit = price <= position['sl']
                    tp_hit = price >= position['entry'] + position['atr']*self.TP_ATR
                    trailing_hit = False
                    if position['highest'] - position['entry'] > position['atr']*1.5:
                        if price < position['highest'] - position['atr']*1.2:
                            trailing_hit = True
                    if sl_hit or tp_hit or trailing_hit:
                        pnl_pct = (price - position['entry'])/position['entry']*100
                        reason = 'SL' if sl_hit else ('TP 3.5 ATR ✅' if tp_hit else 'Trailing ✅')
                        msg = f"CLOSE {reason} @ {price:.1f} Entry {position['entry']:.1f} PnL {pnl_pct:+.2f}%"
                        add_log(msg)
                        signals.append(msg)
                        
                        # ส่ง Telegram
                        tg_msg = f"{'🔴' if pnl_pct < 0 else '🟢'} *ปิดโพซิชั่น* {reason}\n\nEntry: ${position['entry']:.1f}\nExit: ${price:.1f}\nPnL: {pnl_pct:+.2f}%\nTime: {datetime.now().strftime('%H:%M')}"
                        send_telegram(tg_msg)
                        
                        position = None
                    else:
                        add_log(f"HOLD Entry {position['entry']:.1f} Now {price:.1f} PnL {(price-position['entry'])/position['entry']*100:+.2f}%")
                        time.sleep(30)
                        continue

                if not big_up:
                    add_log(f"Trend 4H DOWN - ข้าม BTC {price:.0f}")
                    time.sleep(120)
                    continue
                if last['adx'] < 23:
                    add_log(f"ADX {last['adx']:.1f} อ่อน ข้าม BTC {price:.0f} RSI {last['rsi']:.1f}")
                    time.sleep(60)
                    continue
                if last['vol'] < last['vol_ema']*0.7:
                    add_log(f"Vol น้อย ข้าม BTC {price:.0f}")
                    time.sleep(60)
                    continue

                if 40 <= last['rsi'] <= 54 and last['rsi'] > prev['rsi']:
                    sl_price = price - float(last['atr'])*self.SL_ATR
                    tp_price = price + float(last['atr'])*self.TP_ATR
                    msg = f">>> SIGNAL LONG @ {price:.1f} RSI {last['rsi']:.1f} ADX {last['adx']:.1f} SL {sl_price:.1f} TP {tp_price:.1f}"
                    add_log(msg)
                    signals.append(msg)
                    
                    # ส่ง Telegram สัญญาณเข้า
                    tg_msg = f"🚀 *SIGNAL LONG* 🚀\n\nPrice: ${price:.1f}\nRSI: {last['rsi']:.1f} | ADX: {last['adx']:.1f}\nTrend 4H: UP ✅\n\nSL: ${sl_price:.1f} ({self.SL_ATR} ATR)\nTP: ${tp_price:.1f} ({self.TP_ATR} ATR)\nRisk: 2%\n\nMode: DRY RUN"
                    send_telegram(tg_msg)
                    
                    position = {'entry':price,'sl':sl_price,'highest':price,'atr':float(last['atr'])}
                else:
                    add_log(f"รอ BTC {price:.0f} RSI {last['rsi']:.1f} ADX {last['adx']:.1f} Trend UP")
                time.sleep(60)
            except Exception as e:
                add_log(f"Error: {e}")
                time.sleep(10)

def start_bot():
    bot = MexcBtcDryRunBot()
    bot.run_loop()

if __name__ == "__main__":
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
