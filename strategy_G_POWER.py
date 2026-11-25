"""G_POWER V9 UNIFIED - EMA + Dow + Compat สำหรับ main เก่า
อัปโหลดเป็น strategy_G_POWER.py (ชื่อเดียวเท่านั้น)
- มีทั้ง class Strategy_G_Power และ Strategy_G_PowerMulti (alias เดียวกัน) main เรียกแบบไหนก็เจอ
- มีเมธอดเก่า check_smc / check_trend / check_momentum / check_reversal / check_exit_trend_change / get_trailing_sl ให้ main V6.1 ไม่พัง
- มีเมธอด V9 Dow: detect_swings / count_waves / check_pattern_15m / is_touch_ema36 / get_tp_by_wave / get_sl_by_structure
TF: 1h นับคลื่น / 15m เข้า / 4h คอนเฟิร์ม | รอแตะ EMA36 บน 1h | TP ตามคลื่น
"""
import pandas as pd
import numpy as np

class Strategy_G_Power:
    def __init__(self, symbol_key="btc"):
        # รองรับ main เก่าที่เรียก Strategy_G_Power() แบบไม่มี arg
        if symbol_key is None:
            symbol_key = "btc"
        self.symbol_key = symbol_key
        if symbol_key == "gold":
            self.config = {
                "ema_fast": 12, "ema_slow": 36, "ema_trend": 100,
                "ema50": 50, "ema100": 100, "ema200": 200,
                "adx_min": 15, "adx_sideway": 15, "adx_turbo": 26,
                "di_min": 10, "di_turbo": 20,
                "sl_pct": 0.006, "sl_pct_max": 0.006, "tp_pct": 0.03, "tp_cap": 0.03,
                "touch_tol": 0.001,
                "smc_min_score": 3, "cdc_atr_fast": 10, "cdc_mult_fast": 1.0,
                "cdc_atr_slow": 20, "cdc_mult_slow": 2.5,
                "sideway_pct": 1.2, "retest_pct": 0.006, "max_extension_pct": 2.0,
                "be_trigger": 0.008, "lock_trigger": 0.015, "lock_pct": 0.004,
            }
        else:
            self.config = {
                "ema_fast": 12, "ema_slow": 36, "ema_trend": 80,
                "ema50": 50, "ema100": 100, "ema200": 200,
                "adx_min": 12, "adx_sideway": 12, "adx_turbo": 30,
                "di_min": 10, "di_turbo": 22,
                "sl_pct": 0.008, "sl_pct_max": 0.008, "tp_pct": 0.04, "tp_cap": 0.04,
                "touch_tol": 0.001,
                "smc_min_score": 3, "cdc_atr_fast": 7, "cdc_mult_fast": 0.8,
                "cdc_atr_slow": 14, "cdc_mult_slow": 2.0,
                "sideway_pct": 1.5, "retest_pct": 0.009, "max_extension_pct": 3.0,
                "be_trigger": 0.01, "lock_trigger": 0.02, "lock_pct": 0.005,
            }
        self.WAVE_QUOTA = {"1": 3, "2": 1, "3": 3, "4": 1, "5": 3, "A": 1, "B": 3, "C": 1}

    # ---------- Indicators ----------
    def add_indicators(self, df):
        df = df.copy()
        c = self.config
        df["ema_fast"] = df["close"].ewm(span=c["ema_fast"], adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=c["ema_slow"], adjust=False).mean()
        df["ema_trend"] = df["close"].ewm(span=c["ema_trend"], adjust=False).mean()
        df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()
        df["ema26"] = df["close"].ewm(span=26, adjust=False).mean()
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["ema100"] = df["close"].ewm(span=100, adjust=False).mean()
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        adx, di_p, di_m = self._adx_di(df)
        df["adx"] = adx
        df["di_plus"] = di_p
        df["di_minus"] = di_m
        df["plus_di"] = di_p
        df["minus_di"] = di_m
        df["vol_avg"] = df["volume"].rolling(20).mean() if "volume" in df.columns else 0
        # CDC / Chandelier Stop แบบง่าย ใช้ EMA Slow เป็นฐาน + ATR
        tr = (df["high"] - df["low"]).abs()
        atr = tr.rolling(14).mean().fillna(tr.mean() if len(tr) else 0)
        df["atr"] = atr
        df["cdc_up"] = df["ema_fast"] > df["ema_slow"]
        # cdc_stop: LONG ใช้ Low - ATR*2, SHORT ใช้ High + ATR*2 แต่เก็บเป็นค่าเดียวตามทิศ CDC
        df["cdc_stop"] = np.where(df["cdc_up"], df["low"] - atr * 2.0, df["high"] + atr * 2.0)
        df["cdc_stop"] = df["cdc_stop"].fillna(df["close"])
        return df

    def _adx_di(self, df, period=14):
        high = df["high"].values; low = df["low"].values; close = df["close"].values; n = len(df)
        tr = np.zeros(n); plus_dm = np.zeros(n); minus_dm = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
            up = high[i]-high[i-1]; dn = low[i-1]-low[i]
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

    # ---------- V9 Dow ----------
    def detect_swings(self, df_1h, lookback=2):
        swings = []
        highs = df_1h["high"].values; lows = df_1h["low"].values
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
        highs = [s["price"] for s in swings if s["type"] == "H"]; lows = [s["price"] for s in swings if s["type"] == "L"]
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
        wave1_len = 0; waveA_len = 0; wave5_high = 0; wave1_low = 0
        if len(swings) >= 2:
            base = swings[-8:] if len(swings) >= 8 else swings
            if len(base) >= 2:
                wave1_len = abs(base[1]["price"] - base[0]["price"]); wave1_low = base[0]["price"]
            if len(base) >= 7:
                waveA_len = abs(base[5]["price"] - base[6]["price"]); wave5_high = base[5]["price"]
        cycle_id = len(swings) // 8
        return {"current_wave": current_wave, "trend": trend, "cycle_id": cycle_id, "wave1_len": wave1_len, "waveA_len": waveA_len, "wave5_high": wave5_high, "wave1_low": wave1_low, "swings": swings}

    def check_pattern_15m(self, df_15m, i):
        if i < 1:
            return None
        curr = df_15m.iloc[i]; prev = df_15m.iloc[i-1]
        o, h, l, c = float(curr["open"]), float(curr["high"]), float(curr["low"]), float(curr["close"])
        po, pc = float(prev["open"]), float(prev["close"])
        body = abs(c - o); upper = h - max(o, c); lower = min(o, c) - l
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
            mult = 1.618; base_len = wave1_len if wave1_len > 0 else entry * 0.01
            tp = entry + mult * base_len if side == "LONG" else entry - mult * base_len
        elif wave == "5":
            mult = 1.0; base_len = wave1_len if wave1_len > 0 else entry * 0.01
            tp = entry + mult * base_len if side == "LONG" else entry - mult * base_len
        elif wave in ("A", "C"):
            mult = 1.0; base_len = waveA_len if waveA_len > 0 else (wave1_len if wave1_len > 0 else entry * 0.01)
            tp = entry - mult * base_len if side == "SHORT" else entry + mult * base_len
        elif wave == "B":
            mult = 1.0; base_len = waveA_len if waveA_len > 0 else entry * 0.01
            tp = entry + mult * base_len if side == "LONG" else entry - mult * base_len
        else:
            mult = 1.0; base_len = wave1_len if wave1_len > 0 else entry * 0.01
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

    # ---------- Compat สำหรับ main V6.1 ----------
    def check_smc(self, df):
        # คืนค่าแบบ SMC Checklist 6 ข้อ แบบง่าย ใช้ EMA + Swing
        try:
            if df is None or len(df) < 5:
                return {"score": 0, "bos": False, "choch": False, "trend": "UNKNOWN"}
            last = df.iloc[-1]
            ema_fast = float(last["ema_fast"]); ema_slow = float(last["ema_slow"]); adx = float(last["adx"])
            score = 0
            if ema_fast > ema_slow: score += 1
            if adx >= self.config["adx_min"]: score += 1
            if float(last["di_plus"]) >= self.config["di_min"]: score += 1
            # BOS / CHoCH จาก Swing ล่าสุด
            swings = self.detect_swings(df.tail(60)) if len(df) >= 20 else []
            bos = len(swings) >= 2 and swings[-1]["price"] > swings[-2]["price"] if swings else False
            return {"score": score, "bos": bool(bos), "choch": False, "trend": "UP" if ema_fast > ema_slow else "DOWN", "swings": swings}
        except Exception:
            return {"score": 0, "bos": False, "choch": False, "trend": "UNKNOWN"}

    def check_trend(self, curr, prev, smc=None):
        try:
            ema_fast = float(curr["ema_fast"]); ema_slow = float(curr["ema_slow"])
            adx = float(curr.get("adx", 0)); di_p = float(curr.get("di_plus", curr.get("plus_di", 0))); di_m = float(curr.get("di_minus", curr.get("minus_di", 0)))
            close = float(curr["close"])
            sideway = adx < self.config["adx_min"]
            # Retest = ราคาอยู่ใกล้ EMA Slow ภายใน 0.9%
            retest = abs(close - ema_slow) / ema_slow <= self.config["retest_pct"] if ema_slow else False
            long_cond = (ema_fast > ema_slow) and (adx >= self.config["adx_min"]) and (di_p >= self.config["di_min"])
            short_cond = (ema_fast < ema_slow) and (adx >= self.config["adx_min"]) and (di_m >= self.config["di_min"])
            return {"long": bool(long_cond and not sideway), "short": bool(short_cond and not sideway), "sideway": bool(sideway), "retest": bool(retest), "reasons": []}
        except Exception:
            return {"long": False, "short": False, "sideway": True, "retest": False, "reasons": []}

    def check_momentum(self, curr):
        try:
            close = float(curr["close"]); ema_fast = float(curr["ema_fast"])
            return {"long": bool(close > ema_fast), "short": bool(close < ema_fast)}
        except Exception:
            return {"long": False, "short": False}

    def check_reversal(self, prev, curr):
        try:
            prev_fast = float(prev["ema_fast"]); prev_slow = float(prev["ema_slow"])
            curr_fast = float(curr["ema_fast"]); curr_slow = float(curr["ema_slow"])
            long_rev = prev_fast <= prev_slow and curr_fast > curr_slow
            short_rev = prev_fast >= prev_slow and curr_fast < curr_slow
            return {"long": bool(long_rev), "short": bool(short_rev)}
        except Exception:
            return {"long": False, "short": False}

    def check_exit_trend_change(self, curr, prev, sig, smc=None, df=None):
        # ถ้า EMA กลับทิศ = ออก
        try:
            ema_fast = float(curr["ema_fast"]); ema_slow = float(curr["ema_slow"])
            if sig == "LONG" and ema_fast < ema_slow:
                return {"tp": True, "reasons": ["EMA_FLIP"]}
            if sig == "SHORT" and ema_fast > ema_slow:
                return {"tp": True, "reasons": ["EMA_FLIP"]}
            return {"tp": False, "reasons": []}
        except Exception:
            return {"tp": False, "reasons": []}

    def get_trailing_sl(self, entry, price, cdc_stop, side):
        try:
            sl_pct = self.config["sl_pct"]
            base_sl = entry * (1 - sl_pct) if side == "LONG" else entry * (1 + sl_pct)
            if side == "LONG":
                # ถ้ากำไรแล้ว ขยับ SL ขึ้นตาม cdc_stop แต่ไม่ต่ำกว่า base และไม่เกิน entry ถ้ายังไม่ถึง BE trigger
                tsl = max(base_sl, float(cdc_stop) if cdc_stop else base_sl)
                if price > entry * (1 + self.config["be_trigger"]):
                    tsl = max(tsl, entry)  # BE
                # กัน SL เกินราคา
                return float(min(tsl, price * 0.999))
            else:
                tsl = min(base_sl, float(cdc_stop) if cdc_stop else base_sl)
                if price < entry * (1 - self.config["be_trigger"]):
                    tsl = min(tsl, entry)
                return float(max(tsl, price * 1.001))
        except Exception:
            return float(entry * (1 - sl_pct) if side == "LONG" else entry * (1 + sl_pct))

# Alias ให้ main ทุกเวอร์ชันเรียกได้
Strategy_G_PowerMulti = Strategy_G_Power
StrategyMulti = Strategy_G_Power
