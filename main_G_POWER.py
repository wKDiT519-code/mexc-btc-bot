
"""
G_POWER V2.9 FINAL CLEAN - AUTO 100% REAL ORDER
รวมทุกแก้ที่เคยบอก - ไม่มีไฟล์ซ้ำ - ไฟล์เดียวจบ

ระบบ:
- สมอง: strategy_G_POWER V2.7 ADX+DI FULL
- คำนวณ Pos: ทุน $40 2% 3x = Pos $70 Margin $23
- กดออเดอร์จริง MEXC Futures 100% Auto
- Auto Loop ทุก 15m ในตัวบอท ไม่ต้องตั้ง Cron
- เวลา BKK UTC+7
- /check /on /off /live /auto_run

Deploy Render: Disk /data 1GB + ENV REAL_TRADE=true
"""

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from strategy_G_POWER import Strategy_G_Power
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os, ccxt, pandas as pd, json, requests, time, asyncio

# === TIME BKK ===
BKK_TZ = timezone(timedelta(hours=7))
def now_bkk(): return datetime.now(BKK_TZ)
def bkk_str(fmt='%d/%m %H:%M'): return now_bkk().strftime(fmt)

app = FastAPI(title="G_POWER V2.9 FINAL AUTO 100%")

# === CONFIG ===
strat = Strategy_G_Power()
CAPITAL = 40
RISK_PCT = 0.02
LEVERAGE = 3
strat.config["max_positions"] = 1
strat.config["risk_per_trade"] = RISK_PCT

DATA_DIR = Path('/data') if Path('/data').exists() else Path('/tmp')
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRADES_FILE = DATA_DIR / "g_power_trades.json"
LAST_SIGNAL_FILE = DATA_DIR / "last_signal.json"
AUTO_STATE_FILE = DATA_DIR / "auto_state.json"
LAST_TRADE_FILE = DATA_DIR / "last_trade.json"

print(f"[G_POWER V2.9 FINAL] DATA_DIR={DATA_DIR} BKK={now_bkk()}")

# === PERSISTENT ===
def load_trades():
    if not TRADES_FILE.exists():
        with open(TRADES_FILE, 'w') as f: json.dump([], f)
        return []
    try:
        with open(TRADES_FILE, 'r') as f:
            data = json.load(f)
            clean = [t for t in data if not str(t.get('note','')).lower().startswith('sample')]
            if len(clean) != len(data): save_trades(clean)
            return clean
    except: return []

def save_trades(trades):
    try:
        with open(TRADES_FILE, 'w') as f: json.dump(trades, f, default=str, indent=2)
    except Exception as e: print(f"save_trades {e}")

def get_last_signal():
    if LAST_SIGNAL_FILE.exists():
        try:
            with open(LAST_SIGNAL_FILE, 'r') as f: return json.load(f)
        except: pass
    return {"signal":"WAIT","time":"","symbol":"BTC/USDT"}

def save_last_signal(signal, price, symbol="BTC/USDT"):
    try:
        with open(LAST_SIGNAL_FILE, 'w') as f:
            json.dump({"signal":signal,"price":price,"symbol":symbol,"time":now_bkk().isoformat()}, f)
    except: pass

def get_last_trade():
    if LAST_TRADE_FILE.exists():
        try:
            with open(LAST_TRADE_FILE, 'r') as f: return json.load(f)
        except: pass
    return {}

def save_last_trade(data):
    try:
        with open(LAST_TRADE_FILE, 'w') as f: json.dump(data, f, default=str, indent=2)
    except: pass

def get_auto_state():
    if AUTO_STATE_FILE.exists():
        try:
            with open(AUTO_STATE_FILE, 'r') as f: return json.load(f)
        except: pass
    return {"enabled":False,"since":""}

def set_auto_state(enabled):
    data={"enabled":enabled,"since":now_bkk().isoformat()}
    try:
        with open(AUTO_STATE_FILE, 'w') as f: json.dump(data, f)
    except: pass
    return data

