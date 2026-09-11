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
        event = payload.get("event") or {}
        activities = event.get("activity") or []
        # Alchemy Address Activity uses `hash` for the transaction hash.
        # Keep `transactionHash` as a compatibility fallback for older/custom payloads.
        tx_hashes = {
            (a.get("hash") or a.get("transactionHash"))
            for a in activities
            if (a.get("hash") or a.get("transactionHash"))
        }
        logging.info(
            "Alchemy event type=%s network=%s activities=%d tx_hashes=%d",
            payload.get("type"), event.get("network"), len(activities), len(tx_hashes)
        )
        if not tx_hashes:
            logging.info("Alchemy event contained no transaction hashes; nothing to process")
        count = 0
        activity_by_hash = {}
        for a in activities:
            h = a.get("hash") or a.get("transactionHash")
            if h:
                activity_by_hash.setdefault(h, []).append(a)

        for tx_hash in tx_hashes:
            try:
                count += int(bool(self.process_transaction(tx_hash, activity_by_hash.get(tx_hash, []))))
            except Exception:
                logging.exception("Failed transaction %s", tx_hash)
        return count

    def process_transaction(self, tx_hash, webhook_activities=None):
        logging.info("Processing transaction %s", tx_hash)
        webhook_activities = webhook_activities or []
        if webhook_activities:
            summary = [
                f"{a.get('category')}:{a.get('asset') or a.get('rawContract', {}).get('address') or 'native'}"
                for a in webhook_activities
            ]
            logging.info("Webhook activities for %s: %s", tx_hash, ", ".join(summary))

        receipt = self.chain.get_receipt(tx_hash)
        if not receipt:
            logging.warning("No receipt returned for transaction %s", tx_hash)
            return False
        if receipt.get("status") not in (None, "0x1"):
            logging.info("Skipping failed transaction %s (status=%s)", tx_hash, receipt.get("status"))
            return False

        # Get transaction metadata early.  tx.from is especially important for
        # native-ETH-funded swaps because ETH does not have an ERC20 Transfer log.
        tx = self.chain.rpc("eth_getTransactionByHash", [tx_hash]) or {}
        tx_from = (tx.get("from") or "").lower()
        native_value = int(tx.get("value", "0x0"), 16)

        transfers = self.chain.receipt_transfers(receipt)

        # Alchemy Address Activity is an indexed transfer feed. Prefer its token
        # records when available, but normalize several possible field locations.
        webhook_transfers = []
        activity_addresses = set()
        native_activities = []
        for a in webhook_activities:
            from_addr = (a.get("fromAddress") or a.get("from") or "").lower()
            to_addr = (a.get("toAddress") or a.get("to") or "").lower()
            if from_addr:
                activity_addresses.add(from_addr)
            if to_addr:
                activity_addresses.add(to_addr)

            category = str(a.get("category") or "").lower()
            asset = str(a.get("asset") or "").upper()
            if category in {"external", "internal", "eth"} or asset == "ETH":
                native_activities.append(a)

            if category not in {"token", "erc20"}:
                continue
            raw = a.get("rawContract") or {}
            token = (
                raw.get("address")
                or a.get("contractAddress")
                or a.get("address")
                or (a.get("log") or {}).get("address")
                or ""
            ).lower()
            if not token:
                logging.warning("Skipping Alchemy token activity with no token address: %s", a)
                continue

            raw_value = raw.get("rawValue")
            if raw_value is None:
                raw_value = a.get("rawValue")
            if raw_value is None:
                raw_value = "0x0"
            try:
                amount_raw = int(raw_value, 16) if isinstance(raw_value, str) else int(raw_value or 0)
            except (TypeError, ValueError):
                amount_raw = 0

            webhook_transfers.append({
                "token": token,
                "from": from_addr,
                "to": to_addr,
                "amount_raw": amount_raw,
                "source": "alchemy_webhook",
            })

        if webhook_transfers:
            transfers = webhook_transfers
            logging.info("Using %d token transfers directly from Alchemy Address Activity", len(transfers))
            for x in transfers:
                logging.info(
                    "Alchemy transfer token=%s from=%s to=%s amount_raw=%s",
                    x["token"], x["from"], x["to"], x["amount_raw"]
                )
        else:
            logging.info("Transaction %s contains %d ERC20 Transfer logs", tx_hash, len(transfers))

        if not transfers:
            if native_activities:
                logging.info(
                    "Transaction %s has %d native ETH activities; no token transfer to score",
                    tx_hash, len(native_activities)
                )
            return False

        block = int(receipt.get("blockNumber", "0x0"), 16)
        block_data = self.chain.get_block(block)
        ts = datetime.fromtimestamp(
            int(block_data.get("timestamp", "0x0"), 16), tz=timezone.utc
        ).isoformat()

        monitored = {a.lower(): meta for a, meta in Config.SMART_WALLETS.items()}

        # A monitored wallet can be identified from any of these sources.  This
        # is more robust than assuming only the ERC20 transfer endpoints expose
        # the wallet, which can fail with smart-account/router execution paths.
        candidate_wallets = set()
        if tx_from in monitored:
            candidate_wallets.add(tx_from)
        candidate_wallets.update(activity_addresses.intersection(monitored.keys()))
        for x in transfers:
            if x["from"] in monitored:
                candidate_wallets.add(x["from"])
            if x["to"] in monitored:
                candidate_wallets.add(x["to"])

        logging.info(
            "Wallet detection tx=%s tx_from=%s monitored_candidates=%s",
            tx_hash, tx_from, sorted(candidate_wallets)
        )

        touched_tokens = set()
        recorded = False

        for wallet in candidate_wallets:
            incoming = [
                x for x in transfers
                if x["to"] == wallet and x["token"] not in Config.QUOTE_ASSETS and int(x.get("amount_raw", 0)) > 0
            ]
            outgoing_quote = [
                x for x in transfers
                if x["from"] == wallet and x["token"] in Config.QUOTE_ASSETS and int(x.get("amount_raw", 0)) > 0
            ]

            quote_amount = sum(int(x.get("amount_raw", 0)) for x in outgoing_quote)

            # Native ETH can fund a buy even when the quote leg is not an ERC20
            # transfer. Count it only for the actual transaction sender.
            if tx_from == wallet and native_value > 0:
                quote_amount += native_value

            # If Alchemy delivered a native-ETH activity for this wallet, it is
            # additional evidence that the wallet participated in the transaction.
            # We do not invent an amount from the webhook; tx.value remains the
            # authoritative native amount when tx.from == wallet.

            logging.info(
                "Wallet analysis wallet=%s incoming=%d outgoing_quote=%d quote_raw=%s",
                wallet, len(incoming), len(outgoing_quote), quote_amount
            )

            if not incoming or quote_amount <= 0:
                continue

            logging.info(
                "BUY candidate wallet=%s token_count=%d quote_raw=%s tx=%s",
                wallet, len(incoming), quote_amount, tx_hash
            )
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

        logging.info(
            "Transaction %s recorded=%s touched_tokens=%d",
            tx_hash, recorded, len(touched_tokens)
        )
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
