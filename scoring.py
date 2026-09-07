def score_signal(wallets, market):
    quality=min(30,sum(float(w["quality"]) for w in wallets)/3)
    convergence=min(20,len(wallets)*7)
    early=min(15,sum(float(w["quality"]) for w in wallets)/max(1,len(wallets))*.15)
    liq=float(market.get("liquidity") or 0)
    vol=float(market.get("volume24h") or 0)
    mc=float(market.get("market_cap") or 0)
    buys=float(market.get("buys24h") or 0)
    sells=float(market.get("sells24h") or 0)
    lp=10 if liq>=100000 else 7 if liq>=50000 else 4 if liq>=20000 else 1
    vp=10 if vol>=1000000 else 7 if vol>=250000 else 4 if vol>=50000 else 1
    hp=5 if buys>sells*1.25 else 3 if buys>sells else 1
    mp=5 if 100000<=mc<=5000000 else 3 if mc<=20000000 else 0
    risk=(10 if liq<10000 else 6 if liq<20000 else 0)+(5 if liq and vol/liq>100 else 0)
    final=max(0,min(100,quality+convergence+early+lp+vp+hp+mp-risk))
    level="STRONG CONVERGENCE" if final>=85 else "CONVERGENCE" if final>=70 else "WATCH" if final>=50 else "IGNORE"
    return round(final,1),level,{"risk_penalty":risk}