def calc_position():
    risk=CAPITAL*RISK_PCT
    pos_size=risk*LEVERAGE/0.034
    margin=pos_size/LEVERAGE
    return {"risk_usd":risk,"position_size":pos_size,"margin_needed":margin,"capital":CAPITAL,"leverage":LEVERAGE}

def calc_performance():
    trades=load_trades()
    if not trades: return {"total_pnl_usd":0,"win":0,"loss":0,"win_rate":0,"closed_trades":0,"trades":[]}
    closed=[t for t in trades if t.get('status')=='CLOSED']
    win=len([t for t in closed if t.get('result')=='WIN'])
    loss=len([t for t in closed if t.get('result')=='LOSS'])
    pnl=sum([float(t.get('pnl_usd',0)) for t in closed])
    wr=(win/len(closed)*100) if closed else 0
    return {"total_pnl_usd":pnl,"win":win,"loss":loss,"win_rate":round(wr,1),"closed_trades":len(closed),"trades":trades}

# === TELEGRAM ===
def send_telegram(message, chat_id_override=None):
    token=os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    chat_id=chat_id_override or os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID") or os.environ.get("TG_CHAT_ID")
    if not token or not chat_id: return {"ok":False,"error":"No BOT_TOKEN/CHAT_ID"}
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id":chat_id,"text":message,"parse_mode":"HTML"}, timeout=10)
        return {"ok":r.status_code==200}
    except Exception as e: return {"ok":False,"error":str(e)}

# === MEXC ===
def get_exchange():
    key=os.environ.get("MEXC_API_KEY"); sec=os.environ.get("MEXC_API_SECRET")
    if not key or not sec: return None,"No MEXC_API_KEY/SECRET"
    try: return ccxt.mexc({'apiKey':key,'secret':sec,'options':{'defaultType':'swap'},'enableRateLimit':True}),None
    except Exception as e: return None,str(e)

def get_mexc_data(symbol='BTC/USDT'):
    try:
        ex=ccxt.mexc({"options":{"defaultType":"swap"}})
        ohlcv=ex.fetch_ohlcv(symbol,'15m',limit=250)
        df=pd.DataFrame(ohlcv,columns=['timestamp','open','high','low','close','volume'])
        df['datetime']=pd.to_datetime(df['timestamp'],unit='ms')
        return df
    except Exception as e:
        return None,str(e)

def get_mexc_futures_balance_direct():
    """เรียกตรง contract.mexc.com เพื่อเลี่ยงบั๊ก ccxt capital/config/getAll - จะได้ 38.27 จริง"""
    key=os.environ.get("MEXC_API_KEY"); sec=os.environ.get("MEXC_API_SECRET")
    if not key or not sec: return None
    try:
        import hmac, hashlib, time as _time
        ts = str(int(_time.time()*1000))
        msg = (key + ts).encode()
        sign = hmac.new(sec.encode(), msg, hashlib.sha256).hexdigest()
        headers = {"ApiKey": key, "Request-Time": ts, "Signature": sign, "Content-Type": "application/json"}
        url = "https://contract.mexc.com/api/v1/private/account/assets"
        r = requests.get(url, headers=headers, timeout=10)
        j = r.json()
        if isinstance(j, dict):
            data = j.get("data", [])
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("currency")=="USDT":
                        avail = float(item.get("availableBalance",0) or item.get("available",0) or 0)
                        eq = float(item.get("equity",0) or avail)
                        return {"free": avail, "total": eq}
            if isinstance(data, dict) and data.get("currency")=="USDT":
                return {"free": float(data.get("availableBalance",0) or 0), "total": float(data.get("equity",0) or 0)}
    except Exception as e:
        print(f"direct balance err {e}")
    return None

