"""
Balance tracker — virtual account balance management.
Tracks starting balance, current balance, and per-trade allocation.
"""
import json
import os
import time

_FILE = "balance.json"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_BALANCE      = 100.0   # Starting balance in USD
POSITION_SIZE_PCT    = 25.0    # 25% of available balance per trade
MAX_POSITION_USD     = 50.0    # Max $50 per trade (when balance > $200)
MAX_POSITION_ABOVE   = 200.0   # Apply max cap when balance exceeds this


def _load() -> dict:
    if not os.path.exists(_FILE):
        return {
            "starting_balance": DEFAULT_BALANCE,
            "current_balance":  DEFAULT_BALANCE,
            "allocated":        {},   # {trade_id: amount}
            "total_trades":     0,
            "total_pnl_usd":    0.0,
            "updated_at":       int(time.time()),
        }
    try:
        return json.loads(open(_FILE).read())
    except Exception:
        return _load()


def _save(data: dict):
    data["updated_at"] = int(time.time())
    open(_FILE, "w").write(json.dumps(data, indent=2))


# ── Public API ────────────────────────────────────────────────────────────────

def get_balance() -> dict:
    return _load()

def set_starting_balance(amount: float):
    data = _load()
    data["starting_balance"] = round(amount, 2)
    data["current_balance"]  = round(amount, 2)
    data["allocated"]        = {}
    data["total_pnl_usd"]    = 0.0
    data["total_trades"]     = 0
    _save(data)

def get_current_balance() -> float:
    return _load()["current_balance"]

def get_free_balance() -> float:
    data = _load()
    allocated = sum(data["allocated"].values())
    return round(data["current_balance"] - allocated, 2)

def calculate_position_size() -> float:
    """Returns how much USD to allocate for the next trade."""
    free = get_free_balance()
    current = get_current_balance()

    # Position size = 25% of current balance
    size = round(current * POSITION_SIZE_PCT / 100, 2)

    # Cap at MAX_POSITION_USD if balance > MAX_POSITION_ABOVE
    if current > MAX_POSITION_ABOVE:
        size = min(size, MAX_POSITION_USD)

    # Can't allocate more than free balance
    size = min(size, free)

    return max(size, 0.0)

def allocate_trade(trade_id: str, amount: float):
    """Reserve funds for an open trade."""
    data = _load()
    data["allocated"][str(trade_id)] = round(amount, 2)
    _save(data)

def close_trade(trade_id: str, pnl_pct: float):
    """Release funds and apply PnL when trade closes."""
    data = _load()
    tid = str(trade_id)
    allocated = data["allocated"].pop(tid, 0.0)
    if allocated > 0:
        pnl_usd = round(allocated * pnl_pct / 100, 4)
        data["current_balance"] = round(data["current_balance"] + pnl_usd, 4)
        data["total_pnl_usd"]   = round(data["total_pnl_usd"] + pnl_usd, 4)
        data["total_trades"]   += 1
        _save(data)
        return pnl_usd
    return 0.0

def get_summary() -> dict:
    data = _load()
    allocated_total = sum(data["allocated"].values())
    free = round(data["current_balance"] - allocated_total, 2)
    pnl_usd  = round(data["current_balance"] - data["starting_balance"], 4)
    pnl_pct  = round((pnl_usd / data["starting_balance"]) * 100, 2) if data["starting_balance"] > 0 else 0.0
    return {
        "starting":   data["starting_balance"],
        "current":    data["current_balance"],
        "free":       free,
        "allocated":  round(allocated_total, 2),
        "open_trades": len(data["allocated"]),
        "pnl_usd":    pnl_usd,
        "pnl_pct":    pnl_pct,
        "total_trades": data["total_trades"],
    }
