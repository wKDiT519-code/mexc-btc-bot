"""
G_POWER V2.7 ADX+DI FULL PERSISTENT - Truth Version
แก้ปัญหาลืม + /tmp หาย + เทรดปลอม + เพิ่ม GOLD
เก็บในโฟลเดอร์ MEXC_BTC_bot เป็น Single Source of Truth

การเปลี่ยนแปลงหลัก (ตาม Google Doc ใน MEXC_BTC_bot):
1. DATA_DIR = Path('/data') if exists else /tmp - ใช้ Render Disk 1GB ถาวร
2. load_trades() ไม่สร้างเทรดปลอม +$11.09 อีก - ว่างจริง []
3. get_mexc_futures_data(symbol) รองรับ BTC/USDT และ GOLD/USDT / XAU/USDT
4. พร้อมเชื่อม Google Sheet G_POWER_TRADES_DB เป็นฐานข้อมูลถาวร
5. Truth 100% - ไม่มีบิดเบือน

Deploy: Render + Disk /data 1GB + ENV DATA_DIR=/data
"""

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from strategy_G_POWER import Strategy_G_Power
from datetime import datetime, timedelta
from pathlib import Path
import os
import ccxt
import pandas as pd
import json
import requests

app = FastAPI(title="G_POWER V2.7 ADX+DI FULL PERSISTENT $40 + GOLD + TRUTH")

strat = Strategy_G_Power()

CAPITAL = 40
RISK_PCT = 0.02
LEVERAGE = 3
strat.config["max_positions"] = 1
strat.config["risk_per_trade"] = RISK_PCT

# === FIX PERSISTENT: ใช้ /data ถ้ามี (Render Disk) ไม่งั้น /tmp ===
DATA_DIR = Path('/data') if Path('/data').exists() else Path('/tmp')
DATA_DIR.mkdir(parents=True, exist_ok=True)

TRADES_FILE = DATA_DIR / "g_power_trades.json"
LAST_SIGNAL_FILE = DATA_DIR / "last_signal.json"
AUTO_STATE_FILE = DATA_DIR / "auto_state.json"

print(f"[G_POWER V2.7] DATA_DIR = {DATA_DIR}")

def load_trades():
    """Truth Version - ไม่สร้างเทรดปลอม +11.09 อีก"""
    if not TRADES_FILE.exists():
        TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(TRADES_FILE, 'w') as f:
                json.dump([], f)  # ว่างจริง ไม่ปลอม
        except Exception as e:
            print(f"load_trades create empty fail: {e}")
        return []
    try:
        with open(TRADES_FILE, 'r') as f:
            data = json.load(f)
            # กรองเทรดปลอมเก่าที่มี note sample ออก
            clean = [t for t in data if not str(t.get('note','')).lower().startswith('sample')]
            if len(clean) != len(data):
                print(f"[TRUTH] ลบเทรดปลอม {len(data)-len(clean)} รายการ")
                save_trades(clean)
                return clean
            return data
    except Exception as e:
        print(f"load_trades read fail: {e}")
        return []

def save_trades(trades):
    try:
        TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TRADES_FILE, 'w') as f:
            json.dump(trades, f, default=str, indent=2)
        # TODO: ถ้ามี GOOGLE_SHEET_ID ให้ sync ไป Sheet G_POWER_TRADES_DB ด้วย
        # sync_to_google_sheet(trades)
    except Exception as e:
        print(f"save_trades fail: {e}")

def get_last_signal():
    if LAST_SIGNAL_FILE.exists():
        try:
            with open(LAST_SIGNAL_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"signal": "WAIT", "time": "", "symbol": "BTC/USDT"}
    return {"signal": "WAIT", "time": "", "symbol": "BTC/USDT"}

def save_last_signal(signal, price, symbol="BTC/USDT"):
    try:
        LAST_SIGNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LAST_SIGNAL_FILE, 'w') as f:
            json.dump({"signal": signal, "price": price, "symbol": symbol, "time": datetime.now().isoformat()}, f)
    except Exception as e:
        print(f"save_last_signal fail: {e}")

def get_auto_state():
    if AUTO_STATE_FILE.exists():
        try:
            with open(AUTO_STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"enabled": False, "since": ""}
    return {"enabled": False, "since": ""}