def get_balance():
    key=os.environ.get("MEXC_API_KEY"); sec=os.environ.get("MEXC_API_SECRET")
    if not key or not sec: return {"ok":False,"error":"No API key - ใส่ใน Render ENV"}
    # 1. ลองเรียกตรง Futures ก่อน จะได้ 38.27
    try:
        direct = get_mexc_futures_balance_direct()
        pos=[]
        try:
            ex=ccxt.mexc({'apiKey':key,'secret':sec,'options':{'defaultType':'swap'},'enableRateLimit':True})
            try: pos=ex.fetch_positions(['BTC/USDT:USDT'])
            except:
                try: pos=ex.fetch_positions()
                except: pos=[]
        except: ex=None; pos=[]
        if direct:
            return {"ok":True,"usdt_free":direct["free"],"usdt_total":direct["total"],"positions":pos}
    except: pass
    try:
        ex=ccxt.mexc({'apiKey':key,'secret':sec,'options':{'defaultType':'swap'},'enableRateLimit':True})
        # positions แยก try ไม่ให้ balance พังแล้ว positions หาย
        pos=[]
        try:
            pos=ex.fetch_positions(['BTC/USDT:USDT'])
        except:
            try: pos=ex.fetch_positions()
            except: pos=[]
        free=0; total=0
        bal=None
        # ลอง 3 แบบ กัน MEXC error capital/config/getAll
        for attempt in [{'type':'swap'}, {}, {'type':'future'}]:
            try:
                if attempt:
                    bal=ex.fetch_balance(attempt)
                else:
                    bal=ex.fetch_balance()
                break
            except Exception as e:
                # ถ้า error เป็น capital/config/getAll ให้ข้าม ไม่ต้องโชว์ error ยาว
                err=str(e)
                if 'capital/config/getAll' in err or 'capital/config/getall' in err.lower():
                    continue
                if attempt == {'type':'future'}:
                    bal=None
        if bal:
            try:
                if 'USDT' in bal and isinstance(bal['USDT'],dict):
                    free=bal['USDT'].get('free',0) or 0
                    total=bal['USDT'].get('total',0) or free
                elif 'free' in bal and isinstance(bal['free'],dict):
                    free=bal['free'].get('USDT',0) or 0
                    total=bal.get('total',{}).get('USDT',0) or free
                else:
                    # ลองอ่านจาก info
                    info=bal.get('info',{}) if isinstance(bal,dict) else {}
                    if isinstance(info,dict) and 'data' in info:
                        data=info['data']
                        if isinstance(data,list):
                            for item in data:
                                if isinstance(item,dict) and item.get('currency')=='USDT':
                                    free=float(item.get('availableBalance',0) or 0)
                                    total=float(item.get('equity',0) or free)
            except: pass
        # ถ้าได้ positions แต่ไม่ได้ balance ก็ถือว่า ok แบบเตือน
        if free==0 and total==0 and pos:
            return {"ok":True,"usdt_free":0,"usdt_total":0,"positions":pos,"warn":"Balance API ขัดข้อง แต่เห็น Position"}
        return {"ok":True,"usdt_free":float(free),"usdt_total":float(total),"positions":pos}
    except Exception as e:
        err=str(e)
        if 'capital/config/getAll' in err:
            return {"ok":True,"usdt_free":0,"usdt_total":0,"positions":[],"warn":"MEXC capital/config/getAll error - เช็ค API Permission Futures"}
        return {"ok":False,"error":err[:150]}

# === REAL ORDER 100% ===
def close_positions(ex, symbol='BTC/USDT:USDT'):
    try:
        positions=ex.fetch_positions([symbol])
        closed=[]
        for p in positions:
            amt=float(p.get('contracts',0) or 0)
            if amt==0:
                try: amt=float(p.get('info',{}).get('positionAmt',0) or 0)
                except: amt=0
            if abs(amt)>0.000001:
                side='sell' if amt>0 or p.get('side')=='long' else 'buy'
                try:
                    o=ex.create_order(symbol,'market',side,abs(amt),None,{'reduceOnly':True})
                    closed.append(side)
                except:
                    try: o=ex.create_order(symbol,'market',side,abs(amt)); closed.append(side)
                    except Exception as e: return {"ok":False,"error":str(e)}
        return {"ok":True,"closed":closed}
    except Exception as e: return {"ok":False,"error":str(e)}

