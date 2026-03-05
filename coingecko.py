import requests

_BASE    = "https://api.coingecko.com/api/v3"
_HEADERS = {"User-Agent": "BTC-TradingBot/1.0"}
_TIMEOUT = 10

def fetch_btc_dominance() -> float | None:
    try:
        r = requests.get(f"{_BASE}/global", headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()["data"]["market_cap_percentage"].get("btc")
    except Exception:
        return None

def fetch_stablecoin_volumes() -> dict | None:
    try:
        r = requests.get(
            f"{_BASE}/coins/markets",
            headers=_HEADERS,
            timeout=_TIMEOUT,
            params={"vs_currency": "usd", "ids": "tether,usd-coin"},
        )
        r.raise_for_status()
        data = {coin["id"]: coin.get("total_volume") or 0 for coin in r.json()}
        usdt = data.get("tether", 0)
        usdc = data.get("usd-coin", 0)
        return {"usdt": usdt, "usdc": usdc, "combined": usdt + usdc}
    except Exception:
        return None

def fetch_top200_1h_changes() -> list | None:
    try:
        results = []
        for page in (1, 2):
            r = requests.get(
                f"{_BASE}/coins/markets",
                headers=_HEADERS,
                timeout=_TIMEOUT,
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": 100,
                    "page": page,
                    "price_change_percentage": "1h",
                },
            )
            r.raise_for_status()
            for coin in r.json():
                change = coin.get("price_change_percentage_1h_in_currency")
                if change is not None:
                    results.append({
                        "symbol":    coin["symbol"].upper(),
                        "name":      coin["name"],
                        "change_1h": change,
                        "price":     coin.get("current_price", 0),
                    })
        return results
    except Exception:
        return None
