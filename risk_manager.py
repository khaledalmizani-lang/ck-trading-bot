"""
CK Crypto Bot — Risk Manager
"""
import json, os, time
import config
import binance_client as bc

_state = {
    "daily_pnl_pct": 0.0, "daily_trades": 0,
    "daily_wins": 0, "daily_losses": 0,
    "consecutive_losses": 0, "defensive_mode": False,
    "paused": False, "day_start_balance": 0.0, "last_reset_day": "",
}

def _load():
    global _state
    if os.path.exists(config.STATE_FILE):
        try: _state.update(json.load(open(config.STATE_FILE)))
        except: pass

def _save():
    json.dump(_state, open(config.STATE_FILE, "w"), indent=2)

def _reset_if_needed():
    today = time.strftime("%Y-%m-%d")
    if _state["last_reset_day"] != today:
        bal = bc.get_balance()
        _state.update({"daily_pnl_pct": 0.0, "daily_trades": 0, "daily_wins": 0,
                        "daily_losses": 0, "consecutive_losses": 0, "defensive_mode": False,
                        "paused": False, "day_start_balance": bal, "last_reset_day": today})
        _save()
        print(f"[RISK] 📅 New day | Balance: ${bal:.2f}")

def initialize():
    _load()
    _reset_if_needed()

def get_risk_usdt() -> float:
    bal = bc.get_balance()
    pct = config.RISK_PER_TRADE / 2 if _state["defensive_mode"] else config.RISK_PER_TRADE
    return round(bal * pct / 100, 2)

def can_trade(open_count: int) -> tuple[bool, str]:
    _reset_if_needed()
    if _state["paused"]: return False, "Bot paused"
    if open_count >= config.MAX_OPEN_TRADES: return False, f"Max trades ({config.MAX_OPEN_TRADES})"
    bal = bc.get_balance()
    day_start = _state["day_start_balance"]
    if day_start > 0:
        pnl_pct = ((bal - day_start) / day_start) * 100
        if pnl_pct <= config.DAILY_LOSS_LIMIT:
            _state["paused"] = True; _save()
            return False, f"Daily loss limit ({pnl_pct:.2f}%)"
        if pnl_pct >= config.DAILY_PROFIT_TARGET:
            _state["paused"] = True; _save()
            return False, f"Daily profit target ({pnl_pct:.2f}%) 🎯"
    return True, "OK"

def record_result(won: bool, pnl_pct: float):
    _state["daily_trades"] += 1
    if won:
        _state["daily_wins"] += 1
        _state["consecutive_losses"] = 0
        _state["defensive_mode"] = False
    else:
        _state["daily_losses"] += 1
        _state["consecutive_losses"] += 1
        if _state["consecutive_losses"] >= config.DEFENSIVE_AFTER_SL:
            _state["defensive_mode"] = True
            print(f"[RISK] ⚠️ Defensive mode ON")
    _save()

def get_summary() -> dict:
    return {**_state, "balance": bc.get_balance()}

def save_history(trade: dict):
    history = []
    if os.path.exists(config.HISTORY_FILE):
        try: history = json.load(open(config.HISTORY_FILE))
        except: pass
    history.append({**trade, "closed_at": int(time.time())})
    json.dump(history, open(config.HISTORY_FILE, "w"), indent=2)

def pause(): _state["paused"] = True; _save()
def resume(): _state["paused"] = False; _save()
def is_defensive(): return _state["defensive_mode"]
