# Robinhood Chain Smart-Money Convergence Bot V1

Paper/research-only monitoring engine. It has NO private key and cannot trade.

## Local
python -m venv .venv
Windows: .venv\\Scripts\\activate
macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example to .env and fill in credentials.
python seed_wallets.py
python app.py

## Production
gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 4 app:app

## Alchemy
Create a Robinhood Mainnet Address Activity webhook and add the five wallets listed in config.py.
Webhook URL: https://YOUR-HOST/webhook/alchemy

## Telegram
Create a bot with @BotFather, send /start to it, obtain your chat ID, then set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.

## Render
Push this folder to GitHub, create a Render Web Service from the repository, add environment variables, deploy, then use:
https://YOUR-SERVICE.onrender.com/webhook/alchemy
as the Alchemy webhook.

## V1 limitations
Wallet reputation is seeded research data. Buy classification uses transfer patterns. Holder growth is a proxy. V2 should add historical backtesting, learned early-entry scores, liquidity-change detection, holder growth, contract risk analysis, wallet clustering, and richer DEX/launchpad decoding.
