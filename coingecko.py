import requests
import time
import threading

_BASE    = "https://api.coingecko.com/api/v3"
_HEADERS = {"User-Agent": "CK-TradingBot/2.0"}
_TIMEOUT = 15

# ── Dynamic symbol list ───────────────────────────────────────────────────────
_dynamic_symbols: list[str] = []
_symbols_lock = threading.Lock()
_last_fetch_ts: float = 0.0
_REFRESH_INTERVAL = 21600  # 6 hours

# Stablecoins and wrapped tokens to exclude
_EXCLUDE = {
    "USDT","USDC","BUSD","DAI","TUSD","USDP","USDD","FDUSD","PYUSD",
    "WBTC","WETH","WBNB","STETH","WSTETH","CBETH","RETH",
    "LEO","CRO",
}

def fetch_top30_symbols(limit: int = 30) -> list[str]:
    """Fetch top coins by market cap from CoinGecko, return as Binance USDT pairs."""
    try:
        r = requests.get(
            f"{_BASE}/coins/markets",
            headers=_HEADERS,
            timeout=_TIMEOUT,
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 100,
                "page": 1,
                "price_change_percentage": "1h",
            },
        )
        r.raise_for_status()
        symbols = []
        for coin in r.json():
            sym = coin["symbol"].upper()
            if sym in _EXCLUDE:
                continue
            # Must have meaningful volume
            vol = coin.get("total_volume") or 0
            if vol < 10_000_000:  # min $10M daily volume
                continue
            symbols.append(f"{sym}/USDT")
            if len(symbols) >= limit:
                break
        return symbols
    except Exception as e:
        print(f"[COINGECKO] fetch_top30 error: {e}")
        return []

def get_dynamic_symbols(limit: int = 30) -> list[str]:
    """Return cached symbol list, refresh every 6 hours."""
    global _dynamic_symbols, _last_fetch_ts
    now = time.time()
    with _symbols_lock:
        if now - _last_fetch_ts >= _REFRESH_INTERVAL or not _dynamic_symbols:
            fresh = fetch_top30_symbols(limit)
            if fresh:
                _dynamic_symbols = fresh
                _last_fetch_ts = now
                print(f"[COINGECKO] Updated top {len(fresh)} symbols: {', '.join(s.replace('/USDT','') for s in fresh)}")
            elif not _dynamic_symbols:
                # Fallback list if CoinGecko is down
                _dynamic_symbols = [
                    "BTC/USDT","ETH/USDT","BNB/USDT","SOL/USDT","XRP/USDT",
                    "DOGE/USDT","ADA/USDT","AVAX/USDT","LINK/USDT","DOT/USDT",
                    "MATIC/USDT","UNI/USDT","LTC/USDT","BCH/USDT","ATOM/USDT",
                    "XLM/USDT","NEAR/USDT","APT/USDT","ICP/USDT","FIL/USDT",
                    "HBAR/USDT","VET/USDT","ALGO/USDT","SAND/USDT","MANA/USDT",
                    "AAVE/USDT","GRT/USDT","EOS/USDT","XTZ/USDT","THETA/USDT",
                ]
                print(f"[COINGECKO] Using fallback symbol list ({len(_dynamic_symbols)} coins)")
        return list(_dynamic_symbols)

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

def fetch_top50_1h_changes() -> list | None:
    """Top 50 coins by market cap with 1h price change — for pump alerts."""
    try:
        r = requests.get(
            f"{_BASE}/coins/markets",
            headers=_HEADERS,
            timeout=_TIMEOUT,
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 50,
                "page": 1,
                "price_change_percentage": "1h",
            },
        )
        r.raise_for_status()
        results = []
        for coin in r.json():
            sym = coin["symbol"].upper()
            if sym in _EXCLUDE:
                continue
            change = coin.get("price_change_percentage_1h_in_currency")
            if change is not None:
                results.append({
                    "symbol":    sym,
                    "name":      coin["name"],
                    "change_1h": change,
                    "price":     coin.get("current_price", 0),
                    "volume":    coin.get("total_volume", 0),
                })
        return results
    except Exception:
        return None
