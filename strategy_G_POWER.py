"""
G_POWER V3.0 LITE - 6 อินดิหลัก - ตัดซ้ำซ้อน
แก้พลาด 2 ไม้: 81k LONG ติด sideway 0.69% + 77k SHORT ติด RSI oversold

เก็บ 6 ตัว:
1. CDC ATR Trailing (trend หลัก)
2. DI / ADX (แรงเทรนด์ + ทิศ)
3. EMA12 x EMA26 (ทิศเร็ว)
4. RSI12 (momentum ตัวเดียว)
5. ATR (SL/TP)
6. Vol Avg (กรองวอลุ่มแห้ง)

ตัด:
- EMA200, supertrend_dir, RSI26, RSI200, MFI, OBV, Fractal, Sweep, Swing, high_20/low_20, di_diff
"""

import pandas as pd
import numpy as np

class Strategy_G_Power:
    def __init__(self):
        self.name = "G_POWER V3.0 LITE - 6 อินดิ - TURBO"
        self.config = {
            "ema_fast": 12,
            "ema_slow": 26,
            "rsi_fast": 12,
            "adx_min": 12,
            "adx_sideway": 12,
            "adx_turbo": 35,
            "di_min": 10,
            "di_turbo": 25,
            "sl_pct": 0.034,
            "tp_pct": 0.18,
            "risk_per_trade": 0.02,
            "cdc_atr_fast": 5,
            "cdc_mult_fast": 0.5,
            "cdc_atr_slow": 10,
            "cdc_mult_slow": 2.0,
        }
    
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
        adx_slope = adx.diff(3)
        return plus_di.fillna(0), minus_di.fillna(0), adx, adx_slope

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
        df['cdc_up'] = (trend == 1)
        df['cdc_down'] = (trend == -1)
        df['cdc_dist_pct'] = (df['close'] - df['cdc_stop']) / df['close'] * 100
        return df
    
    def add_indicators(self, df):
        # 6 อินดิหลักเท่านั้น
        df['ema12'] = self._ema(df['close'], 12)
        df['ema26'] = self._ema(df['close'], 26)
        df['rsi12'] = self._rsi(df['close'], 12)
        plus_di, minus_di, adx, adx_slope = self._adx_di(df['high'], df['low'], df['close'], 14)
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        df['adx'] = adx
        df['adx_slope'] = adx_slope
        df['atr'] = self._atr(df['high'], df['low'], df['close'], 14)
        df['vol_avg'] = df['volume'].rolling(20).mean()
        df = self._cdc_atr_trailing(df)
        # compat fields สำหรับ main ที่เคยเรียก
        df['ema200'] = df['ema26']  # dummy ไม่ใช้แล้ว
        return df
    
    def check_reversal(self, prev, curr):
        # เร็วขึ้น - ไม่ต้องรอ EMA+RSI พร้อมกัน
        ema_cross_up = prev['ema12'] <= prev['ema26'] and curr['ema12'] > curr['ema26']
        ema_cross_down = prev['ema12'] >= prev['ema26'] and curr['ema12'] < curr['ema26']
        di_cross_long = prev['plus_di'] <= prev['minus_di'] and curr['plus_di'] > curr['minus_di']
        di_cross_short = prev['minus_di'] <= prev['plus_di'] and curr['minus_di'] > curr['plus_di']
        cdc_flip_long = prev['cdc_down'] and curr['cdc_up']
        cdc_flip_short = prev['cdc_up'] and curr['cdc_down']
        return {
            'long': ema_cross_up or di_cross_long or cdc_flip_long,
            'short': ema_cross_down or di_cross_short or cdc_flip_short,
            'di_cross_long': di_cross_long,
            'di_cross_short': di_cross_short,
            'ema_cross_up': ema_cross_up,
            'ema_cross_down': ema_cross_down,
            'cdc_flip_long': cdc_flip_long,
            'cdc_flip_short': cdc_flip_short,
        }
    
    def check_trend(self, curr):
        # V3 LITE - ไม่ดู EMA200 แล้ว
        ema_align_bull = curr['ema12'] > curr['ema26']
        ema_align_bear = curr['ema12'] < curr['ema26']
        # Sideway ดูแค่ ADX อย่างเดียว - ตัด EMA200 0.69% ออก
        adx_sideway = curr['adx'] < self.config.get("adx_sideway", 12)
        sideway = adx_sideway
        cdc_up = bool(curr.get('cdc_up', False))
        cdc_down = bool(curr.get('cdc_down', False))
        plus_di = curr.get('plus_di', 0)
        minus_di = curr.get('minus_di', 0)
        di_bull = plus_di > minus_di and plus_di > self.config.get("di_min", 10)
        di_bear = minus_di > plus_di and minus_di > self.config.get("di_min", 10)
        long_trend = (cdc_up and di_bull) and ema_align_bull and not sideway
        short_trend = (cdc_down and di_bear) and ema_align_bear and not sideway
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
            'cdc_dist': curr.get('cdc_dist_pct', 0),
            'adx': curr.get('adx', 0),
        }
    
    def check_momentum(self, curr):
        # V3 LITE - Bypass oversold/overbought ถ้าเทรนด์แรง
        rsi = curr.get('rsi12', 50)
        plus_di = curr.get('plus_di', 0)
        minus_di = curr.get('minus_di', 0)
        adx = curr.get('adx', 0)
        vol = curr.get('volume', 0)
        vol_avg = curr.get('vol_avg', 0)
        
        adx_turbo = adx > self.config.get("adx_turbo", 35)
        plus_turbo = plus_di > self.config.get("di_turbo", 25)
        minus_turbo = minus_di > self.config.get("di_turbo", 25)
        
        # LONG: RSI 30-78 ปกติ, แต่ถ้า ADX>35 + +DI>25 ให้ผ่านแม้ RSI 80
        rsi_long_normal = 30 < rsi < 78
        rsi_long_bypass = adx_turbo and plus_turbo
        rsi_long = rsi_long_normal or rsi_long_bypass
        
        # SHORT: RSI 22-70 ปกติ, แต่ถ้า ADX>35 + -DI>25 ให้ผ่านแม้ RSI 15
        rsi_short_normal = 22 < rsi < 70
        rsi_short_bypass = adx_turbo and minus_turbo
        rsi_short = rsi_short_normal or rsi_short_bypass
        
        adx_ok = adx > self.config.get("adx_min", 12)
        vol_ok = vol > vol_avg*0.5 if vol_avg==vol_avg else True
        cdc_strength = abs(curr.get('cdc_dist_pct', 0)) > 0.1
        
        return {
            'long': rsi_long and (adx_ok or cdc_strength) and vol_ok,
            'short': rsi_short and (adx_ok or cdc_strength) and vol_ok,
            'rsi_long': rsi_long,
            'rsi_short': rsi_short,
            'bypass_long': rsi_long_bypass,
            'bypass_short': rsi_short_bypass,
        }
