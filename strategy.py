import config
from analyzer import get_rsi_thresholds

_MTF_ORDER = ("15m", "1h", "4h", "1d")
_MTF_DISPLAY = {"15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}

def check_signal(price: float, rsi: float | None, ema200: float | None) -> str:
    rsi_buy_max, rsi_sell_min = get_rsi_thresholds()
    if rsi is None:
        return "HOLD"
    if rsi <= rsi_buy_max:
        if ema200 is None or price > ema200:
            return "BUY"
        return "TREND_BLOCK_BUY"
    elif rsi >= rsi_sell_min:
        return "SELL"
    return "HOLD"

def _tf_confirms(price, rsi, ema200, direction, rsi_buy_max, rsi_sell_min):
    if rsi is None:
        return False
    if direction == "BUY":
        return rsi <= rsi_buy_max and (ema200 is None or price > ema200)
    else:
        return rsi >= rsi_sell_min

def evaluate_mtf(price, tf_data, direction):
    rsi_buy_max, rsi_sell_min = get_rsi_thresholds()
    count, labels = 0, {}
    for tf in _MTF_ORDER:
        d = tf_data.get(tf, {})
        ok = _tf_confirms(price, d.get("rsi"), d.get("ema200"), direction, rsi_buy_max, rsi_sell_min)
        labels[_MTF_DISPLAY[tf]] = "✅" if ok else "⚠️"
        if ok:
            count += 1
    return count, labels

def tf_labels_to_str(tf_labels):
    return " | ".join(f"{tf} {lbl}" for tf, lbl in tf_labels.items())
