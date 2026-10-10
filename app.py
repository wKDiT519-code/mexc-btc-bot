
import os, time, threading, requests, math
from flask import Flask
import ccxt
import pandas as pd

app = Flask(__name__)

# ===== CONFIG =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "YOUR_CHAT_ID")
SYMBOL = "BTC/USDT"
TIMEFRAME = "15m"
START_BALANCE = 100.0  # พอร์ตจำลอง $100
RISK_PER_TRADE = 20.0  # เปิดไม้ละ $20 (20% พอร์ต)
LEVERAGE = 10
COOLDOWN_SEC = 15*60

# Paper Portfolio (เก็บใน memory, Render restart จะรีเซ็ต)
portfolio = {
    "balance": START_BALANCE,
    "start_balance": START_BALANCE,
    "trades": [],
    "wins": 0,
    "losses": 0,
    "position": None  # {side, entry, amount, sl, tp1,tp2,tp3, opened_at}
}

exchange = ccxt.mexc()

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_ohlcv():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
    return df

def calc_indicators(df):
    # RSI 14
    delta = df["close"].diff()
    gain = delta.where(delta>0,0).rolling(14).mean()
    loss = -delta.where(delta<0,0).rolling(14).mean()
    rs = gain/loss
    df["rsi"] = 100 - (100/(1+rs))
    # ADX simplified
    df["tr"] = pd.concat([df["high"]-df["low"], (df["high"]-df["close"].shift()).abs(), (df["low"]-df["close"].shift()).abs()], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(14).mean()
    # ADX
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
    # Long logic
    if pos["side"]=="LONG":
        # Check SL first
        if current_price <= pos["sl"]:
            pnl = (pos["sl"]-pos["entry"])/pos["entry"] * pos["amount"] * LEVERAGE
            portfolio["balance"] += pnl
            portfolio["losses"]+=1
            portfolio["trades"].append({"pnl":pnl, "result":"SL"})
            send_telegram(f"""🛑 *SL HIT* LONG
Entry: ${pos['entry']:.2f} -> SL: ${pos['sl']:.2f}
PnL: ${pnl:.2f} ({pnl/START_BALANCE*100:+.2f}%)
💰 พอร์ต: ${portfolio['balance']:.2f} ({(portfolio['balance']/START_BALANCE-1)*100:+.2f}%)
📊 Win: {portfolio['wins']} / Loss: {portfolio['losses']}""")
            portfolio["position"]=None
            return
        # Check TPs (partial close simulation - close all at highest TP hit for simplicity)
        if current_price >= pos["tp3"]:
            pnl = (pos["tp3"]-pos["entry"])/pos["entry"] * pos["amount"] * LEVERAGE * 0.2 + (pos["tp2"]-pos["entry"])/pos["entry"]*pos["amount"]*LEVERAGE*0.3 + (pos["tp1"]-pos["entry"])/pos["entry"]*pos["amount"]*LEVERAGE*0.5
            # คำนวณรวม 3 TP ตามสัดส่วน 50%/30%/20%
            portfolio["balance"]+=pnl
            portfolio["wins"]+=1
            portfolio["trades"].append({"pnl":pnl, "result":"TP3"})
            send_telegram(f"""✅ *TP3 HIT* LONG - ปิดครบ 3 เป้า
Entry: ${pos['entry']:.2f}
TP1 ${pos['tp1']:.2f} + TP2 ${pos['tp2']:.2f} + TP3 ${pos['tp3']:.2f}
PnL: +${pnl:.2f} ({pnl/START_BALANCE*100:+.2f}%)
💰 พอร์ต: ${portfolio['balance']:.2f} ({(portfolio['balance']/START_BALANCE-1)*100:+.2f}%)
📊 Win: {portfolio['wins']} / Loss: {portfolio['losses']}
RR: 1:0.7 / 1:1.3 / 1:2.0""")
            portfolio["position"]=None
        elif current_price >= pos["tp2"]:
            # ถ้าถึง TP2 แต่ยังไม่ TP3 ถือต่อ รอ TP3
            pass
        elif current_price >= pos["tp1"]:
            pass

def bot_loop():
    last_signal_time = 0
    send_telegram(f"Bot v9 PAPER TRADE LIVE!\nTF 15m\nATR SL x1.5 TP x1.0/2.0/3.0\n💰 พอร์ตจำลอง: ${START_BALANCE}\nRisk: ${RISK_PER_TRADE}/ไม้ x{LEVERAGE}\nScan every 60s")
    while True:
        try:
            df = get_ohlcv()
            df = calc_indicators(df)
            last = df.iloc[-1]
            price = last["close"]
            rsi = last["rsi"]
            adx = last["adx"]
            atr = last["atr"]
            
            # เช็คปิดออเดอร์ก่อน
            paper_check_close(price)
            
            # หาสัญญาณใหม่ ถ้าไม่มี position
            if portfolio["position"] is None and time.time() - last_signal_time > COOLDOWN_SEC:
                trend_up = last["plus_di"] > last["minus_di"]
                trend_down = not trend_up
                # LONG condition: ADX>20, RSI 50-70, Uptrend
                if adx>20 and 50<rsi<70 and trend_up:
                    atr_val = atr if not math.isnan(atr) else price*0.001
                    entry = price
                    sl = entry - atr_val*1.5
                    tp1 = entry + atr_val*1.0
                    tp2 = entry + atr_val*2.0
                    tp3 = entry + atr_val*3.0
                    
                    # เปิด Paper Position
                    amount = min(RISK_PER_TRADE, portfolio["balance"]*0.2)
                    portfolio["position"]={
                        "side":"LONG","entry":entry,"amount":amount,
                        "sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,
                        "opened_at":time.time()
                    }
                    last_signal_time=time.time()
                    rr1 = (tp1-entry)/(entry-sl) if entry!=sl else 0
                    
                    send_telegram(f"""🚀 *SIGNAL LONG - PAPER TRADE OPEN*

💰 BTC: ${entry:.2f}
📊 RSI: {rsi:.1f} | ADX: {adx:.1f}
📏 ATR: {atr_val:.2f}
🔀 Trend: UP

🎯 TP1: ${tp1:.2f} (+{(tp1/entry-1)*100:.2f}% | x1.0)
🎯 TP2: ${tp2:.2f} (+{(tp2/entry-1)*100:.2f}% | x2.0)
🎯 TP3: ${tp3:.2f} (+{(tp3/entry-1)*100:.2f}% | x3.0)
🛑 SL: ${sl:.2f} ({(sl/entry-1)*100:.2f}% | x1.5)
📐 RR: 1:{rr1:.1f}

💵 เปิด: ${amount:.2f} x{LEVERAGE}
💰 พอร์ตตอนนี้: ${portfolio['balance']:.2f}
🧪 PAPER TRADE - ทดลองพอร์ต $100""")
                    
        except Exception as e:
            print(f"Bot error: {e}")
        time.sleep(60)

@app.route("/")
def home():
    return f"Bot v9 PAPER TRADE LIVE - Balance ${portfolio['balance']:.2f} Win {portfolio['wins']} Loss {portfolio['losses']}"

@app.route("/health")
def health():
    return "OK", 200

@app.route("/portfolio")
def portfolio_view():
    return portfolio

threading.Thread(target=bot_loop, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
