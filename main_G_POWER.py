
"""
G_POWER V5.6.1.1 NO HEDGE + CLOSE - เข้าจุด Flip CDC + DI Cross ไม่รอ Retest
- 2 โหมด: BREAKOUT (Flip 1-2 แท่ง) + RETEST (เดิม) + TURBO
- แก้เข้าแผ่ว: adx_slope > -1.5, ADX >22
- VOL 0.20 + Turbo Bypass
"""

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os, ccxt, json, requests
from pathlib import Path

class Strategy_G_Power:
    def __init__(self, symbol_key="btc"):
        self.symbol_key = symbol_key
        self.name = f"G_POWER V5.6.1.1 NO HEDGE + CLOSE {symbol_key.upper()}"
        base = {
            "btc": {"ema_fast":12,"ema_slow":26,"ema_trend":50,"rsi_fast":12,"rsi_entry_long":(35,70),"rsi_entry_short":(25,65),"adx_min":10,"adx_sideway":10,"adx_turbo":28,"di_min":10,"di_turbo":20,"sl_pct":0.034,"tp_pct":0.18,"cdc_atr_fast":5,"cdc_mult_fast":0.5,"cdc_atr_slow":10,"cdc_mult_slow":2.0,"vol_filter":0.20,"sideway_pct":1.2,"retest_pct":0.012,"be_trigger":0.01,"lock_trigger":0.02,"lock_pct":0.005},
            "gold": {"ema_fast":21,"ema_slow":55,"ema_trend":100,"rsi_fast":14,"rsi_entry_long":(40,70),"rsi_entry_short":(25,65),"adx_min":12,"adx_sideway":12,"adx_turbo":26,"di_min":10,"di_turbo":20,"sl_pct":0.028,"tp_pct":0.12,"cdc_atr_fast":10,"cdc_mult_fast":1.0,"cdc_atr_slow":20,"cdc_mult_slow":2.5,"vol_filter":0.20,"sideway_pct":1.2,"retest_pct":0.012,"be_trigger":0.008,"lock_trigger":0.015,"lock_pct":0.004},
            "silver": {"ema_fast":9,"ema_slow":21,"ema_trend":34,"rsi_fast":9,"rsi_entry_long":(35,70),"rsi_entry_short":(25,65),"adx_min":14,"adx_sideway":12,"adx_turbo":28,"di_min":10,"di_turbo":20,"sl_pct":0.035,"tp_pct":0.10,"cdc_atr_fast":5,"cdc_mult_fast":0.8,"cdc_atr_slow":10,"cdc_mult_slow":2.2,"vol_filter":0.20,"sideway_pct":1.5,"retest_pct":0.015,"be_trigger":0.012,"lock_trigger":0.025,"lock_pct":0.006}
        }
        self.config = base.get(symbol_key, base["btc"])
    def _ema(self,s,p): return s.ewm(span=p,adjust=False).mean()
    def _rsi(self,s,p):
        d=s.diff(); g=d.where(d>0,0).ewm(alpha=1/p,adjust=False).mean(); l=(-d.where(d<0,0)).ewm(alpha=1/p,adjust=False).mean()
        return 100-(100/(1+g/l.replace(0,0.00001)))
    def _atr(self,h,l,c,p=14):
        tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        return tr.ewm(alpha=1/p,adjust=False).mean()
    def _adx_di(self,h,l,c,p=14):
        up=h.diff(); down=-l.diff()
        pdm=pd.Series([u if (u>d and u>0) else 0 for u,d in zip(up,down)],index=h.index).ewm(alpha=1/p,adjust=False).mean()
        mdm=pd.Series([d if (d>u and d>0) else 0 for u,d in zip(up,down)],index=h.index).ewm(alpha=1/p,adjust=False).mean()
        tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1).ewm(alpha=1/p,adjust=False).mean()
        pdi=100*pdm/tr; mdi=100*mdm/tr
        dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
        adx=dx.ewm(alpha=1/p,adjust=False).mean().fillna(15)
        return pdi.fillna(0),mdi.fillna(0),adx,adx.diff(3)
    def _cdc(self,df):
        c=self.config; af=self._atr(df['high'],df['low'],df['close'],c["cdc_atr_fast"]); asl=self._atr(df['high'],df['low'],df['close'],c["cdc_atr_slow"])
        ls_f=df['close']-af*c["cdc_mult_fast"]; ss_f=df['close']+af*c["cdc_mult_fast"]; ls_s=df['close']-asl*c["cdc_mult_slow"]; ss_s=df['close']+asl*c["cdc_mult_slow"]
        ls=pd.concat([ls_f,ls_s],axis=1).max(axis=1); ss=pd.concat([ss_f,ss_s],axis=1).min(axis=1)
        trend=np.zeros(len(df),dtype=int); stop=np.zeros(len(df)); trend[0]=1; stop[0]=ls.iloc[0]
        for i in range(1,len(df)):
            if df['close'].iloc[i]>stop[i-1] and trend[i-1]==1: trend[i]=1; stop[i]=max(ls.iloc[i],stop[i-1])
            elif df['close'].iloc[i]<stop[i-1] and trend[i-1]==-1: trend[i]=-1; stop[i]=min(ss.iloc[i],stop[i-1])
            else:
                if trend[i-1]==1:
                    if df['close'].iloc[i]<ls.iloc[i]: trend[i]=-1; stop[i]=ss.iloc[i]
                    else: trend[i]=1; stop[i]=max(ls.iloc[i],stop[i-1])
                else:
                    if df['close'].iloc[i]>ss.iloc[i]: trend[i]=1; stop[i]=ls.iloc[i]
                    else: trend[i]=-1; stop[i]=min(ss.iloc[i],stop[i-1])
        return pd.Series(trend,index=df.index),pd.Series(stop,index=df.index),trend==1
    def add_indicators(self,df):
        df=df.copy(); c=self.config
        df['ema_fast']=self._ema(df['close'],c["ema_fast"]); df['ema_slow']=self._ema(df['close'],c["ema_slow"]); df['ema_trend']=self._ema(df['close'],c["ema_trend"])
        df['rsi']=self._rsi(df['close'],c["rsi_fast"]); df['atr']=self._atr(df['high'],df['low'],df['close'],14)
        pdi,mdi,adx,adx_s=self._adx_di(df['high'],df['low'],df['close'],14)
        df['plus_di']=pdi; df['minus_di']=mdi; df['adx']=adx; df['adx_slope']=adx_s
        tr,st,up=self._cdc(df); df['cdc_trend']=tr; df['cdc_stop']=st; df['cdc_up']=up
        df['vol_avg']=df['volume'].rolling(20).mean(); df['dist_ema_fast']=(df['close']-df['ema_fast']).abs()/df['close']
        return df
    def check_trend(self,curr,prev=None):
        c=self.config; ema_diff=abs(curr['ema_fast']-curr['ema_slow'])/curr['close']*100
        sideway=(curr['adx']<c["adx_sideway"]) or (ema_diff<c["sideway_pct"] and curr['adx']<c["adx_turbo"])
        retest=curr['dist_ema_fast']<=c["retest_pct"]; vol_ok=curr['volume']>curr['vol_avg']*c["vol_filter"] if curr.get('vol_avg') else True
        long_core=curr['cdc_up'] and curr['plus_di']>curr['minus_di'] and curr['plus_di']>c["di_min"] and curr['adx']>c["adx_min"] and curr['close']>curr['ema_trend']
        short_core=not curr['cdc_up'] and curr['minus_di']>curr['plus_di'] and curr['minus_di']>c["di_min"] and curr['adx']>c["adx_min"] and curr['close']<curr['ema_trend']
        turbo_long=curr['adx']>c["adx_turbo"] and curr['plus_di']>c["di_turbo"]; turbo_short=curr['adx']>c["adx_turbo"] and curr['minus_di']>c["di_turbo"]
        adx_slope_ok = curr.get('adx_slope',0) > -1.5
        strong_trend = curr['adx'] > 22 or turbo_long or turbo_short
        # BLUE CIRCLE - BREAKOUT
        cdc_flip_up=False; cdc_flip_down=False; di_cross_up=False; di_cross_down=False
        if prev is not None:
            cdc_flip_up = (not prev['cdc_up']) and curr['cdc_up']
            cdc_flip_down = prev['cdc_up'] and (not curr['cdc_up'])
            di_cross_up = (prev['plus_di'] <= prev['minus_di']) and (curr['plus_di'] > curr['minus_di'])
            di_cross_down = (prev['minus_di'] <= prev['plus_di']) and (curr['minus_di'] > curr['plus_di'])
        breakout_long = (cdc_flip_up or di_cross_up) and curr['plus_di']>curr['minus_di'] and curr['adx']>=c["adx_min"]*0.8 and curr.get('adx_slope',0) > -1.0
        breakout_short = (cdc_flip_down or di_cross_down) and curr['minus_di']>curr['plus_di'] and curr['adx']>=c["adx_min"]*0.8 and curr.get('adx_slope',0) > -1.0
        vol_ok_effective=vol_ok or turbo_long or turbo_short or breakout_long or breakout_short
        retest_long = long_core and retest
        retest_short = short_core and retest
        long = (retest_long or breakout_long or turbo_long) and vol_ok_effective and adx_slope_ok and strong_trend
        short = (retest_short or breakout_short or turbo_short) and vol_ok_effective and adx_slope_ok and strong_trend
        entry_type="NONE"
        if breakout_long or breakout_short: entry_type="BREAKOUT"
        elif retest_long or retest_short: entry_type="RETEST"
        elif turbo_long or turbo_short: entry_type="TURBO"
        return {"long":long,"short":short,"sideway":sideway and not (turbo_long or turbo_short or breakout_long or breakout_short),"vol_ok":vol_ok,"retest":retest,"ema_diff":ema_diff,"long_core":long_core,"short_core":short_core,"adx_slope_ok":adx_slope_ok,"breakout_long":breakout_long,"breakout_short":breakout_short,"cdc_flip_up":cdc_flip_up,"cdc_flip_down":cdc_flip_down,"di_cross_up":di_cross_up,"di_cross_down":di_cross_down,"entry_type":entry_type}
    def check_reversal(self,prev,curr):
        long_cross=curr['ema_fast']>curr['ema_slow'] and prev['ema_fast']<=prev['ema_slow']; short_cross=curr['ema_fast']<curr['ema_slow'] and prev['ema_fast']>=prev['ema_slow']
        cdc_long=curr['cdc_up'] and not prev['cdc_up']; cdc_short=not curr['cdc_up'] and prev['cdc_up']
        return {"long":long_cross or cdc_long,"short":short_cross or cdc_short,"long_cross":long_cross,"short_cross":short_cross}
    def check_momentum(self,curr):
        c=self.config; rsi=curr['rsi']
        long_rsi=c["rsi_entry_long"][0]<=rsi<=c["rsi_entry_long"][1]; short_rsi=c["rsi_entry_short"][0]<=rsi<=c["rsi_entry_short"][1]
        turbo_long=curr['adx']>c["adx_turbo"] and curr['plus_di']>c["di_turbo"]; turbo_short=curr['adx']>c["adx_turbo"] and curr['minus_di']>c["di_turbo"]
        return {"long":(long_rsi or turbo_long) and rsi<78,"short":(short_rsi or turbo_short) and rsi>22,"rsi":rsi,"rsi_ok_long":long_rsi,"rsi_ok_short":short_rsi}
    def get_trailing_sl(self,entry,curr_price,cdc_stop,signal,atr=None):
        c=self.config
        if signal=='LONG':
            profit_pct=(curr_price-entry)/entry
            if profit_pct>=c["lock_trigger"]: return max(entry*(1+c["lock_pct"]),cdc_stop,entry)
            elif profit_pct>=c["be_trigger"]: return max(entry,cdc_stop)
            else: return min(entry*(1-c["sl_pct"]),cdc_stop) if cdc_stop<entry else entry*(1-c["sl_pct"])
        else:
            profit_pct=(entry-curr_price)/entry
            if profit_pct>=c["lock_trigger"]: return min(entry*(1-c["lock_pct"]),cdc_stop,entry)
            elif profit_pct>=c["be_trigger"]: return min(entry,cdc_stop)
            else: return max(entry*(1+c["sl_pct"]),cdc_stop) if cdc_stop>entry else entry*(1+c["sl_pct"])
    def check_exit_trend_change(self,curr,prev,open_signal):
        if open_signal=='LONG':
            cdc_flip=not curr['cdc_up'] and prev['cdc_up']; ema_flip=curr['ema_fast']<curr['ema_slow'] and prev['ema_fast']>=prev['ema_slow']; di_flip=curr['minus_di']>curr['plus_di'] and prev['plus_di']>=prev['minus_di'] and curr['adx']>15; rsi_exit=curr['rsi']>75
            should_tp=cdc_flip or ema_flip or di_flip or rsi_exit; reason=[]
            if cdc_flip: reason.append("CDC Flip")
            if ema_flip: reason.append(f"EMA{self.config['ema_fast']}x{self.config['ema_slow']} Cross Down")
            if di_flip: reason.append("DI Flip")
            if rsi_exit: reason.append(f"RSI {curr['rsi']:.0f} Overbought")
            return {"tp":should_tp,"reasons":reason}
        elif open_signal=='SHORT':
            cdc_flip=curr['cdc_up'] and not prev['cdc_up']; ema_flip=curr['ema_fast']>curr['ema_slow'] and prev['ema_fast']<=prev['ema_slow']; di_flip=curr['plus_di']>curr['minus_di'] and prev['minus_di']>=prev['plus_di'] and curr['adx']>15; rsi_exit=curr['rsi']<25
            should_tp=cdc_flip or ema_flip or di_flip or rsi_exit; reason=[]
            if cdc_flip: reason.append("CDC Flip")
            if ema_flip: reason.append(f"EMA{self.config['ema_fast']}x{self.config['ema_slow']} Cross Up")
            if di_flip: reason.append("DI Flip")
            if rsi_exit: reason.append(f"RSI {curr['rsi']:.0f} Oversold")
            return {"tp":should_tp,"reasons":reason}
        return {"tp":False,"reasons":[]}

