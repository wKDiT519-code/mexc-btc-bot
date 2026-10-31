"""
G_POWER V5.1 AUDIT FIX - แก้รอยรั่วที่ตรวจเจอ
- PING HEAD 405 -> ใช้ api_route GET,HEAD
- SAVE atomic temp+rename กันไฟล์ corrupt
- MAX_POS 1 ต่อสัญลักษณ์ กันเปิดซ้ำทุก 15m
- COOLDOWN 1 ชม. ต่อสัญลักษณ์
- ENV strip ครบ
- REAL=false ปลอดภัย Paper ก่อน
- 3 หัวใจครบ Retest+Trailing+Trend TP
"""

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
try:
    from strategy_G_POWER_V5_TREND import Strategy_G_Power as StrategyMulti
    print("[V5.1 AUDIT FIX] 3 HEARTS + NO LEAK")
    USE_V5=True
except:
    from strategy_G_POWER import Strategy_G_Power as StrategyMulti
    USE_V5=False

from datetime import datetime, timedelta
import os, ccxt, pandas as pd, json, requests, tempfile, shutil
from pathlib import Path

app = FastAPI(title="G_POWER V5.1 AUDIT NO LEAK")

STRATS = {
    "btc": StrategyMulti("btc"),
    "gold": StrategyMulti("gold"),
    "silver": StrategyMulti("silver"),
}
strat = STRATS["btc"]

CAPITAL = 40
RISK_PCT = 0.02
LEVERAGE = 3

SYMBOLS = {
    "btc": "BTC/USDT",
    "gold": "XAU/USDT",
    "silver": "XAG/USDT",
    "xau": "XAU/USDT",
    "xag": "XAG/USDT",
    "paxg": "PAXG/USDT",
}

DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRADES_FILE = DATA_DIR / "g_power_trades.json"
AUTO_STATE_FILE = DATA_DIR / "auto_state.json"
LAST_TRADE_TIME_FILE = DATA_DIR / "last_trade_time.json"
print(f"[V5.1] DATA_DIR={DATA_DIR} exists={DATA_DIR.exists()}")

def atomic_save(path: Path, data):
    """กันไฟล์ corrupt ตอน Render ดับ - เขียน temp แล้ว rename"""
    try:
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w') as f:
            json.dump(data, f, default=str, indent=2)
        tmp.replace(path)
    except Exception as e:
        print(f"atomic_save {path} err {e}")
        try:
            with open(path, 'w') as f:
                json.dump(data, f, default=str, indent=2)
        except: pass

def load_trades():
    if TRADES_FILE.exists():
        try:
            with open(TRADES_FILE,'r') as f:
                d=json.load(f)
                # clean sample trades
                clean=[t for t in d if not str(t.get('note','')).lower().startswith('sample')]
                return clean
        except: return []
    return []

def save_trades(t): atomic_save(TRADES_FILE, t)

def get_auto_state():
    if AUTO_STATE_FILE.exists():
        try:
            with open(AUTO_STATE_FILE,'r') as f:
                d=json.load(f)
                if isinstance(d,bool): return {"btc":d,"gold":False,"silver":False}
                if "enabled" in d: return {"btc":d.get("enabled",False),"gold":False,"silver":False}
                return d
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
    times=get_last_trade_times()
    times[symbol_key]=datetime.now().isoformat()
    atomic_save(LAST_TRADE_TIME_FILE, times)

def can_open_new(symbol_key, cooldown_hours=1):
    """กันเปิดถี่ - ต้องห่างกัน 1 ชม."""
    times=get_last_trade_times()
    last_str=times.get(symbol_key)
    if not last_str: return True
    try:
        last=datetime.fromisoformat(last_str)
        if datetime.now() - last < timedelta(hours=cooldown_hours):
            return False
        return True
    except: return True

