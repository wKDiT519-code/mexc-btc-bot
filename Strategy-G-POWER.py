
"""
G_POWER - รวมร่างสุดยอดสำหรับ BTC
ฐาน NEW 12/26/200 + D SMC + F Liquidity + MFI/OBV

โครงสร้าง CEO:
1.จุดกลับตัว+เทรนด์+โมเมนตัม+SL/TP
2.Management Port
"""

import pandas as pd
import pandas_ta as ta

class Strategy_G_Power:
    def __init__(self):
        self.name = "G_POWER - BTC Ultimate"
        self.config = {
            # NEW 12/26/200 Base
            "ema_fast": 12,
            "ema_slow": 26,
            "ema_trend": 200,
            "rsi_fast": 12,
            "rsi_slow": 26,
            "rsi_trend": 200,
            # D SMC + F Liquidity
            "sweep_lookback": 20,
            "fractal_period": 5,
            # Momentum
            "mfi_period": 14,
            "obv_fast": 3,
            "obv_slow": 9,
            "adx_min": 20,
            # SL/TP - NEW Base
            "sl_pct": 0.034,
            "tp_pct": 0.18,
            "sl_atr_mult": 1.5,
            # Management
            "risk_per_trade": 0.02,
            "max_positions": 2,
            "cooldown_after_2_losses": 16,  # 4 ชม
        }
        self.loss_streak = 0
        self.cooldown = 0
        self.positions = []
    
    def add_indicators(self, df):
        # === NEW 12/26/200 Base ===
        df['ema12'] = ta.ema(df['close'], length=12)
        df['ema26'] = ta.ema(df['close'], length=26)
        df['ema200'] = ta.ema(df['close'], length=200)
        df['ema200_slope'] = df['ema200'].diff(5)
        
        df['rsi12'] = ta.rsi(df['close'], length=12)
        df['rsi26'] = ta.rsi(df['close'], length=26)
        df['rsi200'] = ta.rsi(df['close'], length=200)
        
        # === D + F: Fractal + Sweep ===
        df['fractal_high'] = df['high'].rolling(5, center=True).max() == df['high']
        df['fractal_low'] = df['low'].rolling(5, center=True).min() == df['low']
        
        df['high_20'] = df['high'].rolling(20).max()
        df['low_20'] = df['low'].rolling(20).min()
        df['sweep_high'] = (df['high'] > df['high_20'].shift(1)) & (df['close'] < df['high_20'].shift(1))
        df['sweep_low'] = (df['low'] < df['low_20'].shift(1)) & (df['close'] > df['low_20'].shift(1))
        
        # BOS
        df['swing_high'] = df['high'].where(df['fractal_high'])
        df['swing_low'] = df['low'].where(df['fractal_low'])
        df['last_swing_high'] = df['swing_high'].ffill()
        df['last_swing_low'] = df['swing_low'].ffill()
        
        # SuperTrend for trend confirm
        st = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3.0)
        df['supertrend_dir'] = st['SUPERTd_10_3.0']
        
        # === Momentum: MFI + OBV + ADX ===
        df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'], length=14)
        df['obv'] = ta.obv(df['close'], df['volume'])
        df['obv_ema3'] = ta.ema(df['obv'], 3)
        df['obv_ema9'] = ta.ema(df['obv'], 9)
        
        df['adx'] = ta.adx(df['high'], df['low'], df['close'], length=14)['ADX_14']
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['vol_avg'] = df['volume'].rolling(20).mean()
        
        return df
    
    def check_reversal(self, prev, curr):
        """
        จุดกลับตัว G_POWER: ต้องครบ
        - NEW: EMA12 ตัด 26 + RSI12 ตัด 26
        - F: Sweep Low/High (กรองหลอก BTC)
        - D: Fractal ยืนยัน
        """
        # NEW Base
        ema_cross_up = prev['ema12'] <= prev['ema26'] and curr['ema12'] > curr['ema26']
        ema_cross_down = prev['ema12'] >= prev['ema26'] and curr['ema12'] < curr['ema26']
        rsi_cross_up = prev['rsi12'] <= prev['rsi26'] and curr['rsi12'] > curr['rsi26']
        rsi_cross_down = prev['rsi12'] >= prev['rsi26'] and curr['rsi12'] < curr['rsi26']
        
        new_long = ema_cross_up and rsi_cross_up
        new_short = ema_cross_down and rsi_cross_down
        
        # F: Sweep filter - ต้อง Sweep ก่อนถึงจะแม่นสำหรับ BTC
        # ถ้าไม่มี Sweep ใน 5 แท่งล่าสุด ให้ลดความสำคัญลง
        sweep_ok_long = curr['sweep_low'] or prev['sweep_low']
        sweep_ok_short = curr['sweep_high'] or prev['sweep_high']
        
        # D: Fractal confirm
        fractal_long = curr['fractal_low']
        fractal_short = curr['fractal_high']
        
        # G_POWER Logic: NEW ต้องเกิด + (Sweep หรือ Fractal อย่างใดอย่างหนึ่ง)
        return {
            'long': new_long and (sweep_ok_long or fractal_long),
            'short': new_short and (sweep_ok_short or fractal_short),
            'sweep_long': sweep_ok_long,
            'sweep_short': sweep_ok_short
        }
    
    def check_trend(self, curr):
        """
        เทรนด์ G_POWER: เข้มสุด กรอง Sideway 81,500
        - NEW: ราคา>EMA200 + 12>26>200 + EMA200 ชี้ขึ้น
        - D: BOS ทำ High ใหม่
        - E: SuperTrend เขียว
        """
        price_above_200 = curr['close'] > curr['ema200']
        price_below_200 = curr['close'] < curr['ema200']
        ema_align_bull = curr['ema12'] > curr['ema26'] > curr['ema200']
        ema_align_bear = curr['ema12'] < curr['ema26'] < curr['ema200']
        ema200_up = curr['ema200_slope'] > 0
        ema200_down = curr['ema200_slope'] < 0
        
        bos_bull = curr['close'] > curr['last_swing_high'] if pd.notna(curr['last_swing_high']) else False
        bos_bear = curr['close'] < curr['last_swing_low'] if pd.notna(curr['last_swing_low']) else False
        
        super_bull = curr['supertrend_dir'] == 1
        super_bear = curr['supertrend_dir'] == -1
        
        sideway = abs(curr['close'] - curr['ema200']) / curr['ema200'] < 0.005
        
        return {
            'long': price_above_200 and ema_align_bull and ema200_up and (bos_bull or super_bull),
            'short': price_below_200 and ema_align_bear and ema200_down and (bos_bear or super_bear),
            'sideway': sideway
        }
    
    def check_momentum(self, curr):
        """
        โมเมนตัม G_POWER: BTC ต้องดู Vol
        - NEW: RSI 12/26/200 >50 + RSI12<70 + ADX>20
        - D: MFI 50-80 + OBV 3>9
        - F: Vol Spike
        """
        # NEW
        rsi_triple_bull = curr['rsi12'] > 50 and curr['rsi26'] > 50 and curr['rsi200'] > 50
        rsi_triple_bear = curr['rsi12'] < 50 and curr['rsi26'] < 50 and curr['rsi200'] < 50
        rsi_not_ob = curr['rsi12'] < 70
        rsi_not_os = curr['rsi12'] > 30
        
        # D: MFI + OBV
        mfi_bull = 50 < curr['mfi'] < 80
        mfi_bear = 20 < curr['mfi'] < 50
        obv_bull = curr['obv_ema3'] > curr['obv_ema9']
        obv_bear = curr['obv_ema3'] < curr['obv_ema9']
        
        # ADX + Vol
        adx_ok = curr['adx'] > 20 if pd.notna(curr['adx']) else False
        vol_ok = curr['volume'] > curr['vol_avg'] * 0.8 if pd.notna(curr['vol_avg']) else False
        
        return {
            'long': rsi_triple_bull and rsi_not_ob and mfi_bull and obv_bull and adx_ok and vol_ok,
            'short': rsi_triple_bear and rsi_not_os and mfi_bear and obv_bear and adx_ok and vol_ok
        }
    
    def calc_sl_tp(self, entry, signal, curr):
        """SL/TP G_POWER: เอาที่ปลอดภัยสุดสำหรับ BTC ไส้ยาว"""
        atr = curr['atr'] if pd.notna(curr['atr']) else entry * 0.01
        
        # SL 3 แบบ เอาที่กว้างสุดเพื่อไม่โดนไส้ BTC กิน
        sl_pct = entry * (1 - self.config['sl_pct']) if signal == 'LONG' else entry * (1 + self.config['sl_pct'])
        sl_atr = entry - atr*1.5 if signal == 'LONG' else entry + atr*1.5
        sl_ob = curr['last_swing_low'] if signal == 'LONG' and pd.notna(curr['last_swing_low']) else curr['last_swing_high'] if signal == 'SHORT' and pd.notna(curr['last_swing_high']) else sl_pct
        
        if signal == 'LONG':
            sl_price = min(sl_pct, sl_atr, sl_ob)  # เอาต่ำสุด = กว้างสุด
            tp_price = entry * (1 + self.config['tp_pct'])  # 18%
        else:
            sl_price = max(sl_pct, sl_atr, sl_ob)  # เอาสูงสุด = กว้างสุด
            tp_price = entry * (1 - self.config['tp_pct'])
        
        return sl_price, tp_price
    
    def get_signal(self, prev, curr, df=None, idx=None):
        if self.cooldown > 0:
            self.cooldown -= 1
            return None
        
        rev = self.check_reversal(prev, curr)
        trend = self.check_trend(curr)
        mom = self.check_momentum(curr)
        
        if trend['sideway']:
            return None
        
        if rev['long'] and trend['long'] and mom['long']:
            return 'LONG'
        if rev['short'] and trend['short'] and mom['short']:
            return 'SHORT'
        return None
    
    def can_open(self):
        return len(self.positions) < self.config['max_positions'] and self.cooldown == 0
    
    def on_close(self, result):
        if result == 'LOSS':
            self.loss_streak += 1
            if self.loss_streak >= 2:
                self.cooldown = self.config['cooldown_after_2_losses']
        else:
            self.loss_streak = 0