def set_auto_state(enabled):
    try:
        data = {"enabled": enabled, "since": datetime.now().isoformat()}
        AUTO_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(AUTO_STATE_FILE, 'w') as f:
            json.dump(data, f)
        return data
    except Exception as e:
        print(f"set_auto_state fail: {e}")
        return {"enabled": enabled, "since": datetime.now().isoformat()}

def send_telegram(message, chat_id_override=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "") or os.environ.get("BOT_TOKEN", "") or os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = chat_id_override or os.environ.get("TELEGRAM_CHAT_ID", "") or os.environ.get("CHAT_ID", "") or os.environ.get("TG_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "error": "ยังไม่ได้ตั้ง BOT_TOKEN / CHAT_ID"}
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        r = requests.post(url, json=data, timeout=10)
        return {"ok": r.status_code == 200, "response": r.json() if r.status_code == 200 else r.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_mexc_futures_data(symbol='BTC/USDT'):
    """
    V2.5 - รองรับ BTC และ GOLD
    symbol: 'BTC/USDT' หรือ 'GOLD/USDT' หรือ 'XAU/USDT'
    บน MEXC Futures: GOLD มักเป็น GOLD/USDT หรือ XAU_USDT ต้องลอง
    """
    try:
        # ลองหลายชื่อสำหรับทอง
        symbols_to_try = [symbol]
        if 'GOLD' in symbol.upper() or 'XAU' in symbol.upper():
            symbols_to_try = ['GOLD/USDT', 'XAU/USDT', 'XAU/USDT:USDT', 'GOLD/USDT:USDT', 'XAUUSDT']
        
        last_error = None
        for sym in symbols_to_try:
            try:
                try:
                    exchange = ccxt.mexc({"options": {"defaultType": "swap"}})
                    ohlcv = exchange.fetch_ohlcv(sym, '15m', limit=250)
                except:
                    exchange = ccxt.mexc()
                    ohlcv = exchange.fetch_ohlcv(sym, '15m', limit=250)
                df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
                df['symbol'] = sym
                return df
            except Exception as e:
                last_error = str(e)
                continue
        
        # ถ้าทองไม่มี ลอง BTC เป็น fallback พร้อม error
        if 'GOLD' in symbol.upper() or 'XAU' in symbol.upper():
            return None, f"GOLD not found on MEXC: {last_error}. ลองเช็คสัญลักษณ์ GOLD/USDT บน MEXC"
        
        # BTC ปกติ
        try:
            exchange = ccxt.mexc({"options": {"defaultType": "swap"}})
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=250)
        except:
            exchange = ccxt.mexc()
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=250)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['symbol'] = 'BTC/USDT'
        return df
        
    except Exception as e:
        return None, str(e)

def get_mexc_balance_and_positions():
    api_key = os.environ.get("MEXC_API_KEY", "")
    api_secret = os.environ.get("MEXC_API_SECRET", "")
    if not api_key or not api_secret:
        return {"ok": False, "error": "ไม่ได้ตั้ง MEXC API - ใส่ใน Render Env"}
    try:
        exchange = ccxt.mexc({
            'apiKey': api_key,
            'secret': api_secret,
            'options': {'defaultType': 'swap'},
            'enableRateLimit': True,
        })
        positions = []
        for sym in [['BTC/USDT:USDT'], ['BTC/USDT'], []]:
            try:
                if sym:
                    positions = exchange.fetch_positions(sym)
                else:
                    positions = exchange.fetch_positions()
                break
            except:
                continue
        
        usdt_free = 0
        usdt_total = 0
        raw_balance = {}
        try:
            raw_balance = exchange.fetch_balance({'type': 'swap'})
        except:
            try:
                raw_balance = exchange.fetch_balance()
            except Exception as e:
                raw_balance = {}
        
        if isinstance(raw_balance, dict):
            if 'USDT' in raw_balance and isinstance(raw_balance['USDT'], dict):
                usdt_free = raw_balance['USDT'].get('free', 0) or 0
                usdt_total = raw_balance['USDT'].get('total', 0) or raw_balance['USDT'].get('free', 0) or 0
            elif 'free' in raw_balance and isinstance(raw_balance['free'], dict):
                usdt_free = raw_balance['free'].get('USDT', 0) or 0
                usdt_total = raw_balance.get('total', {}).get('USDT', 0) or usdt_free
            elif 'info' in raw_balance:
                info = raw_balance['info']
                try:
                    if isinstance(info, dict) and 'data' in info:
                        data = info['data']
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict) and item.get('currency') == 'USDT':
                                    usdt_free = float(item.get('availableBalance', 0) or item.get('available', 0) or 0)
                                    usdt_total = float(item.get('equity', 0) or item.get('balance', 0) or usdt_free)
                        elif isinstance(data, dict) and 'availableBalance' in data:
                            usdt_free = float(data.get('availableBalance', 0))
                            usdt_total = float(data.get('equity', data.get('availableBalance', 0)))
                except:
                    pass
        
        return {"ok": True, "usdt_free": float(usdt_free), "usdt_total": float(usdt_total), "positions": positions, "raw": raw_balance}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def calc_position_40():
    risk_usd = CAPITAL * RISK_PCT
    position_size = risk_usd * LEVERAGE / 0.034
    margin_needed = position_size / LEVERAGE
    return {"risk_usd": risk_usd, "position_size": position_size, "margin_needed": margin_needed, "capital": CAPITAL, "leverage": LEVERAGE}

