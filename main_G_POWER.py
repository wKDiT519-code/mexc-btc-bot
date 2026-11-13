"""G_POWER V5.6.1.1 - 379 lines fixed"""
# 379 lines fixed - _m sets default config if old strategy has no ema_fast
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
try:
    from strategy_G_POWER import Strategy_G_Power as StrategyMulti
    USE_V5=True
except:
    from strategy_G_POWER import Strategy_G_Power as StrategyMulti
    USE_V5=False
from datetime import datetime, timedelta
import os, ccxt, pandas as pd, json, requests
from pathlib import Path
app = FastAPI(title="G_POWER V5.6.1.1 NO HEDGE + CLOSE")
def _m(k):
    try: s=StrategyMulti(k)
    except: s=StrategyMulti(); s.symbol_key=k
    if not getattr(s,'config',{}).get('ema_fast'): s.config={'ema_fast':12 if k=='btc' else 21 if k=='gold' else 9,'ema_slow':26 if k=='btc' else 55 if k=='gold' else 21,'ema_trend':50 if k=='btc' else 100 if k=='gold' else 34,'rsi_fast':12 if k=='btc' else 14 if k=='gold' else 9,'rsi_entry_long':(35,70),'rsi_entry_short':(25,65),'adx_min':10,'adx_sideway':10,'adx_turbo':28,'di_min':10,'di_turbo':20,'sl_pct':0.034 if k=='btc' else 0.028 if k=='gold' else 0.035,'tp_pct':0.18 if k=='btc' else 0.12 if k=='gold' else 0.10,'cdc_atr_fast':5,'cdc_mult_fast':0.5,'cdc_atr_slow':10,'cdc_mult_slow':2.0,'vol_filter':0.20,'sideway_pct':1.2,'retest_pct':0.012,'be_trigger':0.01,'lock_trigger':0.02,'lock_pct':0.005}
    return s
STRATS = {"btc": _m("btc"), "gold": _m("gold")}
strat = STRATS["btc"]
MAX_POS_PER_SYMBOL=3; COOLDOWN_HOURS=0.5
CAPITAL=40; RISK_PCT=0.02; LEVERAGE=3
SYMBOLS = {"btc": "BTC/USDT", "gold": "PAXG/USDT:USDT"}
DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRADES_FILE = DATA_DIR / "g_power_trades.json"
AUTO_STATE_FILE = DATA_DIR / "auto_state.json"
LAST_TRADE_TIME_FILE = DATA_DIR / "last_trade_time.json"
def atomic_save(path: Path, data):
    try:
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w') as f:
            json.dump(data, f, default=str, indent=2)
        tmp.replace(path)
    except Exception as e:
        print(f"atomic_save err {e}")
        try:
            with open(path, 'w') as f: json.dump(data, f, default=str, indent=2)
        except: pass
def load_trades():
    if TRADES_FILE.exists():
        try:
            with open(TRADES_FILE,'r') as f:
                d=json.load(f)
                return [t for t in d if not str(t.get('note','')).lower().startswith('sample')]
        except: return []
    return []
