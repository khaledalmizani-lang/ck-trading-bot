import os

# ── Binance API (optional — only needed for private/trading endpoints) ─────────
API_KEY    = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

EXCHANGE = "binance"
SYMBOL   = "BTC/USDT"

SYMBOLS = [
    "BTC/USDT",   "ETH/USDT",   "DOGE/USDT",  "ADA/USDT",   "SOL/USDT",
    "LINK/USDT",  "HBAR/USDT",  "XRP/USDT",   "AVAX/USDT",  "DOT/USDT",
    "POL/USDT",   "SUI/USDT",   "SEI/USDT",   "ATOM/USDT",  "CHR/USDT",
    "CHZ/USDT",   "FET/USDT",   "QTUM/USDT",  "AXS/USDT",   "SAND/USDT",
    "NEAR/USDT",  "APT/USDT",   "ARB/USDT",   "OP/USDT",    "IMX/USDT",
    "TAO/USDT",   "RENDER/USDT","WLD/USDT",   "AGIX/USDT",  "STRK/USDT",
    "AAVE/USDT",  "UNI/USDT",   "JUP/USDT",
]

RSI_BUY_MAX  = 38
RSI_SELL_MIN = 62

STOP_LOSS_PCT   = 1.5
TAKE_PROFIT_PCT = 3.0

MTF_NORMAL_CONFIRM     = 2
MTF_CAUTIOUS_CONFIRM   = 3
CONSECUTIVE_LOSS_CAUTION = 2
CONSECUTIVE_LOSS_PAUSE   = 4
AUTO_PAUSE_DURATION      = 7200

CHECK_INTERVAL           = 20
DEFENSIVE_CHECK_INTERVAL = 60

CONSECUTIVE_SL_LIMIT = 3

EVAL_DELAY       = 3600
COOLDOWN_MINUTES = 30

DAILY_MAX_TRADES = 50
DAILY_LOSS_LIMIT = -5.0

MIN_SIGNALS_FOR_ADJUSTMENT = 3
STATE_FILE   = "config.json"
HISTORY_FILE = "trade_history.json"

# ── Admin system ──────────────────────────────────────────────────────────────
import json as _json, os as _os
_ADMINS_FILE = "admins.json"

def _load_admins():
    owner = _os.getenv("TELEGRAM_CHAT_ID", "")
    if not _os.path.exists(_ADMINS_FILE):
        return {owner} if owner else set()
    try:
        data = _json.loads(open(_ADMINS_FILE).read())
        admins = set(str(x) for x in data)
        if owner: admins.add(str(owner))
        return admins
    except Exception:
        return {owner} if owner else set()

def _save_admins(admins_set):
    owner = _os.getenv("TELEGRAM_CHAT_ID", "")
    to_save = [x for x in admins_set if x != str(owner)]
    open(_ADMINS_FILE, "w").write(_json.dumps(to_save))

def is_admin(chat_id: str) -> bool:
    return str(chat_id) in _load_admins()

def add_admin(chat_id: str) -> bool:
    admins = _load_admins()
    admins.add(str(chat_id))
    _save_admins(admins)
    return True

def remove_admin(chat_id: str) -> bool:
    owner = _os.getenv("TELEGRAM_CHAT_ID", "")
    if str(chat_id) == str(owner):
        return False  # can't remove owner
    admins = _load_admins()
    admins.discard(str(chat_id))
    _save_admins(admins)
    return True

def list_admins() -> list:
    return list(_load_admins())

MAX_OPEN_TRADES = 5
