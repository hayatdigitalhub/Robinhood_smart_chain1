import os
import sqlite3
import threading
from datetime import datetime, timezone


class Database:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.init()

    def connect(self):
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def init(self):
        with self.lock:
            c = self.connect()
            c.executescript("""
            CREATE TABLE IF NOT EXISTS wallets(
              address TEXT PRIMARY KEY,label TEXT,quality REAL DEFAULT 50,
              buys INTEGER DEFAULT 0,wins INTEGER DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS trades(
              id INTEGER PRIMARY KEY AUTOINCREMENT,tx_hash TEXT,wallet TEXT,token TEXT,
              token_amount TEXT,quote_amount TEXT,block_number INTEGER,timestamp TEXT,side TEXT,raw_json TEXT);
            CREATE TABLE IF NOT EXISTS alerts(
              id INTEGER PRIMARY KEY AUTOINCREMENT,token TEXT,score REAL,level TEXT,
              wallets TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS idx_trades_token ON trades(token);
            CREATE INDEX IF NOT EXISTS idx_trades_token_time ON trades(token,timestamp);
            """)

            # Older V1 builds could have had a UNIQUE constraint/index on tx_hash.
            # Rebuild the table if a single-column unique tx_hash index is present.
            unique_tx_hash = False
            for idx in c.execute("PRAGMA index_list(trades)").fetchall():
                # PRAGMA columns: seq, name, unique, origin, partial
                if not idx[2]:
                    continue
                name = idx[1]
                cols = [row[2] for row in c.execute(f'PRAGMA index_info("{name}")').fetchall()]
                if cols == ["tx_hash"]:
                    unique_tx_hash = True
                    break

            if unique_tx_hash:
                c.execute("ALTER TABLE trades RENAME TO trades_v1")
                c.execute("""
                    CREATE TABLE trades(
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      tx_hash TEXT,wallet TEXT,token TEXT,token_amount TEXT,
                      quote_amount TEXT,block_number INTEGER,timestamp TEXT,
                      side TEXT,raw_json TEXT
                    )
                """)
                c.execute("""
                    INSERT INTO trades
                    (id,tx_hash,wallet,token,token_amount,quote_amount,block_number,timestamp,side,raw_json)
                    SELECT id,tx_hash,wallet,token,token_amount,quote_amount,block_number,timestamp,side,raw_json
                    FROM trades_v1
                """)
                c.execute("DROP TABLE trades_v1")

            c.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_identity
                ON trades(tx_hash,wallet,token,side)
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_trades_token ON trades(token)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_trades_token_time ON trades(token,timestamp)")
            c.commit()
            c.close()

    def upsert_wallet(self, address, label, quality):
        with self.lock:
            c = self.connect()
            c.execute("""INSERT INTO wallets(address,label,quality) VALUES(?,?,?)
                         ON CONFLICT(address) DO UPDATE SET label=excluded.label,quality=excluded.quality""",
                      (address.lower(), label, quality))
            c.commit()
            c.close()

    def get_wallet(self, address):
        c = self.connect()
        r = c.execute("SELECT * FROM wallets WHERE address=?", (address.lower(),)).fetchone()
        c.close()
        return r

    def add_trade(self, tx_hash, wallet, token, token_amount, quote_amount, block, ts, side, raw):
        with self.lock:
            c = self.connect()
            c.execute("""INSERT OR IGNORE INTO trades
                         (tx_hash,wallet,token,token_amount,quote_amount,block_number,timestamp,side,raw_json)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      (tx_hash,wallet.lower(),token.lower(),str(token_amount),str(quote_amount),block,ts,side,raw))
            c.commit()
            c.close()

    def token_wallets(self, token, since=None):
        c = self.connect()
        if since:
            rows = c.execute(
                """SELECT DISTINCT wallet FROM trades
                   WHERE token=? AND side='BUY' AND timestamp>=?""",
                (token.lower(), since),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT DISTINCT wallet FROM trades WHERE token=? AND side='BUY'",
                (token.lower(),),
            ).fetchall()
        c.close()
        return [r["wallet"] for r in rows]

    def recent_alert(self, token, minutes):
        c = self.connect()
        r = c.execute("SELECT created_at FROM alerts WHERE token=? ORDER BY id DESC LIMIT 1",
                      (token.lower(),)).fetchone()
        c.close()
        if not r:
            return False
        try:
            last = datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - last).total_seconds() < minutes * 60
        except (TypeError, ValueError):
            return False

    def add_alert(self, token, score, level, wallets):
        with self.lock:
            c = self.connect()
            c.execute("INSERT INTO alerts(token,score,level,wallets) VALUES(?,?,?,?)",
                      (token.lower(),score,level,",".join(wallets)))
            c.commit()
            c.close()
