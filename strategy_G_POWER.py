"""
G_POWER V5.0 TREND FOLLOWING - 3 หัวใจตามที่ขอ
1. จุดเข้าแม่น - ต้อง Retest + RSI 40-65 + Vol
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
                "ema_fast": 12, "ema_slow": 26, "ema_trend": 50,
                "rsi_fast": 12, "rsi_entry_long": (40, 65), "rsi_entry_short": (35, 60),
                "adx_min": 14, "adx_sideway": 14, "adx_turbo": 32,
                "di_min": 12, "di_turbo": 22,
                "sl_pct": 0.034, "tp_pct": 0.18,
                "cdc_atr_fast": 5, "cdc_mult_fast": 0.5,
                "cdc_atr_slow": 10, "cdc_mult_slow": 2.0,
                "vol_filter": 0.65, "sideway_pct": 0.8,
                "retest_pct": 0.006, # ต้องอยู่ใกล้ EMA12 ไม่เกิน 0.6%
                "be_trigger": 0.01, # กำไร 1% -> BE
                "lock_trigger": 0.02, # กำไร 2% -> Lock 0.5%
                "lock_pct": 0.005,
            },
            "gold": {
                "ema_fast": 21, "ema_slow": 55, "ema_trend": 100,
                "rsi_fast": 14, "rsi_entry_long": (45, 65), "rsi_entry_short": (35, 60),
                "adx_min": 16, "adx_sideway": 15, "adx_turbo": 30,
                "di_min": 14, "di_turbo": 22,
                "sl_pct": 0.028, "tp_pct": 0.12,
                "cdc_atr_fast": 10, "cdc_mult_fast": 1.0,
                "cdc_atr_slow": 20, "cdc_mult_slow": 2.5,
                "vol_filter": 0.6, "sideway_pct": 1.0,
                "retest_pct": 0.008,
                "be_trigger": 0.008, "lock_trigger": 0.015, "lock_pct": 0.004,
            },
            "silver": {
                "ema_fast": 9, "ema_slow": 21, "ema_trend": 34,
                "rsi_fast": 9, "rsi_entry_long": (40, 70), "rsi_entry_short": (30, 60),
                "adx_min": 18, "adx_sideway": 16, "adx_turbo": 32,
                "di_min": 15, "di_turbo": 24,
                "sl_pct": 0.035, "tp_pct": 0.10,
                "cdc_atr_fast": 5, "cdc_mult_fast": 0.8,
                "cdc_atr_slow": 10, "cdc_mult_slow": 2.2,
                "vol_filter": 0.7, "sideway_pct": 1.2,
                "retest_pct": 0.01,
                "be_trigger": 0.012, "lock_trigger": 0.025, "lock_pct": 0.006,
            }
        }
        self.config = base.get(symbol_key, base["btc"])

    def _ema(self, s, p): return s.ewm(span=p, adjust=False).mean()
    def _rsi(self, s, p):
        d=s.diff()
        g=d.where(d>0,0).ewm(alpha=1/p, adjust=False).mean()
        l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
        rs=g/l.replace(0,0.00001)
        return 100-(100/(1+rs))
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
        df['rsi']=self._rsi(df['close'],c["rsi_fast"])
        df['atr']=self._atr(df['high'],df['low'],df['close'],14)
        pdi,mdi,adx,adx_s=self._adx_di(df['high'],df['low'],df['close'],14)
        df['plus_di']=pdi; df['minus_di']=mdi; df['adx']=adx; df['adx_slope']=adx_s
        tr, st, up=self._cdc(df)
        df['cdc_trend']=tr; df['cdc_stop']=st; df['cdc_up']=up
        df['vol_avg']=df['volume'].rolling(20).mean()
        df['dist_ema_fast']= (df['close']-df['ema_fast']).abs()/df['close']
        df['cdc_dist_pct']=(df['close']-df['cdc_stop'])/df['close']*100
        return df

    # 1. จุดเข้าแม่น
    def check_trend(self, curr):
        c=self.config
        ema_diff=abs(curr['ema_fast']-curr['ema_slow'])/curr['close']*100
        sideway=(curr['adx']<c["adx_sideway"]) or (ema_diff<c["sideway_pct"] and curr['adx']<c["adx_turbo"])
        # Retest - ราคาต้องใกล้ EMA fast
        retest=curr['dist_ema_fast'] <= c["retest_pct"]
        vol_ok=curr['volume']>curr['vol_avg']*c["vol_filter"] if curr.get('vol_avg') else True
        # CDC + DI
        long_core=curr['cdc_up'] and curr['plus_di']>curr['minus_di'] and curr['plus_di']>c["di_min"] and curr['adx']>c["adx_min"] and curr['close']>curr['ema_trend']
        short_core=not curr['cdc_up'] and curr['minus_di']>curr['plus_di'] and curr['minus_di']>c["di_min"] and curr['adx']>c["adx_min"] and curr['close']<curr['ema_trend']
        # Turbo bypass แต่ยังต้อง retest
        turbo_long=curr['adx']>c["adx_turbo"] and curr['plus_di']>c["di_turbo"]
        turbo_short=curr['adx']>c["adx_turbo"] and curr['minus_di']>c["di_turbo"]
        # รวม - ต้องมี retest ถึงแม่น
        long=(long_core or turbo_long) and retest and vol_ok
        short=(short_core or turbo_short) and retest and vol_ok
        return {"long":long, "short":short, "sideway":sideway and not (turbo_long or turbo_short), "vol_ok":vol_ok, "retest":retest, "ema_diff":ema_diff, "long_core":long_core, "short_core":short_core}

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
        c=self.config
        rsi=curr['rsi']
        # เข้าแม่น - RSI ต้องอยู่โซนกลาง ไม่ Overbought/Oversold
        rsi_long_range=c["rsi_entry_long"]; rsi_short_range=c["rsi_entry_short"]
        long_rsi= rsi_long_range[0] <= rsi <= rsi_long_range[1]
        short_rsi= rsi_short_range[0] <= rsi <= rsi_short_range[1]
        # Turbo ให้หยวน RSI ได้ถ้า ADX แรงมาก
        turbo_long=curr['adx']>c["adx_turbo"] and curr['plus_di']>c["di_turbo"]
        turbo_short=curr['adx']>c["adx_turbo"] and curr['minus_di']>c["di_turbo"]
        long=(long_rsi or turbo_long) and rsi<78
        short=(short_rsi or turbo_short) and rsi>22
        return {"long":long, "short":short, "rsi":rsi, "rsi_ok_long":long_rsi, "rsi_ok_short":short_rsi}

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
    def check_exit_trend_change(self, curr, prev, open_signal):
        # ถือ LONG อยู่ แต่เทรนเปลี่ยน -> TP
        if open_signal=='LONG':
            cdc_flip=not curr['cdc_up'] and prev['cdc_up']
            ema_flip=curr['ema_fast']<curr['ema_slow'] and prev['ema_fast']>=prev['ema_slow']
            di_flip=curr['minus_di']>curr['plus_di'] and prev['plus_di']>=prev['minus_di'] and curr['adx']>15
            rsi_exit=curr['rsi']>75 # Overbought
            should_tp=cdc_flip or ema_flip or di_flip or rsi_exit
            reason=[]
            if cdc_flip: reason.append("CDC Flip")
            if ema_flip: reason.append(f"EMA{self.config['ema_fast']}x{self.config['ema_slow']} Cross Down")
            if di_flip: reason.append("DI Flip")
            if rsi_exit: reason.append(f"RSI {curr['rsi']:.0f} Overbought")
            return {"tp":should_tp, "reasons":reason, "cdc_flip":cdc_flip, "ema_flip":ema_flip}
        elif open_signal=='SHORT':
            cdc_flip=curr['cdc_up'] and not prev['cdc_up']
            ema_flip=curr['ema_fast']>curr['ema_slow'] and prev['ema_fast']<=prev['ema_slow']
            di_flip=curr['plus_di']>curr['minus_di'] and prev['minus_di']>=prev['plus_di'] and curr['adx']>15
            rsi_exit=curr['rsi']<25
            should_tp=cdc_flip or ema_flip or di_flip or rsi_exit
            reason=[]
            if cdc_flip: reason.append("CDC Flip")
            if ema_flip: reason.append(f"EMA{self.config['ema_fast']}x{self.config['ema_slow']} Cross Up")
            if di_flip: reason.append("DI Flip")
            if rsi_exit: reason.append(f"RSI {curr['rsi']:.0f} Oversold")
            return {"tp":should_tp, "reasons":reason, "cdc_flip":cdc_flip, "ema_flip":ema_flip}
        return {"tp":False, "reasons":[]}
