"""
CK Crypto Bot — Configuration
Binance Spot | MTF + EMA + RSI + MACD + AI
"""
import os

# ── Binance API ───────────────────────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "8604902841:AAGI54S3vDtFSfsgjPxZ4c5CvFtdi9_-YTI")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "6440310690")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1003848131722")

# ── Anthropic AI ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_ENABLED        = False
AI_MIN_CONVICTION = 6
AI_MAX_RISK       = 7

# ── Symbols ───────────────────────────────────────────────────────────────────
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "DOTUSDT", "LINKUSDT", "MATICUSDT", "NEARUSDT",
    "ATOMUSDT", "UNIUSDT", "AAVEUSDT", "APTUSDT",
    "ARBUSDT", "OPUSDT", "SUIUSDT", "TAOUSDT",
    "RENDERUSDT", "FETUSDT", "INJUSDT", "TIAUSDT",
    "SEIUSDT", "WLDUSDT", "JUPUSDT", "STRKUSDT",
    "HBARUSDT", "IMXUSDT", "AXSUSDT", "SANDUSDT",
    "CHRUSDT",
]

# ── Trade Settings ────────────────────────────────────────────────────────────
MAX_OPEN_TRADES  = 5
COOLDOWN_SECONDS = 300   # 5 دقائق بين صفقات نفس الرمز
LOOP_INTERVAL    = 20    # ثانية

# ── Risk Management ───────────────────────────────────────────────────────────
RISK_PER_TRADE      = 2.0    # % من الرصيد
DAILY_LOSS_LIMIT    = -3.0   # % — يوقف البوت
DAILY_PROFIT_TARGET = 7.0    # % — يوقف البوت
DEFENSIVE_AFTER_SL  = 2      # خسارتين → defensive mode (نص المخاطرة)

# ── TP/SL ─────────────────────────────────────────────────────────────────────
TAKE_PROFIT_PCT = 3.0    # % من سعر الدخول
STOP_LOSS_PCT   = 1.5    # % من سعر الدخول

# ── MTF Settings ─────────────────────────────────────────────────────────────
MTF_TIMEFRAMES = ["1m", "5m", "15m"]
MTF_REQUIRED   = 3   # لازم يتوافق الـ 3

# ── Indicators ───────────────────────────────────────────────────────────────
EMA_FAST   = 9
EMA_MID    = 21
EMA_SLOW   = 50
RSI_PERIOD = 14
RSI_BUY    = 40
RSI_SELL   = 60
MACD_FAST  = 12
MACD_SLOW  = 26
MACD_SIG   = 9
ATR_PERIOD = 14
MIN_CONFIRMATIONS = 3

# ── Files ─────────────────────────────────────────────────────────────────────
STATE_FILE   = "crypto_state.json"
HISTORY_FILE = "crypto_history.json"
TRADES_FILE  = "crypto_trades.json"