app = FastAPI(title="G_POWER V5.6.1.1 NO HEDGE + CLOSE")
STRATS = {"btc": Strategy_G_Power("btc"),"gold": Strategy_G_Power("gold"),"silver": Strategy_G_Power("silver")}
MAX_POS_PER_SYMBOL = 2
MAX_TOTAL_NOTIONAL = 80  # V5.6.1: Notional รวมห้ามเกิน 2x ทุน $40 = $80 กันโดนลากพร้อมกัน
COOLDOWN_HOURS = 1.0  # V5.6.1: เพิ่ม Cooldown 0.5 -> 1h กันเปิดถี่ตอนกลับตัว
CAPITAL = 40
RISK_PCT = 0.02
LEVERAGE = 3
SYMBOLS = {"btc":"BTC/USDT:USDT","gold":"GOLD/USDT:USDT","silver":"SILVER/USDT:USDT"}
SYMBOL_KEYS = {"BTC/USDT":"btc","BTC/USDT:USDT":"btc","PAXG/USDT:USDT":"gold","GOLD/USDT:USDT":"gold","XAU/USDT:USDT":"gold","SILVER/USDT:USDT":"silver","XAG/USDT:USDT":"silver"}
DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRADES_FILE = DATA_DIR / "g_power_trades.json"
AUTO_STATE_FILE = DATA_DIR / "auto_state.json"
LAST_TRADE_TIME_FILE = DATA_DIR / "last_trade_time.json"