def calc_performance():
    trades = load_trades()
    if not trades:
        return {"total_pnl_usd": 0, "win": 0, "loss": 0, "win_rate": 0, "closed_trades": 0, "trades": []}
    closed = [t for t in trades if t.get('status') == 'CLOSED']
    win = len([t for t in closed if t.get('result') == 'WIN'])
    loss = len([t for t in closed if t.get('result') == 'LOSS'])
    total_pnl = sum([float(t.get('pnl_usd', 0)) for t in closed])
    win_rate = (win / len(closed) * 100) if closed else 0
    return {"total_pnl_usd": total_pnl, "win": win, "loss": loss, "win_rate": round(win_rate, 1), "closed_trades": len(closed), "trades": trades}

@app.get("/", response_class=HTMLResponse)
def home():
    perf = calc_performance()
    pos = calc_position_40()
    auto = get_auto_state()
    bal = get_mexc_balance_and_positions()
    bal_str = f"USDT {bal.get('usdt_total', 0):.2f}" if bal.get('ok') else bal.get('error', 'No API')
    return f"""
    <html><head><title>G_POWER V2.7 ADX+DI FULL PERSISTENT</title><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>body{{background:#0a0e1a;color:#fff;font-family:Arial;padding:15px;margin:0}}
    .card{{background:#1a2332;padding:12px;border-radius:12px;margin:8px 0;border-left:4px solid #00ff88}}
    .card.red{{border-left-color:#ff4444}} .card.blue{{border-left-color:#00aaff}} .card.yellow{{border-left-color:#ffcc00}}
    h1{{color:#00ff88;font-size:18px}} h2{{color:#ffcc00;font-size:14px}} b{{color:#ffcc00}}
    .btn{{background:#00ff88;color:#000;border:0;padding:10px 14px;border-radius:8px;font-weight:bold;text-decoration:none;display:inline-block;margin:4px;font-size:12px}}
    .btn2{{background:#1a2332;color:#00ff88;border:1px solid #00ff88}}</style></head><body>
    <h1>⚡ G_POWER V2.7 ADX+DI FULL PERSISTENT - TRUTH</h1>
    <p style="font-size:11px;color:#888">DATA_DIR: {DATA_DIR} | {datetime.now().strftime('%d/%m %H:%M:%S')}</p>
    <div class="card {'red' if perf['total_pnl_usd']<0 else ''}"><h2>💰 ทุน ${CAPITAL} Futures {LEVERAGE}x - Truth</h2>
    <p>Balance: {bal_str}</p>
    <p>PnL: <b style="color:{'#00ff88' if perf['total_pnl_usd']>=0 else '#ff4444'}">${perf['total_pnl_usd']:+.2f}</b> | WinRate {perf['win_rate']}% | ปิด {perf['closed_trades']} | {perf['win']}W/{perf['loss']}L</p>
    <p>Risk: ${pos['risk_usd']:.2f} | Pos ${pos['position_size']:.2f} | Margin ${pos['margin_needed']:.2f}</p>
    <p>Auto: {'🟢 ON' if auto['enabled'] else '🔴 OFF'} | ไฟล์: {TRADES_FILE}</p>
    </div>
    <div class="card blue">
    <h3>📊 สัญลักษณ์ที่รองรับ V2.5</h3>
    <p>✅ BTC/USDT - CDC ATR 15m (หลัก)</p>
    <p>✅ GOLD/USDT / XAU/USDT - เพิ่มใหม่ (ถ้า MEXC มี)</p>
    <p>Sheet: <a href="https://docs.google.com/spreadsheets/d/1z1K9BjLh6vJXC5qkRNrBqaV2i2in4318V6I-j2UtPpc/edit" style="color:#00aaff">G_POWER_TRADES_DB</a></p>
    </div>
    <div class="card yellow">
    <h3>🔧 แก้ถาวร V2.5</h3>
    <p>1. DATA_DIR = /data (Disk) ไม่หายเมื่อ Restart</p>
    <p>2. ไม่สร้างเทรดปลอม +$11.09 อีก - Truth 100%</p>
    <p>3. รองรับ GOLD + BTC</p>
    <p>4. Drive MEXC_BTC_bot = Source of Truth</p>
    </div>
    <div class="card blue">
    <h3>📱 คำสั่ง Telegram</h3>
    <p>/check - ดูสถานะ | /on - เปิดออโต้ | /off - ปิดออโต้ | /btc /gold - ดูสัญญาณ</p>
    </div>
    <a class="btn" href="/dashboard">📊 Dashboard</a>
    <a class="btn" href="/live?symbol=BTC/USDT&send_tele=true" style="background:#1a2332;color:#ffcc00;border:1px solid #ffcc00">📡 BTC Signal + Tele</a>
    <a class="btn" href="/live?symbol=GOLD/USDT&send_tele=true" style="background:#1a2332;color:#ffaa00;border:1px solid #ffaa00">🥇 GOLD Signal + Tele</a>
    <a class="btn btn2" href="/health">💚 Health</a>
    </body></html>
    """

