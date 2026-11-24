"""G_POWER V9 - EMA + Dow Theory
TF: 1h นับคลื่น / 15m เข้า / 4h คอนเฟิร์ม (backtest ใช้ 1h จาก 15m resample)
- Dow นับ 1-5 + ABC
- รอราคาแตะ EMA 36 บน 1h
- TP วัดตามคลื่น: Wave3 = 1.618 x Wave1 / Wave5 = 1.0 x Wave1 / ABC = 1.0 x WaveA
- ไม้: Wave1=3, Wave2=1, Wave3=3, Wave4=1, Wave5=3, A=1, B=3, C=1
- SL ตามโครงสร้าง ใต้ HL / เหนือ LH คุมไม่เกิน BTC 0.8% / GOLD 0.6%
- เช็คที่แท่งปิดเท่านั้น ไม่ใช้ราคากลางแท่ง
"""
import pandas as pd
import numpy as np

class Strategy_G_Power:
    def __init__(self, symbol_key="btc"):
        self.symbol_key = symbol_key
        if symbol_key == "gold":
            self.config = {
                "ema_fast": 12, "ema_slow": 36,
                "adx_min": 15, "di_min": 10,
                "sl_pct_max": 0.006, "tp_cap": 0.03,
                "touch_tol": 0.001,
            }
        else:
            self.config = {
                "ema_fast": 12, "ema_slow": 36,
                "adx_min": 12, "di_min": 10,
                "sl_pct_max": 0.008, "tp_cap": 0.04,
                "touch_tol": 0.001,
            }
        self.WAVE_QUOTA = {"1": 3, "2": 1, "3": 3, "4": 1, "5": 3, "A": 1, "B": 3, "C": 1}

    def add_indicators(self, df):
        df = df.copy()
        df["ema_fast"] = df["close"].ewm(span=self.config["ema_fast"], adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.config["ema_slow"], adjust=False).mean()
        df["adx"], df["di_plus"], df["di_minus"] = self._adx_di(df)
        df["vol_avg"] = df["volume"].rolling(20).mean()
        return df

    def _adx_di(self, df, period=14):
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        n = len(df)
        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
            up = high[i]-high[i-1]
            dn = low[i-1]-low[i]
            plus_dm[i] = up if (up > dn and up > 0) else 0
            minus_dm[i] = dn if (dn > up and dn > 0) else 0
        tr_s = pd.Series(tr).ewm(alpha=1/period, adjust=False).mean().values
        plus_s = pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean().values
        minus_s = pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean().values
        di_plus = np.where(tr_s != 0, 100*plus_s/np.maximum(tr_s, 1e-9), 0)
        di_minus = np.where(tr_s != 0, 100*minus_s/np.maximum(tr_s, 1e-9), 0)
        dx = np.where((di_plus+di_minus) != 0, 100*np.abs(di_plus-di_minus)/np.maximum(di_plus+di_minus, 1e-9), 0)
        adx = pd.Series(dx).ewm(alpha=1/period, adjust=False).mean().values
        return adx, di_plus, di_minus

    def detect_swings(self, df_1h, lookback=2):
        swings = []
        highs = df_1h["high"].values
        lows = df_1h["low"].values
        for i in range(lookback, len(df_1h)-lookback):
            if highs[i] == max(highs[i-lookback:i+lookback+1]):
                swings.append({"idx": i, "type": "H", "price": float(highs[i])})
            if lows[i] == min(lows[i-lookback:i+lookback+1]):
                swings.append({"idx": i, "type": "L", "price": float(lows[i])})
        swings = sorted(swings, key=lambda x: x["idx"])
        cleaned = []
        for s in swings:
            if cleaned and cleaned[-1]["type"] == s["type"]:
                if s["type"] == "H" and s["price"] > cleaned[-1]["price"]:
                    cleaned[-1] = s
                elif s["type"] == "L" and s["price"] < cleaned[-1]["price"]:
                    cleaned[-1] = s
            else:
                cleaned.append(s)
        return cleaned

    def count_waves(self, swings):
        if len(swings) < 4:
            return {"current_wave": None, "trend": "UNKNOWN", "cycle_id": 0, "wave1_len": 0, "waveA_len": 0, "wave5_high": 0, "wave1_low": 0, "swings": swings}
        highs = [s["price"] for s in swings if s["type"] == "H"]
        lows = [s["price"] for s in swings if s["type"] == "L"]
        if len(highs) >= 2 and len(lows) >= 2:
            if highs[-1] > highs[0] and lows[-1] > lows[0]:
                trend = "UP"
            elif highs[-1] < highs[0] and lows[-1] < lows[0]:
                trend = "DOWN"
            else:
                trend = "UP" if swings[-1]["price"] > swings[0]["price"] else "DOWN"
        else:
            trend = "UNKNOWN"
        pos = len(swings) % 8
        mapping = {0: "1", 1: "2", 2: "3", 3: "4", 4: "5", 5: "A", 6: "B", 7: "C"}
        current_wave = mapping.get(pos, "1")
        wave1_len = 0
        waveA_len = 0
        wave5_high = 0
        wave1_low = 0
        if len(swings) >= 2:
            base = swings[-8:] if len(swings) >= 8 else swings
            if len(base) >= 2:
                wave1_len = abs(base[1]["price"] - base[0]["price"])
                wave1_low = base[0]["price"]
            if len(base) >= 7:
                waveA_len = abs(base[5]["price"] - base[6]["price"])
                wave5_high = base[5]["price"]
        cycle_id = len(swings) // 8
        return {"current_wave": current_wave, "trend": trend, "cycle_id": cycle_id, "wave1_len": wave1_len, "waveA_len": waveA_len, "wave5_high": wave5_high, "wave1_low": wave1_low, "swings": swings}

    def check_pattern_15m(self, df_15m, i):
        if i < 1:
            return None
        curr = df_15m.iloc[i]
        prev = df_15m.iloc[i-1]
        o, h, l, c = float(curr["open"]), float(curr["high"]), float(curr["low"]), float(curr["close"])
        po, pc = float(prev["open"]), float(prev["close"])
        body = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        if lower > 2 * max(body, 1e-9) and c > o:
            return "PIN_BULL"
        if upper > 2 * max(body, 1e-9) and c < o:
            return "PIN_BEAR"
        if c > o and pc < po and c >= po and o <= pc:
            return "ENG_BULL"
        if c < o and pc > po and c <= po and o >= pc:
            return "ENG_BEAR"
        return None

    def is_touch_ema36(self, low, high, ema36):
        if ema36 is None or ema36 == 0:
            return False
        tol = self.config["touch_tol"]
        if low <= ema36 <= high:
            return True
        if abs(low - ema36) / ema36 <= tol:
            return True
        if abs(high - ema36) / ema36 <= tol:
            return True
        return False

    def get_tp_by_wave(self, wave, side, entry, wave1_len, waveA_len):
        if wave == "3":
            mult = 1.618
            base_len = wave1_len if wave1_len > 0 else entry * 0.01
            tp = entry + mult * base_len if side == "LONG" else entry - mult * base_len
        elif wave == "5":
            mult = 1.0
            base_len = wave1_len if wave1_len > 0 else entry * 0.01
            tp = entry + mult * base_len if side == "LONG" else entry - mult * base_len
        elif wave in ("A", "C"):
            mult = 1.0
            base_len = waveA_len if waveA_len > 0 else (wave1_len if wave1_len > 0 else entry * 0.01)
            tp = entry - mult * base_len if side == "SHORT" else entry + mult * base_len
        elif wave == "B":
            mult = 1.0
            base_len = waveA_len if waveA_len > 0 else entry * 0.01
            tp = entry + mult * base_len if side == "LONG" else entry - mult * base_len
        else:
            mult = 1.0
            base_len = wave1_len if wave1_len > 0 else entry * 0.01
            tp = entry + mult * base_len if side == "LONG" else entry - mult * base_len
        cap = self.config["tp_cap"]
        if side == "LONG":
            tp = min(tp, entry * (1 + cap))
        else:
            tp = max(tp, entry * (1 - cap))
        return float(tp)

    def get_sl_by_structure(self, side, entry, hl_price):
        max_sl = self.config["sl_pct_max"]
        if side == "LONG":
            sl = hl_price if hl_price < entry else entry * (1 - max_sl)
            if (entry - sl) / entry > max_sl:
                sl = entry * (1 - max_sl)
        else:
            sl = hl_price if hl_price > entry else entry * (1 + max_sl)
            if (sl - entry) / entry > max_sl:
                sl = entry * (1 + max_sl)
        return float(sl)
