import os, hmac, hashlib, logging
from flask import Flask, request, jsonify
from config import Config
from database import Database
from engine import SmartMoneyEngine
from telegram_bot import TelegramBot

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
db = Database(Config.DB_PATH)
telegram = TelegramBot(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)
engine = SmartMoneyEngine(db, telegram)

def verify_signature(raw, sig):
    if not Config.ALCHEMY_WEBHOOK_SIGNING_KEY:
        return True
    digest = hmac.new(Config.ALCHEMY_WEBHOOK_SIGNING_KEY.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig or "")

@app.get("/")
def home():
    return jsonify(service="Robinhood Chain Smart-Money Engine", status="online", mode=Config.MODE)

@app.get("/health")
def health():
    return jsonify(ok=True, mode=Config.MODE)

@app.post("/webhook/alchemy")
def alchemy_webhook():
    raw = request.get_data()
    signature = request.headers.get("X-Alchemy-Signature", "")
    if not verify_signature(raw, signature):
        logging.warning("Rejected Alchemy webhook: invalid signature")
        return jsonify(ok=False, error="invalid signature"), 401
    try:
        payload = request.get_json(silent=True) or {}
        event = payload.get("event") or {}
        activities = event.get("activity") or []
        logging.info(
            "Alchemy webhook received type=%s network=%s activities=%d",
            payload.get("type"), event.get("network"), len(activities)
        )
        processed = engine.process_alchemy_event(payload)
        logging.info("Alchemy webhook completed processed=%d", processed)
        return jsonify(ok=True, processed=processed)
    except Exception:
        logging.exception("Webhook processing failed")
        return jsonify(ok=False, error="processing failure"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
