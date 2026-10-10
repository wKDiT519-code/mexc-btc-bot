import os, time, threading, requests, math, sys
print("=== BOT STARTING v9.1 PAPER TRADE $100 ===", flush=True)
from flask import Flask, jsonify
try:
    import ccxt
    print("ccxt OK", flush=True)
except Exception as e:
    print(f"ccxt FAIL: {e}", flush=True)
try:
    import pandas as pd
    print("pandas OK", flush=True)
except Exception as e:
    print(f"pandas FAIL: {e}", flush=True)

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
SYMBOL = "BTC/USDT"
TIMEFRAME = "15m"
START_BALANCE = 100.0
RISK_PER_TRADE = 20.0
LEVERAGE = 10
COOLDOWN_SEC = 15*60

portfolio = {
    "balance": START_BALANCE,
    "start_balance": START_BALANCE,
    "trades": [],
    "wins": 0,
    "losses": 0,
    "position": None,
    "last_price": 0,
    "last_update": ""
}

print(f"TELEGRAM_TOKEN set: {bool(TELEGRAM_TOKEN)}", flush=True)
print(f"CHAT_ID set: {bool(CHAT_ID)}", flush=True)

try:
    exchange = ccxt.mexc()
    print("MEXC exchange OK", flush=True)
except Exception as e:
    print(f"MEXC init FAIL: {e}", flush=True)
    exchange = None

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"SKIP Telegram (no token/chat): {msg[:50]}", flush=True)
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print(f"Telegram sent: {r.status_code}", flush=True)
    except Exception as e:
        print(f"Telegram error: {e}", flush=True)

def get_ohlcv():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
    return df

