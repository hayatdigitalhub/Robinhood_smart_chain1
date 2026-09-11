import json
import logging
from datetime import datetime, timezone, timedelta

from config import Config
from chain import RobinhoodChain
from market_data import token_market_data
from scoring import score_signal


class SmartMoneyEngine:
    def __init__(self, db, telegram):
        self.db = db
        self.telegram = telegram
        self.chain = RobinhoodChain()
        for address, meta in Config.SMART_WALLETS.items():
            db.upsert_wallet(address, meta["label"], meta["quality"])

    def process_alchemy_event(self, payload):
        activities = (payload.get("event") or {}).get("activity") or []
        tx_hashes = {a.get("transactionHash") for a in activities if a.get("transactionHash")}
        count = 0
        for tx_hash in tx_hashes:
            try:
                count += int(bool(self.process_transaction(tx_hash)))
            except Exception:
                logging.exception("Failed transaction %s", tx_hash)
        return count

    def process_transaction(self, tx_hash):
        receipt = self.chain.get_receipt(tx_hash)
        if not receipt:
            return False

        transfers = self.chain.receipt_transfers(receipt)
        if not transfers:
            return False

        block = int(receipt.get("blockNumber", "0x0"), 16)
        block_data = self.chain.get_block(block)
        ts = datetime.fromtimestamp(
            int(block_data.get("timestamp", "0x0"), 16), tz=timezone.utc
        ).isoformat()

        tx = self.chain.rpc("eth_getTransactionByHash", [tx_hash]) or {}
        tx_from = (tx.get("from") or "").lower()
        native_value = int(tx.get("value", "0x0"), 16)

        touched_tokens = set()
        recorded = False

        # A buy must have BOTH:
        #   1) tokens transferred into the smart wallet, and
        #   2) quote/native value sent out by that same wallet.
        for wallet in Config.SMART_WALLETS:
            wallet = wallet.lower()
            incoming = [
                x for x in transfers
                if x["to"] == wallet and x["token"] not in Config.QUOTE_ASSETS
            ]
            outgoing_quote = [
                x for x in transfers
                if x["from"] == wallet and x["token"] in Config.QUOTE_ASSETS
            ]

            quote_amount = sum(int(x.get("amount_raw", 0)) for x in outgoing_quote)

            # Native value belongs to the transaction sender, not every wallet
            # touched by the transaction.
            if tx_from == wallet and native_value > 0:
                quote_amount += native_value

            if not incoming or quote_amount <= 0:
                continue

            for transfer in incoming:
                self.db.add_trade(
                    tx_hash,
                    wallet,
                    transfer["token"],
                    transfer["amount_raw"],
                    quote_amount,
                    block,
                    ts,
                    "BUY",
                    json.dumps(transfer),
                )
                touched_tokens.add(transfer["token"])
                recorded = True

        # Evaluate only after every wallet/trade in this transaction has been
        # recorded, so convergence is calculated from the complete event.
        for token in touched_tokens:
            try:
                self.evaluate_token(token, reference_time=ts)
            except Exception:
                logging.exception("Failed evaluating token %s", token)

        return recorded

    def evaluate_token(self, token, reference_time=None):
        token = token.lower()
        if reference_time:
            try:
                ref = datetime.fromisoformat(reference_time.replace("Z", "+00:00"))
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
            except ValueError:
                ref = datetime.now(timezone.utc)
        else:
            ref = datetime.now(timezone.utc)
        since = (ref - timedelta(minutes=Config.CONVERGENCE_WINDOW_MINUTES)).isoformat()
        addresses = self.db.token_wallets(token, since=since)
        if len(addresses) < Config.MIN_CONVERGENCE:
            return False

        wallets = [self.db.get_wallet(a) for a in addresses]
        wallets = [w for w in wallets if w]
        if len(wallets) < Config.MIN_CONVERGENCE:
            return False

        market = token_market_data(token)
        # Missing market data must never produce an alert from wallet scores alone.
        if not market or not market.get("has_market_data"):
            logging.warning("No valid market data for token %s; skipping alert", token)
            return False

        score, level, parts = score_signal(wallets, market)
        if level == "IGNORE" or score < Config.ALERT_SCORE:
            return False
        if self.db.recent_alert(token, Config.COOLDOWN_MINUTES):
            return False

        labels = [
            f"{w['label']} ({w['address'][:8]}…{w['address'][-6:]})"
            for w in wallets
        ]
        text = (
            f"🚨 {level}\n\n"
            f"Token: ${market.get('symbol', token[:8])}\n"
            f"Contract: {token}\n\n"
            f"Smart wallets: {len(wallets)}\n"
            + "\n".join("🟢 " + x for x in labels)
            + f"\n\nScore: {score}/100\n"
            f"Liquidity: ${market.get('liquidity', 0):,.0f}\n"
            f"24h volume: ${market.get('volume24h', 0):,.0f}\n"
            f"Market cap: ${market.get('market_cap', 0):,.0f}\n"
            f"Buys/Sells: {market.get('buys24h', 0)}/{market.get('sells24h', 0)}\n"
            f"Risk penalty: {parts['risk_penalty']}\n"
            f"Mode: {Config.MODE.upper()}\n\n"
            "⚠️ Research signal only — not financial advice."
        )
        self.db.add_alert(token, score, level, addresses)
        self.telegram.send(text)
        return True
