import asyncio
import os
import threading
from datetime import datetime, timezone, timedelta
from telegram import Bot

_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN",  "")
_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID",    "")
_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
_ENABLED    = bool(_TOKEN and _CHAT_ID)
_AST = timezone(timedelta(hours=3))

def _ast_now() -> str:
    return datetime.now(_AST).strftime("%H:%M:%S AST")

async def _async_send(text: str, chat_id: str) -> None:
    bot = Bot(token=_TOKEN)
    async with bot:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

def send(text: str, *, also_channel: bool = False) -> None:
    if not _ENABLED:
        return
    def _fire():
        try:
            asyncio.run(_async_send(text, _CHAT_ID))
        except Exception:
            pass
        if also_channel and _CHANNEL_ID:
            try:
                asyncio.run(_async_send(text, _CHANNEL_ID))
            except Exception:
                pass
    threading.Thread(target=_fire, daemon=True).start()

def _fmt_price(price: float) -> str:
    if price >= 1:
        return f"${price:,.2f}"
    elif price >= 0.01:
        return f"${price:.4f}"
    elif price >= 0.0001:
        return f"${price:.6f}"
    else:
        return f"${price:.8f}"

def _trend_label(adx: float | None) -> str:
    if adx is None:
        return "n/a"
    pct = round(adx)
    if adx >= 40:
        return f"{pct}% 🔥 Very Strong"
    elif adx >= 25:
        return f"{pct}% 💪 Strong"
    else:
        return f"{pct}% ⚖️ Moderate"

def notify_trade_opened(signal, price, sl, tp, trade_id, symbol="BTC/USDT",
                         tf_labels=None, rsi=None, ema_above=None, volume_pct=None, adx=None):
    ts = _ast_now()
    if signal == "BUY":
        risk, reward = abs(price - sl), abs(tp - price)
    else:
        risk, reward = abs(sl - price), abs(price - tp)
    rr = round(reward / risk) if risk > 0 else 2
    ema_str = "▲ ABOVE" if ema_above is True else ("▼ BELOW" if ema_above is False else "n/a")
    rsi_str = f"{rsi:.1f}" if rsi is not None else "n/a"
    vol_str = f"{volume_pct:.1f}%" if volume_pct is not None else "n/a"
    trend_str = _trend_label(adx)
    header = "🟢  BUY SIGNAL" if signal == "BUY" else "🔴  SELL SIGNAL"
    tf_line = ""
    if tf_labels:
        tf_str = " ".join(f"{tf} {lbl}" for tf, lbl in tf_labels.items())
        tf_line = f"\n🕯 TF: {tf_str}"
    text = (
        f"╔══════════════════╗\n{header}\n╚══════════════════╝\n\n"
        f"🪙 Coin:              <b>{symbol}</b>\n"
        f"💵 Entry:             <b>{_fmt_price(price)}</b>\n"
        f"🛡 Stop Loss:         <b>{_fmt_price(sl)}</b>\n"
        f"🎯 Take Profit:       <b>{_fmt_price(tp)}</b>\n"
        f"⚡ Risk/Reward:       1:{rr}\n\n"
        f"📊 RSI:              {rsi_str}\n"
        f"📈 EMA:              {ema_str}\n"
        f"💹 Volume Strength:  {vol_str}\n"
        f"💪 Trend Strength:   {trend_str}"
        f"{tf_line}\n"
        f"🔢 Trade #{trade_id}\n🕐 {ts}\n══════════════════════"
    )
    send(text, also_channel=True)

def notify_trade_closed(signal, entry, exit_price, pnl_pct, exit_reason, trade_id, outcome, symbol="BTC/USDT"):
    ts = _ast_now()
    pnl_sign = "+" if pnl_pct >= 0 else ""
    pnl_str = f"{pnl_sign}{pnl_pct:.1f}%"
    if exit_reason == "TAKE_PROFIT":
        header = "✅  TARGET REACHED"
    elif exit_reason == "STOP_LOSS":
        header = "❌  STOP LOSS HIT"
    else:
        header = "⏱  TIME LIMIT REACHED"
    text = (
        f"╔══════════════════╗\n{header}\n╚══════════════════╝\n\n"
        f"🪙 Coin:      <b>{symbol}</b>\n"
        f"📈 Direction: {signal}\n"
        f"💵 Entry:     <b>{_fmt_price(entry)}</b>\n"
        f"🏁 Exit:      <b>{_fmt_price(exit_price)}</b>\n"
        f"💰 PnL:       <b>{pnl_str}</b>\n\n"
        f"🔢 Trade #{trade_id}\n🕐 {ts}\n══════════════════════"
    )
    send(text, also_channel=True)