@app.get("/telegram/test")
def telegram_test():
    token = os.environ.get("BOT_TOKEN", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("CHAT_ID", "") or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "error": "ไม่มี BOT_TOKEN/CHAT_ID"}
    msg = f"⚡ G_POWER V2.7 ADX+DI FULL PERSISTENT\n\n✅ ต่อ Tele แล้ว!\nDATA_DIR {DATA_DIR}\nทุน $40 Futures 3x + GOLD\n{datetime.now().strftime('%d/%m %H:%M')}"
    result = send_telegram(msg)
    return {"ok": result['ok'], "result": result}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    perf = calc_performance()
    pos = calc_position_40()
    auto = get_auto_state()
    trades_html = ""
    for t in reversed(perf['trades'][-10:]):
        color = "#00ff88" if t.get('result') == 'WIN' else "#ff4444" if t.get('result') == 'LOSS' else "#ffcc00"
        status = t.get('status', 'UNKNOWN')
        pnl = f"{t.get('pnl_usd', 0):+.2f}$" if status == 'CLOSED' else f"{t.get('pnl_usd', 0):+.2f}$ OPEN"
        exit_val = t.get('exit')
        exit_str = f"${exit_val}" if exit_val else "-"
        sym = t.get('symbol', 'BTC/USDT')
        trades_html += f"<tr style='border-bottom:1px solid #333'><td style='padding:6px'>{t.get('id')}</td><td style='padding:6px'>{sym}</td><td style='padding:6px'><span style='background:{color};color:#000;padding:2px 6px;border-radius:4px;font-weight:bold'>{t.get('signal')}</span></td><td style='padding:6px'>${t.get('entry')}</td><td style='padding:6px'>{exit_str}</td><td style='padding:6px;color:{color}'>{pnl}</td><td style='padding:6px'>{status}</td></tr>"
    return f"""
    <html><head><title>Dashboard V2.5</title><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>body{{background:#0a0e1a;color:#fff;font-family:Arial;padding:15px;margin:0}}
    .card{{background:#1a2332;padding:12px;border-radius:12px;margin:8px 0;border-left:4px solid #00ff88}}
    h1{{color:#00ff88;font-size:18px}}b{{color:#ffcc00}}
    .stat{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}}
    .stat div{{background:#0f172a;padding:10px;border-radius:8px;text-align:center}}
    .stat b{{font-size:20px;display:block}}
    table{{width:100%;font-size:11px;border-collapse:collapse}}
    .btn{{background:#00ff88;color:#000;border:0;padding:8px 12px;border-radius:6px;font-weight:bold;text-decoration:none;display:inline-block;margin:3px;font-size:11px}}
    .btn2{{background:#1a2332;color:#00ff88;border:1px solid #00ff88}}</style></head><body>
    <h1>📊 Dashboard V2.5 - Auto {'🟢 ON' if auto['enabled'] else '🔴 OFF'} | {DATA_DIR}</h1>
    <div class="stat">
        <div><b style="color:{'#00ff88' if perf['total_pnl_usd']>=0 else '#ff4444'}">${perf['total_pnl_usd']:+.2f}</b>PnL Truth</div>
        <div><b>{perf['win_rate']}%</b>Win Rate</div>
        <div><b>{perf['closed_trades']}</b>ปิด</div>
        <div><b>{perf['win']}/{perf['loss']}</b>W/L</div>
    </div>
    <div class="card"><table><tr style="background:#0f172a"><th>ID</th><th>Symbol</th><th>Signal</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Status</th></tr>{trades_html or "<tr><td colspan=7 style='padding:10px;text-align:center;color:#888'>ยังไม่มีเทรด - Truth 100% รอสัญญาณจริง</td></tr>"}</table></div>
    <a class="btn" href="/live?symbol=BTC/USDT">📡 BTC สัญญาณ</a>
    <a class="btn" href="/live?symbol=GOLD/USDT" style="background:#ffaa00">🥇 GOLD สัญญาณ</a>
    <a class="btn btn2" href="/">🏠 หน้าแรก</a>
    </body></html>
    """

