"""
G_POWER - FIXED for Render - ไม่ใช้ pandas_ta
แก้ ModuleNotFoundError: pkg_resources + pandas build failed
ใช้ pandas ล้วนๆ คำนวณ EMA RSI เอง
"""

import pandas as pd
import numpy as np

class Strategy_G_Power:
    def __init__(self):
        self.name = "G_POWER - BTC Ultimate"
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
            "adx_min": 20,
            "sl_pct": 0.034,
            "tp_pct": 0.18,
            "sl_atr_mult": 1.5,
            "risk_per_trade": 0.02,
            "max_positions": 2,
            "cooldown_after_2_losses": 16,
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
    
    def _adx(self, high, low, close, period=14):
        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series([u if (u>d and u>0) else 0 for u,d in zip(up,down)], index=high.index).ewm(alpha=1/period, adjust=False).mean()
        minus_dm = pd.Series([d if (d>u and d>0) else 0 for u,d in zip(up,down)], index=high.index).ewm(alpha=1/period, adjust=False).mean()
        tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
        tr14 = tr.ewm(alpha=1/period, adjust=False).mean()
        plus_di = 100*plus_dm/tr14
        minus_di = 100*minus_dm/tr14
        dx = 100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0, np.nan)
        return dx.ewm(alpha=1/period, adjust=False).mean().fillna(20)
    
    def _mfi(self, high, low, close, volume, period=14):
        tp = (high+low+close)/3
        rmf = tp * volume
        pos = rmf.where(tp > tp.shift(1), 0).rolling(period).sum()
        neg = rmf.where(tp < tp.shift(1), 0).rolling(period).sum().replace(0, 0.00001)
        mfr = pos/neg
        return 100 - (100/(1+mfr))
    
    def _obv(self, close, volume):
        return (np.sign(close.diff()) * volume).fillna(0).cumsum()
    
    def add_indicators(self, df):
        # NEW 12/26/200 Base
        df['ema12'] = self._ema(df['close'], 12)
        df['ema26'] = self._ema(df['close'], 26)
        df['ema200'] = self._ema(df['close'], 200)
        df['ema200_slope'] = df['ema200'].diff(5)
        
        df['rsi12'] = self._rsi(df['close'], 12)
        df['rsi26'] = self._rsi(df['close'], 26)
        df['rsi200'] = self._rsi(df['close'], 200)
        
        # Fractal + Sweep
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
        
        # SuperTrend simplified: use EMA trend
        df['supertrend_dir'] = np.where(df['close'] > df['ema200'], 1, -1)
        
        # Momentum
        df['mfi'] = self._mfi(df['high'], df['low'], df['close'], df['volume'], 14)
        df['obv'] = self._obv(df['close'], df['volume'])
        df['obv_ema3'] = self._ema(df['obv'], 3)
        df['obv_ema9'] = self._ema(df['obv'], 9)
        
        df['adx'] = self._adx(df['high'], df['low'], df['close'], 14)
        df['atr'] = self._atr(df['high'], df['low'], df['close'], 14)
        df['vol_avg'] = df['volume'].rolling(20).mean()
        
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
        
        return {
            'long': new_long and (sweep_ok_long or fractal_long),
            'short': new_short and (sweep_ok_short or fractal_short),
        }
    
    def check_trend(self, curr):
        price_above_200 = curr['close'] > curr['ema200']
        ema_align_bull = curr['ema12'] > curr['ema26'] > curr['ema200']
        ema_align_bear = curr['ema12'] < curr['ema26'] < curr['ema200']
        ema200_up = curr['ema200_slope'] > 0
        sideway = abs(curr['close'] - curr['ema200']) / curr['ema200'] < 0.005 if curr['ema200']>0 else False
        
        bos_bull = curr['close'] > curr['last_swing_high'] if pd.notna(curr['last_swing_high']) else False
        super_bull = curr['supertrend_dir'] == 1
        
        return {
            'long': price_above_200 and ema_align_bull and ema200_up and (bos_bull or super_bull),
            'short': (not price_above_200) and ema_align_bear and not ema200_up,
            'sideway': sideway
        }
    
    def check_momentum(self, curr):
        rsi_triple_bull = curr['rsi12']>50 and curr['rsi26']>50 and curr['rsi200']>50
        rsi_triple_bear = curr['rsi12']<50 and curr['rsi26']<50 and curr['rsi200']<50
        rsi_not_ob = curr['rsi12'] < 70
        mfi_bull = 50 < curr['mfi'] < 80 if pd.notna(curr['mfi']) else False
        mfi_bear = 20 < curr['mfi'] < 50 if pd.notna(curr['mfi']) else False
        obv_bull = curr['obv_ema3'] > curr['obv_ema9'] if pd.notna(curr['obv_ema3']) else False
        obv_bear = curr['obv_ema3'] < curr['obv_ema9'] if pd.notna(curr['obv_ema3']) else False
        adx_ok = curr['adx'] > 20 if pd.notna(curr['adx']) else False
        vol_ok = curr['volume'] > curr['vol_avg']*0.8 if pd.notna(curr['vol_avg']) else False
        
        return {
            'long': rsi_triple_bull and rsi_not_ob and mfi_bull and obv_bull and adx_ok and vol_ok,
            'short': rsi_triple_bear and mfi_bear and obv_bear and adx_ok
        }
