"""
MEXC BTC Futures Bot - FINAL VERSION
Config: Long Only + Risk 2% + SL 2.2 ATR + TP 3.5 ATR + 4H Trend Filter
Backtest: +4.73% / 3M | PF 2.02 | WR 63.6% | DD 3.12%

วิธีใช้:
1. pip install ccxt pandas
2. ใส่ API KEY ในบรรทัดล่างสุด
3. รัน python mexc_btc_final_bot.py
"""

import ccxt
import pandas as pd
import time
from datetime import datetime
import os

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
        print(f" MEXC BTC BOT FINAL | Long Only | Risk 2% | TP 3.5 ATR")
        print(f" Mode: {'DRY RUN (ทดสอบ ไม่เสียเงิน)' if dry_run else '*** LIVE เทรดจริง ***'}")
        print(f" Symbol: {self.symbol} | Leverage: {self.leverage}x")
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

    def setup(self):
        try:
            self.exchange.set_leverage(self.leverage, self.symbol)
            print(f"[Setup] Leverage {self.leverage}x OK")
        except Exception as e:
            print(f"[Setup] Leverage set skip: {e}")
        try:
            bal = self.exchange.fetch_balance()
            free = bal['USDT']['free'] if 'USDT' in bal else bal.get('USDT',{}).get('free',0)
            print(f"[Setup] Balance USDT Free: {free}")
        except Exception as e:
            print(f"[Setup] Balance check: {e}")

    def run(self):
        self.setup()
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

                # --- จัดการโพซิชั่นที่มีอยู่ ---
                if position:
                    if price > position['highest']:
                        position['highest'] = price
                    
                    sl_hit = price <= position['sl']
                    tp_hit = price >= position['entry'] + position['atr']*self.TP_ATR
                    trailing_hit = False
                    # trailing เริ่มทำงานเมื่อกำไรเกิน 1.5 ATR
                    if position['highest'] - position['entry'] > position['atr']*1.5:
                        if price < position['highest'] - position['atr']*1.2:
                            trailing_hit = True
                    
                    if sl_hit or tp_hit or trailing_hit:
                        pnl = (price - position['entry'])*position['qty']
                        reason = 'SL' if sl_hit else ('TP 3.5 ATR' if tp_hit else 'Trailing')
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] CLOSE {reason} @ {price:.1f} PnL ${pnl:+.2f}")
                        
                        if not self.dry_run:
                            try:
                                # ปิดโพซิชั่น
                                self.exchange.create_market_order(self.symbol, 'sell', position['qty'])
                            except Exception as e:
                                print(f"Close error: {e}")

                        if pnl < 0:
                            consecutive_losses += 1
                        else:
                            consecutive_losses = 0
                        
                        position = None

                        # กฎหยุดเมื่อเสีย 3 ไม้ติด
                        if consecutive_losses >= 3:
                            print(f"!!! เสีย 3 ไม้ติด หยุดพัก 1 ชั่วโมง !!!")
                            time.sleep(3600)
                            consecutive_losses = 0
                            continue
                    else:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] HOLD Entry {position['entry']:.1f} Now {price:.1f} High {position['highest']:.1f} PnL ${ (price-position['entry'])*position['qty'] :+.2f}")
                        time.sleep(30)
                        continue

                # --- หาสัญญาณใหม่ ---
                if not big_up:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Big Trend DOWN (4H) - Long Only ข้าม")
                    time.sleep(120)
                    continue

                if last['adx'] < 23:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ADX {last['adx']:.1f} อ่อน ข้าม")
                    time.sleep(60)
                    continue

                if last['vol'] < last['vol_ema']*0.7:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Volume น้อย ข้าม")
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
                    if sl_dist == 0:
                        time.sleep(30)
                        continue

                    qty = min(balance*self.RISK_PCT/sl_dist, balance*0.4/price)
                    if qty*price < 20:
                        print(f"Qty น้อยเกินไป ข้าม")
                        time.sleep(60)
                        continue

                    sl_price = price - sl_dist
                    tp_price = price + float(last['atr'])*self.TP_ATR

                    print(f"\n>>> SIGNAL LONG @ {price:.1f} RSI {last['rsi']:.1f} ADX {last['adx']:.1f}")
                    print(f"    Qty {qty:.4f} BTC (~${qty*price:.1f}) | SL {sl_price:.1f} | TP {tp_price:.1f} | Risk {self.RISK_PCT*100}%")

                    if not self.dry_run:
                        try:
                            order = self.exchange.create_market_order(self.symbol, 'buy', qty)
                            print(f"    Order OK: {order['id']}")
                            # ตั้ง SL
                            try:
                                self.exchange.create_order(self.symbol, 'STOP_MARKET', 'sell', qty, None, {'stopPrice': sl_price})
                                print(f"    SL Order set @ {sl_price:.1f}")
                            except Exception as e:
                                print(f"    SL set error: {e}")
                        except Exception as e:
                            print(f"    Open error: {e}")
                            time.sleep(10)
                            continue
                    else:
                        print(f"    (DRY RUN - ไม่ส่งออเดอร์จริง)")

                    position = {
                        'side': 'long',
                        'entry': price,
                        'qty': qty,
                        'sl': sl_price,
                        'highest': price,
                        'atr': float(last['atr']),
                        'entry_time': datetime.now()
                    }
                
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] รอสัญญาณ BTC {price:.0f} RSI {last['rsi']:.1f} ADX {last['adx']:.1f} Trend {'UP' if big_up else 'DOWN'}")

                time.sleep(60)

            except Exception as e:
                print(f"[Error] {e}")
                time.sleep(10)


if __name__ == "__main__":
    # ========== ใส่ API KEY ของคุณตรงนี้ ==========
    API_KEY = os.getenv("MEXC_API_KEY", "ใส่_api_key_ตรงนี้")
    API_SECRET = os.getenv("MEXC_API_SECRET", "ใส่_api_secret_ตรงนี้")
    
    # True = ทดสอบ, False = เทรดจริง
    DRY_RUN = True  

    if API_KEY == "ใส่_api_key_ตรงนี้":
        print("!!! กรุณาใส่ API KEY ก่อนรัน !!!")
        print("ไปที่ MEXC > Futures > API Management สร้าง Key ที่มีสิทธิ์ Futures Trading")
    else:
        bot = MexcBtcFinalBot(API_KEY, API_SECRET, dry_run=DRY_RUN)
        bot.run()
