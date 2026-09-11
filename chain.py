import logging
import time
import requests
from web3 import Web3
from config import Config

TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()


class RobinhoodChain:
    """Robinhood Chain RPC client with Alchemy-first reads and public-RPC fallback."""

    def __init__(self):
        self.rpc_urls = []

        # Alchemy is the recommended production RPC for Robinhood Chain.
        # Never hard-code the user's key into source; construct the URL from the
        # existing environment variable at runtime.
        if Config.ALCHEMY_RPC_URL:
            self.rpc_urls.append(("alchemy", Config.ALCHEMY_RPC_URL))

        if Config.RH_RPC_URL and Config.RH_RPC_URL not in {
            url for _, url in self.rpc_urls
        }:
            self.rpc_urls.append(("public", Config.RH_RPC_URL))

        if not self.rpc_urls:
            raise RuntimeError("No Robinhood Chain RPC endpoint configured")

        self.w3 = Web3(
            Web3.HTTPProvider(self.rpc_urls[0][1], request_kwargs={"timeout": 20})
        )

    def rpc(self, method, params, retries=3, retry_delay=1.0):
        """Call JSON-RPC, retrying transient/null responses and failing over providers."""
        last_error = None

        for provider_name, url in self.rpc_urls:
            for attempt in range(1, retries + 1):
                try:
                    r = requests.post(
                        url,
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": method,
                            "params": params,
                        },
                        timeout=20,
                    )
                    r.raise_for_status()
                    data = r.json()

                    if "error" in data:
                        raise RuntimeError(data["error"])

                    result = data.get("result")

                    # A null receipt/transaction can simply mean the provider has
                    # not indexed the transaction yet. Give it a few short retries
                    # before failing over to the next provider.
                    if result is None and method in {
                        "eth_getTransactionReceipt",
                        "eth_getTransactionByHash",
                    }:
                        logging.warning(
                            "RPC %s returned null for %s (attempt %d/%d)",
                            provider_name,
                            method,
                            attempt,
                            retries,
                        )
                        if attempt < retries:
                            time.sleep(retry_delay)
                            continue

                    logging.info(
                        "RPC %s succeeded method=%s result=%s",
                        provider_name,
                        method,
                        "null" if result is None else "ok",
                    )
                    return result

                except Exception as exc:
                    last_error = exc
                    logging.warning(
                        "RPC %s failed method=%s attempt=%d/%d: %s",
                        provider_name,
                        method,
                        attempt,
                        retries,
                        exc,
                    )
                    if attempt < retries:
                        time.sleep(retry_delay)

            logging.warning("Falling back from RPC provider %s for %s", provider_name, method)

        if last_error:
            raise last_error
        return None

    def get_receipt(self, h):
        # Address Activity can arrive immediately around block inclusion. Retry
        # before declaring the receipt missing.
        return self.rpc("eth_getTransactionReceipt", [h], retries=5, retry_delay=1.0)

    def get_block(self, n):
        return self.rpc("eth_getBlockByNumber", [hex(n), False])

    def receipt_transfers(self, receipt):
        out = []
        for log in receipt.get("logs", []):
            topics = log.get("topics", [])
            if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC.lower():
                continue
            out.append({
                "token": log["address"].lower(),
                "from": "0x" + topics[1][-40:].lower(),
                "to": "0x" + topics[2][-40:].lower(),
                "amount_raw": int(topics[3], 16) if len(topics) > 3 else 0,
            })
        return out
