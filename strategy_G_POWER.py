"""
G_POWER V5.0 TREND FOLLOWING - ADX + DI ล้วน (ไม่มี RSI / Volume แล้ว)
1. จุดเข้าแม่น - Retest + ADX + DI + CDC + EMA
2. ยังอยู่ในเทรน -> Trailing SL กันทุน/กำไร (BE -> Lock -> CDC Trail)
3. TP เมื่อเปลี่ยนเทรน - CDC Flip / EMA Cross / DI Cross
"""

import pandas as pd
import numpy as np

class Strategy_G_Power:
    def __init__(self, symbol_key="btc"):
        self.symbol_key = symbol_key
        self.name = f"G_POWER V5.0 TREND {symbol_key.upper()}"
        base = {
            "btc": {
                # BTC นิสัย: เร็ว + เหวี่ยงแรง + หลอกบ่อย (15m ATR% ~0.8-1.2% vs GOLD ~0.3-0.5%)
                # เลยต้อง: EMA เร็วกว่า GOLD นิดนึง / ADX สูงกว่า (กรองหลอก) / Retest กว้างกว่า (noise ใหญ่) / ห้ามไล่กว้างกว่า (BTC ยืดได้ 3%)
                "ema_fast": 15, "ema_slow": 40, "ema_trend": 80, "ema50": 50, "ema100": 100, "ema200": 200, "smc_min_score": 4,
                "adx_min": 15, "adx_sideway": 15, "adx_turbo": 30,
                "di_min": 12, "di_turbo": 22,
                "sl_pct": 0.034, "tp_pct": 0.18,
                "cdc_atr_fast": 7, "cdc_mult_fast": 0.8,
                "cdc_atr_slow": 14, "cdc_mult_slow": 2.0,
                "sideway_pct": 1.5,
                "retest_pct": 0.009, "max_extension_pct": 3.0,
                "be_trigger": 0.01,
                "lock_trigger": 0.02,
                "lock_pct": 0.005,
            },
            "gold": {
                # GOLD นิสัย: ช้า + เทรนด์เนียน + เคารพ EMA/CDC (15m ATR% ~0.3-0.5%)
                # เลย: EMA ช้า / ADX ต่ำกว่า / Retest แคบ / ห้ามไล่แคบ
                "ema_fast": 21, "ema_slow": 55, "ema_trend": 100, "ema50": 50, "ema100": 100, "ema200": 200, "smc_min_score": 4,
                "adx_min": 12, "adx_sideway": 12, "adx_turbo": 26,
                "di_min": 10, "di_turbo": 20,
                "sl_pct": 0.028, "tp_pct": 0.12,
                "cdc_atr_fast": 10, "cdc_mult_fast": 1.0,
                "cdc_atr_slow": 20, "cdc_mult_slow": 2.5,
                "sideway_pct": 1.2,
                "retest_pct": 0.006, "max_extension_pct": 2.0,
                "be_trigger": 0.008, "lock_trigger": 0.015, "lock_pct": 0.004,
            },
        }
        self.config = base.get(symbol_key, base["btc"])

    def _ema(self, s, p): return s.ewm(span=p, adjust=False).mean()
    def _atr(self, h,l,c,p=14):
        tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        return tr.ewm(alpha=1/p, adjust=False).mean()
    def _adx_di(self, h,l,c,p=14):
        up=h.diff(); down=-l.diff()
        pdm=pd.Series([u if (u>d and u>0) else 0 for u,d in zip(up,down)], index=h.index).ewm(alpha=1/p, adjust=False).mean()
        mdm=pd.Series([d if (d>u and d>0) else 0 for u,d in zip(up,down)], index=h.index).ewm(alpha=1/p, adjust=False).mean()
        tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1).ewm(alpha=1/p, adjust=False).mean()
        pdi=100*pdm/tr; mdi=100*mdm/tr
        dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
        adx=dx.ewm(alpha=1/p, adjust=False).mean().fillna(15)
        return pdi.fillna(0), mdi.fillna(0), adx, adx.diff(3)

    def _cdc(self, df):
        c=self.config
        af=self._atr(df['high'],df['low'],df['close'],c["cdc_atr_fast"])
        asl=self._atr(df['high'],df['low'],df['close'],c["cdc_atr_slow"])
        ls_f=df['close']-af*c["cdc_mult_fast"]; ss_f=df['close']+af*c["cdc_mult_fast"]
        ls_s=df['close']-asl*c["cdc_mult_slow"]; ss_s=df['close']+asl*c["cdc_mult_slow"]
        ls=pd.concat([ls_f,ls_s],axis=1).max(axis=1); ss=pd.concat([ss_f,ss_s],axis=1).min(axis=1)
        trend=np.zeros(len(df),dtype=int); stop=np.zeros(len(df))
        trend[0]=1; stop[0]=ls.iloc[0]
        for i in range(1,len(df)):
            if df['close'].iloc[i]>stop[i-1] and trend[i-1]==1:
                trend[i]=1; stop[i]=max(ls.iloc[i],stop[i-1])
            elif df['close'].iloc[i]<stop[i-1] and trend[i-1]==-1:
                trend[i]=-1; stop[i]=min(ss.iloc[i],stop[i-1])
            else:
                if trend[i-1]==1:
                    if df['close'].iloc[i]<ls.iloc[i]: trend[i]=-1; stop[i]=ss.iloc[i]
                    else: trend[i]=1; stop[i]=max(ls.iloc[i],stop[i-1])
                else:
                    if df['close'].iloc[i]>ss.iloc[i]: trend[i]=1; stop[i]=ls.iloc[i]
                    else: trend[i]=-1; stop[i]=min(ss.iloc[i],stop[i-1])
        return pd.Series(trend,index=df.index), pd.Series(stop,index=df.index), trend==1

    def add_indicators(self, df):
        df=df.copy()
        c=self.config
        df['ema_fast']=self._ema(df['close'],c["ema_fast"])
        df['ema_slow']=self._ema(df['close'],c["ema_slow"])
        df['ema_trend']=self._ema(df['close'],c["ema_trend"])
        # SMC Trend: EMA 50/100/200 ของพี่ (ดูเทรนด์หลัก)
        df['ema50']=self._ema(df['close'],50)
        df['ema100']=self._ema(df['close'],100)
        df['ema200']=self._ema(df['close'],200)
        df['atr']=self._atr(df['high'],df['low'],df['close'],14)
        pdi,mdi,adx,adx_s=self._adx_di(df['high'],df['low'],df['close'],14)
        df['plus_di']=pdi; df['minus_di']=mdi; df['adx']=adx; df['adx_slope']=adx_s
        tr, st, up=self._cdc(df)
        df['cdc_trend']=tr; df['cdc_stop']=st; df['cdc_up']=up
        df['dist_ema_fast']= (df['close']-df['ema_fast']).abs()/df['close']
        df['cdc_dist_pct']=(df['close']-df['cdc_stop'])/df['close']*100
        return df

    # SMC Checklist 6 ข้อ (ตามที่พี่ใช้) - รับ df ทั้งก้อนเพื่อดูโครงสร้างย้อนหลัง
    def check_smc(self, df):
        # df ต้องผ่าน add_indicators แล้ว มี ema50/100/200, high/low/close
        if df is None or len(df) < 30:
            return {"long_score": 0, "short_score": 0, "long_pass": False, "short_pass": False, "detail": {}, "need": self.config.get("smc_min_score", 4)}
        curr = df.iloc[-1]; prev = df.iloc[-2]
        close = float(curr["close"]); high = float(curr["high"]); low = float(curr["low"])
        ema50=float(curr["ema50"]); ema100=float(curr["ema100"]); ema200=float(curr["ema200"])
        # --- 6) เทรนด์หลัก EMA 50/100/200 ---
        trend_long = ema50 > ema100 > ema200 and close > ema50
        trend_short = ema50 < ema100 < ema200 and close < ema50
        # --- 1) CHoCH / BOS: เบรก Swing High/Low 10 แท่งย้อนหลัง ---
        look = df.iloc[-11:-1]  # 10 แท่งก่อนแท่งปัจจุบัน
        swing_high = float(look["high"].max()); swing_low = float(look["low"].min())
        # BOS = เบรกตามเทรนด์, CHoCH = เบรกสวนเทรนด์ (ใช้รวมกันเป็นข้อ 1 ตาม Checklist พี่)
        bos_long = close > swing_high
        bos_short = close < swing_low
        # CHoCH: ถ้าเทรนด์ลงอยู่แต่เบรก High = CHoCH ขึ้น, เทรนด์ขึ้นอยู่แต่เบรก Low = CHoCH ลง
        choch_long = bos_long and (ema50 < ema100)  # เดิมลงอยู่ เบรกขึ้น = เปลี่ยนคาแรคเตอร์
        choch_short = bos_short and (ema50 > ema100)
        check1_long = bos_long or choch_long
        check1_short = bos_short or choch_short
        # --- 2) FVG: ช่องว่างราคา 3 แท่งย้อนหลัง ---
        fvg_long = False; fvg_short = False
        for i in range(max(2, len(df)-4), len(df)):
            # Bullish FVG: low[i] > high[i-2]
            try:
                if float(df.iloc[i]["low"]) > float(df.iloc[i-2]["high"]): fvg_long = True
                if float(df.iloc[i]["high"]) < float(df.iloc[i-2]["low"]): fvg_short = True
            except: pass
        # FVG ต้องอยู่ใกล้ราคาปัจจุบัน (ห่างไม่เกิน 1.5% สำหรับ BTC, 0.8% GOLD) ถึงนับ
        # ใช้แบบง่าย: ถ้ามี FVG ใน 3 แท่งล่าสุดให้นับเลย เพราะเพิ่งเกิด
        # --- 3) Discount / Premium: Swing 50 แท่ง ---
        w = df.iloc[-50:]
        sh = float(w["high"].max()); sl = float(w["low"].min())
        mid = (sh + sl) / 2
        # Fibonacci 61.8 / 78.6 ของ Swing: สำหรับ LONG ต้องอยู่ Discount (<50%) ดีสุดคือแถว 61.8-78.6% retracement จาก High
        # คิดแบบ Swing Low->High: retracement = (sh - close)/(sh-sl)
        retr = (sh - close) / (sh - sl) if (sh-sl) != 0 else 0.5
        discount_long = close < mid  # อยู่โซน Discount
        premium_short = close > mid  # อยู่โซน Premium
        # โซนทอง 61.8-78.6%: retracement 0.618-0.886 = จุดที่ SMC บอกว่า 61.8 คือ BSL / 78.6 คือ IDM ดักหลอก ต้องระวัง
        in_golden = 0.618 <= retr <= 0.886
        # สำหรับ LONG: ถ้าอยู่ใน Golden + Discount = ดี, สำหรับ SHORT: ถ้าอยู่ Premium + Golden = ดี (แต่ถ้าเป็น IDM หลอก ต้องมี Sweep ยืนยัน)
        check3_long = discount_long
        check3_short = premium_short
        # --- 4) Fresh OB: Order Block ยังไม่เคยถูกใช้ = ยังไม่โดนทะลุ ---
        # OB คือแท่งก่อนเบรก (prev) - Fresh ถ้าราคายังไม่เคยปิดทะลุ OB นั้น (แค่แตะแล้วเด้งกลับ ยังถือว่า Fresh)
        # แบบเดิมที่เช็คแค่แตะ จะบล็อกทุกไม้ เพราะราคาต้องแตะ OB อยู่แล้วตอน Pullback
        fresh_long = True; fresh_short = True
        try:
            ob_high = float(prev["high"]); ob_low = float(prev["low"])
            hist = df.iloc[-12:-1]  # 11 แท่งก่อนแท่งปัจจุบัน
            # นับปิดใน OB: ถ้าปิดใน OB 2 แท่งติด = OB ถูกใช้แล้ว / แค่แตะแล้วเด้งกลับ ยัง Fresh
            inside = ((hist["close"] >= ob_low) & (hist["close"] <= ob_high)).astype(int)
            # เช็ค 2 แท่งติด
            used = False
            for k in range(len(inside)-1):
                if inside.iloc[k]==1 and inside.iloc[k+1]==1: used=True; break
            fresh_long = not used; fresh_short = not used
        except: pass
        # --- 5) IDM / Liquidity Sweep: กวาด High/Low แล้วปิดกลับ ---
        # Sweep High: high แท่งล่าสุด > swing_high เก่า แต่ close < swing_high (กวาดแล้วโดนตบกลับ) = IDM หลอกขาขึ้น -> เตรียม SHORT
        # Sweep Low: low < swing_low เก่า แต่ close > swing_low = IDM หลอกขาลง -> เตรียม LONG
        sweep_high = high > swing_high and close < swing_high
        sweep_low = low < swing_low and close > swing_low
        check5_long = sweep_low  # กวาด Low แล้วดีดกลับ = สะสม Long
        check5_short = sweep_high  # กวาด High แล้วร่วงกลับ = สะสม Short
        # --- รวมคะแนน ---
        long_checks = [check1_long, fvg_long, check3_long, fresh_long, check5_long, trend_long]
        short_checks = [check1_short, fvg_short, check3_short, fresh_short, check5_short, trend_short]
        long_score = sum(1 for x in long_checks if x)
        short_score = sum(1 for x in short_checks if x)
        need = self.config.get("smc_min_score", 4)
        detail = {
            "choch_bos_long": bool(check1_long), "choch_bos_short": bool(check1_short),
            "fvg_long": bool(fvg_long), "fvg_short": bool(fvg_short),
            "discount_long": bool(check3_long), "premium_short": bool(check3_short), "retr_pct": round(retr*100,1), "in_golden_618_886": bool(in_golden),
            "fresh_ob": bool(fresh_long),
            "sweep_low_long": bool(check5_long), "sweep_high_short": bool(check5_short),
            "trend_long_ema501001200": bool(trend_long), "trend_short_ema501001200": bool(trend_short),
            "swing_high": swing_high, "swing_low": swing_low,
        }
        return {"long_score": long_score, "short_score": short_score, "long_pass": long_score >= need, "short_pass": short_score >= need, "detail": detail, "need": need, "long_checks": long_checks, "short_checks": short_checks}

    # Pattern TP: วัดระยะ Pattern ที่พรีดิก TP ได้ (Flag/Triangle/Double/QML/SMC Liquidity)
    # Pattern แท่งเทียนเดี่ยว (Engulfing/Pin Bar/Doji) วัด TP ไม่ได้ -> return None ให้ใช้ TP ตายตัวเดิม
    def get_pattern_tp(self, df, signal, pattern_name=""):
        if df is None or len(df) < 20: return None
        try:
            curr = df.iloc[-1]; close=float(curr["close"])
            # Swing 30 แท่ง: ใช้วัดระยะ Pattern
            w30 = df.iloc[-30:]; swing_high=float(w30["high"].max()); swing_low=float(w30["low"].min()); swing_range=swing_high-swing_low
            w20 = df.iloc[-20:]; base=float(w20["high"].max())-float(w20["low"].min())
            # EMA200 = แนวต้าน/รับถัดไป (Liquidity) - ถ้า Pattern TP เลย EMA200 ให้ตัด TP ไว้ก่อน EMA200
            ema200=float(curr.get("ema200", close))
            name=(pattern_name or "").lower()
            factor=None; tp=None
            if "flag" in name or "pennant" in name:
                # Flag: TP = วัดเสาธง (Swing 30) ต่อจากจุดเบรก
                factor=1.0; tp=close + swing_range*factor if signal=="LONG" else close - swing_range*factor
            elif "triangle" in name:
                # Triangle: TP = ฐานสามเหลี่ยม (20 แท่ง)
                factor=1.0; tp=close + base*factor if signal=="LONG" else close - base*factor
            elif "double" in name:
                # Double Top/Bottom: TP = ระยะยอด -> Neckline (ใช้ Swing 30)
                factor=1.0; tp=close + swing_range*factor if signal=="LONG" else close - swing_range*factor
            elif "qml" in name or "quasimodo" in name:
                # QML: TP = OB ถัดไป (ไหล่ -> หัว) ใช้ 1.2 เท่าของ Swing เพราะ QML ยืดไปถึง 88.6%
                factor=1.2; tp=close + swing_range*factor if signal=="LONG" else close - swing_range*factor
            elif "head" in name and "shoulder" in name:
                # H&S: TP = หัว -> Neckline
                factor=1.0; tp=close + swing_range*factor if signal=="LONG" else close - swing_range*factor
            elif "smc" in name or "liquidity" in name or "fvg" in name or "order_block" in name or "ob" in name:
                # SMC: TP = Liquidity ถัดไป = Swing High/Low เดิม หรือ EMA200
                if signal=="LONG":
                    tp=min(swing_high, ema200) if ema200>close else swing_high
                    # ถ้า TP ใกล้เกินไป (<0.5%) ให้ใช้ Swing แทน
                    if (tp-close)/close < 0.005: tp=swing_high
                else:
                    tp=max(swing_low, ema200) if ema200<close else swing_low
                    if (close-tp)/close < 0.005: tp=swing_low
                factor=0.0  # SMC ไม่ใช้ factor ใช้ Liquidity ตรงๆ
            else:
                return None  # Engulfing/Pin Bar/Doji/Morning Star วัด TP ไม่ได้
            # กัน TP เลย TP ตายตัวเดิม (BTC 18% / GOLD 12%) - ถ้า Pattern TP ไกลกว่า TP ตายตัว ให้ใช้ TP ตายตัวเป็นเพดาน
            max_tp_pct=self.config.get("tp_pct", 0.12)
            max_tp=close*(1+max_tp_pct) if signal=="LONG" else close*(1-max_tp_pct)
            if signal=="LONG": tp=min(tp, max_tp)
            else: tp=max(tp, max_tp)
            # กัน TP ใกล้เกินไป (<0.8% BTC / <0.5% GOLD) ไม่คุ้มค่าธรรมเนียม
            min_dist=0.008 if self.symbol_key=="btc" else 0.005
            if abs(tp-close)/close < min_dist: return None
            return {"tp": float(tp), "pattern": pattern_name, "factor": factor, "swing_range": swing_range, "max_tp": float(max_tp)}
        except Exception as e:
            return None

    # 1. จุดเข้าแม่น - Pullback แบบในรูป: เทรนด์ลง + ดีดกลับหา EMA Fast/CDC + Rejection กลับลง = S
    # S1/S2/S3 ในรูปคือจุดนี้ ไม่ใช่ S ตรงก้น
    def check_trend(self, curr, prev=None, prev2=None, smc=None):
        c=self.config
        ema_diff=abs(curr['ema_fast']-curr['ema_slow'])/curr['close']*100
        sideway=(curr['adx']<c["adx_sideway"]) or (ema_diff<c["sideway_pct"] and curr['adx']<c["adx_turbo"])
        # ห้ามไล่ตอนยืด: ราคาห่าง EMA Trend เกิน 2% = วิ่งไปไกลแล้ว ข้าม รอ Pullback
        ext=(curr['close']-curr['ema_trend'])/curr['close']*100
        extended=abs(ext)>c.get("max_extension_pct",2.0)
        # เทรนด์หลัก (ADX + DI ล้วน ไม่ใช้ RSI/Volume) - Turbo ไม่ Bypass เทรนด์แล้ว
        long_core=curr['cdc_up'] and curr['plus_di']>curr['minus_di'] and curr['plus_di']>c["di_min"] and curr['adx']>c["adx_min"] and curr['close']>curr['ema_trend']
        short_core=not curr['cdc_up'] and curr['minus_di']>curr['plus_di'] and curr['minus_di']>c["di_min"] and curr['adx']>c["adx_min"] and curr['close']<curr['ema_trend']
        # Pullback + Rejection: แท่งก่อนหน้าดีดขึ้นไปแตะ EMA Fast/CDC แล้วแท่งนี้ปิดกลับลงมา
        pull_short=False; pull_long=False
        if prev is not None:
            try:
                # SHORT: แท่งก่อน High แตะ EMA Fast/CDC (Pullback ขึ้น) + แท่งนี้ปิดต่ำกว่า EMA Fast + ปิดต่ำกว่าแท่งก่อน (Rejection)
                _prev_touch_high=max(float(prev.get('high',0)), float(prev.get('close',0)))>=float(prev.get('ema_fast',0))
                _prev_touch_cdc=float(prev.get('high',0))>=float(prev.get('cdc_stop',0)) if 'cdc_stop' in prev else False
                pull_short=(_prev_touch_high or _prev_touch_cdc) and float(curr['close'])<float(curr['ema_fast']) and float(curr['close'])<float(prev.get('close',0))
                # LONG: แท่งก่อน Low แตะ EMA Fast/CDC (Pullback ลง) + แท่งนี้ปิดสูงกว่า EMA Fast + ปิดสูงกว่าแท่งก่อน
                _prev_touch_low=min(float(prev.get('low',0)), float(prev.get('close',0)))<=float(prev.get('ema_fast',0))
                _prev_touch_cdc_l=float(prev.get('low',0))<=float(prev.get('cdc_stop',0)) if 'cdc_stop' in prev else False
                pull_long=(_prev_touch_low or _prev_touch_cdc_l) and float(curr['close'])>float(curr['ema_fast']) and float(curr['close'])>float(prev.get('close',0))
            except: pass
        # กรณี Pullback+Rejection ในแท่งเดียว: High แตะ EMA Fast แล้วปิดต่ำกว่า EMA Fast
        try:
            if float(curr.get('high',0))>=float(curr['ema_fast']) and float(curr['close'])<float(curr['ema_fast']):
                pull_short=True
            if float(curr.get('low',0))<=float(curr['ema_fast']) and float(curr['close'])>float(curr['ema_fast']):
                pull_long=True
        except: pass
        retest=curr['dist_ema_fast'] <= c["retest_pct"]
        # SMC Checklist 6 ข้อ: ถ้ามี smc ส่งมา ต้องผ่าน >=4/6 ถึงเข้า (ถ้าไม่ส่งมา = ใช้ Pullback เดิม ไม่กรอง SMC)
        smc_long_ok = True if smc is None else bool(smc.get("long_pass"))
        smc_short_ok = True if smc is None else bool(smc.get("short_pass"))
        long=long_core and pull_long and retest and not extended and smc_long_ok
        short=short_core and pull_short and retest and not extended and smc_short_ok
        return {"long":long, "short":short, "sideway":sideway and not (long or short), "retest":retest, "ema_diff":ema_diff, "long_core":long_core, "short_core":short_core, "pull_long":pull_long, "pull_short":pull_short, "extended":extended, "smc_long_ok":smc_long_ok, "smc_short_ok":smc_short_ok, "smc":smc}

    def check_reversal(self, prev, curr):
        # EMA cross + CDC flip = จุดกลับตัวแม่น
        long_cross=curr['ema_fast']>curr['ema_slow'] and prev['ema_fast']<=prev['ema_slow']
        short_cross=curr['ema_fast']<curr['ema_slow'] and prev['ema_fast']>=prev['ema_slow']
        cdc_long=curr['cdc_up'] and not prev['cdc_up']
        cdc_short=not curr['cdc_up'] and prev['cdc_up']
        long=long_cross or cdc_long
        short=short_cross or cdc_short
        return {"long":long, "short":short, "long_cross":long_cross, "short_cross":short_cross}

    def check_momentum(self, curr):
        # ADX + DI ล้วน - ไม่ใช้ RSI แล้ว
        c=self.config
        long = curr['plus_di'] > curr['minus_di'] and curr['plus_di'] > c["di_min"] and curr['adx'] > c["adx_min"]
        short = curr['minus_di'] > curr['plus_di'] and curr['minus_di'] > c["di_min"] and curr['adx'] > c["adx_min"]
        # Turbo - ADX แรงมากยิ่งยืนยัน
        turbo_long = curr['adx'] > c["adx_turbo"] and curr['plus_di'] > c["di_turbo"]
        turbo_short = curr['adx'] > c["adx_turbo"] and curr['minus_di'] > c["di_turbo"]
        long = long or turbo_long
        short = short or turbo_short
        return {"long":long, "short":short, "adx":curr['adx'], "plus_di":curr['plus_di'], "minus_di":curr['minus_di']}

    # 2. Trailing SL กันทุน/กำไร
    def get_trailing_sl(self, entry, curr_price, cdc_stop, signal, atr=None):
        c=self.config
        if signal=='LONG':
            profit_pct=(curr_price-entry)/entry
            if profit_pct>=c["lock_trigger"]:
                # Lock 0.5% + ตาม CDC
                lock_sl=entry*(1+c["lock_pct"])
                return max(lock_sl, cdc_stop, entry) # สูงสุด
            elif profit_pct>=c["be_trigger"]:
                return max(entry, cdc_stop) # BE
            else:
                return min(entry*(1-c["sl_pct"]), cdc_stop) if cdc_stop<entry else entry*(1-c["sl_pct"])
        else: # SHORT
            profit_pct=(entry-curr_price)/entry
            if profit_pct>=c["lock_trigger"]:
                lock_sl=entry*(1-c["lock_pct"])
                return min(lock_sl, cdc_stop, entry)
            elif profit_pct>=c["be_trigger"]:
                return min(entry, cdc_stop)
            else:
                return max(entry*(1+c["sl_pct"]), cdc_stop) if cdc_stop>entry else entry*(1+c["sl_pct"])

    # 3. TP เมื่อเปลี่ยนเทรน
    def check_exit_trend_change(self, curr, prev, open_signal, smc=None, df=None):
        # ถือ LONG อยู่ แต่เทรนเปลี่ยน -> TP
        if open_signal=='LONG':
            cdc_flip=not curr['cdc_up'] and prev['cdc_up']
            ema_flip=curr['ema_fast']<curr['ema_slow'] and prev['ema_fast']>=prev['ema_slow']
            di_flip=curr['minus_di']>curr['plus_di'] and prev['plus_di']>=prev['minus_di'] and curr['adx']>15
            # ออกไว: ปิดหลุด EMA Fast ลงมา 2 แท่งติด = Pullback ล้มเหลว ออกเลย ไม่รอ CDC Flip
            ema_fail=float(curr['close'])<float(curr['ema_fast']) and float(prev.get('close',0))<float(prev.get('ema_fast',0))
            # --- V6.1 FIX: ทำไมบอทไม่ปิด SHORT ในภาพ PAXG 3,847 --- 
            # ปัญหาเดิม: ต้องรอ CDC Flip / EMA Cross พอดีแท่งนั้น / DI Flip พอดีแท่งนั้น / EMA Fast Fail 2 แท่งติด
            # แต่ในภาพ ราคาขึ้นไปเหนือ EMA Trend + EMA50 แล้วหลายแท่ง แต่ Cross พอดีแท่งนั้นมันผ่านไปแล้ว -> บอทเลยไม่ปิด
            # แก้: ออกทันทีถ้า ราคาปิดสวน EMA Trend หรือ EMA50 (เทรนด์หลัก SMC) หรือ SMC ฝั่งตรงข้ามผ่าน 4/6 หรือ CHoCH ฝั่งตรงข้าม
            trend_break=False; ema50_break=False; smc_flip=False; choch_flip=False
            try:
                trend_break=float(curr['close'])<float(curr.get('ema_trend', curr['close']))
                ema50_break=float(curr['close'])<float(curr.get('ema50', curr['close']))
            except: pass
            try:
                if smc is not None: smc_flip=bool(smc.get('short_pass'))
            except: pass
            try:
                if df is not None and len(df)>=12:
                    swing_low=float(df.iloc[-11:-1]['low'].min())
                    # CHoCH ลง: ปิดต่ำกว่า Swing Low เดิม = โครงสร้างเปลี่ยนลง
                    choch_flip=float(curr['close'])<swing_low
            except: pass
            should_tp=cdc_flip or ema_flip or di_flip or ema_fail or trend_break or ema50_break or smc_flip or choch_flip
            reason=[]
            if cdc_flip: reason.append("CDC Flip")
            if ema_fail: reason.append("EMA Fast Fail")
            if ema_flip: reason.append(f"EMA{self.config['ema_fast']}x{self.config['ema_slow']} Cross Down")
            if di_flip: reason.append("DI Flip")
            if trend_break: reason.append("Close < EMA Trend")
            if ema50_break: reason.append("Close < EMA50 (SMC Trend)")
            if smc_flip: reason.append("SMC SHORT 4/6 Flip")
            if choch_flip: reason.append("CHoCH Down")
            return {"tp":should_tp, "reasons":reason, "cdc_flip":cdc_flip, "ema_flip":ema_flip}
        elif open_signal=='SHORT':
            cdc_flip=curr['cdc_up'] and not prev['cdc_up']
            ema_flip=curr['ema_fast']>curr['ema_slow'] and prev['ema_fast']<=prev['ema_slow']
            di_flip=curr['plus_di']>curr['minus_di'] and prev['minus_di']>=prev['plus_di'] and curr['adx']>15
            # ออกไว: ปิดทะลุ EMA Fast ขึ้นไป 2 แท่งติด = Pullback ล้มเหลว ออกเลย
            ema_fail=float(curr['close'])>float(curr['ema_fast']) and float(prev.get('close',0))>float(prev.get('ema_fast',0))
            # --- V6.1 FIX SHORT (เคสในภาพ PAXG) ---
            trend_break=False; ema50_break=False; smc_flip=False; choch_flip=False
            try:
                trend_break=float(curr['close'])>float(curr.get('ema_trend', curr['close']))
                ema50_break=float(curr['close'])>float(curr.get('ema50', curr['close']))
            except: pass
            try:
                if smc is not None: smc_flip=bool(smc.get('long_pass'))
            except: pass
            try:
                if df is not None and len(df)>=12:
                    swing_high=float(df.iloc[-11:-1]['high'].max())
                    choch_flip=float(curr['close'])>swing_high
            except: pass
            should_tp=cdc_flip or ema_flip or di_flip or ema_fail or trend_break or ema50_break or smc_flip or choch_flip
            reason=[]
            if cdc_flip: reason.append("CDC Flip")
            if ema_fail: reason.append("EMA Fast Fail")
            if ema_flip: reason.append(f"EMA{self.config['ema_fast']}x{self.config['ema_slow']} Cross Up")
            if di_flip: reason.append("DI Flip")
            if trend_break: reason.append("Close > EMA Trend")
            if ema50_break: reason.append("Close > EMA50 (SMC Trend)")
            if smc_flip: reason.append("SMC LONG 4/6 Flip")
            if choch_flip: reason.append("CHoCH Up")
            return {"tp":should_tp, "reasons":reason, "cdc_flip":cdc_flip, "ema_flip":ema_flip}
        return {"tp":False, "reasons":[]}