def notify_hourly_report(win_rate, profit_factor, cumulative_pnl, closed, wins, losses, pending,
                          best_trade=None, worst_trade=None, btc_dominance=None):
    ts = _ast_now()
    pf_str = "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}"
    pnl_s = "+" if cumulative_pnl >= 0 else ""
    best_line = ""
    worst_line = ""
    if best_trade is not None:
        bs = "+" if best_trade >= 0 else ""
        best_line = f"\n🥇 Best:  <b>{bs}{best_trade:.2f}%</b>"
    if worst_trade is not None:
        worst_line = f"\n💀 Worst: <b>{worst_trade:.2f}%</b>"
    text = (
        f"╔══════════════════╗\n📊  PERFORMANCE REPORT\n╚══════════════════╝\n\n"
        f"🏆 Win Rate:      <b>{win_rate:.1f}%</b>\n"
        f"💰 Total PnL:     <b>{pnl_s}{cumulative_pnl:.2f}%</b>\n"
        f"📈 Profit Factor: <b>{pf_str}</b>\n"
        f"✅ Wins:          <b>{wins}</b>\n"
        f"❌ Losses:        <b>{losses}</b>\n"
        f"⏳ Open Trades:   <b>{pending}</b>"
        f"{best_line}{worst_line}\n"
        f"🕐 {ts}\n══════════════════════"
    )
    send(text, also_channel=True)

def notify_no_trades_yet():
    send(f"📭 No Trades Yet – Bot is Active and Monitoring\n🕐 {_ast_now()}")

def notify_weekly_report(win_rate, cumulative_pnl, profit_factor, wins, losses,
                          best_trade, worst_trade, timeouts, tp_count, sl_count, total_closed):
    ts = _ast_now()
    pf_str = "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}"
    pnl_s = "+" if cumulative_pnl >= 0 else ""
    bs = "+" if best_trade >= 0 else ""
    text = (
        f"╔══════════════════╗\n📅  WEEKLY REPORT\n╚══════════════════╝\n\n"
        f"🏆 Win Rate:      <b>{win_rate:.1f}%</b>\n"
        f"💰 Total PnL:     <b>{pnl_s}{cumulative_pnl:.2f}%</b>\n"
        f"📈 Profit Factor: <b>{pf_str}</b>\n"
        f"✅ Wins:          <b>{wins}</b>\n❌ Losses:        <b>{losses}</b>\n"
        f"🥇 Best Trade:    <b>{bs}{best_trade:.2f}%</b>\n"
        f"💀 Worst Trade:   <b>{worst_trade:.2f}%</b>\n"
        f"🎯 TP Hit:        <b>{tp_count}</b>\n"
        f"🛡 SL Hit:        <b>{sl_count}</b>\n"
        f"⏱ Timeout:       <b>{timeouts}</b>\n"
        f"🕐 {ts}\n══════════════════════"
    )
    send(text, also_channel=True)

def notify_daily_loss_pause():
    send(f"╔══════════════════╗\n⚠️  TRADING PAUSED\n╚══════════════════╝\n\n📛 Reason: Daily Loss Limit Reached\n🔄 Resumes: Tomorrow 00:00 AST\n══════════════════════", also_channel=True)

def notify_autopause_losses(count=4):
    send(f"╔══════════════════╗\n⚠️  TRADING PAUSED\n╚══════════════════╝\n\n📛 Reason: {count} Consecutive Losses\n🔄 Resumes: In 2 hours\n══════════════════════", also_channel=True)

def notify_volume_alert(level):
    ts = _ast_now()
    if level == "extreme":
        header, body = "⚡  EXTREME VOLUME ALERT", "Massive trading activity detected"
    elif level == "strong":
        header, body = "🔥  STRONG VOLUME ALERT", "Heavy trading activity – possible big move incoming"
    else:
        header, body = "📈  HIGH VOLUME ALERT", "Unusual trading activity detected"
    send(f"╔══════════════════╗\n{header}\n╚══════════════════╝\n{body}\n🕐 {ts}\n══════════════════════", also_channel=True)

def notify_pump_alert(name, change, price_str):
    ts = _ast_now()
    send(f"╔══════════════════╗\n🚀  PUMP ALERT\n╚══════════════════╝\n\n🪙 {name}/USDT\n📈 Up {change:.1f}% in the last hour\n💵 Price: {price_str}\n🕐 {ts}\n══════════════════════", also_channel=True)

def notify_connection_issue():
    ts = _ast_now()
    send(f"╔══════════════════╗\n🔌  CONNECTION ISSUE\n╚══════════════════╝\nRetrying in 60 seconds...\n🕐 {ts}\n══════════════════════", also_channel=True)
