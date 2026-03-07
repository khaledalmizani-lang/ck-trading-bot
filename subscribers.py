import json
import os
import time

_FILE = "subscribers.json"
_TRIAL_LIMIT = 5  # free signals before join required

# ── Data structure ─────────────────────────────────────────────────────────
# {
#   "chat_id": {
#     "status": "trial" | "member" | "banned",
#     "name": "...",
#     "username": "...",
#     "signals_seen": 3,
#     "joined_at": 1234567890,
#     "approved_at": null
#   }
# }

def _load() -> dict:
    if not os.path.exists(_FILE):
        return {}
    try:
        return json.loads(open(_FILE).read())
    except Exception:
        return {}

def _save(data: dict):
    open(_FILE, "w").write(json.dumps(data, indent=2))

# ── User management ────────────────────────────────────────────────────────

def get_user(chat_id: str) -> dict | None:
    return _load().get(str(chat_id))

def is_member(chat_id: str) -> bool:
    u = get_user(chat_id)
    return u is not None and u.get("status") == "member"

def is_trial(chat_id: str) -> bool:
    u = get_user(chat_id)
    if u is None:
        return True  # new user = trial
    return u.get("status") == "trial"

def is_banned(chat_id: str) -> bool:
    u = get_user(chat_id)
    return u is not None and u.get("status") == "banned"

def can_use(chat_id: str) -> bool:
    """Returns True if user can use commands"""
    u = get_user(chat_id)
    if u is None:
        return True  # new user, start trial
    if u.get("status") == "member":
        return True
    if u.get("status") == "trial":
        return u.get("signals_seen", 0) < _TRIAL_LIMIT
    return False

def trial_remaining(chat_id: str) -> int:
    u = get_user(chat_id)
    if u is None:
        return _TRIAL_LIMIT
    seen = u.get("signals_seen", 0)
    return max(0, _TRIAL_LIMIT - seen)

def register_user(chat_id: str, name: str = "", username: str = ""):
    """Register new user as trial"""
    data = _load()
    cid = str(chat_id)
    if cid not in data:
        data[cid] = {
            "status": "trial",
            "name": name,
            "username": username,
            "signals_seen": 0,
            "joined_at": int(time.time()),
            "approved_at": None,
        }
        _save(data)

def increment_signals(chat_id: str):
    """Count a signal view for trial users"""
    data = _load()
    cid = str(chat_id)
    if cid in data and data[cid].get("status") == "trial":
        data[cid]["signals_seen"] = data[cid].get("signals_seen", 0) + 1
        _save(data)

def approve_member(chat_id: str) -> bool:
    data = _load()
    cid = str(chat_id)
    if cid not in data:
        return False
    data[cid]["status"] = "member"
    data[cid]["approved_at"] = int(time.time())
    _save(data)
    return True

def reject_member(chat_id: str) -> bool:
    data = _load()
    cid = str(chat_id)
    if cid not in data:
        return False
    data[cid]["status"] = "banned"
    _save(data)
    return True

def remove_member(chat_id: str) -> bool:
    data = _load()
    cid = str(chat_id)
    if cid not in data:
        return False
    data[cid]["status"] = "trial"
    data[cid]["signals_seen"] = _TRIAL_LIMIT  # block trial too
    _save(data)
    return True

def list_members() -> list:
    data = _load()
    return [(cid, u) for cid, u in data.items() if u.get("status") == "member"]

def list_pending() -> list:
    data = _load()
    return [(cid, u) for cid, u in data.items() if u.get("status") == "trial" and u.get("signals_seen", 0) >= _TRIAL_LIMIT]

def total_users() -> dict:
    data = _load()
    members = sum(1 for u in data.values() if u.get("status") == "member")
    trial   = sum(1 for u in data.values() if u.get("status") == "trial")
    banned  = sum(1 for u in data.values() if u.get("status") == "banned")
    return {"members": members, "trial": trial, "banned": banned, "total": len(data)}
