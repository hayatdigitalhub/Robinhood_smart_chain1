import os
from dotenv import load_dotenv
from telegram_bot import TelegramBot
load_dotenv()
ok=TelegramBot(os.getenv("TELEGRAM_BOT_TOKEN",""),os.getenv("TELEGRAM_CHAT_ID","")).send(
    "✅ Robinhood Smart-Money Bot Telegram test successful.")
print("SUCCESS" if ok else "FAILED")
