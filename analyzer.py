import json
import os
import config

def _default_state():
    return {"rsi_buy_max": config.RSI_BUY_MAX, "rsi_sell_min": config.RSI_SELL_MIN,
            "consecutive_sl": 0, "defensive_mode": False}

def _load_state():
    if os.path.exists(config.STATE_FILE):
        saved = {}
        with open(config.STATE_FILE) as f:
            saved = json.load(f)
        defaults = _default_state()
        defaults.update(saved)
        return defaults
    return _default_state()

def _save_state(state):
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_rsi_thresholds():
    state = _load_state()
    return state["rsi_buy_max"], state["rsi_sell_min"]

def is_defensive_mode():
    return _load_state().get("defensive_mode", False)

def get_check_interval():
    if is_defensive_mode():
        return config.DEFENSIVE_CHECK_INTERVAL
    return config.CHECK_INTERVAL

def record_exit(exit_reason):
    state = _load_state()
    was_defensive = state["defensive_mode"]
    if exit_reason == "STOP_LOSS":
        state["consecutive_sl"] += 1
    else:
        state["consecutive_sl"] = 0
    now_defensive = state["consecutive_sl"] >= config.CONSECUTIVE_SL_LIMIT
    state["defensive_mode"] = now_defensive
    _save_state(state)
    return {"consecutive_sl": state["consecutive_sl"], "defensive_mode": now_defensive,
            "just_activated": now_defensive and not was_defensive,
            "just_deactivated": not now_defensive and was_defensive}

def analyze_performance():
    if not os.path.exists(config.HISTORY_FILE):
        return {"total_evaluated": 0, "success_rate": None, "adjusted": False}
    with open(config.HISTORY_FILE) as f:
        history = json.load(f)
    evaluated = [e for e in history if e["outcome"] in ("SUCCESS", "FAILURE")]
    total_evaluated = len(evaluated)
    if total_evaluated == 0:
        return {"total_evaluated": 0, "success_rate": None, "adjusted": False}
    window = evaluated[-10:]
    successes = sum(1 for e in window if e["outcome"] == "SUCCESS")
    failures = sum(1 for e in window if e["outcome"] == "FAILURE")
    success_rate = successes / len(window)
    sl_exits = sum(1 for e in window if e.get("exit_reason") == "STOP_LOSS")
    tp_exits = sum(1 for e in window if e.get("exit_reason") == "TAKE_PROFIT")
    timeout_exits = sum(1 for e in window if e.get("exit_reason") == "TIMEOUT")
    sl_rate = sl_exits / len(window)
    state = _load_state()
    adjustments = []
    enough_data = len(window) >= config.MIN_SIGNALS_FOR_ADJUSTMENT
    if enough_data and success_rate < 0.5:
        old_buy, old_sell = state["rsi_buy_max"], state["rsi_sell_min"]
        new_buy = max(old_buy - 5, 5)
        new_sell = min(old_sell + 5, 95)
        if new_buy != old_buy or new_sell != old_sell:
            state["rsi_buy_max"] = new_buy
            state["rsi_sell_min"] = new_sell
            adjustments.append(f"Low success rate: RSI {old_buy}→{new_buy}, {old_sell}→{new_sell}")
    if enough_data and failures > 0 and sl_exits / max(failures, 1) > 0.5:
        old_buy, old_sell = state["rsi_buy_max"], state["rsi_sell_min"]
        new_buy = max(state["rsi_buy_max"] - 5, 5)
        new_sell = min(state["rsi_sell_min"] + 5, 95)
        if new_buy != old_buy or new_sell != old_sell:
            state["rsi_buy_max"] = new_buy
            state["rsi_sell_min"] = new_sell
            adjustments.append(f"High SL rate: RSI {old_buy}→{new_buy}, {old_sell}→{new_sell}")
    if adjustments:
        _save_state(state)
    return {"total_evaluated": total_evaluated, "window_size": len(window),
            "successes": successes, "failures": failures, "success_rate": success_rate,
            "sl_exits": sl_exits, "tp_exits": tp_exits, "timeout_exits": timeout_exits,
            "sl_rate": sl_rate, "rsi_buy_max": state["rsi_buy_max"],
            "rsi_sell_min": state["rsi_sell_min"], "defensive_mode": state["defensive_mode"],
            "consecutive_sl": state["consecutive_sl"], "adjusted": bool(adjustments),
            "adjustment_msgs": adjustments}
