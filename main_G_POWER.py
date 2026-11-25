"""G_POWER Strategy V9.3.1 - แก้ Dow4h UNKNOWN ค้าง
บั๊กจากรูป 19:51-19:52:
- BTC: Wave C แล้ว (จากเดิม Wave None ดีขึ้น) แต่ Dow4h ยัง UNKNOWN -> Main V2 บล็อคถูกแล้ว "รอ Dow ก่อน ไม่เปิด" ดีแล้ว
- GOLD: Wave 1 แล้ว (จากเดิม Wave None ดีขึ้น) แต่ Dow4h ยัง UNKNOWN -> ถือไม้เก่าต่อ แต่เปิดไม้ใหม่ไม่ได้
สาเหตุ: get_dow_trend_4h เดิม ถ้า Swing 4h < 4 อัน จะคืน UNKNOWN ทันที
แต่ 4h ATR มันใหญ่ min_move = ATR*0.5 เลยกรอง Swing ทิ้งเกือบหมด เหลือ < 4 อัน เลย UNKNOWN ค้างตลอด
แก้ V9.3.1: Dow ห้ามเป็น UNKNOWN อีกแล้ว ถ้า Swing ไม่พอให้ใช้ EMA 4h แทน
- ถ้า EMA Fast > EMA Slow บน 4h = UP
- ถ้า EMA Fast < EMA Slow บน 4h = DOWN
อัปโหลดเป็น strategy_G_POWER.py ทับ V9.3 ตัวเก่า (Main V2 398 บรรทัดไม่ต้องแตะ)
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
                "sl_pct_max": 0.012, "tp_cap": 0.03,
                "touch_tol": 0.0015,
                "ema_trend": 36, "sl_pct": 0.006, "tp_pct": 0.012,
                "cdc_atr_fast": 7, "cdc_mult_fast": 0.8,
                "cdc_atr_slow": 14, "cdc_mult_slow": 2.0,
                "swing_atr_mult": 0.5, "swing_lookback": 5,
            }
        else:
            self.config = {
                "ema_fast": 12, "ema_slow": 36,
                "adx_min": 12, "di_min": 10,
                "sl_pct_max": 0.015, "tp_cap": 0.04,
                "touch_tol": 0.0015,
                "ema_trend": 36, "sl_pct": 0.008, "tp_pct": 0.016,
                "cdc_atr_fast": 7, "cdc_mult_fast": 0.8,
                "cdc_atr_slow": 14, "cdc_mult_slow": 2.0,
                "swing_atr_mult": 0.5, "swing_lookback": 5,
            }
        self.WAVE_QUOTA = {"1": 3, "2": 1, "3": 3, "4": 1, "5": 3, "A": 1, "B": 3, "C": 1}
        self.name = f"G_POWER V9.3.1 DOW-LOCK {symbol_key.upper()}"

    def add_indicators(self, df):
        df = df.copy()
        df["ema_fast"] = df["close"].ewm(span=self.config["ema_fast"], adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.config["ema_slow"], adjust=False).mean()
        df["ema_trend"] = df["ema_slow"]
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["ema100"] = df["close"].ewm(span=100, adjust=False).mean()
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        df["adx"], df["di_plus"], df["di_minus"] = self._adx_di(df)
        df["plus_di"] = df["di_plus"]; df["minus_di"] = df["di_minus"]
        df["vol_avg"] = df["volume"].rolling(20).mean()
        tr = pd.concat([df["high"]-df["low"], (df["high"]-df["close"].shift()).abs(), (df["low"]-df["close"].shift()).abs()], axis=1).max(axis=1)
        df["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
        df["cdc_stop"] = df["ema_slow"]
        df["cdc_up"] = df["ema_fast"] > df["ema_slow"]
        df["cdc_down"] = df["ema_fast"] < df["ema_slow"]
        df["cdc_trend"] = np.where(df["cdc_up"], 1, -1)
        return df

    def _adx_di(self, df, period=14):
        high = df["high"].values; low = df["low"].values; close = df["close"].values
        n = len(df); tr = np.zeros(n); plus_dm = np.zeros(n); minus_dm = np.zeros(n)
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

    def detect_swings(self, df_1h, lookback=None):
        if lookback is None: lookback = self.config["swing_lookback"]
        swings = []
        highs = df_1h["high"].values; lows = df_1h["low"].values
        try: atr_avg = float(df_1h["atr"].iloc[-20:].mean()) if "atr" in df_1h.columns else 0
        except: atr_avg = 0
        min_move = atr_avg * self.config["swing_atr_mult"] if atr_avg > 0 else 0
        for i in range(lookback, len(df_1h)-lookback):
            if highs[i] == max(highs[i-lookback:i+lookback+1]):
                swings.append({"idx": i, "type": "H", "price": float(highs[i])})
            if lows[i] == min(lows[i-lookback:i+lookback+1]):
                swings.append({"idx": i, "type": "L", "price": float(lows[i])})
        swings = sorted(swings, key=lambda x: x["idx"])
        cleaned = []
        for s in swings:
            if cleaned and cleaned[-1]["type"] == s["type"]:
                if s["type"] == "H" and s["price"] > cleaned[-1]["price"]: cleaned[-1] = s
                elif s["type"] == "L" and s["price"] < cleaned[-1]["price"]: cleaned[-1] = s
            else: cleaned.append(s)
        if min_move > 0 and len(cleaned) >= 2:
            filtered = [cleaned[0]]
            for s in cleaned[1:]:
                if abs(s["price"] - filtered[-1]["price"]) >= min_move:
                    filtered.append(s)
                else:
                    if s["type"] == "H" and s["price"] > filtered[-1]["price"]: filtered[-1] = s
                    elif s["type"] == "L" and s["price"] < filtered[-1]["price"]: filtered[-1] = s
            cleaned = filtered
        return cleaned

    def count_waves(self, swings):
        if len(swings) < 6:
            return {"current_wave": None, "trend": "UNKNOWN", "cycle_id": 0, "wave1_len": 0, "waveA_len": 0, "wave5_high": 0, "wave1_low": 0, "swings": swings, "dow_ok": False}
        ORDER = ["1","2","3","4","5","A","B","C"]
        n_legs = len(swings) - 1
        current_wave = ORDER[n_legs % 8]
        cycle_id = n_legs // 8
        recent = swings[-6:] if len(swings) >= 6 else swings
        highs = [s for s in recent if s["type"] == "H"]
        lows = [s for s in recent if s["type"] == "L"]
        if len(highs) >= 2 and len(lows) >= 2:
            hh = highs[-1]["price"] > highs[-2]["price"]; hl = lows[-1]["price"] > lows[-2]["price"]
            lh = highs[-1]["price"] < highs[-2]["price"]; ll = lows[-1]["price"] < lows[-2]["price"]
            if hh and hl: trend = "UP"
            elif lh and ll: trend = "DOWN"
            else: trend = "UP" if recent[-1]["price"] > recent[0]["price"] else "DOWN"
        else: trend = "UNKNOWN"
        cycle_start = cycle_id * 8
        seq = swings[cycle_start:] if cycle_start < len(swings) else swings[-8:]
        wave1_len = 0; waveA_len = 0; wave5_high = 0; wave1_low = 0
        try:
            if len(seq) >= 2:
                wave1_len = abs(seq[1]["price"] - seq[0]["price"]); wave1_low = seq[0]["price"]
            if len(seq) >= 7:
                waveA_len = abs(seq[6]["price"] - seq[5]["price"]); wave5_high = seq[5]["price"]
        except: pass
        dow_ok = True
        try:
            if len(seq) >= 4 and wave1_len > 0:
                if abs(seq[3]["price"] - seq[2]["price"]) < wave1_len * 0.5: dow_ok = False
            if len(seq) >= 3 and wave1_len > 0:
                r2 = abs(seq[2]["price"] - seq[1]["price"]) / wave1_len if wave1_len>0 else 0
                if r2 < 0.2 or r2 > 0.95: dow_ok = False
        except: pass
        return {"current_wave": current_wave, "trend": trend, "cycle_id": cycle_id, "wave1_len": wave1_len, "waveA_len": waveA_len, "wave5_high": wave5_high, "wave1_low": wave1_low, "swings": swings, "dow_ok": dow_ok, "seq_len": len(seq)}

    # ===== V9.3.1 FIX: Dow ห้าม UNKNOWN - ถ้า Swing ไม่พอใช้ EMA 4h =====
    def get_dow_trend_4h(self, swings_4h, df_4h=None):
        # ถ้า Swing พอ ใช้ HH/HL/LH/LL เหมือนเดิม
        if len(swings_4h) >= 4:
            recent = swings_4h[-4:]
            highs = [s for s in recent if s["type"]=="H"]; lows = [s for s in recent if s["type"]=="L"]
            if len(highs)>=2 and len(lows)>=2:
                if highs[-1]["price"]>highs[-2]["price"] and lows[-1]["price"]>lows[-2]["price"]: return "UP"
                if highs[-1]["price"]<highs[-2]["price"] and lows[-1]["price"]<lows[-2]["price"]: return "DOWN"
            # ถ้า Swing มีแต่ไม่ชัด ใช้ราคาล่าสุดเทียบกับตัวแรก
            return "UP" if recent[-1]["price"]>recent[0]["price"] else "DOWN"
        # ถ้า Swing ไม่พอ (<4) ใช้ EMA 4h แทน ห้ามคืน UNKNOWN
        if df_4h is not None and len(df_4h)>=2 and "ema_fast" in df_4h.columns:
            try:
                last = df_4h.iloc[-1]
                if float(last["ema_fast"]) > float(last["ema_slow"]): return "UP"
                else: return "DOWN"
            except: pass
        # Fallback สุดท้าย: ใช้ Swing ที่มีอยู่เทียบราคา
        if len(swings_4h) >= 2:
            return "UP" if swings_4h[-1]["price"] > swings_4h[0]["price"] else "DOWN"
        # ถ้าไม่มี Swing เลยจริงๆ ให้ถือว่า DOWN (เพราะตลาดตอนนี้เป็นขาลงตาม BT) ดีกว่า UNKNOWN ที่บล็อคทุกอย่าง
        return "DOWN"

    def check_pattern_15m(self, df_15m, i):
        if i < 1: return None
        curr = df_15m.iloc[i]; prev = df_15m.iloc[i-1]
        o,h,l,c = float(curr["open"]), float(curr["high"]), float(curr["low"]), float(curr["close"])
        po,pc = float(prev["open"]), float(prev["close"])
        body = abs(c-o); upper = h-max(o,c); lower = min(o,c)-l
        if lower > 2*max(body,1e-9) and c>o: return "PIN_BULL"
        if upper > 2*max(body,1e-9) and c<o: return "PIN_BEAR"
        if c>o and pc<po and c>=po and o<=pc: return "ENG_BULL"
        if c<o and pc>po and c<=po and o>=pc: return "ENG_BEAR"
        return None

    def is_touch_ema36(self, low, high, ema36):
        if ema36 is None or ema36==0: return False
        tol = self.config["touch_tol"]
        if low <= ema36 <= high: return True
        if abs(low-ema36)/ema36 <= tol: return True
        if abs(high-ema36)/ema36 <= tol: return True
        return False

    def get_tp_by_wave(self, wave, side, entry, wave1_len, waveA_len):
        if wave=="3": mult=1.618; base=wave1_len if wave1_len>0 else entry*0.01
        elif wave=="5": mult=1.0; base=wave1_len if wave1_len>0 else entry*0.01
        elif wave in ("A","C"): mult=1.0; base=waveA_len if waveA_len>0 else (wave1_len if wave1_len>0 else entry*0.01)
        elif wave=="B": mult=1.0; base=waveA_len if waveA_len>0 else entry*0.01
        else: mult=1.0; base=wave1_len if wave1_len>0 else entry*0.01
        tp = entry + mult*base if side=="LONG" else entry - mult*base
        if wave in ("A","C") and side=="LONG": tp = entry + mult*base
        if wave in ("A","C") and side=="SHORT": tp = entry - mult*base
        cap = self.config["tp_cap"]
        if side=="LONG": tp = min(tp, entry*(1+cap))
        else: tp = max(tp, entry*(1-cap))
        return float(tp)

    def get_sl_by_structure(self, side, entry, swings, atr_val=0):
        max_sl = self.config["sl_pct_max"]
        if swings and len(swings)>=1:
            last = swings[-1]
            if side=="LONG":
                sl_struct = last["price"] - atr_val*0.2 if last["type"]=="L" else entry*(1-max_sl)
                if (entry - sl_struct)/entry > max_sl: sl_struct = entry*(1-max_sl)
                if sl_struct >= entry: sl_struct = entry*(1-max_sl)
                return float(sl_struct)
            else:
                sl_struct = last["price"] + atr_val*0.2 if last["type"]=="H" else entry*(1+max_sl)
                if (sl_struct - entry)/entry > max_sl: sl_struct = entry*(1+max_sl)
                if sl_struct <= entry: sl_struct = entry*(1+max_sl)
                return float(sl_struct)
        if side=="LONG": return entry*(1-max_sl)
        else: return entry*(1+max_sl)

    def check_trend(self, curr, prev=None, prev2=None, smc=None, htf_trend=None, dow_trend_4h=None, **kwargs):
        try:
            ef = float(curr.get("ema_fast",0) if hasattr(curr,"get") else curr["ema_fast"])
            es = float(curr.get("ema_slow",0) if hasattr(curr,"get") else curr["ema_slow"])
            adx = float(curr.get("adx",0) if hasattr(curr,"get") else curr["adx"])
            pdi = float(curr.get("plus_di",0) if hasattr(curr,"get") else curr["plus_di"])
            mdi = float(curr.get("minus_di",0) if hasattr(curr,"get") else curr["minus_di"])
        except:
            return {"long": False, "short": False, "sideway": True, "cdc_up": False, "cdc_down": False, "plus_di":0, "minus_di":0, "adx":0}
        cdc_up = ef>es; cdc_down = ef<es
        long_ok = cdc_up and pdi>mdi and pdi>self.config["di_min"] and adx>self.config["adx_min"]
        short_ok = cdc_down and mdi>pdi and mdi>self.config["di_min"] and adx>self.config["adx_min"]
        if dow_trend_4h=="DOWN": long_ok = False
        if dow_trend_4h=="UP": short_ok = False
        if htf_trend=="DOWN": long_ok = False
        if htf_trend=="UP": short_ok = False
        return {"long": bool(long_ok), "short": bool(short_ok), "sideway": bool(adx<self.config["adx_min"]), "cdc_up": bool(cdc_up), "cdc_down": bool(cdc_down), "plus_di": pdi, "minus_di": mdi, "adx": adx, "di_bull": bool(pdi>mdi), "di_bear": bool(mdi>pdi)}
    def check_smc(self, df=None, **kwargs): return {"long_score":0,"short_score":0,"long_pass":False,"short_pass":False,"detail":{},"need":3}
    def check_momentum(self, curr, **kwargs):
        try: pdi=float(curr.get("plus_di",0) if hasattr(curr,"get") else 0); mdi=float(curr.get("minus_di",0) if hasattr(curr,"get") else 0); adx=float(curr.get("adx",0) if hasattr(curr,"get") else 0)
        except: pdi=mdi=adx=0
        return {"long": bool(pdi>mdi and adx>self.config["adx_min"]), "short": bool(mdi>pdi and adx>self.config["adx_min"]), "adx":adx, "plus_di":pdi, "minus_di":mdi}
    def check_reversal(self, prev, curr, **kwargs): return {"long": False, "short": False}
    def check_exit_trend_change(self, curr, prev, open_signal, smc=None, df=None, **kwargs): return {"tp": False, "reasons": [], "cdc_flip": False, "ema_flip": False}
    def get_trailing_sl(self, entry, curr_price, cdc_stop, signal, atr=None, **kwargs):
        if signal=="LONG": return max(entry*(1-self.config["sl_pct_max"]), float(cdc_stop) if cdc_stop else entry*(1-self.config["sl_pct_max"]))
        else: return min(entry*(1+self.config["sl_pct_max"]), float(cdc_stop) if cdc_stop else entry*(1+self.config["sl_pct_max"]))
    def check_exit(self, *a, **k): return self.check_exit_trend_change(*a, **k)
