"""
G_POWER + CDC ATR - FIXED for Render
CDC ATR Trailing Stop V2.1 (close 5 0.5 10 2) - จาก TradingView BTC 15m
"""

import pandas as pd
import numpy as np

class Strategy_G_Power:
    def __init__(self):
        self.name = "G_POWER + CDC ATR - BTC Ultimate"
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
            "cdc_atr_fast": 5,
            "cdc_mult_fast": 0.5,
            "cdc_atr_slow": 10,
            "cdc_mult_slow": 2.0,
            "cdc_use": True,
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
        df['cdc_atr_fast'] = atr_fast
        df['cdc_atr_slow'] = atr_slow
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
        
        df['adx'] = self._adx(df['high'], df['low'], df['close'], 14)
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
        
        return {
            'long': (new_long and (sweep_ok_long or fractal_long)) or cdc_flip_long,
            'short': (new_short and (sweep_ok_short or fractal_short)) or cdc_flip_short,
        }
    
    def check_trend(self, curr):
        price_above_200 = curr['close'] > curr['ema200']
        ema_align_bull = curr['ema12'] > curr['ema26'] > curr['ema200']
        ema_align_bear = curr['ema12'] < curr['ema26'] < curr['ema200']
        ema200_up = curr['ema200_slope'] > 0
        sideway = abs(curr['close'] - curr['ema200']) / curr['ema200'] < 0.005 if curr['ema200']>0 else False
        
        bos_bull = curr['close'] > curr['last_swing_high'] if pd.notna(curr['last_swing_high']) else False
        super_bull = curr['supertrend_dir'] == 1
        
        cdc_up = bool(curr.get('cdc_up', True))
        cdc_down = bool(curr.get('cdc_down', False))
        
        if self.config.get("cdc_use", False):
            cdc_long_ok = cdc_up
            cdc_short_ok = cdc_down
        else:
            cdc_long_ok = True
            cdc_short_ok = True
        
        return {
            'long': price_above_200 and ema_align_bull and ema200_up and (bos_bull or super_bull) and cdc_long_ok,
            'short': (not price_above_200) and ema_align_bear and not ema200_up and cdc_short_ok,
            'sideway': sideway,
            'cdc_up': cdc_up,
            'cdc_down': cdc_down,
            'cdc_dist': curr.get('cdc_dist_pct', 0)
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
        
        cdc_strength = abs(curr.get('cdc_dist_pct', 0)) > 0.3
        
        return {
            'long': rsi_triple_bull and rsi_not_ob and mfi_bull and obv_bull and adx_ok and vol_ok and cdc_strength,
            'short': rsi_triple_bear and mfi_bear and obv_bear and adx_ok and cdc_strength
        }
