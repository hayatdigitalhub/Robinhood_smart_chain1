from config import Config
from database import Database
db=Database(Config.DB_PATH)
for a,m in Config.SMART_WALLETS.items():
    db.upsert_wallet(a,m["label"],m["quality"])
print("Seeded",len(Config.SMART_WALLETS),"wallets.")
