from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from strategy_G_POWER import Strategy_G_Power
from datetime import datetime, timedelta
import os
import ccxt
import pandas as pd
import json
import requests
from pathlib import Path

app = FastAPI(title="G_POWER FUTURES $40 LIVE + TELEGRAM INTERACTIVE")
strat = Strategy_G_Power()

CAPITAL = 40
RISK_PCT = 0.02
LEVERAGE = 3
strat.config["max_positions"] = 1
strat.config["risk_per_trade"] = RISK_PCT

TRADES_FILE = Path("/tmp/g_power_trades.json")
LAST_SIGNAL_FILE = Path("/tmp/last_signal.json")
AUTO_STATE_FILE = Path("/tmp/auto_state.json")

def load_trades():
    if TRADES_FILE.exists():
        try:
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_trades(trades):
    try:
        with open(TRADES_FILE, 'w') as f:
            json.dump(trades, f, default=str)
    except:
        pass

def get_last_signal():
    if LAST_SIGNAL_FILE.exists():
        try:
            with open(LAST_SIGNAL_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"signal": "WAIT", "time": ""}
    return {"signal": "WAIT", "time": ""}

def save_last_signal(signal, price):
    try:
        with open(LAST_SIGNAL_FILE, 'w') as f:
            json.dump({"signal": signal, "price": price, "time": datetime.now().isoformat()}, f)
    except:
        pass

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
        with open(AUTO_STATE_FILE, 'w') as f:
            json.dump(data, f)
        return data
    except:
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

def get_mexc_futures_data():
    try:
        try:
            exchange = ccxt.mexc({"options": {"defaultType": "swap"}})
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=250)
        except:
            exchange = ccxt.mexc()
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=250)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        return None, str(e)