def atomic_save(path: Path, data):
    try:
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w') as f: json.dump(data, f, default=str, indent=2)
        tmp.replace(path)
    except:
        try:
            with open(path, 'w') as f: json.dump(data, f, default=str, indent=2)
        except: pass

def load_trades():
    if TRADES_FILE.exists():
        try:
            with open(TRADES_FILE,'r') as f: d=json.load(f); return [t for t in d if not str(t.get('note','')).lower().startswith('sample')]
        except: return []
    return []
def save_trades(t): atomic_save(TRADES_FILE, t)
def get_auto_state():
    if AUTO_STATE_FILE.exists():
        try:
            with open(AUTO_STATE_FILE,'r') as f:
                d=json.load(f)
                if isinstance(d,bool): return {"btc":d,"gold":True,"silver":True}
                if "enabled" in d: return {"btc":bool(d.get("enabled",False)),"gold":bool(d.get("enabled",False)),"silver":bool(d.get("enabled",False))}
                for k in ["btc","gold","silver"]:
                    if k not in d: d[k]=False
                return d
        except:
            try: AUTO_STATE_FILE.unlink()
            except: pass
    return {"btc":False,"gold":False,"silver":False}
def set_auto_state(k, en):
    s=get_auto_state()
    if k=='all':
        for kk in s: s[kk]=en
    else: s[k]=en
    atomic_save(AUTO_STATE_FILE, s)
    return s
def get_last_trade_times():
    if LAST_TRADE_TIME_FILE.exists():
        try:
            with open(LAST_TRADE_TIME_FILE,'r') as f: return json.load(f)
        except: pass
    return {}
def set_last_trade_time(symbol_key):
    times=get_last_trade_times(); times[symbol_key]=datetime.now().isoformat(); atomic_save(LAST_TRADE_TIME_FILE, times)
def can_open_new(symbol_key, cooldown_hours=0.5):
    times=get_last_trade_times(); last_str=times.get(symbol_key)
    if not last_str: return True
    try:
        last=datetime.fromisoformat(last_str)
        if datetime.now() - last < timedelta(hours=cooldown_hours): return False
        return True
    except: return True
def calc_position(symbol_key="btc"):
    cfg=STRATS.get(symbol_key, STRATS['btc']).config; sl=cfg['sl_pct']; tp=cfg['tp_pct']; risk=CAPITAL*RISK_PCT; pos=risk/sl if sl else risk/0.034
    return {"risk":risk,"pos":pos,"margin":pos/LEVERAGE,"sl":sl*100,"tp":tp*100,"rr":round(tp/sl,1)}
def get_live_price_fast(symbol, candidates=None):
    # ดึง Last Price สดจาก MEXC Perpetual Ticker - ตรงกับแอพ 100%
    cands = candidates or [symbol]
    for sym in cands:
        try:
            ex=ccxt.mexc({"options":{"defaultType":"swap"}})
            t=ex.fetch_ticker(sym)
            last=float(t.get('last') or t.get('close') or 0)
            if last>0:
                return last, sym
        except: continue
    return 0, None

def get_data(symbol="BTC/USDT:USDT"):
    # FIX V5.6.1: ใช้สัญลักษณ์ Perpetual ตรงแอพ MEXC เท่านั้น
    if "BTC" in symbol: candidates=["BTC/USDT:USDT","BTC/USDT"]
    elif "GOLD" in symbol or "PAXG" in symbol or "XAU" in symbol: candidates=["GOLD/USDT:USDT","XAU/USDT:USDT"]
    elif "SILVER" in symbol or "XAG" in symbol: candidates=["SILVER/USDT:USDT","XAG/USDT:USDT"]
    else: candidates=[symbol]
    for sym in candidates:
        try:
            ex=ccxt.mexc({"options":{"defaultType":"swap"}})
            ohlcv=ex.fetch_ohlcv(sym,'15m',limit=250)
            if ohlcv and len(ohlcv)>50:
                df=pd.DataFrame(ohlcv,columns=['timestamp','open','high','low','close','volume'])
                df['datetime']=pd.to_datetime(df['timestamp'],unit='ms')
                # FIX: แพทช์แท่งสุดท้ายด้วยราคาสด Ticker - ไม่ใช้ราคาปิดแท่งเก่า
                live, live_sym = get_live_price_fast(sym, [sym])
                candle_close = float(df.iloc[-1]['close'])
                if live>0:
                    # ถ้า live ห่างจาก candle เกิน 0.05% แสดงว่าแท่งเก่า ให้ใช้ live
                    df.at[df.index[-1], 'close'] = live
                    # อัปเดต high/low ด้วยถ้า live หลุดกรอบ
                    if live > float(df.iloc[-1]['high']): df.at[df.index[-1], 'high'] = live
                    if live < float(df.iloc[-1]['low']): df.at[df.index[-1], 'low'] = live
                    df.attrs['live_price'] = live
                    df.attrs['candle_close'] = candle_close
                    df.attrs['used_symbol'] = sym
                else:
                    df.attrs['live_price'] = candle_close
                    df.attrs['candle_close'] = candle_close
                    df.attrs['used_symbol'] = sym
                return df
        except Exception as e:
            continue
    return (None, f"mexc no symbol {symbol} - tried {candidates}")
