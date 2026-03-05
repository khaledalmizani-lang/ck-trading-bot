import json
import os
import tempfile
import threading
from datetime import datetime, timezone
import config

_lock = threading.Lock()

def _load():
    if os.path.exists(config.HISTORY_FILE):
        with open(config.HISTORY_FILE, "r") as f:
            return json.load(f)
    return []

def _save(history):
    dir_name = os.path.dirname(os.path.abspath(config.HISTORY_FILE)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(history, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, config.HISTORY_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

def load_history():
    with _lock:
        return _load()

def log_signal(signal, price, rsi, volume, symbol=None, sl_price=None, tp_price=None):
    if sl_price is not None and tp_price is not None:
        stop_loss = round(sl_price, 6)
        take_profit = round(tp_price, 6)
    else:
        sl_mult = config.STOP_LOSS_PCT / 100
        tp_mult = config.TAKE_PROFIT_PCT / 100
        if signal == "BUY":
            stop_loss = round(price * (1 - sl_mult), 6)
            take_profit = round(price * (1 + tp_mult), 6)
        else:
            stop_loss = round(price * (1 + sl_mult), 6)
            take_profit = round(price * (1 - tp_mult), 6)
    with _lock:
        history = _load()
        if any(e["outcome"] == "PENDING" for e in history):
            return None
        entry_id = len(history)
        entry = {"id": entry_id, "timestamp": datetime.now(timezone.utc).isoformat(),
                 "symbol": symbol or config.SYMBOL, "signal": signal, "price": price,
                 "rsi": rsi, "volume": volume, "stop_loss": stop_loss, "take_profit": take_profit,
                 "outcome": "PENDING", "exit_reason": "PENDING",
                 "outcome_price": None, "outcome_timestamp": None}
        history.append(entry)
        _save(history)
    return {"id": entry_id, "stop_loss": stop_loss, "take_profit": take_profit}

def close_trade(entry_id, current_price, exit_reason):
    with _lock:
        history = _load()
        entry = next((e for e in history if e["id"] == entry_id), None)
        if entry is None or entry["exit_reason"] != "PENDING":
            return "ALREADY_CLOSED"
        if exit_reason == "TAKE_PROFIT":
            outcome = "SUCCESS"
        elif exit_reason == "STOP_LOSS":
            outcome = "FAILURE"
        else:
            if entry["signal"] == "BUY":
                outcome = "SUCCESS" if current_price > entry["price"] else "FAILURE"
            else:
                outcome = "SUCCESS" if current_price < entry["price"] else "FAILURE"
        entry["outcome"] = outcome
        entry["exit_reason"] = exit_reason
        entry["outcome_price"] = current_price
        entry["outcome_timestamp"] = datetime.now(timezone.utc).isoformat()
        _save(history)
    return outcome

def get_pending_trades():
    with _lock:
        history = _load()
    result = []
    for entry in history:
        if entry["outcome"] != "PENDING":
            continue
        opened_at = datetime.fromisoformat(entry["timestamp"]).timestamp()
        due_at = opened_at + config.EVAL_DELAY
        result.append({"entry_id": entry["id"], "symbol": entry.get("symbol", config.SYMBOL),
                        "signal": entry["signal"], "entry_price": entry["price"],
                        "stop_loss": entry["stop_loss"], "take_profit": entry["take_profit"], "due_at": due_at})
    return result

def count_summary():
    with _lock:
        history = _load()
    return {"success": sum(1 for e in history if e["outcome"] == "SUCCESS"),
            "failure": sum(1 for e in history if e["outcome"] == "FAILURE"),
            "pending": sum(1 for e in history if e["outcome"] == "PENDING"),
            "total": len(history),
            "stop_losses": sum(1 for e in history if e.get("exit_reason") == "STOP_LOSS"),
            "take_profits": sum(1 for e in history if e.get("exit_reason") == "TAKE_PROFIT"),
            "timeouts": sum(1 for e in history if e.get("exit_reason") == "TIMEOUT")}
