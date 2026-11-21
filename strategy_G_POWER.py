"""G_POWER V7.6 - Fast x Slow เป็นตัวสั่ง / อย่างอื่นเป็นตัวคอนเฟิร์ม
- ข้อ 4: Pattern ดูบน 15m (Pin Bar 1 แท่ง / Engulfing 2 แท่ง รอแท่งปิด)
- ข้อ 5: TP ทอง 0.6% / BTC 0.8% - ถึง TP แล้วถ้า Fast/Slow ยังอยู่ถือต่อ ออกเมื่อ Fast x Slow ตัดกลับ
- SL ขยับตาม: ถึง TP -> SL = จุดเข้า (BE) หลังจากนั้น Trail ห่าง SL% จากจุดสูงสุด/ต่ำสุด
- 1h = เทรนใหญ่ / 15m = จุดเข้า / LONG เฉพาะขาขึ้น SHORT เฉพาะขาลง
"""
import pandas as pd
import numpy as np

class Strategy_G_Power:
    def __init__(self, symbol_key="btc"):
        self.symbol_key = symbol_key
        if symbol_key == "gold":
            self.config = {
                "ema_fast": 12, "ema_slow": 36, "ema_trend": 100,
                "adx_min": 15, "di_min": 10,
                "sl_pct": 0.006, "tp_pct": 0.006,
                "retest_pct": 0.006, "max_ext_pct": 0.01,
                "pattern_tf": "15m", "cross_window": 10,
            }
        else:
            self.config = {
                "ema_fast": 15, "ema_slow": 40, "ema_trend": 80,
                "adx_min": 15, "di_min": 10,
                "sl_pct": 0.008, "tp_pct": 0.008,
                "retest_pct": 0.009, "max_ext_pct": 0.01,
                "pattern_tf": "15m", "cross_window": 10,
            }

    def _ema(self, s, p):
        return s.ewm(span=p, adjust=False).mean()

    def _adx_di(self, high, low, close, period=14):
        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series([u if (u > d and u > 0) else 0 for u, d in zip(up, down)], index=high.index).ewm(alpha=1/period, adjust=False).mean()
        minus_dm = pd.Series([d if (d > u and d > 0) else 0 for u, d in zip(up, down)], index=high.index).ewm(alpha=1/period, adjust=False).mean()
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        tr14 = tr.ewm(alpha=1/period, adjust=False).mean()
        plus_di = 100 * plus_dm / tr14
        minus_di = 100 * minus_dm / tr14
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1/period, adjust=False).mean().fillna(15)
        return plus_di.fillna(0), minus_di.fillna(0), adx

    def add_indicators(self, df, df_1h=None):
        df = df.copy()
        c = self.config
        df["ema_fast"] = self._ema(df["close"], c["ema_fast"])
        df["ema_slow"] = self._ema(df["close"], c["ema_slow"])
        df["ema_trend"] = self._ema(df["close"], c["ema_trend"])
        df["cross_up"] = (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1)) & (df["ema_fast"] > df["ema_slow"])
        df["cross_down"] = (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1)) & (df["ema_fast"] < df["ema_slow"])
        pdi, mdi, adx = self._adx_di(df["high"], df["low"], df["close"], 14)
        df["plus_di"] = pdi
        df["minus_di"] = mdi
        df["adx"] = adx
        if df_1h is not None and len(df_1h) > 0:
            h = df_1h.copy()
            h["ema_trend_1h"] = self._ema(h["close"], c["ema_trend"])
            h["trend_1h_up"] = h["close"] > h["ema_trend_1h"]
            h = h.set_index("time")[["trend_1h_up"]]
            df = df.set_index("time").join(h, how="left").reset_index()
            df["trend_1h_up"] = df["trend_1h_up"].ffill().fillna(False)
        else:
            df["trend_1h_up"] = df["close"] > df["ema_trend"]
        df["pat_bull"], df["pat_bear"] = self._pattern_15m(df)
        return df

    def _pattern_15m(self, df):
        bull = pd.Series(False, index=df.index)
        bear = pd.Series(False, index=df.index)
        for i in range(1, len(df)):
            o, h, l, cl = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
            po, pcl = df["open"].iloc[i-1], df["close"].iloc[i-1]
            body = abs(cl - o)
            lower_wick = min(o, cl) - l
            upper_wick = h - max(o, cl)
            pin_bull = lower_wick > 2 * max(body, 0.00001) and cl > o
            pin_bear = upper_wick > 2 * max(body, 0.00001) and cl < o
            eng_bull = (pcl < po) and (cl > o) and (o <= pcl) and (cl >= po) and (body > abs(pcl - po))
            eng_bear = (pcl > po) and (cl < o) and (o >= pcl) and (cl <= po) and (body > abs(pcl - po))
            bull.iloc[i] = bool(pin_bull or eng_bull)
            bear.iloc[i] = bool(pin_bear or eng_bear)
        return bull, bear

    def check_entry(self, df, i):
        if i < 30:
            return None, ""
        c = self.config
        row = df.iloc[i]
        win = df.iloc[max(0, i - c["cross_window"]):i+1]
        cross_up_recent = bool(win["cross_up"].any())
        cross_down_recent = bool(win["cross_down"].any())
        fast_up = row["ema_fast"] > row["ema_slow"]
        fast_down = row["ema_fast"] < row["ema_slow"]
        trend_up = bool(row["trend_1h_up"])
        trend_down = not trend_up
        adx_ok = row["adx"] >= c["adx_min"]
        di_bull = row["plus_di"] > row["minus_di"] and row["plus_di"] >= c["di_min"]
        di_bear = row["minus_di"] > row["plus_di"] and row["minus_di"] >= c["di_min"]
        lows = df.iloc[max(0, i-2):i+1]["low"]
        highs = df.iloc[max(0, i-2):i+1]["high"]
        trend = row["ema_trend"]
        pullback_long = bool(((lows - trend).abs() / trend <= c["max_ext_pct"]).any() or (lows.min() <= trend <= highs.max()))
        pullback_short = bool(((highs - trend).abs() / trend <= c["max_ext_pct"]).any() or (lows.min() <= trend <= highs.max()))
        pat_bull = bool(row["pat_bull"])
        pat_bear = bool(row["pat_bear"])
        if fast_up and cross_up_recent and trend_up and adx_ok and di_bull and pullback_long and pat_bull:
            return "LONG", "FastUp+1hUp+ADX+Pullback+Pat15m"
        if fast_down and cross_down_recent and trend_down and adx_ok and di_bear and pullback_short and pat_bear:
            return "SHORT", "FastDown+1hDown+ADX+Pullback+Pat15m"
        return None, ""

    def initial_sl_tp(self, entry, side):
        c = self.config
        if side == "LONG":
            return entry * (1 - c["sl_pct"]), entry * (1 + c["tp_pct"])
        return entry * (1 + c["sl_pct"]), entry * (1 - c["tp_pct"])

    def update_trailing_sl(self, pos, price):
        c = self.config
        entry = pos["entry"]
        side = pos["side"]
        if side == "LONG":
            pos["highest"] = max(pos.get("highest", entry), price)
            gain = (price - entry) / entry
            if gain >= c["tp_pct"]:
                trail = pos["highest"] * (1 - c["sl_pct"])
                pos["sl"] = max(pos["sl"], entry, trail)
                pos["be_done"] = True
        else:
            pos["lowest"] = min(pos.get("lowest", entry), price)
            gain = (entry - price) / entry
            if gain >= c["tp_pct"]:
                trail = pos["lowest"] * (1 + c["sl_pct"])
                pos["sl"] = min(pos["sl"], entry, trail)
                pos["be_done"] = True
        return pos["sl"]

    def check_exit(self, df, i, pos):
        row = df.iloc[i]
        price = float(row["close"])
        side = pos["side"]
        if side == "LONG" and price <= pos["sl"]:
            return "SL_TRAIL" if pos.get("be_done") else "SL"
        if side == "SHORT" and price >= pos["sl"]:
            return "SL_TRAIL" if pos.get("be_done") else "SL"
        if side == "LONG" and row["ema_fast"] < row["ema_slow"]:
            return "FAST_FLIP"
        if side == "SHORT" and row["ema_fast"] > row["ema_slow"]:
            return "FAST_FLIP"
        return None