def save_trades(t): atomic_save(TRADES_FILE, t)
def get_auto_state():
    if AUTO_STATE_FILE.exists():
        try:
            with open(AUTO_STATE_FILE,'r') as f:
                d=json.load(f)
                if isinstance(d,bool): return {"btc":d,"gold":d}
                if not isinstance(d, dict): return {"btc":True,"gold":True}
                if "enabled" in d:
                    val=bool(d.get("enabled",False))
                    return {"btc":val,"gold":val}
                if "btc" in d or "gold" in d:
                    return {"btc": bool(d.get("btc",False)), "gold": bool(d.get("gold",False))}
                return {"btc":True,"gold":True}
        except Exception as e:
            print(f"get_auto_state error {e}, reset to ON")
            try:
                AUTO_STATE_FILE.unlink(missing_ok=True)
            except: pass
            return {"btc":True,"gold":True}
    return {"btc":True,"gold":True}
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
    candidates=[symbol]
    if "PAXG" in symbol: candidates+= ["PAXG/USDT","XAUT/USDT:USDT"]
    for sym in candidates:
        try:
            ex=ccxt.mexc({"options":{"defaultType":"swap"}})
            ohlcv=ex.fetch_ohlcv(sym,'15m',limit=250)
            if ohlcv and len(ohlcv)>50:
                df=pd.DataFrame(ohlcv,columns=['timestamp','open','high','low','close','volume'])
                df['datetime']=pd.to_datetime(df['timestamp'],unit='ms')
                if sym!=symbol:
                    print(f"[FALLBACK] {symbol}->{sym}")
                return df
        except: continue
    return (None, f"mexc no symbol {symbol}")
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
def send_tele_photo(img_bytes, caption, chat_id=None):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    chat=chat_id or os.environ.get("TELEGRAM_CHAT_ID","").strip() or os.environ.get("CHAT_ID","").strip()
    if not token or not chat: return {"ok":False}
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id":chat,"caption":caption,"parse_mode":"HTML"}, files={"photo":("portfolio.png", img_bytes, "image/png")}, timeout=20)
        return {"ok":r.status_code==200}
    except Exception as e: print(f"send_photo err {e}"); return {"ok":False}
def make_portfolio_image(paper, unpnl, closed_pnl, win_rate, win_n, total_n, btc_pnl, gold_pnl, opens):
    # PIL infographic - English only (Thai font not on Render)
    try:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as e:
            print(f"PIL NOT INSTALLED: {e} - add Pillow to requirements.txt")
            return None
        import io
        W,H=1080,1350
        img=Image.new("RGB",(W,H),"#0A0E1A"); d=ImageDraw.Draw(img)
        try:
            f_big=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",56)
            f_mid=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",36)
            f_small=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",28)
        except:
            try: f_big=ImageFont.truetype("DejaVuSans-Bold.ttf",56); f_mid=ImageFont.truetype("DejaVuSans-Bold.ttf",36); f_small=ImageFont.truetype("DejaVuSans.ttf",28)
            except: f_big=ImageFont.load_default(); f_mid=f_big; f_small=f_big
        d.rectangle([30,30,W-30,170],fill="#1E2A4A")
        d.text((60,55),"G_POWER  PORTFOLIO",font=f_big,fill="white")
        d.text((60,120),f"{datetime.now().strftime('%d/%m %H:%M')}  -  BTC + GOLD  -  PAPER",font=f_small,fill="#8FA3C8")
        def card(x,y,w,h,label,value,color):
            d.rectangle([x,y,x+w,y+h],fill="#141D33")
            d.text((x+30,y+20),label,font=f_small,fill="#8FA3C8")
            d.text((x+30,y+60),value,font=f_mid,fill=color)
        card(30,200,500,170,"PAPER BALANCE",f"${paper:.2f}","white")
        card(550,200,500,170,"UNREALIZED PnL",f"{unpnl:+.2f}","#2ED573" if unpnl>=0 else "#FF4757")
        card(30,390,500,170,"TOTAL CLOSED",f"{closed_pnl:+.2f}","#2ED573" if closed_pnl>=0 else "#FF4757")
        card(550,390,500,170,"WIN RATE",f"{win_rate:.0f}%  ({win_n}/{total_n})","white")
        d.rectangle([30,580,W-30,880],fill="#141D33")
        d.text((60,600),"PnL BY COIN",font=f_mid,fill="white")
        # BTC bar
        d.text((60,660),"BTC",font=f_mid,fill="white")
        bw=int(min(abs(btc_pnl)/max(1,abs(btc_pnl)+abs(gold_pnl))*650,650)) if (btc_pnl!=0 or gold_pnl!=0) else 0
        d.rectangle([200,660,200+max(bw,20),700],fill="#2ED573" if btc_pnl>=0 else "#FF4757")
        d.text((870,660),f"{btc_pnl:+.2f}",font=f_mid,fill="#2ED573" if btc_pnl>=0 else "#FF4757")
        d.text((60,730),"GOLD",font=f_mid,fill="white")
        gw=int(min(abs(gold_pnl)/max(1,abs(btc_pnl)+abs(gold_pnl))*650,650)) if (btc_pnl!=0 or gold_pnl!=0) else 0
        d.rectangle([200,730,200+max(gw,20),770],fill="#2ED573" if gold_pnl>=0 else "#FF4757")
        d.text((300 if gold_pnl>=0 else 300,730),f"{gold_pnl:+.2f}",font=f_mid,fill="#2ED573" if gold_pnl>=0 else "#FF4757")
        d.rectangle([30,900,W-30,1250],fill="#141D33")
        d.text((60,920),f"OPEN  {len(opens)} TRADES",font=f_mid,fill="white")
        y=980
        for o in opens[:5]:
            col="#2ED573" if o['pnl']>=0 else "#FF4757"
            d.text((60,y),f"{o['key']} {o['sig']}",font=f_small,fill="white")
            d.text((360,y),o['txt'],font=f_small,fill="#8FA3C8")
            d.text((820,y),f"{o['pnl']:+.2f}",font=f_small,fill=col)
            y+=50
        d.text((60,1210),"MEXC Paper Only - Not Real Trade",font=f_small,fill="#8FA3C8")
        buf=io.BytesIO(); img.save(buf,format="PNG"); buf.seek(0); return buf.getvalue()
    except Exception as e:
        print(f"make_image err {e}"); return None