def place_order(symbol, signal, price):
    real=os.environ.get("REAL_TRADE","false").lower() in ["true","1","yes","on"]
    if not real:
        return {"ok":True,"paper":True,"message":"Paper mode - ตั้ง REAL_TRADE=true เพื่อเทรดจริง"}
    ex,err=get_exchange()
    if not ex: return {"ok":False,"error":err}
    try:
        try: ex.set_leverage(LEVERAGE,symbol)
        except: pass
        pos=calc_position()
        amt=round(pos['position_size']/price,6)
        if amt<0.0001: amt=0.0001
        close_positions(ex,symbol)
        side='buy' if signal=='LONG' else 'sell'
        order=ex.create_order(symbol,'market',side,amt)
        sl=price*0.966 if signal=='LONG' else price*1.034
        tp=price*1.18 if signal=='LONG' else price*0.82
        try: ex.create_order(symbol,'market','sell' if signal=='LONG' else 'buy',amt,None,{'stopPrice':sl,'reduceOnly':True})
        except: pass
        try: ex.create_order(symbol,'limit','sell' if signal=='LONG' else 'buy',amt,tp,None,{'reduceOnly':True})
        except: pass
        trade={"id":f"G29-{now_bkk().strftime('%y%m%d-%H%M')}-{signal}","symbol":symbol,"signal":signal,"entry":price,"amount":amt,"sl":sl,"tp":tp,"status":"OPEN","time":now_bkk().isoformat(),"order_id":str(order.get('id','')),"real":True}
        trades=load_trades(); trades.append(trade); save_trades(trades); save_last_trade(trade); save_last_signal(signal,price,symbol)
        return {"ok":True,"real":True,"trade":trade,"amount":amt,"order":order}
    except Exception as e: return {"ok":False,"error":str(e)}

def execute_auto(symbol='BTC/USDT'):
    auto=get_auto_state()
    if not auto.get('enabled'): return {"ok":False,"reason":"Auto OFF"}
    data=get_mexc_data(symbol)
    if isinstance(data,tuple): return {"ok":False,"error":data[1]}
    df=strat.add_indicators(data)
    curr=df.iloc[-1]; prev=df.iloc[-2]
    rev=strat.check_reversal(prev,curr); trend=strat.check_trend(curr); mom=strat.check_momentum(curr)
    price=float(curr['close'])
    sig="WAIT"
    if rev['long'] and trend['long'] and mom['long'] and not trend['sideway']: sig="LONG"
    elif rev['short'] and trend['short'] and mom['short'] and not trend['sideway']: sig="SHORT"
    if sig=="WAIT": return {"ok":True,"signal":"WAIT","price":price,"action":"no trade"}
    last=get_last_signal()
    if last.get('signal')==sig:
        try:
            lt=datetime.fromisoformat(last.get('time','').replace('Z','+00:00'))
            if (now_bkk()-lt).total_seconds()<900: return {"ok":True,"signal":sig,"price":price,"action":"duplicate skip 15m"}
        except: pass
    fut='BTC/USDT:USDT'
    res=place_order(fut,sig,price)
    if res.get('ok'):
        if res.get('paper'):
            send_telegram(f"📄 PAPER {sig} ${price:,.0f} | Pos ${calc_position()['position_size']:.2f} DI +{curr.get('plus_di',0):.1f} -{curr.get('minus_di',0):.1f} ADX {curr.get('adx',0):.1f} | ตั้ง REAL_TRADE=true เพื่อเทรดจริง {bkk_str()}")
        else:
            send_telegram(f"🚀 AUTO {sig} กดจริง ${price:,.0f} Amt {res.get('amount')} SL ${res['trade']['sl']:,.0f} TP ${res['trade']['tp']:,.0f} DI +{curr.get('plus_di',0):.1f} -{curr.get('minus_di',0):.1f} ADX {curr.get('adx',0):.1f} {bkk_str()} BKK")
    else:
        send_telegram(f"❌ AUTO {sig} FAIL ${price:,.0f} {res.get('error','')[:150]} {bkk_str()}")
    return {"ok":res.get('ok'),"signal":sig,"price":price,"result":res}

