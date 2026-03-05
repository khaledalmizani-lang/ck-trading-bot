import time
import ccxt
import config

_exchange:      ccxt.Exchange | None = None
_data_exchange: ccxt.Exchange | None = None

_RATE_LIMIT_MS   = 1000
_KUCOIN_RL_MS    = 200
_BACKOFF_SECONDS = 60
_MAX_RETRIES     = 3

_KUCOIN_SYM_MAP: dict[str, str] = {
    "POL/USDC": "POL/USDT",
    "SUI/USDC": "SUI/USDT",
    "SEI/USDC": "SEI/USDT",
}

def _kucoin_sym(symbol: str) -> str:
    return _KUCOIN_SYM_MAP.get(symbol, symbol)

def get_exchange() -> ccxt.Exchange:
    global _exchange
    if _exchange is None:
        exchange_class = getattr(ccxt, config.EXCHANGE)
        options: dict = {"enableRateLimit": True, "rateLimit": _RATE_LIMIT_MS}
        if config.API_KEY and config.API_SECRET:
            options["apiKey"] = config.API_KEY
            options["secret"] = config.API_SECRET
        _exchange = exchange_class(options)
    return _exchange

def get_data_exchange() -> ccxt.Exchange:
    global _data_exchange
    if _data_exchange is None:
        _data_exchange = ccxt.kucoin({"enableRateLimit": True, "rateLimit": _KUCOIN_RL_MS})
    return _data_exchange

def _call_with_backoff(fn, *args):
    last_exc = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn(*args)
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            last_exc = exc
            ts = time.strftime("%H:%M:%S", time.gmtime())
            print(f"[{ts}] [429 BACKOFF] attempt {attempt}/{_MAX_RETRIES} — waiting {_BACKOFF_SECONDS}s")
            time.sleep(_BACKOFF_SECONDS)
        except Exception:
            raise
    raise last_exc

def calculate_rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calculate_ema(closes: list, period: int = 200) -> float | None:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)

def calculate_atr(highs, lows, closes, period=14):
    n = len(closes)
    if n < period + 1 or len(highs) < n or len(lows) < n:
        return None
    true_ranges = []
    for i in range(1, n):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        true_ranges.append(tr)
    if len(true_ranges) < period:
        return None
    return sum(true_ranges[-period:]) / period

def calculate_adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period * 2 + 1 or len(highs) < n or len(lows) < n:
        return None
    plus_dm_raw, minus_dm_raw, tr_raw = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        plus_dm_raw.append(up if up > down and up > 0 else 0.0)
        minus_dm_raw.append(down if down > up and down > 0 else 0.0)
        tr_raw.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))

    def _wilder_sum(values, p):
        if len(values) < p:
            return []
        smoothed = [sum(values[:p])]
        for v in values[p:]:
            smoothed.append(smoothed[-1] - smoothed[-1]/p + v)
        return smoothed

    atr_s = _wilder_sum(tr_raw, period)
    pdm_s = _wilder_sum(plus_dm_raw, period)
    mdm_s = _wilder_sum(minus_dm_raw, period)
    min_len = min(len(atr_s), len(pdm_s), len(mdm_s))
    if min_len == 0:
        return None

    dx_values = []
    for i in range(min_len):
        if atr_s[i] == 0:
            continue
        pdi = 100.0 * pdm_s[i] / atr_s[i]
        mdi = 100.0 * mdm_s[i] / atr_s[i]
        di_sum = pdi + mdi
        if di_sum == 0:
            continue
        dx_values.append(100.0 * abs(pdi - mdi) / di_sum)

    if len(dx_values) < period:
        return None

    def _wilder_avg(values, p):
        if len(values) < p:
            return []
        smoothed = [sum(values[:p]) / p]
        for v in values[p:]:
            smoothed.append(smoothed[-1] - smoothed[-1]/p + v/p)
        return smoothed

    adx_s = _wilder_avg(dx_values, period)
    if not adx_s:
        return None
    return round(adx_s[-1], 2)

_MTF_TIMEFRAMES = ("15m", "1h", "4h", "1d")

def fetch_mtf_indicators(symbol: str) -> dict:
    exchange = get_data_exchange()
    ksym = _kucoin_sym(symbol)
    result = {}
    for tf in _MTF_TIMEFRAMES:
        try:
            ohlcv = _call_with_backoff(exchange.fetch_ohlcv, ksym, tf, None, 215)
            closes = [c[4] for c in ohlcv]
            result[tf] = {"rsi": calculate_rsi(closes[-50:]), "ema200": calculate_ema(closes, 200)}
        except Exception:
            result[tf] = {"rsi": None, "ema200": None}
    return result

def fetch_market_data(symbol: str) -> dict:
    cb_exchange = get_exchange()
    ticker = _call_with_backoff(cb_exchange.fetch_ticker, symbol)
    price = ticker["last"]
    quote_vol = ticker.get("quoteVolume") or 0
    base_vol = ticker.get("baseVolume") or 0
    if quote_vol > 0 and quote_vol >= price:
        volume = quote_vol
    elif base_vol > 0:
        volume = base_vol * price
    else:
        volume = quote_vol

    kex = get_data_exchange()
    ksym = _kucoin_sym(symbol)
    ohlcv = _call_with_backoff(kex.fetch_ohlcv, ksym, "15m", None, 350)

    highs = [c[2] for c in ohlcv]
    lows = [c[3] for c in ohlcv]
    closes = [c[4] for c in ohlcv]
    vols = [c[5] for c in ohlcv]

    rsi = calculate_rsi(closes[-50:])
    ema200 = calculate_ema(closes, 200)
    atr = calculate_atr(highs, lows, closes, 14)
    adx = calculate_adx(highs, lows, closes, 14)

    candle_volume = vols[-1] if vols else 0
    avg_volume_20 = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else 0
    volume_pct = (candle_volume / avg_volume_20 * 100) if avg_volume_20 > 0 else 0.0

    return {
        "price": price, "volume": round(volume, 2),
        "rsi": rsi, "ema200": ema200, "atr": atr, "adx": adx,
        "candle_volume": round(candle_volume, 4),
        "avg_volume_20": round(avg_volume_20, 4),
        "volume_pct": round(volume_pct, 1),
    }
