from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def home():
    return """
    <h1>🤖 MEXC BTC Bot Running ✅ LIVE!</h1>
    <p>Bot is UP - Next step: Add full trading logic</p>
    <p><a href='/health'>/health</a> | <a href='/test-telegram'>/test-telegram</a></p>
    """

@app.route('/health')
def health():
    return "OK", 200

@app.route('/test-telegram')
def test_telegram():
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return "Missing TELEGRAM_BOT_TOKEN or CHAT_ID"
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={"chat_id": chat, "text": "🧪 Telegram OK - Bot is LIVE!"}, timeout=10)
        return f"Sent! {r.text}"
    except Exception as e:
        return f"Error {e}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