# === TELEGRAM WEBHOOK ===
@app.post("/telegram/webhook")
async def webhook(request: Request):
    try:
        data=await request.json()
        msg=data.get('message',{}) or data.get('edited_message',{}) or {}
        chat=msg.get('chat',{}); chat_id=str(chat.get('id','')); text=(msg.get('text','') or '').strip()
        if not chat_id or not text: return {"ok":True}
        tl=text.lower()
        if tl.startswith('/check') or tl.startswith('/status') or tl.startswith('/balance') or text=='check':
            perf=calc_performance(); pos=calc_position(); auto=get_auto_state(); bal=get_balance(); last=get_last_trade()
            price=0; cdc=""; di=""
            try:
                df=get_mexc_data('BTC/USDT')
                if not isinstance(df,tuple):
                    df=strat.add_indicators(df); curr=df.iloc[-1]
                    price=float(curr['close'])
                    cdc=f"\nCDC: {'🟢 UPTREND' if curr.get('cdc_up') else '🔴 DOWNTREND'} Stop ${float(curr.get('cdc_stop',0)):,.0f} ({float(curr.get('cdc_dist_pct',0)):+.2f}%)"
                    di=f"\nDI: +DI {float(curr.get('plus_di',0)):.1f} -DI {float(curr.get('minus_di',0)):.1f} ADX {float(curr.get('adx',0)):.1f}"
            except: pass
            bal_str=f"\n🏦 MEXC: Free ${bal.get('usdt_free',0):.2f} Total ${bal.get('usdt_total',0):.2f}" if bal.get('ok') else f"\n🏦 {bal.get('error','No API')[:80]}"
            last_str=f"\n📦 Last: {last.get('signal')} ${last.get('entry')}" if last else ""
            real=os.environ.get("REAL_TRADE","false")
            send_telegram(f"📊 <b>G_POWER V2.9 FINAL CHECK</b>\n💰 ทุน ${CAPITAL} | BTC ${price:,.0f}{cdc}{di}{bal_str}{last_str}\n📜 ปิด {perf['closed_trades']} | Win {perf['win_rate']}% | PnL ${perf['total_pnl_usd']:+.2f}\n💵 Risk ${pos['risk_usd']:.2f} Pos ${pos['position_size']:.2f} Margin ${pos['margin_needed']:.2f}\n🤖 Auto: {'🟢 ON REAL 100%' if auto['enabled'] else '🔴 OFF'} REAL={real}\n⏰ {bkk_str()} BKK", chat_id)
            return {"ok":True}
        elif tl.startswith('/on') or tl.startswith('/open') or text=='on':
            set_auto_state(True)
            send_telegram(f"🟢 <b>Auto ON 100% V2.9 FINAL</b>\nกดออเดอร์จริงอัตโนมัติทุก 15m\nทุน ${CAPITAL} {LEVERAGE}x SL 3.4% TP 18%\nREAL_TRADE={os.environ.get('REAL_TRADE','false')}\n/off เพื่อปิด {bkk_str()} BKK", chat_id)
            return {"ok":True}
        elif tl.startswith('/off') or tl.startswith('/close') or text=='off':
            set_auto_state(False)
            send_telegram(f"🔴 <b>Auto OFF</b> {bkk_str()} BKK", chat_id)
            return {"ok":True}
        elif tl.startswith('/auto_run') or tl.startswith('/run'):
            send_telegram("⏳ เช็คสัญญาณและกดออเดอร์...", chat_id)
            res=execute_auto('BTC/USDT')
            send_telegram(f"🤖 {res}"[:3500], chat_id)
            return {"ok":True,"result":res}
        elif tl.startswith('/live'):
            df=get_mexc_data('BTC/USDT')
            if isinstance(df,tuple): send_telegram(f"❌ {df[1][:100]}", chat_id)
            else:
                df=strat.add_indicators(df); curr=df.iloc[-1]; prev=df.iloc[-2]
                rev=strat.check_reversal(prev,curr); trend=strat.check_trend(curr); mom=strat.check_momentum(curr)
                sig="WAIT"
                if rev['long'] and trend['long'] and mom['long'] and not trend['sideway']: sig="LONG"
                elif rev['short'] and trend['short'] and mom['short'] and not trend['sideway']: sig="SHORT"
                send_telegram(f"📡 {sig} ${float(curr['close']):,.0f} +DI {float(curr.get('plus_di',0)):.1f} -DI {float(curr.get('minus_di',0)):.1f} ADX {float(curr.get('adx',0)):.1f}", chat_id)
            return {"ok":True}
        else:
            send_telegram(f"❓ {text}\n/check ดูพอร์ต\n/on เปิด Auto 100%\n/off ปิด\n/live สัญญาณ\n/auto_run กดทันที", chat_id)
            return {"ok":True}
    except Exception as e: print(f"webhook {e}"); return {"ok":False}

