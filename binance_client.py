"""
CK Crypto Bot — Binance Client
Binance Spot API
"""
import time
import hmac
import hashlib
import urllib.request
import urllib.parse
import json
import config

BASE_URL = "https://api.binance.com"


def _sign(params: dict) -> str:
    query = urllib.parse.urlencode(params)
    return hmac.new(config.BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()


def _get(path: str, params: dict = None, signed: bool = False) -> dict:
    params = params or {}
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = _sign(params)
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-MBX-APIKEY": config.BINANCE_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[BINANCE] GET error {path}: {e}")
        return {}


def _post(path: str, params: dict) -> dict:
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = _sign(params)
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        BASE_URL + path, data=data,
        headers={"X-MBX-APIKEY": config.BINANCE_API_KEY},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[BINANCE] POST error {path}: {e}")
        return {}


def _delete(path: str, params: dict) -> dict:
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = _sign(params)
    url = BASE_URL + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"X-MBX-APIKEY": config.BINANCE_API_KEY},
        method="DELETE"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[BINANCE] DELETE error {path}: {e}")
        return {}


def get_balance(asset: str = "USDT") -> float:
    resp = _get("/api/v3/account", signed=True)
    balances = resp.get("balances", [])
    for b in balances:
        if b["asset"] == asset:
            return float(b["free"])
    return 0.0


def get_price(symbol: str) -> float | None:
    resp = _get("/api/v3/ticker/price", {"symbol": symbol})
    price = resp.get("price")
    return float(price) if price else None


def get_candles(symbol: str, interval: str, limit: int = 150) -> list:
    """interval: 1m, 5m, 15m, 1h, 4h, 1d"""
    data = _get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    if not data or not isinstance(data, list):
        return []
    return [{"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])} for c in data]


def get_symbol_info(symbol: str) -> dict | None:
    resp = _get("/api/v3/exchangeInfo", {"symbol": symbol})
    symbols = resp.get("symbols", [])
    if symbols:
        return symbols[0]
    return None


def calculate_qty(symbol: str, usdt_amount: float, price: float) -> float:
    """يحسب الكمية بناءً على المبلغ والسعر"""
    info = get_symbol_info(symbol)
    if not info:
        return 0.0
    # جلب stepSize
    step_size = 0.001
    for f in info.get("filters", []):
        if f["filterType"] == "LOT_SIZE":
            step_size = float(f["stepSize"])
            break
    qty = usdt_amount / price
    # تقريب للـ stepSize
    precision = len(str(step_size).rstrip("0").split(".")[-1]) if "." in str(step_size) else 0
    qty = round(qty // step_size * step_size, precision)
    return qty


def buy_market(symbol: str, usdt_amount: float) -> dict | None:
    """شراء بالسوق"""
    price = get_price(symbol)
    if not price:
        return None
    qty = calculate_qty(symbol, usdt_amount, price)
    if qty <= 0:
        print(f"[BINANCE] qty=0 for {symbol}")
        return None
    resp = _post("/api/v3/order", {
        "symbol":   symbol,
        "side":     "BUY",
        "type":     "MARKET",
        "quantity": qty,
    })
    if "orderId" in resp:
        print(f"[BINANCE] ✅ BUY {symbol} qty:{qty} @ ~{price}")
        return {"order_id": resp["orderId"], "qty": qty, "entry_price": price, "symbol": symbol}
    print(f"[BINANCE] ❌ BUY failed {symbol}: {resp}")
    return None


def sell_market(symbol: str, qty: float) -> dict | None:
    """بيع بالسوق"""
    price = get_price(symbol)
    resp = _post("/api/v3/order", {
        "symbol":   symbol,
        "side":     "SELL",
        "type":     "MARKET",
        "quantity": qty,
    })
    if "orderId" in resp:
        print(f"[BINANCE] ✅ SELL {symbol} qty:{qty} @ ~{price}")
        return {"order_id": resp["orderId"], "qty": qty, "exit_price": price}
    print(f"[BINANCE] ❌ SELL failed {symbol}: {resp}")
    return None


def get_open_orders(symbol: str = None) -> list:
    params = {}
    if symbol:
        params["symbol"] = symbol
    return _get("/api/v3/openOrders", params, signed=True) or []
