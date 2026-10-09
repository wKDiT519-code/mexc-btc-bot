"""
MEXC BTC Bot - FREE TIER VERSION for Render.com
รันเป็น Web Service แทน Worker เพื่อใช้ฟรีได้
มีเว็บเล็กๆ ให้ UptimeRobot มา ping ไม่ให้หลับ
"""
import ccxt
import pandas as pd
import time
from datetime import datetime
import os
import threading
from flask import Flask

app = Flask(__name__)

# หน้าเว็บไว้ให้ UptimeRobot ping
@app.route('/')
def home():
    return f"""
    <h1>🤖 MEXC BTC Bot is Running</h1>
    <p>Config: Long Only + Risk 2% + TP 3.5 ATR</p>
    <p>Last check: {datetime.now()}</p>
    <p>Status: OK - Bot scanning every 60s</p>
    <p>Backtest: +4.73% / 3M | PF 2.02 | WR 63.6%</p>
    """

@app.route('/health')
def health():
    return "OK", 200

class MexcBtcFinalBot:
    def __init__(self, api_key, api_secret, dry_run=True):
        self.exchange = ccxt.mexc({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        self.symbol = 'BTC/USDT:USDT'
        self.dry_run = dry_run
        self.RISK_PCT = 0.02
        self.SL_ATR = 2.2
        self.TP_ATR = 3.5
        self.leverage = 5
        print(f"==================================================")
        print(f" MEXC BTC BOT FREE | Long Only | Risk 2% | TP 3.5 ATR")
        print(f" Mode: {'DRY RUN' if dry_run else 'LIVE'}")
        print(f"==================================================")

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
        consecutive_losses = 0
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
                        pnl = (price - position['entry'])*position['qty']
                        reason = 'SL' if sl_hit else ('TP 3.5 ATR' if tp_hit else 'Trailing')
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] CLOSE {reason} @ {price:.1f} PnL ${pnl:+.2f}")
                        if not self.dry_run:
                            try:
                                self.exchange.create_market_order(self.symbol, 'sell', position['qty'])
                            except Exception as e:
                                print(f"Close error: {e}")
                        consecutive_losses = consecutive_losses + 1 if pnl < 0 else 0
                        position = None
                        if consecutive_losses >= 3:
                            print(f"!!! เสีย 3 ไม้ติด หยุด 1 ชม.")
                            time.sleep(3600)
                            consecutive_losses = 0
                            continue
                    else:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] HOLD Entry {position['entry']:.1f} Now {price:.1f} PnL ${(price-position['entry'])*position['qty']:+.2f}")
                        time.sleep(30)
                        continue

                if not big_up:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Trend DOWN - ข้าม")
                    time.sleep(120)
                    continue
                if last['adx'] < 23 or last['vol'] < last['vol_ema']*0.7:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ADX {last['adx']:.1f} / Vol น้อย ข้าม")
                    time.sleep(60)
                    continue

                if 40 <= last['rsi'] <= 54 and last['rsi'] > prev['rsi']:
                    balance = 10000
                    if not self.dry_run:
                        try:
                            bal = self.exchange.fetch_balance()
                            balance = bal['USDT']['free']
                        except:
                            balance = 10000
                    sl_dist = float(last['atr'])*self.SL_ATR
                    qty = min(balance*self.RISK_PCT/sl_dist, balance*0.4/price) if sl_dist>0 else 0
                    if qty*price < 20:
                        time.sleep(60)
                        continue
                    sl_price = price - sl_dist
                    tp_price = price + float(last['atr'])*self.TP_ATR
                    print(f"\n>>> SIGNAL LONG @ {price:.1f} RSI {last['rsi']:.1f} ADX {last['adx']:.1f} Qty {qty:.4f} SL {sl_price:.1f} TP {tp_price:.1f}")
                    if not self.dry_run:
                        try:
                            self.exchange.create_market_order(self.symbol, 'buy', qty)
                        except Exception as e:
                            print(f"Open error: {e}")
                            time.sleep(10)
                            continue
                    position = {'side':'long','entry':price,'qty':qty,'sl':sl_price,'highest':price,'atr':float(last['atr']),'entry_time':datetime.now()}
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] รอ BTC {price:.0f} RSI {last['rsi']:.1f} ADX {last['adx']:.1f}")
                time.sleep(60)
            except Exception as e:
                print(f"[Error] {e}")
                time.sleep(10)

def start_bot():
    API_KEY = os.getenv("MEXC_API_KEY", "ใส่_api_key_ตรงนี้")
    API_SECRET = os.getenv("MEXC_API_SECRET", "ใส่_api_secret_ตรงนี้")
    DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"
    
    if API_KEY == "ใส่_api_key_ตรงนี้":
        print("!!! ยังไม่ได้ใส่ API KEY - รอใส่ใน Environment Variables !!!")
        # รันแบบไม่มี API ก็ให้เว็บติดก่อน
        while True:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for API KEY in Env Vars...")
            time.sleep(60)
    else:
        bot = MexcBtcFinalBot(API_KEY, API_SECRET, dry_run=DRY_RUN)
        bot.run_loop()

if __name__ == "__main__":
    # รันบอทใน thread แยก
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    # รันเว็บเซิร์ฟเวอร์ (Render จะตรวจ port 10000)
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting web server on port {port} for free tier keep-alive...")
    app.run(host='0.0.0.0', port=port)