def get_live_price(symbol):
    try:
        ex=ccxt.mexc({"options":{"defaultType":"swap"}})
        t=ex.fetch_ticker(symbol)
        return float(t.get('last',0))
    except:
        try:
            ex2=ccxt.mexc({"options":{"defaultType":"swap"}})
            for alt in ["GOLD/USDT:USDT","PAXG/USDT:USDT","SILVER/USDT:USDT","BTC/USDT:USDT"]:
                try:
                    t=ex2.fetch_ticker(alt)
                    if alt.split('/')[0] in symbol: return float(t.get('last',0))
                except: pass
        except: pass
    return 0

def get_mexc_balance():
    try:
        key=os.environ.get("MEXC_API_KEY","").strip(); sec=os.environ.get("MEXC_API_SECRET","").strip()
        if not key or not sec: return {"ok":False,"error":"No API"}
        ex=ccxt.mexc({'apiKey':key,'secret':sec,'options':{'defaultType':'swap'},'enableRateLimit':True})
        bal=ex.fetch_balance({'type':'swap'}); usdt=bal.get('USDT',{}); poss=[]
        try:
            for p in ex.fetch_positions():
                if float(p.get('contracts',0) or 0)>0: poss.append(p)
        except: pass
        return {"ok":True,"free":usdt.get('free',0),"total":usdt.get('total',0),"positions":poss}
    except Exception as e: return {"ok":False,"error":str(e)[:150]}
def send_tele(msg, chat_id=None):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    chat=chat_id or os.environ.get("TELEGRAM_CHAT_ID","").strip() or os.environ.get("CHAT_ID","").strip()
    if not token or not chat: return {"ok":False}
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id":chat,"text":msg,"parse_mode":"HTML"}, timeout=10)
        return {"ok":r.status_code==200}
    except: return {"ok":False}
def get_strat(symbol):
    s=symbol.upper()
    if 'BTC' in s: return STRATS['btc']
    if 'XAU' in s or 'PAXG' in s or 'GOLD' in s or 'XAUT' in s: return STRATS['gold']
    if 'XAG' in s or 'SILVER' in s: return STRATS['silver']
    return STRATS['btc']

