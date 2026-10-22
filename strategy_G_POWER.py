
"""
G_POWER V2.7 ADX+DI FULL - จับทุกการวิ่ง + ADX/DI เต็มระบบ
รวม V2.6 OPPORTUNITY + ADX/DI

จุดเด่น ADX+DI:
- +DI = แรงซื้อ, -DI = แรงขาย, ADX = ความแข็งเทรนด์
- DI Cross เร็วกว่า EMA Cross 1-2 แท่ง
- ADX <15 = Sideway ไม่ต้องใช้ EMA200 0.5%

แก้จาก V2.5/V2.6:
- Trend: ตัด price_above_200 ออกสำหรับ SHORT, ให้ SHORT ได้แม้เหนือ EMA200 ถ้า CDC แดง + DI Bear + Sweep
- Momentum: RSI Double แทน Triple, MFI 40-85/15-60, ADX 15, Vol 0.6, dist 0.15%, sideway 1.5%
- ADX/DI FULL: เก็บ plus_di, minus_di, adx_slope, ใช้ DI Cross เป็นสัญญาณกลับตัวเสริม
"""

import pandas as pd
import numpy as np

class Strategy_G_Power:
    def __init__(self):
        self.name = "G_POWER V2.7 ADX+DI FULL - จับทุกการวิ่ง"
        self.config = {
            "ema_fast": 12,
            "ema_slow": 26,
            "ema_trend": 200,
            "rsi_fast": 12,
            "rsi_slow": 26,
            "rsi_trend": 200,
            "sweep_lookback": 20,
            "fractal_period": 5,
            "mfi_period": 14,
            "obv_fast": 3,
            "obv_slow": 9,
            "adx_min": 15,  # V2.7: 15 แทน 20 - ผ่อน
            "adx_sideway": 15,  # <15 = Sideway
            "di_min": 15,  # DI ต้อง >15 ถึงมีแรง
            "sl_pct": 0.034,
            "tp_pct": 0.18,
            "sl_atr_mult": 1.5,
            "risk_per_trade": 0.02,
            "max_positions": 2,
            "cooldown_after_2_losses": 16,
            "cdc_atr_fast": 5,
            "cdc_mult_fast": 0.5,
            "cdc_atr_slow": 10,
            "cdc_mult_slow": 2.0,
            "cdc_use": True,
            "sideway_pct": 0.015,  # 1.5% แทน 0.5%
        }
        self.loss_streak = 0
        self.cooldown = 0
        self.positions = []
    
    def _ema(self, series, period):
        return series.ewm(span=period, adjust=False).mean()
    
    def _rsi(self, series, period):
        delta = series.diff()
        gain = delta.where(delta>0, 0).ewm(alpha=1/period, adjust=False).mean()
        loss = (-delta.where(delta<0, 0)).ewm(alpha=1/period, adjust=False).mean()
        rs = gain / loss.replace(0, 0.00001)
        return 100 - (100/(1+rs))
    
    def _atr(self, high, low, close, period=14):
        tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, adjust=False).mean()
    
    def _adx_di(self, high, low, close, period=14):
        """V2.7 ADX+DI FULL - คืนค่า plus_di, minus_di, adx, adx_slope"""
        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series([u if (u>d and u>0) else 0 for u,d in zip(up,down)], index=high.index).ewm(alpha=1/period, adjust=False).mean()
        minus_dm = pd.Series([d if (d>u and d>0) else 0 for u,d in zip(up,down)], index=high.index).ewm(alpha=1/period, adjust=False).mean()
        tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
        tr14 = tr.ewm(alpha=1/period, adjust=False).mean()
        plus_di = 100*plus_dm/tr14
        minus_di = 100*minus_dm/tr14
        dx = 100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1/period, adjust=False).mean().fillna(15)
        adx_slope = adx.diff(3)  # ADX กำลังขึ้นหรือลง
        
        return plus_di.fillna(0), minus_di.fillna(0), adx, adx_slope
    
    def _mfi(self, high, low, close, volume, period=14):
        tp = (high+low+close)/3
        rmf = tp * volume
        pos = rmf.where(tp > tp.shift(1), 0).rolling(period).sum()
        neg = rmf.where(tp < tp.shift(1), 0).rolling(period).sum().replace(0, 0.00001)
        mfr = pos/neg
        return 100 - (100/(1+mfr))
    
    def _obv(self, close, volume):
        return (np.sign(close.diff()) * volume).fillna(0).cumsum()

    def _cdc_atr_trailing(self, df):
        atr_fast = self._atr(df['high'], df['low'], df['close'], self.config["cdc_atr_fast"])
        atr_slow = self._atr(df['high'], df['low'], df['close'], self.config["cdc_atr_slow"])
        
        long_stop_fast = df['close'] - atr_fast * self.config["cdc_mult_fast"]
        short_stop_fast = df['close'] + atr_fast * self.config["cdc_mult_fast"]
        long_stop_slow = df['close'] - atr_slow * self.config["cdc_mult_slow"]
        short_stop_slow = df['close'] + atr_slow * self.config["cdc_mult_slow"]
        
        long_stop = pd.concat([long_stop_fast, long_stop_slow], axis=1).max(axis=1)
        short_stop = pd.concat([short_stop_fast, short_stop_slow], axis=1).min(axis=1)
        
        trend = np.zeros(len(df), dtype=int)
        stop_level = np.zeros(len(df))
        
        trend[0] = 1
        stop_level[0] = long_stop.iloc[0]
        
        for i in range(1, len(df)):
            close = df['close'].iloc[i]
            prev_trend = trend[i-1]
            prev_stop = stop_level[i-1]
            
            if prev_trend == 1:
                curr_long = long_stop.iloc[i]
                new_stop = max(curr_long, prev_stop) if not np.isnan(prev_stop) else curr_long
                if close < new_stop:
                    trend[i] = -1
                    stop_level[i] = short_stop.iloc[i]
                else:
                    trend[i] = 1
                    stop_level[i] = new_stop
            else:
                curr_short = short_stop.iloc[i]
                new_stop = min(curr_short, prev_stop) if not np.isnan(prev_stop) else curr_short
                if close > new_stop:
                    trend[i] = 1
                    stop_level[i] = long_stop.iloc[i]
                else:
                    trend[i] = -1
                    stop_level[i] = new_stop
        
        df['cdc_trend'] = trend
        df['cdc_stop'] = stop_level
        df['cdc_long_stop'] = long_stop
        df['cdc_short_stop'] = short_stop
        df['cdc_up'] = (trend == 1)
        df['cdc_down'] = (trend == -1)
        df['cdc_dist_pct'] = (df['close'] - df['cdc_stop']) / df['close'] * 100
        
        return df
    
    def add_indicators(self, df):
        df['ema12'] = self._ema(df['close'], 12)
        df['ema26'] = self._ema(df['close'], 26)
        df['ema200'] = self._ema(df['close'], 200)
        df['ema200_slope'] = df['ema200'].diff(5)
        
        df['rsi12'] = self._rsi(df['close'], 12)
        df['rsi26'] = self._rsi(df['close'], 26)
        df['rsi200'] = self._rsi(df['close'], 200)
        
        df['fractal_high'] = df['high'].rolling(5, center=True).max() == df['high']
        df['fractal_low'] = df['low'].rolling(5, center=True).min() == df['low']
        
        df['high_20'] = df['high'].rolling(20).max()
        df['low_20'] = df['low'].rolling(20).min()
        df['sweep_high'] = (df['high'] > df['high_20'].shift(1)) & (df['close'] < df['high_20'].shift(1))
        df['sweep_low'] = (df['low'] < df['low_20'].shift(1)) & (df['close'] > df['low_20'].shift(1))
        
        df['swing_high'] = df['high'].where(df['fractal_high'])
        df['swing_low'] = df['low'].where(df['fractal_low'])
        df['last_swing_high'] = df['swing_high'].ffill()
        df['last_swing_low'] = df['swing_low'].ffill()
        
        df['supertrend_dir'] = np.where(df['close'] > df['ema200'], 1, -1)
        
        df['mfi'] = self._mfi(df['high'], df['low'], df['close'], df['volume'], 14)
        df['obv'] = self._obv(df['close'], df['volume'])
        df['obv_ema3'] = self._ema(df['obv'], 3)
        df['obv_ema9'] = self._ema(df['obv'], 9)
        
        # V2.7 ADX+DI FULL
        plus_di, minus_di, adx, adx_slope = self._adx_di(df['high'], df['low'], df['close'], 14)
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        df['adx'] = adx
        df['adx_slope'] = adx_slope
        df['di_diff'] = plus_di - minus_di
        
        df['atr'] = self._atr(df['high'], df['low'], df['close'], 14)
        df['vol_avg'] = df['volume'].rolling(20).mean()
        
        df = self._cdc_atr_trailing(df)
        
        return df
    
    def check_reversal(self, prev, curr):
        ema_cross_up = prev['ema12'] <= prev['ema26'] and curr['ema12'] > curr['ema26']
        ema_cross_down = prev['ema12'] >= prev['ema26'] and curr['ema12'] < curr['ema26']
        rsi_cross_up = prev['rsi12'] <= prev['rsi26'] and curr['rsi12'] > curr['rsi26']
        rsi_cross_down = prev['rsi12'] >= prev['rsi26'] and curr['rsi12'] < curr['rsi26']
        
        new_long = ema_cross_up and rsi_cross_up
        new_short = ema_cross_down and rsi_cross_down
        
        sweep_ok_long = curr['sweep_low'] or prev['sweep_low']
        sweep_ok_short = curr['sweep_high'] or prev['sweep_high']
        
        fractal_long = curr['fractal_low']
        fractal_short = curr['fractal_high']
        
        cdc_flip_long = prev['cdc_down'] and curr['cdc_up']
        cdc_flip_short = prev['cdc_up'] and curr['cdc_down']
        
        # V2.7 ADX+DI: DI Cross เป็นสัญญาณกลับตัวเสริม
        di_cross_long = prev['plus_di'] <= prev['minus_di'] and curr['plus_di'] > curr['minus_di']
        di_cross_short = prev['minus_di'] <= prev['plus_di'] and curr['minus_di'] > curr['plus_di']
        
        return {
            'long': (new_long and (sweep_ok_long or fractal_long)) or cdc_flip_long or di_cross_long,
            'short': (new_short and (sweep_ok_short or fractal_short)) or cdc_flip_short or di_cross_short,
            'di_cross_long': di_cross_long,
            'di_cross_short': di_cross_short,
        }
    
    def check_trend(self, curr):
        # V2.7 ADX+DI FULL + OPPORTUNITY
        price_above_200 = curr['close'] > curr['ema200']
        ema_align_bull = curr['ema12'] > curr['ema26']
        ema_align_bear = curr['ema12'] < curr['ema26']
        sideway_thresh = self.config.get("sideway_pct", 0.015)
        # V2.7: ใช้ ADX เป็น sideway filter ด้วย
        adx_sideway = curr['adx'] < self.config.get("adx_sideway", 15)
        ema_sideway = abs(curr['close'] - curr['ema200']) / curr['ema200'] < sideway_thresh if curr['ema200']>0 else False
        sideway = adx_sideway or ema_sideway
        
        bos_bull = curr['close'] > curr['last_swing_high'] if pd.notna(curr['last_swing_high']) else False
        super_bull = curr['supertrend_dir'] == 1
        
        cdc_up = bool(curr.get('cdc_up', True))
        cdc_down = bool(curr.get('cdc_down', False))
        
        sweep_low = bool(curr.get('sweep_low', False))
        sweep_high = bool(curr.get('sweep_high', False))
        fractal_low = bool(curr.get('fractal_low', False))
        fractal_high = bool(curr.get('fractal_high', False))
        
        # V2.7 DI
        plus_di = curr.get('plus_di', 0)
        minus_di = curr.get('minus_di', 0)
        di_bull = plus_di > minus_di and plus_di > self.config.get("di_min", 15)
        di_bear = minus_di > plus_di and minus_di > self.config.get("di_min", 15)
        adx_slope_up = curr.get('adx_slope', 0) > 0
        
        # V2.7 LONG: (price>200 or sweep/fractal) + EMA12>26 + (CDC up or DI bull) + ADX rising + not sideway
        long_trend = (price_above_200 or sweep_low or fractal_low) and ema_align_bull and (cdc_up or di_bull) and not sideway
        long_trend = long_trend and (bos_bull or super_bull or sweep_low or fractal_low or di_bull)
        
        # V2.7 SHORT: (CDC down or DI bear) + (EMA12<26 or sweep/fractal) + ADX rising + not sideway - ไม่ต้องเช็ค price>200!
        short_trend = (cdc_down or di_bear) and (ema_align_bear or sweep_high or fractal_high) and not sideway
        
        return {
            'long': long_trend,
            'short': short_trend,
            'sideway': sideway,
            'cdc_up': cdc_up,
            'cdc_down': cdc_down,
            'di_bull': di_bull,
            'di_bear': di_bear,
            'plus_di': plus_di,
            'minus_di': minus_di,
            'cdc_dist': curr.get('cdc_dist_pct', 0)
        }
    
    def check_momentum(self, curr):
        # V2.7 OPPORTUNITY + DI
        rsi_double_bull = curr['rsi12']>45 and curr['rsi26']>45
        rsi_double_bear = curr['rsi12']<55 and curr['rsi26']<55
        rsi_not_ob = curr['rsi12'] < 75
        rsi_not_os = curr['rsi12'] > 25
        
        mfi_bull = 40 < curr['mfi'] < 85 if pd.notna(curr['mfi']) else False
        mfi_bear = 15 < curr['mfi'] < 60 if pd.notna(curr['mfi']) else False
        
        obv_bull = curr['obv_ema3'] > curr['obv_ema9'] if pd.notna(curr['obv_ema3']) else False
        obv_bear = curr['obv_ema3'] < curr['obv_ema9'] if pd.notna(curr['obv_ema3']) else False
        
        adx_ok = curr['adx'] > self.config.get("adx_min", 15) if pd.notna(curr['adx']) else False
        adx_slope_ok = curr.get('adx_slope', 0) > -1  # ADX ไม่ลงแรง
        
        # V2.7 DI momentum
        plus_di = curr.get('plus_di', 0)
        minus_di = curr.get('minus_di', 0)
        di_mom_bull = plus_di > minus_di
        di_mom_bear = minus_di > plus_di
        
        vol_ok = curr['volume'] > curr['vol_avg']*0.6 if pd.notna(curr['vol_avg']) else False
        
        cdc_strength = abs(curr.get('cdc_dist_pct', 0)) > 0.15
        
        return {
            'long': rsi_double_bull and rsi_not_ob and mfi_bull and (obv_bull or adx_ok) and (di_mom_bull or cdc_strength) and adx_slope_ok,
            'short': rsi_double_bear and rsi_not_os and mfi_bear and (obv_bear or adx_ok) and (di_mom_bear or cdc_strength) and vol_ok and adx_slope_ok
        }