@app.get("/live")
def live_signal(symbol: str = Query("BTC/USDT"), send_tele: bool = Query(False)):
    try:
        result = get_mexc_futures_data(symbol)
        if isinstance(result, tuple):
            return {"error": f"MEXC fetch fail {symbol}", "detail": result[1], "symbol": symbol}
        df = result
        df = strat.add_indicators(df)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        rev = strat.check_reversal(prev, curr)
        trend = strat.check_trend(curr)
        mom = strat.check_momentum(curr)
        price = float(curr['close'])
        pos = calc_position_40()
        auto = get_auto_state()
        
        cdc_up = bool(curr.get('cdc_up', False))
        cdc_down = bool(curr.get('cdc_down', False))
        cdc_stop = float(curr.get('cdc_stop', 0))
        cdc_dist = float(curr.get('cdc_dist_pct', 0))
        cdc_trend_str = "🟢 UPTREND" if cdc_up else "🔴 DOWNTREND"
        
        signal = "WAIT"
        if rev['long'] and trend['long'] and mom['long'] and not trend['sideway']:
            signal = "LONG"
        elif rev['short'] and trend['short'] and mom['short'] and not trend['sideway']:
            signal = "SHORT"
        
        last = get_last_signal()
        should_send = (signal != last.get('signal') and signal != "WAIT" and auto['enabled'])
        
        tele_result = None
        if should_send or send_tele:
            cdc_info = f"CDC: {cdc_trend_str} Stop ${cdc_stop:,.0f}"
            if signal == "LONG":
                msg = f"🚀 {symbol} LONG ${price:,.2f}\n{cdc_info}\nPos ${pos['position_size']:.2f} Margin ${pos['margin_needed']:.2f}\nTP ${price*1.18:,.2f} SL ${price*0.966:,.2f}\n{datetime.now().strftime('%d/%m %H:%M')}"
            elif signal == "SHORT":
                msg = f"🔻 {symbol} SHORT ${price:,.2f}\n{cdc_info}\nPos ${pos['position_size']:.2f} Margin ${pos['margin_needed']:.2f}\nTP ${price*0.82:,.2f} SL ${price*1.034:,.2f}\n{datetime.now().strftime('%d/%m %H:%M')}"
            else:
                msg = f"⏳ {symbol} WAIT ${price:,.2f}\n{cdc_info} ({cdc_dist:+.2f}%)\n{datetime.now().strftime('%d/%m %H:%M')}"
            tele_result = send_telegram(msg)
            if should_send:
                save_last_signal(signal, price, symbol)
        
        return {"symbol": symbol, "price": price, "signal": signal, "cdc_trend": cdc_trend_str, "cdc_stop": cdc_stop, "cdc_dist": cdc_dist, "auto": auto['enabled'], "telegram_sent": tele_result is not None, "data_dir": str(DATA_DIR)}
    except Exception as e:
        return {"error": str(e), "symbol": symbol}

@app.get("/health")
def health():
    trades = load_trades()
    return {"status": "OK V2.7 ADX+DI FULL PERSISTENT", "capital": CAPITAL, "data_dir": str(DATA_DIR), "trades_count": len(trades), "auto": get_auto_state()['enabled'], "telegram": bool(os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")), "truth": "No fake trades +11.09", "symbols": ["BTC/USDT", "GOLD/USDT", "XAU/USDT"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