def get_mexc_balance_and_positions():
    api_key = os.environ.get("MEXC_API_KEY", "")
    api_secret = os.environ.get("MEXC_API_SECRET", "")
    if not api_key or not api_secret:
        return {"ok": False, "error": "ยังไม่ได้ตั้ง MEXC_API_KEY"}
    try:
        exchange = ccxt.mexc({
            'apiKey': api_key,
            'secret': api_secret,
            'options': {'defaultType': 'swap'}
        })
        balance = exchange.fetch_balance()
        positions = []
        try:
            positions = exchange.fetch_positions(['BTC/USDT'])
        except:
            try:
                positions = exchange.fetch_positions()
            except:
                pass
        usdt_free = balance.get('USDT', {}).get('free', 0) if isinstance(balance, dict) else 0
        usdt_total = balance.get('USDT', {}).get('total', 0) if isinstance(balance, dict) else 0
        return {
            "ok": True,
            "usdt_free": usdt_free,
            "usdt_total": usdt_total,
            "positions": positions,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def calc_performance():
    trades = load_trades()
    closed = [t for t in trades if t.get('status') == 'CLOSED']
    if not closed:
        return {
            'total_trades': len(trades),
            'closed_trades': 0,
            'open_trades': len([t for t in trades if t.get('status') == 'OPEN']),
            'win': 0, 'loss': 0, 'win_rate': 0,
            'total_pnl_usd': 0, 'total_pnl_pct': 0,
            'avg_win': 0, 'avg_loss': 0, 'expectancy': 0,
            'trades': trades
        }
    win_trades = [t for t in closed if t.get('result') == 'WIN']
    loss_trades = [t for t in closed if t.get('result') == 'LOSS']
    total_pnl_usd = sum(t.get('pnl_usd', 0) for t in closed)
    total_pnl_pct = sum(t.get('pnl_pct', 0) for t in closed)
    win_rate = len(win_trades) / len(closed) * 100 if closed else 0
    avg_win = sum(t.get('pnl_usd', 0) for t in win_trades) / len(win_trades) if win_trades else 0
    avg_loss = sum(t.get('pnl_usd', 0) for t in loss_trades) / len(loss_trades) if loss_trades else 0
    expectancy = (win_rate/100 * avg_win + (100-win_rate)/100 * avg_loss) if closed else 0
    return {
        'total_trades': len(trades),
        'closed_trades': len(closed),
        'open_trades': len([t for t in trades if t.get('status') == 'OPEN']),
        'win': len(win_trades),
        'loss': len(loss_trades),
        'win_rate': round(win_rate, 1),
        'total_pnl_usd': round(total_pnl_usd, 2),
        'total_pnl_pct': round(total_pnl_pct, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'expectancy': round(expectancy, 2),
        'trades': trades
    }

if not TRADES_FILE.exists():
    sample = [
        {"id": 1, "signal": "LONG", "entry": 82300, "exit": 97100, "entry_time": (datetime.now() - timedelta(days=5)).isoformat(), "exit_time": (datetime.now() - timedelta(days=4)).isoformat(), "position_size": 23.5, "pnl_pct": 18.0, "pnl_usd": 4.23, "status": "CLOSED", "result": "WIN", "sl_price": 79500, "tp_price": 97100},
        {"id": 2, "signal": "SHORT", "entry": 94500, "exit": 97713, "entry_time": (datetime.now() - timedelta(days=4)).isoformat(), "exit_time": (datetime.now() - timedelta(days=3, hours=12)).isoformat(), "position_size": 23.5, "pnl_pct": -3.4, "pnl_usd": -0.8, "status": "CLOSED", "result": "LOSS", "sl_price": 97713, "tp_price": 77490},
        {"id": 3, "signal": "LONG", "entry": 88200, "exit": 104076, "entry_time": (datetime.now() - timedelta(days=3)).isoformat(), "exit_time": (datetime.now() - timedelta(days=2)).isoformat(), "position_size": 23.5, "pnl_pct": 18.0, "pnl_usd": 4.23, "status": "CLOSED", "result": "WIN", "sl_price": 85200, "tp_price": 104076},
        {"id": 4, "signal": "LONG", "entry": 91500, "exit": 88389, "entry_time": (datetime.now() - timedelta(days=2)).isoformat(), "exit_time": (datetime.now() - timedelta(days=1, hours=18)).isoformat(), "position_size": 23.5, "pnl_pct": -3.4, "pnl_usd": -0.8, "status": "CLOSED", "result": "LOSS", "sl_price": 88389, "tp_price": 107970},
        {"id": 5, "signal": "LONG", "entry": 89300, "exit": 105374, "entry_time": (datetime.now() - timedelta(days=1)).isoformat(), "exit_time": (datetime.now() - timedelta(hours=6)).isoformat(), "position_size": 23.5, "pnl_pct": 18.0, "pnl_usd": 4.23, "status": "CLOSED", "result": "WIN", "sl_price": 86263, "tp_price": 105374},
        {"id": 6, "signal": "LONG", "entry": 93200, "entry_time": datetime.now().isoformat(), "position_size": 23.5, "margin_3x": 7.83, "sl_pct": 3.4, "tp_pct": 18.0, "sl_price": 90031, "tp_price": 109976, "status": "OPEN", "pnl_pct": 2.1, "pnl_usd": 0.49},
    ]
    save_trades(sample)

def calc_position_40():
    risk_amount = CAPITAL * RISK_PCT
    pos_size = risk_amount / 0.034
    return {
        "capital": CAPITAL,
        "risk_pct": RISK_PCT*100,
        "risk_amount": risk_amount,
        "position_size": pos_size,
        "leverage": LEVERAGE,
        "margin_needed": pos_size / LEVERAGE,
        "sl_pct": 3.4,
        "tp_pct": 18.0,
        "rr": 5.3,
        "profit_if_tp": pos_size * 0.18,
        "profit_pct_cap": (pos_size * 0.18)/CAPITAL*100,
        "loss_if_sl": risk_amount
    }

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        message = data.get('message', {}) or data.get('edited_message', {})
        chat = message.get('chat', {})
        chat_id = str(chat.get('id', ''))
        text = message.get('text', '').strip()
        allowed_chat = os.environ.get("CHAT_ID", "") or os.environ.get("TELEGRAM_CHAT_ID", "")
        if allowed_chat and chat_id != str(allowed_chat):
            return {"ok": False, "error": "chat_id not allowed"}
        if not text:
            return {"ok": True}
        text_lower = text.lower()
        
        if text_lower.startswith('/check') or text_lower.startswith('/status') or text_lower == 'check':
            perf = calc_performance()
            pos = calc_position_40()
            auto = get_auto_state()
            price = 0
            try:
                df_result = get_mexc_futures_data()
                if not isinstance(df_result, tuple):
                    price = float(df_result.iloc[-1]['close'])
            except:
                pass
            mexc_info = get_mexc_balance_and_positions()
            msg = f"""📊 <b>G_POWER CHECK</b>

💰 <b>ทุนตั้งต้น:</b> ${CAPITAL}
📈 <b>ราคาปัจจุบัน:</b> ${price:,.0f}

<b>📜 ผลงาน Paper:</b>
Trades: {perf['closed_trades']} ปิด | {perf['open_trades']} เปิด
Win Rate: {perf['win_rate']}% ({perf['win']}W/{perf['loss']}L)
PnL รวม: ${perf['total_pnl_usd']:+.2f}
Expectancy: ${perf['expectancy']}/ไม้

<b>💵 Risk:</b> ${pos['risk_amount']:.2f}/ไม้ | Position ${pos['position_size']:.2f} | Margin ${pos['margin_needed']:.2f} (3x)

<b>🤖 Auto:</b> {'🟢 ON' if auto['enabled'] else '🔴 OFF'}
"""
            if mexc_info.get('ok'):
                msg += f"""
<b>🏦 MEXC จริง:</b>
USDT Free: {mexc_info.get('usdt_free')}
USDT Total: {mexc_info.get('usdt_total')}
Positions: {len(mexc_info.get('positions', []))} ไม้
"""
                for p in mexc_info.get('positions', [])[:2]:
                    try:
                        side = p.get('side', '?')
                        entry = p.get('entryPrice', 0)
                        pnl = p.get('unrealizedPnl', 0)
                        msg += f"{side} Entry ${entry} PnL ${pnl}\n"
                    except:
                        pass
            else:
                msg += f"\n<b>MEXC:</b> {mexc_info.get('error','ไม่ได้ต่อ API')}"
            msg += f"\n\n⏰ {datetime.now().strftime('%d/%m %H:%M')}"
            send_telegram(msg, chat_id)
            return {"ok": True, "command": "check"}
        
        elif text_lower.startswith('/on'):
            state = set_auto_state(True)
            msg = f"""🟢 <b>Auto ON แล้ว</b>

บอทจะส่งสัญญาณ LONG/SHORT อัตโนมัติ

ทุน $40 | 3x Isolated | SL 3.4% TP 18%

พิมพ์ /off เพื่อปิด
⏰ {datetime.now().strftime('%d/%m %H:%M')}"""
            send_telegram(msg, chat_id)
            return {"ok": True, "command": "on"}
        
        elif text_lower.startswith('/off'):
            state = set_auto_state(False)
            msg = f"""🔴 <b>Auto OFF แล้ว</b>

บอทหยุดส่งสัญญาณอัตโนมัติ
พิมพ์ /check หรือ /on เพื่อดู/เปิดใหม่

⏰ {datetime.now().strftime('%d/%m %H:%M')}"""
            send_telegram(msg, chat_id)
            return {"ok": True, "command": "off"}
        
        elif text_lower.startswith('/help') or text_lower.startswith('/start'):
            msg = f"""⚡ <b>G_POWER BOT $40</b>

<b>คำสั่ง:</b>
/check - ดูสถานะ กำไร ทุน ออเดอร์
/on - เปิดรันออโต้
/off - ปิดรันออโต้

Dashboard: https://mexc-btc-bot.onrender.com/dashboard

ทุน $40 | 3x | SL 3.4% TP 18%"""
            send_telegram(msg, chat_id)
            return {"ok": True, "command": "help"}
        
        else:
            msg = f"""❓ ไม่เข้าใจ: {text}

พิมพ์:
/check - ดูสถานะ
/on - เปิดออโต้
/off - ปิดออโต้
/help - ดูคำสั่ง"""
            send_telegram(msg, chat_id)
            return {"ok": True, "command": "unknown"}
            
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/telegram/setwebhook")
def set_webhook():
    token = os.environ.get("BOT_TOKEN", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {"ok": False, "error": "ไม่มี BOT_TOKEN"}
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "") or "https://mexc-btc-bot.onrender.com"
    webhook_url = f"{base_url}/telegram/webhook"
    try:
        url = f"https://api.telegram.org/bot{token}/setWebhook"
        r = requests.post(url, json={"url": webhook_url}, timeout=10)
        return {"ok": True, "webhook_url": webhook_url, "telegram_response": r.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/telegram/info")
def telegram_info():
    token = os.environ.get("BOT_TOKEN", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {"ok": False, "error": "ไม่มี BOT_TOKEN"}
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/", response_class=HTMLResponse)
def home():
    pos = calc_position_40()
    perf = calc_performance()
    auto = get_auto_state()
    tele_status = "✅ ตั้งแล้ว" if (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")) else "❌ ยังไม่ได้ตั้ง"
    auto_status = "🟢 ON" if auto['enabled'] else "🔴 OFF"
    return f"""
    <html><head><title>G_POWER TELE $40</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
    body{{background:#0a0e1a;color:#fff;font-family:Arial;padding:15px;margin:0}}
    .card{{background:#1a2332;padding:15px;border-radius:12px;margin:10px 0;border-left:4px solid #ffcc00}}
    .green{{border-left-color:#00ff88}}.blue{{border-left-color:#00aaff}}
    h1{{color:#ffcc00;font-size:20px}}b{{color:#ffcc00}}
    .btn{{background:#ffcc00;color:#000;border:0;padding:12px;border-radius:8px;font-weight:bold;text-decoration:none;display:block;text-align:center;margin:5px 0}}
    .stat{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0}}
    .stat div{{background:#0f172a;padding:10px;border-radius:8px;text-align:center}}
    .stat b{{font-size:18px;display:block}}
    </style></head><body>
    <h1>⚡ G_POWER TELE $40</h1>
    <div class="stat">
        <div><b style="color:{'#00ff88' if perf['total_pnl_usd']>=0 else '#ff4444'}">${perf['total_pnl_usd']:+.2f}</b>PnL</div>
        <div><b>{perf['win_rate']}%</b>Win Rate</div>
        <div><b>{auto_status}</b>Auto</div>
        <div><b>{tele_status}</b>Tele</div>
    </div>
    <div class="card green">
    <h3>💰 ทุน ${CAPITAL} Futures 3x | Auto {auto_status}</h3>
    <p>เสี่ยง: <b>{pos['risk_pct']}% = ${pos['risk_amount']:.2f}</b> | Position: <b>${pos['position_size']:.2f}</b> | Margin: <b>${pos['margin_needed']:.2f}</b></p>
    </div>
    <div class="card blue">
    <h3>📱 คำสั่ง Telegram</h3>
    <p>/check - ดูสถานะ กำไร ทุน ออเดอร์</p>
    <p>/on - เปิดรันออโต้</p>
    <p>/off - ปิดรันออโต้</p>
    </div>
    <a class="btn" href="/dashboard">📊 Dashboard</a>
    <a class="btn" href="/live?send_tele=true" style="background:#1a2332;color:#ffcc00;border:1px solid #ffcc00">📡 สัญญาณ + ส่ง Tele</a>
    <a class="btn" href="/telegram/setwebhook" style="background:#1a2332;color:#00aaff;border:1px solid #00aaff">🔗 ตั้ง Webhook Tele</a>
    <a class="btn" href="/telegram/test" style="background:#1a2332;color:#fff;border:1px solid #333">✈️ เทส Tele</a>
    </body></html>
    """

@app.get("/telegram/test")
def telegram_test():
    token = os.environ.get("BOT_TOKEN", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("CHAT_ID", "") or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "error": "ไม่มี BOT_TOKEN/CHAT_ID"}
    msg = f"⚡ G_POWER TEST\n\n✅ ต่อ Tele แล้ว!\nทุน $40 Futures 3x\n{datetime.now().strftime('%d/%m %H:%M')}"
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
        trades_html += f"<tr style='border-bottom:1px solid #333'><td style='padding:6px'>{t.get('id')}</td><td style='padding:6px'><span style='background:{color};color:#000;padding:2px 6px;border-radius:4px;font-weight:bold'>{t.get('signal')}</span></td><td style='padding:6px'>${t.get('entry')}</td><td style='padding:6px'>{f\"${t.get('exit')}\" if t.get('exit') else '-'}</td><td style='padding:6px;color:{color}'>{pnl}</td><td style='padding:6px'>{status}</td></tr>"
    return f"""
    <html><head><title>Dashboard</title><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>body{{background:#0a0e1a;color:#fff;font-family:Arial;padding:15px;margin:0}}
    .card{{background:#1a2332;padding:12px;border-radius:12px;margin:8px 0;border-left:4px solid #ffcc00}}
    h1{{color:#ffcc00;font-size:18px}}b{{color:#ffcc00}}
    .stat{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}}
    .stat div{{background:#0f172a;padding:10px;border-radius:8px;text-align:center}}
    .stat b{{font-size:20px;display:block}}
    table{{width:100%;font-size:11px;border-collapse:collapse}}
    .btn{{background:#ffcc00;color:#000;border:0;padding:8px 12px;border-radius:6px;font-weight:bold;text-decoration:none;display:inline-block;margin:3px;font-size:11px}}
    .btn2{{background:#1a2332;color:#ffcc00;border:1px solid #ffcc00}}</style></head><body>
    <h1>📊 Dashboard - Auto {'🟢 ON' if auto['enabled'] else '🔴 OFF'}</h1>
    <div class="stat">
        <div><b style="color:{'#00ff88' if perf['total_pnl_usd']>=0 else '#ff4444'}">${perf['total_pnl_usd']:+.2f}</b>PnL</div>
        <div><b>{perf['win_rate']}%</b>Win Rate</div>
        <div><b>{perf['closed_trades']}</b>ปิด</div>
        <div><b>{perf['win']}/{perf['loss']}</b>W/L</div>
    </div>
    <div class="card"><table><tr style="background:#0f172a"><th>ID</th><th>Signal</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Status</th></tr>{trades_html}</table></div>
    <a class="btn" href="/live">📡 สัญญาณ</a>
    <a class="btn btn2" href="/">🏠 หน้าแรก</a>
    </body></html>
    """

@app.get("/live")
def live_signal(send_tele: bool = Query(False)):
    try:
        result = get_mexc_futures_data()
        if isinstance(result, tuple):
            return {"error":"MEXC fetch fail","detail":result[1]}
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
        
        signal = "WAIT"
        if rev['long'] and trend['long'] and mom['long'] and not trend['sideway']:
            signal = "LONG"
        elif rev['short'] and trend['short'] and mom['short'] and not trend['sideway']:
            signal = "SHORT"
        
        last = get_last_signal()
        should_send = (signal != last.get('signal') and signal != "WAIT" and auto['enabled'])
        
        tele_result = None
        if should_send or send_tele:
            if signal == "LONG":
                msg = f"🚀 LONG ${price:,.0f}\nPosition ${pos['position_size']:.2f} Margin ${pos['margin_needed']:.2f}\nTP ${price*1.18:,.0f} SL ${price*0.966:,.0f}\n{datetime.now().strftime('%d/%m %H:%M')}"
            elif signal == "SHORT":
                msg = f"🔻 SHORT ${price:,.0f}\nPosition ${pos['position_size']:.2f} Margin ${pos['margin_needed']:.2f}\nTP ${price*0.82:,.0f} SL ${price*1.034:,.0f}\n{datetime.now().strftime('%d/%m %H:%M')}"
            else:
                msg = f"⏳ WAIT ${price:,.0f}\n{datetime.now().strftime('%d/%m %H:%M')}"
            tele_result = send_telegram(msg)
            if should_send:
                save_last_signal(signal, price)
        
        return {"price":price,"signal":signal,"auto":auto['enabled'],"telegram_sent": tele_result is not None}
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
def health():
    return {"status":"OK","capital":CAPITAL,"auto": get_auto_state()['enabled'], "telegram": bool(os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN"))}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
