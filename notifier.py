"""
CK Crypto Bot — Notifier
Telegram | Binance Spot
"""
import asyncio, time
import config
from telegram import Bot

_bot = None

def _get_bot():
    global _bot
    if _bot is None:
        _bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    return _bot

def send(text: str, also_channel: bool = True):
    async def _send():
        bot = _get_bot()
        async with bot:
            await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")
            if also_channel and config.TELEGRAM_CHANNEL_ID:
                try:
                    await bot.send_message(chat_id=config.TELEGRAM_CHANNEL_ID, text=text, parse_mode="HTML")
                except: pass
    try: asyncio.run(_send())
    except Exception as e: print(f"[NOTIFY] {e}")

def ksa():
    return time.strftime("%I:%M %p", time.gmtime(time.time() + 10800))

def notify_online(balance: float, symbols: int):
    send(
        f"📊 <b>Binance Spot — Crypto Bot Online</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 Platform: <b>Binance Spot</b>\n"
        f"📌 Type: <b>Spot Trading (BUY only)</b>\n"
        f"💰 Balance: <b>${balance:.2f} USDT</b>\n"
        f"📈 Symbols: <b>{symbols}</b>\n"
        f"🎯 Strategy: MTF + EMA9/21/50 + RSI + MACD\n"
        f"⚡ TP: {config.TAKE_PROFIT_PCT}% | SL: {config.STOP_LOSS_PCT}%\n"
        f"🕐 {ksa()} KSA"
    )

def notify_open(symbol: str, entry: float, qty: float,
                tp: float, sl: float, usdt_amount: float,
                rsi: float, confirmations: int, mtf_signals: dict, balance: float):
    mtf_str = " | ".join([f"{tf}:{sig}" for tf, sig in mtf_signals.items()])
    send(
        f"🟢 <b>BUY • Binance Spot</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 <b>Binance Spot</b>\n"
        f"📈 <b>{symbol}</b>\n"
        f"💵 Entry: <b>{entry:.4f}</b>\n"
        f"📦 Qty: <b>{qty}</b>\n"
        f"💰 Amount: <b>${usdt_amount:.2f}</b>\n"
        f"🎯 TP: <b>{tp:.4f}</b> (+{config.TAKE_PROFIT_PCT}%)\n"
        f"🛑 SL: <b>{sl:.4f}</b> (-{config.STOP_LOSS_PCT}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📉 RSI: <b>{rsi}</b>\n"
        f"✅ Confirms: <b>{confirmations}/5</b>\n"
        f"📊 MTF: {mtf_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: <b>${balance:.2f}</b>\n"
        f"🕐 {ksa()} KSA"
    )

def notify_close(symbol: str, entry: float, exit_price: float,
                 pnl_pct: float, pnl_usdt: float, reason: str, balance: float):
    emoji = "✅" if pnl_usdt >= 0 else "❌"
    sign  = "+" if pnl_usdt >= 0 else ""
    reasons = {"TP": "🎯 Take Profit", "SL": "🛑 Stop Loss", "MANUAL": "👤 Manual"}
    send(
        f"{emoji} <b>CLOSED • Binance Spot</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 <b>Binance Spot</b>\n"
        f"📈 <b>{symbol}</b>\n"
        f"💵 Entry: <b>{entry:.4f}</b>\n"
        f"💵 Exit: <b>{exit_price:.4f}</b>\n"
        f"📊 PnL: <b>{sign}{pnl_pct:.2f}%</b> ({sign}${pnl_usdt:.2f})\n"
        f"📌 {reasons.get(reason, reason)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: <b>${balance:.2f}</b>"
    )

def notify_daily(summary: dict):
    emoji = "🟢" if summary["daily_pnl_pct"] >= 0 else "🔴"
    sign  = "+" if summary["daily_pnl_pct"] >= 0 else ""
    send(
        f"📊 <b>Daily Summary • Binance Spot</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} PnL: <b>{sign}{summary['daily_pnl_pct']:.2f}%</b>\n"
        f"✅ Wins: <b>{summary['daily_wins']}</b>\n"
        f"❌ Losses: <b>{summary['daily_losses']}</b>\n"
        f"📋 Total: <b>{summary['daily_trades']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: <b>${summary['balance']:.2f}</b>"
    )

def notify_pause(reason: str):
    send(f"⏸️ <b>Binance Spot Bot Paused</b>\n📌 {reason}")

def notify_error(msg: str):
    send(f"⚠️ <b>Binance Spot Bot Error</b>\n{msg}")
