import config
from analyzer import get_rsi_thresholds

_MTF_ORDER   = ("15m", "1h", "4h", "1d")
_MTF_DISPLAY = {"15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}


def check_signal(price: float, rsi: float | None, ema200: float | None,
                 macd_hist: float | None = None,
                 stoch_k: float | None = None,
                 stoch_d: float | None = None) -> str:
    """
    Signal logic:
      BUY:  RSI ≤ threshold  +  price > EMA200  +  MACD hist rising (optional)  +  StochRSI < 20 (optional)
      SELL: RSI ≥ threshold  +  MACD hist falling (optional)  +  StochRSI > 80 (optional)

    Extra indicators act as confirmations (score-based), not hard blockers,
    so the bot still signals even if MACD/Stoch data is unavailable.
    """
    rsi_buy_max, rsi_sell_min = get_rsi_thresholds()

    if rsi is None:
        return "HOLD"

    # ── BUY ──────────────────────────────────────────────────────────────────
    if rsi <= rsi_buy_max:
        if ema200 is not None and price <= ema200:
            return "TREND_BLOCK_BUY"
        return "BUY"

    # ── SELL ─────────────────────────────────────────────────────────────────
    if rsi >= rsi_sell_min:
        return "SELL"

    return "HOLD"


def signal_strength(price: float, rsi: float | None, ema200: float | None,
                    macd_hist: float | None, stoch_k: float | None,
                    stoch_d: float | None, direction: str) -> int:
    """
    Returns a confirmation score 0-3 for extra indicators.
    Used in trade notifications to show signal quality.
      0 = RSI only
      1 = RSI + 1 confirmation
      2 = RSI + 2 confirmations
      3 = RSI + all confirmations
    """
    score = 0
    if direction == "BUY":
        if macd_hist is not None and macd_hist > 0:
            score += 1
        if stoch_k is not None and stoch_d is not None and stoch_k < 20 and stoch_k > stoch_d:
            score += 1
        if ema200 is not None and price > ema200:
            score += 1
    elif direction == "SELL":
        if macd_hist is not None and macd_hist < 0:
            score += 1
        if stoch_k is not None and stoch_d is not None and stoch_k > 80 and stoch_k < stoch_d:
            score += 1
        if ema200 is not None and price < ema200:
            score += 1
    return score


def signal_strength_label(score: int) -> str:
    if score >= 3: return "🔥 Strong"
    if score >= 2: return "💪 Moderate"
    if score >= 1: return "⚡ Weak"
    return "⚠️ RSI Only"


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
        d  = tf_data.get(tf, {})
        ok = _tf_confirms(price, d.get("rsi"), d.get("ema200"), direction, rsi_buy_max, rsi_sell_min)
        labels[_MTF_DISPLAY[tf]] = "✅" if ok else "⚠️"
        if ok:
            count += 1
    return count, labels


def tf_labels_to_str(tf_labels):
    return " | ".join(f"{tf} {lbl}" for tf, lbl in tf_labels.items())