def get_strat(symbol):
    s=symbol.upper()
    if 'BTC' in s: return STRATS['btc']
    if 'XAU' in s or 'PAXG' in s or 'GOLD' in s or 'XAUT' in s: return STRATS['gold']
    return STRATS['btc']
def execute_symbol(symbol, manage_open=True):
    try:
        st=get_strat(symbol)
        symbol_key=st.symbol_key
        df=get_data(symbol)
        if isinstance(df,tuple): return {"ok":False,"symbol":symbol,"error":df[1]}
        df=st.add_indicators(df)
        for _c,_d in [('rsi',50.0),('ema_fast',df['ema12'] if 'ema12' in df.columns else df['close']),('ema_slow',df['ema26'] if 'ema26' in df.columns else df['close']),('plus_di',0.0),('minus_di',0.0),('adx',15.0),('cdc_up',True),('cdc_stop',df['close'])]: df[_c]=_d if _c not in df.columns else df[_c]
        curr=df.iloc[-1]; prev=df.iloc[-2]
        price=float(curr['close'])
        trades=load_trades()
        open_trades=[t for t in trades if t.get('symbol')==symbol and str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
        actions=[]
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
                pnl=(price-entry)/entry*ot.get('position_size',0) if sig=='LONG' else (entry-price)/entry*ot.get('position_size',0)
                ot['pnl_usd']=pnl
                actions.append(f"TP TREND CHANGE {symbol} {sig} {','.join(exit_info['reasons'])} PnL ${pnl:+.2f}")
        if actions:
            save_trades(trades)
        rev=st.check_reversal(prev,curr)
        trend=st.check_trend(curr)
        mom=st.check_momentum(curr)
        signal="WAIT"
        # V5.2.4 PYRAMID: เข้าเพิ่มได้ถ้ามีจังหวะดี จาก 1 เป็น 3 ไม้
        can_open=len(open_trades) < MAX_POS_PER_SYMBOL and can_open_new(symbol_key, cooldown_hours=COOLDOWN_HOURS)
        if len(open_trades)>0 and can_open:
            existing_sig=open_trades[0]['signal']
            if (trend['long'] and existing_sig!='LONG') or (trend['short'] and existing_sig!='SHORT'):
                can_open=False  # ไม่เพิ่มไม้สวนทาง
        if can_open and not trend['sideway']:
            # V5.2.2 PULLBACK ENTRY: ไม่ต้องรอ cross ทุกครั้ง
            if trend['long'] and mom['long']:
                signal="LONG"
            elif trend['short'] and mom['short']:
                signal="SHORT"
        elif not can_open:
            if len(open_trades)>=MAX_POS_PER_SYMBOL:
                signal=f"MAX {len(open_trades)}/{MAX_POS_PER_SYMBOL} HOLD {open_trades[0]['signal']}"
            elif len(open_trades)>0:
                signal=f"HOLD {open_trades[0]['signal']} {len(open_trades)}/{MAX_POS_PER_SYMBOL}"
            else:
                signal="COOLDOWN"
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
                "note":f"V5.2.2 pullback rev:{rev['long'] or rev['short']}"
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
                "actions":actions, "can_open":can_open, "open_count":len(open_trades),
                "sideway":bool(trend.get('sideway')), "long":bool(trend.get('long')), "short":bool(trend.get('short')),
                "rev_long":bool(rev.get('long')), "rev_short":bool(rev.get('short')),
                "mom_long":bool(mom.get('long')), "mom_short":bool(mom.get('short'))}
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
        if allowed and chat_id!=str(allowed):
            try: send_tele("CHAT_ID ไม่ตรง คุณพิมพ์จาก ID: " + str(chat_id) + " แต่ใน Render = " + str(allowed), chat_id=chat_id)
            except: pass
            return {"ok":True}
        if not text: return {"ok":True}
        def parse_sym(a):
            a=a.lower()
            return {'btc':('btc',SYMBOLS['btc']),'gold':('gold',SYMBOLS['gold']),'all':('all',None)}.get(a,('unknown',None))
        if tl.startswith('/check'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            if key=="unknown": send_tele(f"❓ ไม่มีเหรียญ {parts[1]} แล้ว มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            results={}
            for k in ['btc','gold']:
                if key!='all' and k!=key: continue
                results[k]=execute_symbol(SYMBOLS[k])
            trades=load_trades(); auto=get_auto_state(); bal=get_mexc_balance()
            out=f"📊 <b>G_POWER V5.2.2 CHECK {key.upper()}</b> {datetime.now().strftime('%d/%m %H:%M')}\n"
            for k,r in results.items():
                if not r.get('ok'): out+=f"\n{k.upper()} ❌ {r.get('error')}\n"
                else:
                    cfg=STRATS[k].config
                    out+=f"\n<b>{k.upper()} {r['symbol']}</b> {'🟢 ON' if auto.get(k) else '🔴 OFF'} {r['signal']}\n${r['price']:,.2f} CDC {'🟢' if r['cdc_up'] else '🔴'} Stop ${r['cdc_stop']:,.2f}\nEMA{cfg['ema_fast']}/{cfg['ema_slow']} +DI {r['plus_di']:.1f} -DI {r['minus_di']:.1f} ADX {r['adx']:.1f} RSI {r['rsi']:.0f}\nRetest {'✅' if r['retest'] else '❌'} Vol {'✅' if r['vol_ok'] else '❌'} Sideway {'❌' if not r.get('sideway') else '✅'} Trend Long {r.get('long')} Mom {r.get('mom_long') or r.get('mom_short')} Rev {r.get('rev_long') or r.get('rev_short')} CanOpen {'✅' if r['can_open'] else '❌'} Open {r['open_count']} SL {r['sl_pct']:.1f}% TP {r['tp_pct']:.0f}%\n"
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
            out+=f"\n✅ V5.2.2 VOL 0.25 + PULLBACK + BTC+GOLD FIX\n💡 1.Retest 2.Trailing 3.TP Trend"
            send_tele(out, chat_id)
            return {"ok":True}
        elif tl.startswith('/total') or tl.startswith('/portfolio') or tl.startswith('/port'):
            trades=load_trades(); bal=get_mexc_balance()
            results={}
            for k in ['btc','gold']:
                try: results[k]=execute_symbol(SYMBOLS[k])
                except: results[k]={'ok':False}
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            closeds=[t for t in trades if str(t.get('status')).upper()=='CLOSED']
            total_closed=sum([float(t.get('pnl_usd',0)) for t in closeds])
            out=f"PORTFOLIO {datetime.now().strftime('%d/%m %H:%M')} MEXC {bal.get('total',0) if bal.get('ok') else 0} USDT\n"
            if opens:
                total_upnl=0
                for ot in opens:
                    entry=float(ot['entry']); ps=float(ot.get('position_size',0)); key=ot.get('symbol_key','btc'); curr_p=results.get(key,{}).get('price',entry); sig=ot['signal']
                    upnl=(curr_p-entry)/entry*ps if sig=='LONG' else (entry-curr_p)/entry*ps
                    total_upnl+=upnl
                    out+=f"{sig} {ot['symbol']} ${entry:,.2f} -> ${curr_p:,.2f} PnL ${upnl:+.2f}\n"
                out+=f"UnPnL {total_upnl:+.2f} Paper ${40+total_closed+total_upnl:.2f}\n"
            else: out+=f"ไม่มีไม้ถืออยู่ Paper ${40+total_closed:.2f}\n"
            # ส่งรูปอินโฟกราฟฟิกด้วย
            try:
                btc_p=sum([float(t.get('pnl_usd',0)) if t.get('symbol_key')=='btc' else 0 for t in closeds])
                gold_p=sum([float(t.get('pnl_usd',0)) if t.get('symbol_key')=='gold' else 0 for t in closeds])
                # รวม UnPnL เข้าไปด้วย
                for ot in opens:
                    entry=float(ot['entry']); ps=float(ot.get('position_size',0)); key2=ot.get('symbol_key','btc'); curr_p=results.get(key2,{}).get('price',entry); sig2=ot['signal']
                    up2=(curr_p-entry)/entry*ps if sig2=='LONG' else (entry-curr_p)/entry*ps
                    if key2=='btc': btc_p+=up2
                    else: gold_p+=up2
                wins=len([t for t in closeds if float(t.get('pnl_usd',0))>0])
                tot_c=len(closeds) if closeds else len(opens)
                wr=(wins/len(closeds)*100) if closeds else (100 if total_upnl>0 else 0)
                opens_info=[]
                for ot in opens:
                    entry=float(ot['entry']); ps=float(ot.get('position_size',0)); key2=ot.get('symbol_key','btc'); curr_p=results.get(key2,{}).get('price',entry); sig2=ot['signal']
                    up2=(curr_p-entry)/entry*ps if sig2=='LONG' else (entry-curr_p)/entry*ps
                    opens_info.append({"key":key2.upper(),"sig":sig2,"txt":f"${entry:,.0f} -> ${curr_p:,.0f}","pnl":up2})
                paper_val=40+total_closed+(total_upnl if opens else 0)
                img_bytes=make_portfolio_image(paper_val, total_upnl if opens else 0, total_closed, wr, wins, len(closeds) if closeds else len(opens), btc_p, gold_p, opens_info)
                if img_bytes: send_tele_photo(img_bytes, out, chat_id)
                else: send_tele(out, chat_id)
            except Exception as e: print(f"portfolio img err {e}"); send_tele(out, chat_id)
            return {'ok':True}
        elif tl.startswith('/info') or tl.startswith('/infographic'):
            trades=load_trades(); bal=get_mexc_balance(); results={}
            for k in ['btc','gold']:
                try: results[k]=execute_symbol(SYMBOLS[k])
                except: results[k]={'ok':False}
            opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            closeds=[t for t in trades if str(t.get('status')).upper()=='CLOSED']
            total_closed=sum([float(t.get('pnl_usd',0)) for t in closeds])
            total_upnl=0; opens_info=[]
            btc_p=sum([float(t.get('pnl_usd',0)) if t.get('symbol_key')=='btc' else 0 for t in closeds]); gold_p=sum([float(t.get('pnl_usd',0)) if t.get('symbol_key')=='gold' else 0 for t in closeds])
            for ot in opens:
                entry=float(ot['entry']); ps=float(ot.get('position_size',0)); key2=ot.get('symbol_key','btc'); curr_p=results.get(key2,{}).get('price',entry); sig2=ot['signal']; up2=(curr_p-entry)/entry*ps if sig2=='LONG' else (entry-curr_p)/entry*ps; total_upnl+=up2
                opens_info.append({'key':key2.upper(),'sig':sig2,'txt':f"${entry:,.0f} -> ${curr_p:,.0f}",'pnl':up2})
                btc_p+=up2 if key2=='btc' else 0; gold_p+=up2 if key2=='gold' else 0
            wins=len([t for t in closeds if float(t.get('pnl_usd',0))>0]); wr=(wins/len(closeds)*100) if closeds else (100 if total_upnl>0 else 0)
            paper_val=40+total_closed+total_upnl
            img_bytes=None
            try: img_bytes=make_portfolio_image(paper_val,total_upnl,total_closed,wr,wins,len(closeds) if closeds else len(opens),btc_p,gold_p,opens_info)
            except Exception as e: send_tele(f'IMG ERR: {e}',chat_id); return {'ok':True}
            cap=f"G_POWER PORTFOLIO {datetime.now().strftime('%d/%m %H:%M')} Paper ${paper_val:.2f} UnPnL {total_upnl:+.2f}"
            
            
            send_tele_photo(img_bytes,cap,chat_id) if img_bytes else send_tele('สร้างรูปไม่ได้ - เช็ค Render Logs: ถ้าขึ้น PIL NOT INSTALLED = ต้องเพิ่ม Pillow ใน requirements.txt แล้ว Clear build cache & Deploy',chat_id)
            return {'ok':True}
        elif tl.startswith('/close'):
            trades=load_trades(); opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            if not opens: send_tele('ไม่มีไม้ถืออยู่', chat_id); return {'ok':True}
            results={}
            for k in ['btc','gold']:
                try: results[k]=execute_symbol(SYMBOLS[k])
                except: results[k]={'ok':False}
            total=0; out=f"CLOSE ALL {len(opens)} ไม้\n"
            for ot in opens:
                key=ot.get('symbol_key','btc'); curr_p=results.get(key,{}).get('price', ot.get('entry')); entry=float(ot['entry']); sig=ot['signal']; ps=float(ot.get('position_size',0))
                pnl=(curr_p-entry)/entry*ps if sig=='LONG' else (entry-curr_p)/entry*ps
                total+=pnl; ot['status']='CLOSED'; ot['result']='WIN' if pnl>0 else 'LOSS'; ot['exit']=curr_p; ot['exit_time']=datetime.now().isoformat(); ot['exit_reason']='MANUAL CLOSE'; ot['pnl_usd']=pnl
                out+=f"{sig} {ot['symbol']} PnL ${pnl:+.2f}\n"
            save_trades(trades); set_auto_state('all', False)
            out+=f"รวม PnL ${total:+.2f} Auto OFF แล้ว"
            send_tele(out, chat_id); return {'ok':True}
        elif tl.startswith('/reset'):
            trades=load_trades(); opens=[t for t in trades if str(t.get('status')).upper() in ['OPEN','PAPER_OPEN','PAPER']]
            if opens: send_tele(f"ยังถือ {len(opens)} ไม้อยู่! พิมพ์ /close all ก่อน", chat_id); return {'ok':True}
            try:
                for f in ['/data/g_power_trades.json','/data/auto_state.json']:
                    try:
                        if os.path.exists(f): os.remove(f)
                    except: pass
                save_trades([]); set_auto_state('all', False)
            except Exception as e: send_tele(f"RESET Error: {e}", chat_id); return {'ok':True}
            send_tele('ล้างไพ่เรียบร้อย Paper $40.00 Auto OFF - พิมพ์ /on all เพื่อเริ่มใหม่', chat_id); return {'ok':True}
        elif tl.startswith('/on'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            if key=="unknown": send_tele(f"❓ ไม่มีเหรียญ {parts[1]} แล้ว มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            set_auto_state(key, True)
            send_tele(f"🟢 Auto ON {key.upper()} {datetime.now().strftime('%d/%m %H:%M')} V5.2.2 PULLBACK", chat_id)
            return {"ok":True}
        elif tl.startswith('/off'):
            parts=tl.split(); key='all' if len(parts)<2 else parse_sym(parts[1])[0]
            if key=="unknown": send_tele(f"❓ ไม่มีเหรียญ {parts[1]} แล้ว มีแค่ BTC / GOLD", chat_id); return {"ok":True}
            set_auto_state(key, False)
            send_tele(f"🔴 Auto OFF {key.upper()}", chat_id)
            return {"ok":True}
        else:
            send_tele(f"❓ {text}\n/check [btc|gold|all]\n/on [btc|gold|all]\n/off [btc|gold|all]\n/portfolio = รูปสรุปพอร์ต\n/info = รูปอย่างเดียว\n/live [btc|gold]", chat_id)
            return {"ok":True}
    except Exception as e:
        print(f"ERR {e}"); return {"ok":True}
@app.on_event("startup")
async def auto_set_webhook():
    import requests, os
    token = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    if not token: return
    base = os.environ.get("RENDER_EXTERNAL_URL","").strip() or "https://mexc-btc-bot-1.onrender.com"
    url = base.rstrip("/") + "/telegram/webhook"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook?url={url}", timeout=10)
        print(f"STARTUP setWebhook {url} : {r.text[:200]}")
    except Exception as e: print(f"STARTUP fail {e}")
@app.get("/set_webhook")
def set_webhook():
    import requests, os
    token = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    if not token: return {"ok":False,"error":"No BOT_TOKEN"}
    url = "https://mexc-btc-bot-1.onrender.com/telegram/webhook"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook?url={url}", timeout=10)
        return {"ok":r.status_code==200,"telegram":r.json(),"set_to":url}
    except Exception as e: return {"ok":False,"error":str(e)[:200]}
@app.get("/webhook_info")
def webhook_info():
    import requests, os
    token = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("BOT_TOKEN","").strip()
    if not token: return {"ok":False,"error":"No BOT_TOKEN"}
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10)
        return r.json()
    except Exception as e: return {"ok":False,"error":str(e)[:200]}
@app.get("/test_send")
def test_send():
    r = send_tele("TEST จาก Render - ถ้าเห็นข้อความนี้ = BOT_TOKEN + CHAT_ID ถูกแล้ว")
    return {"sent":r}
@app.api_route("/ping", methods=["GET","HEAD"])
def ping():
    return {"status":"ok V5.6.1.1 NO HEDGE + CLOSE CIRCLE","auto":get_auto_state(),"dir":str(DATA_DIR),"trades":len(load_trades())}
@app.get("/", response_class=HTMLResponse)
def home():
    auto=get_auto_state()
    return f"<html><body style='background:#0a0e1a;color:#fff;font-family:Arial;padding:20px'><h1>G_POWER V5.2.3 BTC+GOLD 2COINS</h1><p>BTC {'🟢' if auto.get('btc') else '🔴'} GOLD {'🟢' if auto.get('gold') else '🔴'}</p><p>✅ VOL 0.25 | PULLBACK ENTRY | BTC+GOLD FIX</p><a href='/ping'>Ping</a></body></html>"