def calc_position(symbol_key="btc"):
    cfg=STRATS.get(symbol_key, STRATS['btc']).config
    sl=cfg['sl_pct']; tp=cfg['tp_pct']
    risk=CAPITAL*RISK_PCT
    pos=risk/sl if sl else risk/0.034
    return {"risk":risk,"pos":pos,"margin":pos/LEVERAGE,"sl":sl*100,"tp":tp*100,"rr":round(tp/sl,1)}

def get_data(symbol="BTC/USDT"):
    try:
        ex=ccxt.mexc({"options":{"defaultType":"swap"}})
        ohlcv=ex.fetch_ohlcv(symbol,'15m',limit=250)
        df=pd.DataFrame(ohlcv,columns=['timestamp','open','high','low','close','volume'])
        df['datetime']=pd.to_datetime(df['timestamp'],unit='ms')
        return df
    except Exception as e: return (None,str(e))

def get_mexc_balance():
    try:
        key=os.environ.get("MEXC_API_KEY","").strip(); sec=os.environ.get("MEXC_API_SECRET","").strip()
        if not key or not sec: return {"ok":False,"error":"No API"}
        ex=ccxt.mexc({'apiKey':key,'secret':sec,'options':{'defaultType':'swap'},'enableRateLimit':True})
        bal=ex.fetch_balance({'type':'swap'}); usdt=bal.get('USDT',{})
        poss=[]
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
    if 'XAU' in s or 'PAXG' in s or 'GOLD' in s: return STRATS['gold']
    if 'XAG' in s or 'SILVER' in s: return STRATS['silver']
    return STRATS['btc']

