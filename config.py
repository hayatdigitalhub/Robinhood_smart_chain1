import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    MODE = os.getenv("MODE", "paper")
    RH_CHAIN_ID = int(os.getenv("RH_CHAIN_ID", "4663"))
    RH_RPC_URL = os.getenv("RH_RPC_URL", "https://rpc.mainnet.chain.robinhood.com")
    ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "")
    ALCHEMY_WEBHOOK_SIGNING_KEY = os.getenv("ALCHEMY_WEBHOOK_SIGNING_KEY", "")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    DB_PATH = os.getenv("DB_PATH", "data/smart_money.db")
    MIN_CONVERGENCE = int(os.getenv("MIN_CONVERGENCE", "2"))
    ALERT_SCORE = float(os.getenv("ALERT_SCORE", "70"))
    STRONG_SCORE = float(os.getenv("STRONG_SCORE", "85"))
    COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "60"))
    QUOTE_ASSETS = {x.strip().lower() for x in os.getenv(
        "QUOTE_ASSETS",
        "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73,0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
    ).split(",") if x.strip()}

    SMART_WALLETS = {
        "0x7e3ba68c49561aae7c23c1d20fef0f1d7615a3ad": {"label":"Benchmark CASHCAT/PONS wallet","quality":95},
        "0xeee29d1a6fa5873065ad8789c6e15231b48318a0": {"label":"Early CASHCAT wallet","quality":90},
        "0xfa19f4bc05bc059d2384ae2792a3b0bcb1dc06e1": {"label":"CASHCAT active wallet","quality":82},
        "0x3d731e31ca544cb7c0ee908880e48789f0139529": {"label":"Active research wallet","quality":70},
        "0xd6e884a6948fe91bafb3be7d0d485a2feb9e01bb": {"label":"Active research wallet","quality":70}
    }
