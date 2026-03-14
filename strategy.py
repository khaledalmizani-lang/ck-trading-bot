"""
CK Crypto Bot — Strategy
MTF + EMA 9/21/50 + RSI + MACD + ATR
BUY فقط (Binance Spot)
"""
import config
import binance_client as bc


def calc_ema(closes: list, period: int) -> float | None:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 8)


def calc_rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-i] - closes[-i - 1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)


def calc_macd(closes: list) -> dict | None:
    fast, slow, sig = config.MACD_FAST, config.MACD_SLOW, config.MACD_SIG
    if len(closes) < slow + sig:
        return None
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    if not ema_fast or not ema_slow:
        return None
    macd_line = ema_fast - ema_slow
    macd_values = []
    for i in range(slow, len(closes)):
        ef = calc_ema(closes[:i+1], fast)
        es = calc_ema(closes[:i+1], slow)
        if ef and es:
            macd_values.append(ef - es)
    if len(macd_values) < sig:
        return None
    signal_line = calc_ema(macd_values, sig)
    histogram = macd_line - (signal_line or 0)
    return {"macd": macd_line, "signal": signal_line, "histogram": round(histogram, 8)}


def calc_atr(candles: list, period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i-1]["close"]),
            abs(candles[i]["low"] - candles[i-1]["close"]),
        )
        trs.append(tr)
    return round(sum(trs[-period:]) / period, 8)


def detect_trend(closes: list) -> str:
    ema9  = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)
    if not all([ema9, ema21, ema50]):
        return "SIDEWAYS"
    price = closes[-1]
    if price > ema9 > ema21 > ema50:
        return "UP"
    elif price < ema9 < ema21 < ema50:
        return "DOWN"
    return "SIDEWAYS"


def analyze_timeframe(candles: list) -> dict:
    if len(candles) < 60:
        return {"signal": "HOLD", "confirmations": 0, "trend": "SIDEWAYS"}

    closes = [c["close"] for c in candles]
    price  = closes[-1]

    ema9  = calc_ema(closes, config.EMA_FAST)
    ema21 = calc_ema(closes, config.EMA_MID)
    ema50 = calc_ema(closes, config.EMA_SLOW)
    rsi   = calc_rsi(closes, config.RSI_PERIOD)
    macd  = calc_macd(closes)
    atr   = calc_atr(candles, config.ATR_PERIOD)
    trend = detect_trend(closes)

    if not all([ema9, ema21, ema50, rsi, macd]):
        return {"signal": "HOLD", "confirmations": 0, "trend": trend}

    confirms = 0

    # EMA9 فوق EMA21
    if ema9 > ema21:
        confirms += 1

    # السعر فوق EMA50
    if price > ema50:
        confirms += 1

    # RSI oversold
    if rsi <= config.RSI_BUY:
        confirms += 1

    # MACD histogram موجب
    if macd["histogram"] > 0:
        confirms += 1

    # الاتجاه صاعد
    if trend == "UP":
        confirms += 1

    signal = "BUY" if confirms >= config.MIN_CONFIRMATIONS else "HOLD"

    return {
        "signal":        signal,
        "confirmations": confirms,
        "trend":         trend,
        "ema9":          ema9,
        "ema21":         ema21,
        "ema50":         ema50,
        "rsi":           rsi,
        "macd":          macd,
        "atr":           atr,
        "price":         price,
    }


def check_signal(symbol: str) -> dict:
    """يحلل الرمز عبر 3 timeframes"""
    result = {
        "signal": "HOLD", "reason": "",
        "rsi": None, "atr": None,
        "confirmations": 0, "mtf_signals": {},
    }

    analyses = {}
    for tf in config.MTF_TIMEFRAMES:
        candles = bc.get_candles(symbol, tf, limit=150)
        if not candles:
            result["reason"] = f"No candles {symbol} {tf}"
            return result
        analyses[tf] = analyze_timeframe(candles)

    result["mtf_signals"] = {tf: a["signal"] for tf, a in analyses.items()}

    # لازم الـ 3 كلهم BUY
    all_buy = all(a["signal"] == "BUY" for a in analyses.values())

    if all_buy:
        main = analyses["5m"]
        result["signal"]        = "BUY"
        result["reason"]        = f"MTF BUY ✅ | RSI:{main['rsi']} | {main['trend']}"
        result["rsi"]           = main["rsi"]
        result["atr"]           = main["atr"]
        result["confirmations"] = main["confirmations"]
    else:
        signals_str = " | ".join([f"{tf}:{a['signal']}" for tf, a in analyses.items()])
        result["reason"] = f"MTF: {signals_str}"

    return result


def check_exit(trade: dict, current_price: float) -> str | None:
    """يتحقق هل نغلق الصفقة"""
    entry = trade["entry_price"]
    tp    = entry * (1 + config.TAKE_PROFIT_PCT / 100)
    sl    = entry * (1 - config.STOP_LOSS_PCT / 100)

    if current_price >= tp:
        return "TP"
    if current_price <= sl:
        return "SL"
    return None
