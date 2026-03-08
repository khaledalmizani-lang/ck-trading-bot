import config
from analyzer import get_rsi_thresholds

_MTF_ORDER   = ("15m", "1h", "4h", "1d")
_MTF_DISPLAY = {"15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}

# ── Volume & ATR settings ─────────────────────────────────────────────────────
VOLUME_SPIKE_MIN  = 120   # volume must be >= 120% of 20-candle average
ATR_SL_MULTIPLIER = 1.5   # stop loss = ATR * multiplier
ATR_TP_MULTIPLIER = 3.0   # take profit = ATR * multiplier


def check_signal(price: float, rsi: float | None, ema200: float | None,
                 macd_hist: float | None = None,
                 stoch_k: float | None = None,
                 stoch_d: float | None = None,
                 volume_pct: float | None = None) -> str:
    """
    Signal logic:
      BUY:  RSI <= threshold  +  price > EMA200  +  Volume Spike confirmed
      SELL: RSI >= threshold  +  Volume Spike confirmed

    Volume Spike acts as a filter — low volume signals are ignored.
    """
    rsi_buy_max, rsi_sell_min = get_rsi_thresholds()

    if rsi is None:
        return "HOLD"

    # ── Volume Spike filter ───────────────────────────────────────────────────
    volume_ok = (volume_pct is None) or (volume_pct >= VOLUME_SPIKE_MIN)

    # ── BUY ──────────────────────────────────────────────────────────────────
    if rsi <= rsi_buy_max:
        if ema200 is not None and price <= ema200:
            return "TREND_BLOCK_BUY"
        if not volume_ok:
            return "LOW_VOLUME"
        return "BUY"

    # ── SELL ─────────────────────────────────────────────────────────────────
    if rsi >= rsi_sell_min:
        if not volume_ok:
            return "LOW_VOLUME"
        return "SELL"

    return "HOLD"


def calculate_atr_levels(price: float, atr: float | None) -> dict:
    """
    Returns dynamic SL and TP based on ATR.
    Falls back to config fixed percentages if ATR is unavailable.
    """
    if atr is None or atr <= 0:
        sl_pct = config.STOP_LOSS_PCT
        tp_pct = config.TAKE_PROFIT_PCT
        sl = round(price * (1 - sl_pct / 100), 6)
        tp = round(price * (1 + tp_pct / 100), 6)
        return {
            "sl": sl,
            "tp": tp,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "atr_based": False,
        }

    sl_distance = atr * ATR_SL_MULTIPLIER
    tp_distance = atr * ATR_TP_MULTIPLIER
    sl = round(price - sl_distance, 6)
    tp = round(price + tp_distance, 6)
    sl_pct = round((sl_distance / price) * 100, 2)
    tp_pct = round((tp_distance / price) * 100, 2)
    return {
        "sl": sl,
        "tp": tp,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "atr_based": True,
    }


def signal_strength(price: float, rsi: float | None, ema200: float | None,
                    macd_hist: float | None, stoch_k: float | None,
                    stoch_d: float | None, direction: str,
                    volume_pct: float | None = None) -> int:
    """
    Returns a confirmation score 0-4 for extra indicators.
      0 = RSI only
      1 = RSI + 1 confirmation
      2 = RSI + 2 confirmations
      3 = RSI + 3 confirmations
      4 = RSI + all confirmations (including volume)
    """
    score = 0
    if direction == "BUY":
        if macd_hist is not None and macd_hist > 0:
            score += 1
        if stoch_k is not None and stoch_d is not None and stoch_k < 20 and stoch_k > stoch_d:
            score += 1
        if ema200 is not None and price > ema200:
            score += 1
        if volume_pct is not None and volume_pct >= VOLUME_SPIKE_MIN:
            score += 1
    elif direction == "SELL":
        if macd_hist is not None and macd_hist < 0:
            score += 1
        if stoch_k is not None and stoch_d is not None and stoch_k > 80 and stoch_k < stoch_d:
            score += 1
        if ema200 is not None and price < ema200:
            score += 1
        if volume_pct is not None and volume_pct >= VOLUME_SPIKE_MIN:
            score += 1
    return score


def signal_strength_label(score: int) -> str:
    if score >= 4: return "🔥 Strong"
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


def update_trailing_stop(trade: dict, current_price: float) -> dict:
    """Update trailing stop loss based on current price."""
    import config
    direction  = trade["signal"]
    trail_pct  = config.TRAILING_STOP_PCT / 100
    peak       = trade.get("peak_price", trade["entry_price"])

    if direction == "BUY":
        if current_price > peak:
            trade["peak_price"] = current_price
            peak = current_price
        new_sl = round(peak * (1 - trail_pct), 6)
        if new_sl > trade["stop_loss"]:
            trade["stop_loss"] = new_sl
    elif direction == "SELL":
        if current_price < peak:
            trade["peak_price"] = current_price
            peak = current_price
        new_sl = round(peak * (1 + trail_pct), 6)
        if new_sl < trade["stop_loss"]:
            trade["stop_loss"] = new_sl

    return trade