# === AUTO LOOP ไม่ต้องตั้ง Cron ===
async def auto_loop():
    await asyncio.sleep(10)
    print(f"[AUTO LOOP] Start 15m BKK {now_bkk()}")
    while True:
        try:
            if get_auto_state().get('enabled'):
                print(f"[LOOP] {bkk_str()} ON checking...")
                execute_auto('BTC/USDT')
            else: print(f"[LOOP] {bkk_str()} OFF skip")
        except Exception as e: print(f"[LOOP] err {e}")
        await asyncio.sleep(900)

@app.on_event("startup")
async def startup(): asyncio.create_task(auto_loop())

# === ENDPOINTS ===
@app.get("/telegram/setwebhook")
def setwebhook():
    token=os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    if not token: return {"ok":False}
    base=os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("BASE_URL") or "https://mexc-btc-bot.onrender.com"
    url=f"{base}/telegram/webhook"
    try: r=requests.post(f"https://api.telegram.org/bot{token}/setWebhook", json={"url":url}, timeout=10); return {"ok":r.status_code==200,"url":url}
    except Exception as e: return {"ok":False,"error":str(e)}

@app.get("/telegram/info")
def teleinfo():
    token=os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    if not token: return {"ok":False}
    try: r=requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10); return r.json()
    except Exception as e: return {"ok":False}