def calc_indicators(df):
    delta = df["close"].diff()
    gain = delta.where(delta>0,0).rolling(14).mean()
    loss = -delta.where(delta<0,0).rolling(14).mean()
    rs = gain/loss
    df["rsi"] = 100 - (100/(1+rs))
    df["tr"] = pd.concat([df["high"]-df["low"], (df["high"]-df["close"].shift()).abs(), (df["low"]-df["close"].shift()).abs()], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(14).mean()
    df["up"] = df["high"].diff()
    df["down"] = -df["low"].diff()
    df["plus_dm"] = df.apply(lambda x: x["up"] if x["up"]>x["down"] and x["up"]>0 else 0, axis=1)
    df["minus_dm"] = df.apply(lambda x: x["down"] if x["down"]>x["up"] and x["down"]>0 else 0, axis=1)
    df["plus_di"] = 100 * (df["plus_dm"].rolling(14).mean() / df["atr"])
    df["minus_di"] = 100 * (df["minus_dm"].rolling(14).mean() / df["atr"])
    df["dx"] = 100 * abs(df["plus_di"]-df["minus_di"]) / (df["plus_di"]+df["minus_di"])
    df["adx"] = df["dx"].rolling(14).mean()
    return df

def paper_check_close(current_price):
    pos = portfolio["position"]
    if not pos:
        return
    if pos["side"]=="LONG":
        if current_price <= pos["sl"]:
            pnl = (pos["sl"]-pos["entry"])/pos["entry"] * pos["amount"] * LEVERAGE
            portfolio["balance"] += pnl
            portfolio["losses"]+=1
            portfolio["trades"].append({"pnl":pnl, "result":"SL", "price":current_price})
            send_telegram(f"🛑 *SL HIT* LONG\nEntry: ${pos['entry']:.2f} -> SL: ${pos['sl']:.2f}\nPnL: ${pnl:.2f}\n💰 พอร์ต: ${portfolio['balance']:.2f} ({(portfolio['balance']/START_BALANCE-1)*100:+.2f}%)\n📊 W:{portfolio['wins']} L:{portfolio['losses']}")
            portfolio["position"]=None
            return
        if current_price >= pos["tp3"]:
            # คิดแบบปิด 50/30/20
            pnl1 = (pos["tp1"]-pos["entry"])/pos["entry"] * pos["amount"] * LEVERAGE * 0.5
            pnl2 = (pos["tp2"]-pos["entry"])/pos["entry"] * pos["amount"] * LEVERAGE * 0.3
            pnl3 = (pos["tp3"]-pos["entry"])/pos["entry"] * pos["amount"] * LEVERAGE * 0.2
            pnl = pnl1+pnl2+pnl3
            portfolio["balance"]+=pnl
            portfolio["wins"]+=1
            portfolio["trades"].append({"pnl":pnl, "result":"TP3", "price":current_price})
            send_telegram(f"✅ *TP3 HIT* LONG\nEntry: ${pos['entry']:.2f}\nTPs: ${pos['tp1']:.0f} / ${pos['tp2']:.0f} / ${pos['tp3']:.0f}\nPnL: +${pnl:.2f}\n💰 พอร์ต: ${portfolio['balance']:.2f} ({(portfolio['balance']/START_BALANCE-1)*100:+.2f}%)\n📊 W:{portfolio['wins']} L:{portfolio['losses']}")
            portfolio["position"]=None

def bot_loop():
    print("BOT LOOP STARTED", flush=True)
    last_signal_time = 0
    time.sleep(5)
    send_telegram(f"🚀 Bot v9.1 PAPER TRADE LIVE!\n💰 พอร์ตจำลอง: ${START_BALANCE}\nRisk: ${RISK_PER_TRADE}/ไม้ x{LEVERAGE}\nTF {TIMEFRAME} ATR SL x1.5 TP x1/2/3")
    while True:
        try:
            df = get_ohlcv()
            df = calc_indicators(df)
            last = df.iloc[-1]
            price = float(last["close"])
            rsi = float(last["rsi"]) if not pd.isna(last["rsi"]) else 50
            adx = float(last["adx"]) if not pd.isna(last["adx"]) else 0
            atr = float(last["atr"]) if not pd.isna(last["atr"]) else price*0.001
            
            portfolio["last_price"] = price
            portfolio["last_update"] = time.strftime("%H:%M:%S")
            
            print(f"SCAN {time.strftime('%H:%M:%S')} BTC ${price:.2f} RSI {rsi:.1f} ADX {adx:.1f} ATR {atr:.2f} Bal ${portfolio['balance']:.2f} Pos {portfolio['position'] is not None}", flush=True)
            
            paper_check_close(price)
            
            if portfolio["position"] is None and time.time() - last_signal_time > COOLDOWN_SEC:
                trend_up = last["plus_di"] > last["minus_di"]
                if adx>20 and 50<rsi<70 and trend_up:
                    entry = price
                    sl = entry - atr*1.5
                    tp1 = entry + atr*1.0
                    tp2 = entry + atr*2.0
                    tp3 = entry + atr*3.0
                    amount = min(RISK_PER_TRADE, portfolio["balance"]*0.2)
                    portfolio["position"]={"side":"LONG","entry":entry,"amount":amount,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"opened_at":time.time()}
                    last_signal_time=time.time()
                    send_telegram(f"🚀 *SIGNAL LONG - PAPER OPEN*\nBTC ${entry:.2f} RSI {rsi:.1f} ADX {adx:.1f}\nTP1 ${tp1:.2f} TP2 ${tp2:.2f} TP3 ${tp3:.2f}\nSL ${sl:.2f}\nเปิด ${amount:.2f} x{LEVERAGE} พอร์ต ${portfolio['balance']:.2f}")
                    
        except Exception as e:
            print(f"Bot error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        time.sleep(60)

@app.route("/")
def home():
    return f"Bot v9.1 PAPER TRADE LIVE - Balance ${portfolio['balance']:.2f} Win {portfolio['wins']} Loss {portfolio['losses']} Price ${portfolio['last_price']} Updated {portfolio['last_update']}"

@app.route("/health")
def health():
    return "OK", 200

@app.route("/portfolio")
def portfolio_view():
    return jsonify(portfolio)

threading.Thread(target=bot_loop, daemon=True).start()
print("Thread started", flush=True)

if __name__=="__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting Flask on {port}", flush=True)
    app.run(host="0.0.0.0", port=port)
