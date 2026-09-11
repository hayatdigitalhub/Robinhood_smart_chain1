import requests

from config import Config

URL = "https://api.dexscreener.com/latest/dex/tokens/{}"
ROBINHOOD_DEXSCREENER_CHAIN = "robinhood"


def token_market_data(token):
    try:
        r = requests.get(URL.format(token), timeout=15)
        r.raise_for_status()
        pairs = r.json().get("pairs") or []

        # DexScreener's token endpoint can return pairs from multiple chains.
        # Only score the Robinhood Chain market, otherwise a token deployed on
        # another chain can leak unrelated liquidity/volume into the signal.
        pairs = [
            p for p in pairs
            if str(p.get("chainId", "")).lower() == ROBINHOOD_DEXSCREENER_CHAIN
        ]
        if not pairs:
            return {}

        pairs.sort(
            key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
            reverse=True,
        )
        p = pairs[0]
        q = p.get("txns", {}).get("h24", {})

        return {
            "has_market_data": True,
            "symbol": p.get("baseToken", {}).get("symbol", "UNKNOWN"),
            "liquidity": float((p.get("liquidity") or {}).get("usd") or 0),
            "volume24h": float((p.get("volume") or {}).get("h24") or 0),
            "market_cap": float(p.get("marketCap") or p.get("fdv") or 0),
            "buys24h": int(q.get("buys") or 0),
            "sells24h": int(q.get("sells") or 0),
            "pair_address": (p.get("pairAddress") or "").lower(),
        }
    except Exception:
        return {}