@app.get("/", response_class=HTMLResponse)
def home():
    perf=calc_performance(); pos=calc_position(); auto=get_auto_state(); bal=get_balance(); last=get_last_trade()
    real=os.environ.get("REAL_TRADE","false")
    return f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{{background:#0a0e1a;color:#fff;font-family:Arial;padding:15px}} .card{{background:#1a2332;padding:12px;border-radius:12px;margin:8px 0;border-left:4px solid #00ff88}} .btn{{background:#00ff88;color:#000;padding:10px 14px;border-radius:8px;font-weight:bold;text-decoration:none;display:inline-block;margin:4px}}</style></head><body><h1>⚡ G_POWER V2.9 FINAL - {'🟢 REAL' if real=='true' else '🟡 PAPER'} AUTO 100%</h1><p>{DATA_DIR} | {now_bkk()} BKK | REAL_TRADE={real}</p><div class='card'><h2>ทุน ${CAPITAL} {LEVERAGE}x AUTO {'🟢 ON' if auto['enabled'] else '🔴 OFF'}</h2><p>Balance: {bal.get('usdt_total',0) if bal.get('ok') else bal.get('error','No API')} | Last {last.get('signal','-')}</p><p>PnL ${perf['total_pnl_usd']:+.2f} Win {perf['win_rate']}% ปิด {perf['closed_trades']}</p><p>Risk ${pos['risk_usd']:.2f} Pos ${pos['position_size']:.2f} Margin ${pos['margin_needed']:.2f}</p></div><a class='btn' href='/live?symbol=BTC/USDT'>📡 BTC</a><a class='btn' href='/auto/run?symbol=BTC/USDT' style='background:#ff4444;color:#fff'>🤖 AUTO RUN</a><a class='btn' href='/dashboard'>📊 Dashboard</a><a class='btn' href='/health'>💚 Health</a></body></html>"

@app.get("/telegram/test")
def teletest():
    token=os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token: return {"ok":False}
    send_telegram(f"⚡ G_POWER V2.9 FINAL ✅ ต่อ Tele แล้ว! {bkk_str()} BKK REAL={os.environ.get('REAL_TRADE','false')}")
    return {"ok":True}

@app.get("/dashboard", response_class=HTMLResponse)
def dash():
    perf=calc_performance(); pos=calc_position(); auto=get_auto_state()
    rows=""
    for t in reversed(perf['trades'][-15:]):
        color="#00ff88" if t.get('result')=='WIN' else "#ff4444" if t.get('result')=='LOSS' else "#ffcc00"
        rows+=f"<tr><td>{t.get('id')}</td><td>{t.get('symbol')}<br>{'REAL' if t.get('real') else 'PAPER'}</td><td><b style='background:{color};color:#000;padding:2px 6px;border-radius:4px'>{t.get('signal')}</b></td><td>${t.get('entry')}</td><td>{t.get('status')}</td></tr>"
    return f"<html><body style='background:#0a0e1a;color:#fff;font-family:Arial;padding:15px'><h1>Dashboard V2.9 Auto {'🟢 ON' if auto['enabled'] else '🔴 OFF'}</h1><p>PnL ${perf['total_pnl_usd']:+.2f} Win {perf['win_rate']}%</p><table border=1 style='width:100%;font-size:11px'>{rows or '<tr><td>ยังไม่มีเทรด</td></tr>'}</table><a href='/' style='color:#00ff88'>Home</a></body></html>"

@app.get("/live")
def live(symbol: str = Query("BTC/USDT"), send_tele: bool = Query(False)):
    df=get_mexc_data(symbol)
    if isinstance(df,tuple): return {"error":df[1]}
    df=strat.add_indicators(df); curr=df.iloc[-1]; prev=df.iloc[-2]
    rev=strat.check_reversal(prev,curr); trend=strat.check_trend(curr); mom=strat.check_momentum(curr)
    price=float(curr['close'])
    sig="WAIT"
    if rev['long'] and trend['long'] and mom['long'] and not trend['sideway']: sig="LONG"
    elif rev['short'] and trend['short'] and mom['short'] and not trend['sideway']: sig="SHORT"
    return {"symbol":symbol,"price":price,"signal":sig,"plus_di":float(curr.get('plus_di',0)),"minus_di":float(curr.get('minus_di',0)),"adx":float(curr.get('adx',0)),"auto":get_auto_state()['enabled'],"bkk":now_bkk().isoformat()}

@app.get("/auto/run")
def autorun(symbol: str = Query("BTC/USDT")): return execute_auto(symbol)

@app.api_route("/ping", methods=["GET","HEAD"])
def ping():
    # UptimeRobot ใช้ตัวนี้เบาสุด ไม่เรียก MEXC จะไม่ 405/500
    return {"status":"ok","bkk":now_bkk().isoformat(),"auto":get_auto_state()['enabled'],"real":os.environ.get("REAL_TRADE","false")}

@app.api_route("/health", methods=["GET","HEAD"])
def health():
    try:
        bal=get_balance()
        mexc_ok=bal.get('ok')
    except: mexc_ok=False
    return {"status":"OK V2.9 FINAL CLEAN","capital":CAPITAL,"data_dir":str(DATA_DIR),"trades":len(load_trades()),"auto":get_auto_state()['enabled'],"mexc_ok":mexc_ok,"real":os.environ.get("REAL_TRADE","false"),"bkk":now_bkk().isoformat()}

if __name__=="__main__":
    import uvicorn; uvicorn.run(app,host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