def execute_symbol(symbol, manage_open=True):
    try:
        st=get_strat(symbol)
        symbol_key=st.symbol_key
        df=get_data(symbol)
        if isinstance(df,tuple): return {"ok":False,"symbol":symbol,"error":df[1]}
        df=st.add_indicators(df)
        curr=df.iloc[-1]; prev=df.iloc[-2]
        price=float(curr['close'])
        trades=load_trades()
        open_trades=[t for t in trades if t.get('symbol')==symbol and str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]

        actions=[]
        # 2+3 Trailing + TP Trend Change
        for ot in open_trades:
            entry=float(ot['entry']); sig=ot['signal']
            new_sl=st.get_trailing_sl(entry, price, float(curr['cdc_stop']), sig)
            old_sl=float(ot.get('sl', entry*(1-st.config['sl_pct']) if sig=='LONG' else entry*(1+st.config['sl_pct'])))
            if sig=='LONG' and new_sl>old_sl:
                ot['sl']=new_sl; ot['trailing']=f"Trail {old_sl:.0f}->{new_sl:.0f}"; actions.append(f"Trailing LONG {symbol} SL {old_sl:.0f}->{new_sl:.0f}")
            elif sig=='SHORT' and new_sl<old_sl:
                ot['sl']=new_sl; ot['trailing']=f"Trail {old_sl:.0f}->{new_sl:.0f}"; actions.append(f"Trailing SHORT {symbol} SL {old_sl:.0f}->{new_sl:.0f}")
            exit_info=st.check_exit_trend_change(curr, prev, sig)
            if exit_info['tp']:
                ot['status']='CLOSED'; ot['result']='WIN' if (price>entry and sig=='LONG') or (price<entry and sig=='SHORT') else 'LOSS'
                ot['exit']=price; ot['exit_time']=datetime.now().isoformat(); ot['exit_reason']='TREND CHANGE: '+','.join(exit_info['reasons'])
                pnl=(price-entry)/entry*ot.get('position_size', calc_position(symbol_key)['pos']) if sig=='LONG' else (entry-price)/entry*ot.get('position_size',0)
                ot['pnl_usd']=pnl
                actions.append(f"TP TREND CHANGE {symbol} {sig} {','.join(exit_info['reasons'])} PnL ${pnl:+.2f}")
        if actions:
            save_trades(trades)

        # 1. จุดเข้าแม่น + กันเปิดซ้ำ
        rev=st.check_reversal(prev,curr)
        trend=st.check_trend(curr)
        mom=st.check_momentum(curr)
        signal="WAIT"
        can_open=len(open_trades)==0 and can_open_new(symbol_key, cooldown_hours=1)  # MAX_POS + COOLDOWN
        if can_open:
            if rev['long'] and trend['long'] and mom['long'] and not trend['sideway']: signal="LONG"
            elif rev['short'] and trend['short'] and mom['short'] and not trend['sideway']: signal="SHORT"
        else:
            if len(open_trades)>0:
                signal=f"HOLD {open_trades[0]['signal']}"
            else:
                signal="COOLDOWN"

        # ถ้า signal ใหม่ไม่ใช่ WAIT ให้บันทึก Paper
        if signal in ['LONG','SHORT'] and can_open:
            pos_info=calc_position(symbol_key)
            new_trade={
                "id":len(trades)+1,
                "symbol":symbol,
                "symbol_key":symbol_key,
                "signal":signal,
                "entry":price,
                "entry_time":datetime.now().isoformat(),
                "position_size":pos_info['pos'],
                "sl":price*(1-st.config['sl_pct']) if signal=='LONG' else price*(1+st.config['sl_pct']),
                "tp":price*(1+st.config['tp_pct']) if signal=='LONG' else price*(1-st.config['tp_pct']),
                "status":"PAPER_OPEN",
                "real":False,
            }
            trades.append(new_trade)
            save_trades(trades)
            set_last_trade_time(symbol_key)
            actions.append(f"OPEN {signal} {symbol} ${price:.2f} SL {new_trade['sl']:.2f}")

        return {"ok":True,"symbol":symbol,"symbol_key":symbol_key,"signal":signal,"price":price,
                "plus_di":float(curr['plus_di']),"minus_di":float(curr['minus_di']),"adx":float(curr['adx']),
                "cdc_up":bool(curr['cdc_up']),"cdc_stop":float(curr['cdc_stop']),
                "rsi":float(curr['rsi']),"ema_fast":float(curr['ema_fast']),"ema_slow":float(curr['ema_slow']),
                "retest":bool(trend.get('retest')), "vol_ok":bool(trend.get('vol_ok')),
                "sl_pct":st.config['sl_pct']*100,"tp_pct":st.config['tp_pct']*100,
                "actions":actions, "can_open":can_open, "open_count":len(open_trades)}
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
            out=f"📊 <b>G_POWER V5.1 AUDIT CHECK {key.upper()}</b> {datetime.now().strftime('%d/%m %H:%M')}\n"
            for k,r in results.items():
                if not r.get('ok'): out+=f"\n{k.upper()} ❌ {r.get('error')}\n"
                else:
                    cfg=STRATS[k].config
                    out+=f"\n<b>{k.upper()} {r['symbol']}</b> {'🟢 ON' if auto.get(k) else '🔴 OFF'} {r['signal']}\n${r['price']:,.2f} CDC {'🟢' if r['cdc_up'] else '🔴'} Stop ${r['cdc_stop']:,.2f}\nEMA{cfg['ema_fast']}/{cfg['ema_slow']} +DI {r['plus_di']:.1f} -DI {r['minus_di']:.1f} ADX {r['adx']:.1f} RSI {r['rsi']:.0f}\nRetest {'✅' if r['retest'] else '❌'} Vol {'✅' if r['vol_ok'] else '❌'} CanOpen {'✅' if r['can_open'] else '❌'} Open {r['open_count']} SL {r['sl_pct']:.1f}% TP {r['tp_pct']:.0f}%\n"
                    if r['actions']: out+=f"⚡ {'; '.join(r['actions'])}\n"
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            if opens:
                out+=f"\n📌 ถือ {len(opens)} ไม้:\n"
                for ot in opens[-3:]:
                    entry=float(ot['entry']); curr_p=results.get(ot.get('symbol_key','btc'),{}).get('price',entry)
                    sig=ot['signal']; ps=ot.get('position_size',0)
                    if sig=='LONG': upnl=(curr_p-entry)/entry*ps if entry else 0; upp=(curr_p-entry)/entry*100 if entry else 0
                    else: upnl=(entry-curr_p)/entry*ps if entry else 0; upp=(entry-curr_p)/entry*100 if entry else 0
                    sl=ot.get('sl',0)
                    out+=f"{sig} {ot['symbol']} Entry ${entry:,.2f} Now ${curr_p:,.2f} UnPnL ${upnl:+.2f} ({upp:+.1f}%) SL ${sl:,.2f} {ot.get('trailing','')}\n"
            else: out+=f"\n📌 ไม่มีไม้ถืออยู่ - WAIT\n"
            if bal.get('ok'): out+=f"\n🏦 MEXC {bal.get('total')} USDT | Pos {len(bal.get('positions',[]))}\n"
            out+=f"\n✅ AUDIT: HEAD OK | Atomic Save | MAX_POS 1 | COOLDOWN 1h | ENV strip | REAL=false\n💡 1.Retest 2.Trailing BE Lock CDC 3.TP Trend Change"
            send_tele(out, chat_id)
            return {"ok":True}

        elif tl.startswith('/on'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            set_auto_state(key, True)
            send_tele(f"🟢 Auto ON {key.upper()} {datetime.now().strftime('%d/%m %H:%M')} V5.1 AUDIT", chat_id)
            return {"ok":True}
        elif tl.startswith('/off'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            set_auto_state(key, False)
            send_tele(f"🔴 Auto OFF {key.upper()}", chat_id)
            return {"ok":True}
        elif tl.startswith('/live'):
            parts=tl.split(); key='btc' if len(parts)<2 else parse_sym(parts[1])[0]
            sym=SYMBOLS.get(key, SYMBOLS['btc']); r=execute_symbol(sym)
            send_tele(f"📡 {sym} {r.get('signal')} ${r.get('price',0):,.2f} +DI {r.get('plus_di',0):.1f} -DI {r.get('minus_di',0):.1f} ADX {r.get('adx',0):.1f} RSI {r.get('rsi',0):.0f} Retest {'✅' if r.get('retest') else '❌'}", chat_id)
            return {"ok":True}
        else:
            send_tele(f"❓ {text}\n/check [btc|gold|silver|all]\n/on [btc|gold|silver|all]\n/off [btc|gold|silver|all]\n/live [btc|gold|silver]", chat_id)
            return {"ok":True}
    except Exception as e:
        print(f"ERR {e}"); return {"ok":True}

@app.api_route("/ping", methods=["GET","HEAD"])
def ping():
    return {"status":"ok V5.1 AUDIT","auto":get_auto_state(),"dir":str(DATA_DIR),"trades":len(load_trades())}

@app.api_route("/health", methods=["GET","HEAD"])
def health():
    return {"status":"OK V5.1 NO LEAK","dir":str(DATA_DIR),"auto":get_auto_state().get('btc',False)}

@app.get("/", response_class=HTMLResponse)
def home():
    auto=get_auto_state()
    return f"<html><body style='background:#0a0e1a;color:#fff;font-family:Arial;padding:20px'><h1>G_POWER V5.1 AUDIT NO LEAK</h1><p>BTC {'🟢' if auto.get('btc') else '🔴'} GOLD {'🟢' if auto.get('gold') else '🔴'} SILVER {'🟢' if auto.get('silver') else '🔴'}</p><p>✅ HEAD OK | Atomic Save | MAX_POS | COOLDOWN | ENV strip</p><p>1.Retest 2.Trailing BE Lock CDC 3.TP Trend Change</p><a href='/ping'>Ping</a></body></html>"

@app.get("/live")
def live_api(symbol: str = Query("BTC/USDT")): return execute_symbol(symbol)

@app.get("/auto/run")
def autorun():
    auto=get_auto_state(); res=[]
    for k in ['btc','gold','silver']:
        if auto.get(k): res.append(execute_symbol(SYMBOLS[k]))
    return {"results":res}
