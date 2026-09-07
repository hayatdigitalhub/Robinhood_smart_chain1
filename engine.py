import json, logging
from datetime import datetime, timezone
from config import Config
from chain import RobinhoodChain
from market_data import token_market_data
from scoring import score_signal

class SmartMoneyEngine:
    def __init__(self, db, telegram):
        self.db=db
        self.telegram=telegram
        self.chain=RobinhoodChain()
        for a,m in Config.SMART_WALLETS.items():
            db.upsert_wallet(a,m["label"],m["quality"])

    def process_alchemy_event(self,payload):
        activities=(payload.get("event") or {}).get("activity") or []
        txs={a.get("transactionHash") for a in activities if a.get("transactionHash")}
        count=0
        for h in txs:
            try:
                count += int(bool(self.process_transaction(h)))
            except Exception:
                logging.exception("Failed transaction %s",h)
        return count

    def process_transaction(self,h):
        receipt=self.chain.get_receipt(h)
        if not receipt:return False
        transfers=self.chain.receipt_transfers(receipt)
        if not transfers:return False
        block=int(receipt.get("blockNumber","0x0"),16)
        b=self.chain.get_block(block)
        ts=datetime.fromtimestamp(int(b.get("timestamp","0x0"),16),tz=timezone.utc).isoformat()
        tx=self.chain.rpc("eth_getTransactionByHash",[h])
        native=int(tx.get("value","0x0"),16) if tx else 0

        for wallet in Config.SMART_WALLETS:
            incoming=[x for x in transfers if x["to"]==wallet and x["token"] not in Config.QUOTE_ASSETS]
            outgoing=[x for x in transfers if x["from"]==wallet and x["token"] in Config.QUOTE_ASSETS]
            if native: outgoing.append({"amount_raw":native})
            for t in incoming:
                self.db.add_trade(h,wallet,t["token"],t["amount_raw"],
                                  sum(x.get("amount_raw",0) for x in outgoing),
                                  block,ts,"BUY",json.dumps(t))
                self.evaluate_token(t["token"])
        return True

    def evaluate_token(self,token):
        addresses=self.db.token_wallets(token)
        if len(addresses)<Config.MIN_CONVERGENCE:return
        wallets=[self.db.get_wallet(a) for a in addresses]
        wallets=[w for w in wallets if w]
        if len(wallets)<Config.MIN_CONVERGENCE:return
        market=token_market_data(token)
        score,level,parts=score_signal(wallets,market)
        if level=="IGNORE" or score<Config.ALERT_SCORE:return
        if self.db.recent_alert(token,Config.COOLDOWN_MINUTES):return
        labels=[f"{w['label']} ({w['address'][:8]}…{w['address'][-6:]})" for w in wallets]
        text=(f"🚨 {level}\n\nToken: ${market.get('symbol',token[:8])}\n"
              f"Contract: {token}\n\nSmart wallets: {len(wallets)}\n"+
              "\n".join("🟢 "+x for x in labels)+
              f"\n\nScore: {score}/100\nLiquidity: ${market.get('liquidity',0):,.0f}\n"
              f"24h volume: ${market.get('volume24h',0):,.0f}\n"
              f"Market cap: ${market.get('market_cap',0):,.0f}\n"
              f"Buys/Sells: {market.get('buys24h',0)}/{market.get('sells24h',0)}\n"
              f"Risk penalty: {parts['risk_penalty']}\nMode: {Config.MODE.upper()}\n\n"
              "⚠️ Research signal only — not financial advice.")
        self.db.add_alert(token,score,level,addresses)
        self.telegram.send(text)