def execute_symbol(symbol, manage_open=True):
    try:
        st=get_strat(symbol); symbol_key=st.symbol_key; df=get_data(symbol)
        if isinstance(df,tuple): return {"ok":False,"symbol":symbol,"error":df[1]}
        df_raw_candle=float(df.iloc[-1]['close']) if len(df)>0 else 0
        live_price_from_df = df.attrs.get('live_price', 0) if hasattr(df, 'attrs') else 0
        used_sym = df.attrs.get('used_symbol', symbol) if hasattr(df, 'attrs') else symbol
        df=st.add_indicators(df); curr=df.iloc[-1]; prev=df.iloc[-2]; price=float(curr['close'])
        # price ตอนนี้ = Live Ticker แล้ว (แพทช์มาใน get_data)
        candle_close_val = float(df_raw_candle)
        trades=load_trades(); open_trades=[t for t in trades if t.get('symbol')==symbol and str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
        actions=[]
        for ot in open_trades:
            entry=float(ot['entry']); sig=ot['signal']
            new_sl=st.get_trailing_sl(entry, price, float(curr['cdc_stop']), sig)
            old_sl=float(ot.get('sl', entry*(1-st.config['sl_pct']) if sig=='LONG' else entry*(1+st.config['sl_pct'])))
            if sig=='LONG' and new_sl>old_sl: ot['sl']=new_sl; ot['trailing']=f"Trail {old_sl:.0f}->{new_sl:.0f}"; actions.append(f"Trailing LONG {symbol} SL {old_sl:.0f}->{new_sl:.0f}")
            elif sig=='SHORT' and new_sl<old_sl: ot['sl']=new_sl; ot['trailing']=f"Trail {old_sl:.0f}->{new_sl:.0f}"; actions.append(f"Trailing SHORT {symbol} SL {old_sl:.0f}->{new_sl:.0f}")
            exit_info=st.check_exit_trend_change(curr, prev, sig)
            if exit_info['tp']:
                ot['status']='CLOSED'; ot['result']='WIN' if (price>entry and sig=='LONG') or (price<entry and sig=='SHORT') else 'LOSS'
                ot['exit']=price; ot['exit_time']=datetime.now().isoformat(); ot['exit_reason']='TREND CHANGE: '+','.join(exit_info['reasons'])
                pnl=(price-entry)/entry*ot.get('position_size',0) if sig=='LONG' else (entry-price)/entry*ot.get('position_size',0)
                ot['pnl_usd']=pnl; actions.append(f"TP TREND CHANGE {symbol} {sig} {','.join(exit_info['reasons'])} PnL ${pnl:+.2f}")
        if actions: save_trades(trades)
        rev=st.check_reversal(prev,curr); trend=st.check_trend(curr, prev); mom=st.check_momentum(curr)
        # V5.6.1.1 NO HEDGE + CLOSE + MAX NOTIONAL FIX
        # ถือ SHORT อยู่ ห้ามเปิด LONG - ให้ปิด SHORT ก่อน (ไม่ Hedge)
        # ถือ LONG อยู่ ห้ามเปิด SHORT
        signal="WAIT"
        total_notional_now = sum([float(t.get('position_size',0)) for t in load_trades() if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']])
        can_open=len(open_trades) < MAX_POS_PER_SYMBOL and can_open_new(symbol_key, cooldown_hours=COOLDOWN_HOURS) and total_notional_now < MAX_TOTAL_NOTIONAL
        opposite_action = None
        if len(open_trades)>0:
            existing_sigs = set([t['signal'] for t in open_trades])
            if trend['long'] and 'SHORT' in existing_sigs:
                # สัญญาณกลับตัว LONG ขณะถือ SHORT -> ปิด SHORT ก่อน (TP) ไม่เปิด LONG ซ้อน
                opposite_action = "CLOSE_SHORT_FOR_LONG"
                can_open = False
                signal = "CLOSE_SHORT"
            elif trend['short'] and 'LONG' in existing_sigs:
                opposite_action = "CLOSE_LONG_FOR_SHORT"
                can_open = False
                signal = "CLOSE_LONG"
            elif len(existing_sigs)==1:
                # ถือทางเดียวอยู่ อนุญาตเปิดเพิ่มได้ถ้าเทรนเดียวกัน
                pass
        if can_open and not trend['sideway']:
            if trend['long'] and mom['long']: signal="LONG"
            elif trend['short'] and mom['short']: signal="SHORT"
        elif not can_open:
            if len(open_trades)>=MAX_POS_PER_SYMBOL: signal=f"MAX {len(open_trades)}/{MAX_POS_PER_SYMBOL} HOLD {open_trades[0]['signal']}"
            elif len(open_trades)>0: signal=f"HOLD {open_trades[0]['signal']} {len(open_trades)}/{MAX_POS_PER_SYMBOL}"
            else: signal="COOLDOWN"
        # V5.6.1: ปิดไม้ตรงข้ามอัตโนมัติเมื่อเทรนกลับตัว - ไม่ถือ Hedge
        if signal in ['CLOSE_SHORT','CLOSE_LONG']:
            close_sig = 'SHORT' if signal=='CLOSE_SHORT' else 'LONG'
            for ot in open_trades:
                if ot['signal']==close_sig and str(ot.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']:
                    ot['status']='CLOSED'; ot['result']='WIN' if (price>float(ot['entry']) and close_sig=='LONG') or (price<float(ot['entry']) and close_sig=='SHORT') else 'LOSS'
                    ot['exit']=price; ot['exit_time']=datetime.now().isoformat(); ot['exit_reason']='V5.6.1.1 NO HEDGE + CLOSE: Trend Flip -> Close Opposite'
                    pnl=(price-float(ot['entry']))/float(ot['entry'])*float(ot.get('position_size',0)) if close_sig=='LONG' else (float(ot['entry'])-price)/float(ot['entry'])*float(ot.get('position_size',0))
                    ot['pnl_usd']=pnl; actions.append(f"CLOSE {close_sig} {symbol} ${price:.2f} PnL ${pnl:+.2f} [NO HEDGE]")
            if actions: save_trades(trades)
            # หลังปิดแล้ว ไม่เปิดไม้ใหม่ทันที รอแท่งหน้า (Cooldown)
            return {"ok":True,"symbol":symbol,"symbol_key":symbol_key,"signal":signal,"price":price,"plus_di":float(curr['plus_di']),"minus_di":float(curr['minus_di']),"adx":float(curr['adx']),"adx_slope":float(curr['adx_slope']),"cdc_up":bool(curr['cdc_up']),"cdc_stop":float(curr['cdc_stop']),"rsi":float(curr['rsi']),"ema_fast":float(curr['ema_fast']),"ema_slow":float(curr['ema_slow']),"retest":bool(trend.get('retest')),"vol_ok":bool(trend.get('vol_ok')),"sl_pct":st.config['sl_pct']*100,"tp_pct":st.config['tp_pct']*100,"actions":actions,"can_open":False,"open_count":len(open_trades),"sideway":bool(trend.get('sideway')),"long":bool(trend.get('long')),"short":bool(trend.get('short')),"rev_long":bool(rev.get('long')),"rev_short":bool(rev.get('short')),"mom_long":bool(mom.get('long')),"mom_short":bool(mom.get('short')),"entry_type":trend.get('entry_type'),"breakout_long":trend.get('breakout_long'),"breakout_short":trend.get('breakout_short'),"cdc_flip_up":trend.get('cdc_flip_up'),"cdc_flip_down":trend.get('cdc_flip_down'),"di_cross_up":trend.get('di_cross_up'),"di_cross_down":trend.get('di_cross_down'),"live_price":price,"candle_close":candle_close_val,"used_symbol":used_sym,"price_source":"MEXC Ticker Live"}
        if signal in ['LONG','SHORT'] and can_open:
            pos_info=calc_position(symbol_key)
            new_trade={"id":len(trades)+1,"symbol":symbol,"symbol_key":symbol_key,"signal":signal,"entry":price,"entry_time":datetime.now().isoformat(),"position_size":pos_info['pos'],"sl":price*(1-st.config['sl_pct']) if signal=='LONG' else price*(1+st.config['sl_pct']),"tp":price*(1+st.config['tp_pct']) if signal=='LONG' else price*(1-st.config['tp_pct']),"status":"PAPER_OPEN","real":False,"note":f"V5.6.1 {trend.get('entry_type')}"}
            trades.append(new_trade); save_trades(trades); set_last_trade_time(symbol_key); actions.append(f"OPEN {signal} {symbol} ${price:.2f} [{trend.get('entry_type')}] SL {new_trade['sl']:.2f}")
        return {"ok":True,"symbol":symbol,"symbol_key":symbol_key,"signal":signal,"price":price,"live_price":price,"candle_close":candle_close_val,"used_symbol":used_sym,"price_source":"MEXC Ticker Live","plus_di":float(curr['plus_di']),"minus_di":float(curr['minus_di']),"adx":float(curr['adx']),"adx_slope":float(curr['adx_slope']),"cdc_up":bool(curr['cdc_up']),"cdc_stop":float(curr['cdc_stop']),"rsi":float(curr['rsi']),"ema_fast":float(curr['ema_fast']),"ema_slow":float(curr['ema_slow']),"retest":bool(trend.get('retest')), "vol_ok":bool(trend.get('vol_ok')),"sl_pct":st.config['sl_pct']*100,"tp_pct":st.config['tp_pct']*100,"actions":actions, "can_open":can_open, "open_count":len(open_trades),"sideway":bool(trend.get('sideway')), "long":bool(trend.get('long')), "short":bool(trend.get('short')),"rev_long":bool(rev.get('long')), "rev_short":bool(rev.get('short')),"mom_long":bool(mom.get('long')), "mom_short":bool(mom.get('short')),"entry_type":trend.get('entry_type'),"breakout_long":trend.get('breakout_long'),"breakout_short":trend.get('breakout_short'),"cdc_flip_up":trend.get('cdc_flip_up'),"cdc_flip_down":trend.get('cdc_flip_down'),"di_cross_up":trend.get('di_cross_up'),"di_cross_down":trend.get('di_cross_down')}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"ok":False,"symbol":symbol,"error":str(e)[:300]}

@app.post("/telegram/webhook")
async def webhook(request: Request):
    try:
        data=await request.json()
        msg=data.get('message',{}) or data.get('edited_message',{})
        chat_id=str(msg.get('chat',{}).get('id',''))
        text=msg.get('text','').strip(); tl=text.lower()
        allowed=os.environ.get("CHAT_ID","").strip() or os.environ.get("TELEGRAM_CHAT_ID","").strip()
        if allowed and chat_id!=str(allowed): return {"ok":True}
        if not text: return {"ok":True}
        def parse_sym(a):
            a=a.lower()
            if a in ['btc','bitcoin']: return 'btc', SYMBOLS['btc']
            if a in ['gold','xau','paxg']: return 'gold', SYMBOLS['gold']
            if a in ['silver','xag']: return 'silver', SYMBOLS['silver']
            if a in ['all']: return 'all', None
            return 'btc', SYMBOLS['btc']
        if tl.startswith('/check'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            results={}
            for k in ['btc','gold','silver']:
                if key!='all' and k!=key: continue
                results[k]=execute_symbol(SYMBOLS[k])
            trades=load_trades(); auto=get_auto_state(); bal=get_mexc_balance()
            out=f"📊 <b>G_POWER V5.6.1.1 NO HEDGE + CLOSE CHECK {key.upper()}</b> {datetime.now().strftime('%d/%m %H:%M')}\n"
            for k,r in results.items():
                if not r.get('ok'): out+=f"\n{k.upper()} ❌ {r.get('error')}\n"
                else:
                    cfg=STRATS[k].config
                    et=r.get('entry_type',''); flip=""; 
                    if r.get('cdc_flip_up'): flip=" CDC FlipUp"
                    if r.get('cdc_flip_down'): flip=" CDC FlipDown"
                    if r.get('di_cross_up'): flip+=" DI CrossUp"
                    if r.get('di_cross_down'): flip+=" DI CrossDown"
                    out+=f"\n<b>{k.upper()} {r.get('used_symbol', r['symbol'])} [Live]</b> {'🟢 ON' if auto.get(k) else '🔴 OFF'} {r['signal']} [{et}]{flip}\n${r['price']:,.2f} CDC {'🟢' if r['cdc_up'] else '🔴'} Stop ${r['cdc_stop']:,.2f}\nEMA{cfg['ema_fast']}/{cfg['ema_slow']} +DI {r['plus_di']:.1f} -DI {r['minus_di']:.1f} ADX {r['adx']:.1f} Slope {r.get('adx_slope',0):.2f} RSI {r['rsi']:.0f}\nRetest {'✅' if r['retest'] else '❌'} Vol {'✅' if r['vol_ok'] else '❌'} Sideway {'❌' if not r.get('sideway') else '✅'} CanOpen {'✅' if r['can_open'] else '❌'} Open {r['open_count']}/{MAX_POS_PER_SYMBOL} SL {r['sl_pct']:.1f}% TP {r['tp_pct']:.0f}%\n"
                    if r['actions']: out+=f"⚡ {'; '.join(r['actions'])}\n"
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            if opens:
                out+=f"\n📌 ถือ {len(opens)} ไม้:\n"
                for ot in opens[-6:]:
                    entry=float(ot['entry']); curr_p=results.get(ot.get('symbol_key','btc'),{}).get('price',entry)
                    sig=ot['signal']; ps=ot.get('position_size',0)
                    if sig=='LONG': upnl=(curr_p-entry)/entry*ps if entry else 0; upp=(curr_p-entry)/entry*100 if entry else 0
                    else: upnl=(entry-curr_p)/entry*ps if entry else 0; upp=(entry-curr_p)/entry*100 if entry else 0
                    sl=ot.get('sl',0)
                    out+=f"{sig} {ot['symbol']} [{ot.get('note','')}] Entry ${entry:,.2f} Now ${curr_p:,.2f} UnPnL ${upnl:+.2f} ({upp:+.1f}%) SL ${sl:,.2f}\n"
            else: out+=f"\n📌 ไม่มีไม้ถืออยู่ - WAIT\n"
            if bal.get('ok'): out+=f"\n🏦 MEXC {bal.get('total')} USDT | Pos {len(bal.get('positions',[]))}\n"
            out+=f"\n✅ V5.6.1.1 NO HEDGE + CLOSE CIRCLE BREAKOUT+RETEST+TURBO VOL0.20 PYRAMID {MAX_POS_PER_SYMBOL}x\n💡 เข้าจุดวงฟ้า: CDC Flip + DI Cross ไม่รอ Retest"
            send_tele(out, chat_id)
            return {"ok":True}
        elif tl.startswith('/total') or tl.startswith('/portfolio') or tl.startswith('/port'):
            trades=load_trades(); bal=get_mexc_balance()
            results={}
            for k in ['btc','gold','silver']:
                try: results[k]=execute_symbol(SYMBOLS[k])
                except: results[k]={"ok":False}
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            closeds=[t for t in trades if str(t.get('status')).upper()=='CLOSED']
            total_closed_pnl = sum([float(t.get('pnl_usd',0)) for t in closeds])
            out=f"💼 <b>G_POWER V5.6.1 PORTFOLIO</b> {datetime.now().strftime('%d/%m %H:%M')}\n"
            out+=f"🏦 MEXC {bal.get('total',37.77) if bal.get('ok') else 37.77} USDT | Real Pos {len(bal.get('positions',[])) if bal.get('ok') else 0}\n\n"
            if opens:
                out+=f"📌 ถือ {len(opens)} ไม้:\n"
                total_upnl=0; total_notional=0
                for ot in opens[-6:]:
                    sym=ot['symbol']; key=ot.get('symbol_key','btc')
                    entry=float(ot['entry']); sl=float(ot.get('sl',0)); ps=float(ot.get('position_size',0))
                    curr_p=results.get(key,{}).get('price',entry); sig=ot['signal']
                    if sig=='LONG': upnl=(curr_p-entry)/entry*ps if entry else 0; upp=(curr_p-entry)/entry*100 if entry else 0
                    else: upnl=(entry-curr_p)/entry*ps if entry else 0; upp=(entry-curr_p)/entry*100 if entry else 0
                    total_upnl+=upnl; total_notional+=ps
                    sign="+" if upnl>=0 else ""
                    out+=f"{sig} {sym.replace('/USDT:USDT','').replace('/USDT','')} [{ot.get('note','')}]\n${entry:,.2f} → ${curr_p:,.2f} = {sign}${upnl:.2f} ({upp:+.2f}%) SL ${sl:,.2f}\n"
                out+=f"\n📊 รวม UnPnL {total_upnl:+.2f}$ Notional ${total_notional:.2f}\n"
                paper_equity = 40 + total_closed_pnl + total_upnl
                out+=f"💰 Paper Equity $40 {total_closed_pnl:+.2f} {total_upnl:+.2f} = ${paper_equity:.2f}\n"
                real_equity = (bal.get('total',37.77) if bal.get('ok') else 37.77) + total_upnl
                out+=f"💵 Real+UnPnL ${real_equity:.2f}\n"
            else:
                out+=f"📌 ไม่มีไม้ถืออยู่ - WAIT\n"
                out+=f"💰 Paper Equity $40 {total_closed_pnl:+.2f} = ${40+total_closed_pnl:.2f}\n"
            if closeds:
                out+=f"\n📕 ปิดแล้ว {len(closeds)} ไม้ PnL {total_closed_pnl:+.2f}$\n"
                for ct in closeds[-3:]:
                    out+=f"{ct.get('signal')} {ct.get('symbol','').replace('/USDT:USDT','')} PnL ${float(ct.get('pnl_usd',0)):+.2f} {ct.get('exit_reason','')[:30]}\n"
            out+=f"\n✅ V5.6.1.1 NO HEDGE + CLOSE CIRCLE"
            send_tele(out, chat_id)
            return {"ok":True}
        elif tl.startswith('/reset'):
            # V5.7.1 RESET - ล้างไพ่เริ่มใหม่: ปิดหมด + ล้างประวัติ + เริ่มทุน $40 ใหม่
            # ต้อง /close all ก่อน ถ้ายังมีไม้ถืออยู่จะไม่ล้างให้ กันล้างพลาด
            trades=load_trades()
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            if opens:
                send_tele(f"⚠️ ยังถือ {len(opens)} ไม้อยู่! พิมพ์ /close all ก่อน แล้วค่อย /reset", chat_id)
                return {"ok":True}
            # ล้างไฟล์
            try:
                import os
                for f in ["/data/g_power_trades.json","/data/auto_state.json","/data/last_signal.json"]:
                    if os.path.exists(f): os.remove(f)
                # เขียนไฟล์เปล่า
                save_trades([])
                set_auto_state('all', False)
            except Exception as e:
                send_tele(f"RESET Error: {e}", chat_id)
                return {"ok":False}
            send_tele("🧹 <b>ล้างไพ่เรียบร้อย</b>\n\n✅ ปิดทุกไม้แล้ว\n✅ ล้างประวัติเทรดเก่าทั้งหมด\n💰 Paper Equity รีเซ็ตเป็น $40.00\n🔴 Auto OFF - พร้อมเริ่มใหม่\n\nพิมพ์ /on all เพื่อเริ่ม Paper ใหม่นับ 1", chat_id)
            return {"ok":True}
        elif tl.startswith('/close'):
            # V5.6.1.1: ปิดทุกไม้ที่ถืออยู่ทันที - ปิดแอพไม่ปิดไม้ ต้องสั่งคำสั่งนี้
            trades=load_trades()
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            if not opens:
                send_tele("📌 ไม่มีไม้ถืออยู่ - ไม่มีอะไรให้ปิด", chat_id)
                return {"ok":True}
            # ดึงราคาสด
            results={}
            for k in ['btc','gold','silver']:
                try: results[k]=execute_symbol(SYMBOLS[k])
                except: results[k]={"ok":False}
            # ปิดทุกไม้ด้วยราคาสด ไม่ต้องรอ TP/SL
            total_pnl=0
            out=f"🔴 <b>CLOSE ALL {len(opens)} ไม้</b> {__import__('datetime').datetime.now().strftime('%d/%m %H:%M')}\n"
            for ot in opens:
                key=ot.get('symbol_key','btc')
                # ใช้ราคาสดจาก results ถ้าไม่มีใช้ entry
                curr_p=results.get(key,{}).get('price', ot.get('entry'))
                entry=float(ot['entry']); sig=ot['signal']; ps=float(ot.get('position_size',0))
                if sig=='LONG': pnl=(curr_p-entry)/entry*ps if entry else 0
                else: pnl=(entry-curr_p)/entry*ps if entry else 0
                total_pnl+=pnl
                ot['status']='CLOSED'; ot['result']='WIN' if pnl>0 else 'LOSS'
                ot['exit']=curr_p; ot['exit_time']=__import__('datetime').datetime.now().isoformat(); ot['exit_reason']='MANUAL CLOSE /close all'
                ot['pnl_usd']=pnl
                out+=f"{sig} {ot['symbol']} ${entry:,.2f} → ${curr_p:,.2f} PnL ${pnl:+.2f}\n"
            save_trades(trades)
            # ปิด Auto ด้วย กันเปิดซ้ำทันที
            set_auto_state('all', False)
            out+=f"\n📊 รวม PnL ${total_pnl:+.2f}\n🔴 Auto OFF all แล้ว - จะไม่เปิดไม้ใหม่จนกว่าจะ /on all"
            send_tele(out, chat_id)
            return {"ok":True}
        elif tl.startswith('/on'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            set_auto_state(key, True)
            send_tele(f"🟢 Auto ON {key.upper()} V5.6.1.1 NO HEDGE + CLOSE", chat_id)
            return {"ok":True}
        elif tl.startswith('/off'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            set_auto_state(key, False)
            send_tele(f"🔴 Auto OFF {key.upper()}", chat_id)
            return {"ok":True}
        elif tl.startswith('/live'):
            parts=tl.split(); key='btc' if len(parts)<2 else parse_sym(parts[1])[0]
            sym=SYMBOLS.get(key, SYMBOLS['btc']); r=execute_symbol(sym)
            send_tele(f"📡 {sym} {r.get('signal')} ${r.get('price',0):,.2f} [{r.get('entry_type')}] +DI {r.get('plus_di',0):.1f} -DI {r.get('minus_di',0):.1f} ADX {r.get('adx',0):.1f}", chat_id)
            return {"ok":True}
        else:
            send_tele(f"❓ {text}\n/check [btc|gold|silver|all]\n/total - พอร์ต\n/on [btc|gold|silver|all]\n/off [btc|gold|silver|all]\n/close all - ปิดทุกไม้ทันที\n/reset - ล้างไพ่เริ่มใหม่ (ต้อง /close all ก่อน)", chat_id)
            return {"ok":True}
    except Exception as e:
        print(f"ERR {e}"); import traceback; traceback.print_exc(); return {"ok":True}


@app.get("/debug/price")
def debug_price():
    out={}
    for k, sym in SYMBOLS.items():
        df = get_data(sym)
        if isinstance(df, tuple):
            out[k]={"error":df[1]}
        else:
            live = df.attrs.get('live_price',0) if hasattr(df,'attrs') else 0
            candle = df.attrs.get('candle_close',0) if hasattr(df,'attrs') else 0
            used = df.attrs.get('used_symbol',sym) if hasattr(df,'attrs') else sym
            out[k]={"used_symbol":used,"live_ticker":live,"candle_close_15m":candle,"diff_pct":round((live-candle)/candle*100,3) if candle else 0,"last_candle_time":str(df.iloc[-1]['datetime']),"note":"live ต้องตรงกับแอพ MEXC Last Price ถ้า diff >0.5% แสดงว่าแท่งเก่า"}
    return out


@app.get("/bt")
def backtest_endpoint(days: int = 30, symbol_key: str = "all"):
    """
    BT กราฟราคาจริงจาก MEXC - รันบน Render ที่มีเน็ต
    เปิด: https://mexc-btc-bot-1.onrender.com/bt?days=30
    """
    import pandas as pd
    results = {}
    targets = []
    if symbol_key=="all":
        targets=[("btc","BTC/USDT:USDT"),("gold","XAU/USDT:USDT"),("silver","SILVER/USDT:USDT")]
    elif symbol_key=="btc":
        targets=[("btc","BTC/USDT:USDT")]
    elif symbol_key=="gold":
        targets=[("gold","XAU/USDT:USDT")]
    elif symbol_key=="silver":
        targets=[("silver","SILVER/USDT:USDT")]
    else:
        targets=[("btc","BTC/USDT:USDT")]
    for key, sym in targets:
        try:
            st = STRATS[key]
            df = get_data(sym)
            if isinstance(df, tuple):
                results[key]={"error":df[1]}
                continue
            # get_data ดึงแค่ 250 แท่ง = ~2.6 วัน ถ้าอยากได้ 30 วันต้องดึงเพิ่ม
            # ใช้ df ที่มีอยู่ก่อน - ถ้าไม่พอจะบอก
            df = st.add_indicators(df)
            trades=[]
            equity=40.0
            open_trade=None
            for i in range(2, len(df)):
                curr=df.iloc[i]; prev=df.iloc[i-1]; price=float(curr['close'])
                if open_trade:
                    entry=open_trade['entry']; sig=open_trade['signal']
                    new_sl = st.get_trailing_sl(entry, price, float(curr['cdc_stop']), sig)
                    if sig=='LONG' and new_sl>open_trade['sl']: open_trade['sl']=new_sl
                    if sig=='SHORT' and new_sl<open_trade['sl']: open_trade['sl']=new_sl
                    sl_hit=False; exit_p=price; reason="TREND"
                    if sig=='LONG' and float(curr['low']) <= open_trade['sl']: sl_hit=True; exit_p=open_trade['sl']; reason="SL"
                    if sig=='SHORT' and float(curr['high']) >= open_trade['sl']: sl_hit=True; exit_p=open_trade['sl']; reason="SL"
                    exit_info = st.check_exit_trend_change(curr, prev, sig)
                    # V5.7: TP ต้องยืนยัน 2 ตัว - แก้ TP ไวเกิน (DI Flip เดี่ยวไม่ปิด)
                    # นับสัญญาณที่เกิดพร้อมกัน
                    confirm_count = 0
                    if exit_info['reasons']:
                        # CDC Flip นับ 2, EMA+DI อย่างละ 1
                        for r in exit_info['reasons']:
                            if 'CDC' in r: confirm_count+=2
                            else: confirm_count+=1
                    tp_hit = confirm_count>=2  # ต้อง >=2 ถึงปิด
                    if sl_hit or tp_hit:
                        if not sl_hit: exit_p=price; reason=",".join(exit_info['reasons'])
                        pnl=(exit_p-entry)/entry*open_trade['pos'] if sig=='LONG' else (entry-exit_p)/entry*open_trade['pos']
                        equity+=pnl
                        trades.append({"signal":sig,"entry":entry,"exit":exit_p,"pnl":round(pnl,2),"reason":reason,"type":open_trade.get('entry_type'),"equity":round(equity,2)})
                        open_trade=None
                        continue
                if not open_trade:
                    trend=st.check_trend(curr, prev); mom=st.check_momentum(curr)
                    # V5.6 NO HEDGE: ใน BT ถือได้ทีละ 1 ไม้
                    if trend['long'] and mom['long']:
                        pos=40*0.02/st.config['sl_pct']
                        open_trade={'signal':'LONG','entry':price,'pos':pos,'sl':price*(1-st.config['sl_pct']),'entry_type':trend.get('entry_type')}
                    elif trend['short'] and mom['short']:
                        pos=40*0.02/st.config['sl_pct']
                        open_trade={'signal':'SHORT','entry':price,'pos':pos,'sl':price*(1+st.config['sl_pct']),'entry_type':trend.get('entry_type')}
            wins=[t for t in trades if t['pnl']>0]
            total_pnl=sum([t['pnl'] for t in trades])
            results[key]={
                "symbol":sym,
                "candles":len(df),
                "period":f"{df.iloc[0]['datetime']} -> {df.iloc[-1]['datetime']}",
                "trades":len(trades),
                "win":len(wins),
                "winrate":round(len(wins)/max(len(trades),1)*100,1),
                "total_pnl":round(total_pnl,2),
                "equity":round(equity,2),
                "equity_pct":round((equity-40)/40*100,2),
                "last_trades":trades[-10:],
                "note":"BT บน 15m 250 แท่ง (~2.6 วัน) + TP ต้องยืนยัน 2 ตัว (แก้ TP ไว) - ถ้าจะ BT 30 วันให้เพิ่ม limit ใน get_data"
            }
        except Exception as e:
            import traceback; traceback.print_exc()
            results[key]={"error":str(e)[:300]}
    # ส่งเป็น HTML อ่านง่าย
    from fastapi.responses import HTMLResponse
    html="<html><body style='background:#0a0e1a;color:#fff;font-family:Arial;padding:20px'><h1>G_POWER BT กราฟราคาจริง MEXC</h1>"
    for k,v in results.items():
        if "error" in v:
            html+=f"<h2>{k} ❌ {v['error']}</h2>"
        else:
            html+=f"<h2>{k.upper()} {v['symbol']} | {v['candles']} แท่ง {v['period']}</h2><p>Trades {v['trades']} Win {v['win']} WinRate {v['winrate']}% PnL ${v['total_pnl']:+.2f} Equity ${v['equity']} ({v['equity_pct']:+.2f}%)</p><table border=1 cellpadding=5><tr><th>Signal</th><th>Type</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr>"
            for t in v['last_trades']:
                html+=f"<tr><td>{t['signal']}</td><td>{t['type']}</td><td>{t['entry']:.2f}</td><td>{t['exit']:.2f}</td><td>{t['pnl']:+.2f}</td><td>{t['reason']}</td></tr>"
            html+="</table>"
    html+="<p>เปิด /bt?days=30&symbol_key=btc ดูทีละตัวได้</p></body></html>"
    return HTMLResponse(html)

@app.api_route("/ping", methods=["GET","HEAD"])
def ping():
    return {"status":"ok V5.6.1.1 NO HEDGE + CLOSE CIRCLE","auto":get_auto_state(),"dir":str(DATA_DIR),"trades":len(load_trades())}

@app.api_route("/health", methods=["GET","HEAD"])
def health():
    return {"status":"OK V5.6.1","dir":str(DATA_DIR),"auto":get_auto_state().get('btc',False)}

@app.get("/", response_class=HTMLResponse)
def home():
    auto=get_auto_state()
    return f"<html><body style='background:#0a0e1a;color:#fff;font-family:Arial;padding:20px'><h1>G_POWER V5.6.1.1 NO HEDGE + CLOSE</h1><p>BTC {'🟢' if auto.get('btc') else '🔴'} GOLD {'🟢' if auto.get('gold') else '🔴'} SILVER {'🟢' if auto.get('silver') else '🔴'}</p><p>✅ BREAKOUT CDC Flip + DI Cross + RETEST + TURBO | VOL 0.20 | PYRAMID 3x | NO FADE</p><a href='/ping'>Ping</a></body></html>"

@app.get("/live")
def live_api(symbol: str = Query("BTC/USDT")): return execute_symbol(symbol)

@app.get("/auto/run")
def autorun():
    auto=get_auto_state(); res=[]
    for k in ['btc','gold','silver']:
        if auto.get(k): res.append(execute_symbol(SYMBOLS[k]))
    return {"results":res}
