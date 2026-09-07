import requests
URL="https://api.dexscreener.com/latest/dex/tokens/{}"

def token_market_data(token):
    try:
        r=requests.get(URL.format(token),timeout=15)
        if r.status_code!=200:return {}
        pairs=r.json().get("pairs") or []
        if not pairs:return {}
        pairs.sort(key=lambda p:float((p.get("liquidity") or {}).get("usd") or 0),reverse=True)
        p=pairs[0]
        q=p.get("txns",{}).get("h24",{})
        return {
            "symbol":p.get("baseToken",{}).get("symbol","UNKNOWN"),
            "liquidity":float((p.get("liquidity") or {}).get("usd") or 0),
            "volume24h":float((p.get("volume") or {}).get("h24") or 0),
            "market_cap":float(p.get("marketCap") or p.get("fdv") or 0),
            "buys24h":int(q.get("buys") or 0),
            "sells24h":int(q.get("sells") or 0)
        }
    except Exception:
        return {}
