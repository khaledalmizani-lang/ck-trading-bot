import asyncio
import os
import time
import threading
from telegram import Bot
import config

_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID",   "")
_ENABLED = bool(_TOKEN and _CHAT_ID)
_POLL_INTERVAL = 2

_open_trades  = []
_last_market  = {}
_last_scan_ts = 0.0
_paused       = False

def configure(open_trades):
    global _open_trades
    _open_trades = open_trades

def update_snapshot(market_data):
    global _last_scan_ts
    _last_market.clear()
    _last_market.update(market_data)
    _last_scan_ts = time.time()

def is_paused():
    return _paused

def _fmt(price):
    if price >= 1:
        return f"${price:,.2f}"
    elif price >= 0.01:
        return f"${price:.4f}"
    elif price >= 0.0001:
        return f"${price:.6f}"
    return f"${price:.8f}"

def _cmd_status():
    if not _last_market:
        return "⏳ <b>First scan in progress</b> — please try again in ~20 seconds."
    age = int(time.time() - _last_scan_ts)
    stamp = f"{age}s ago" if age < 120 else f"{age // 60}m ago"
    lines = [f"📊 <b>Current Market Snapshot</b>  <i>({stamp})</i>", "━━━━━━━━━━━━━━━━━━"]
    for sym in config.SYMBOLS:
        d = _last_market.get(sym)
        if not d:
            lines.append(f"{sym} | –")
            continue
        rsi = d.get("rsi")
        lines.append(
            f"<b>{sym}</b> | RSI: <b>{rsi:.1f}</b> | {_fmt(d['price'])}"
            if rsi else f"<b>{sym}</b> | RSI: n/a | {_fmt(d['price'])}"
        )
    lines.append("━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

def _cmd_report():
    from report import build_report
    from datetime import datetime, timezone, timedelta
    r = build_report()
    if r is None or r.get("no_data"):
        return "📭 <b>No closed trades yet.</b> Bot is active and monitoring."
    pf = r["profit_factor"]
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    pnl_s = "+" if r["cumulative_pnl"] >= 0 else ""
    ts = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d %b %Y  %H:%M AST")
    best_line = ""
    worst_line = ""
    if r.get("best_trade") is not None:
        bs = "+" if r["best_trade"] >= 0 else ""
        best_line = f"\n🥇 Best:  <b>{bs}{r['best_trade']:.2f}%</b>"
    if r.get("worst_trade") is not None:
        worst_line = f"\n💀 Worst: <b>{r['worst_trade']:.2f}%</b>"
    return (
        f"╔══════════════════╗\n📊  PERFORMANCE REPORT\n╚══════════════════╝\n\n"
        f"🏆 Win Rate:      <b>{r['win_rate']:.1f}%</b>\n"
        f"💰 Total PnL:     <b>{pnl_s}{r['cumulative_pnl']:.2f}%</b>\n"
        f"📈 Profit Factor: <b>{pf_str}</b>\n"
        f"✅ Wins:          <b>{r['win_count']}</b>\n"
        f"❌ Losses:        <b>{r['loss_count']}</b>\n"
        f"⏳ Open Trades:   <b>{r['pending']}</b>"
        f"{best_line}{worst_line}\n"
        f"🎯 TP: {r['tp_count']}  |  🛡 SL: {r['sl_count']}  |  ⏱ Timeout: {r['timeout_count']}\n"
        f"🕐 {ts}\n══════════════════════"
    )

def _cmd_pause():
    global _paused
    if _paused:
        return "⏸ Bot is already paused. Send /resume to restart."
    _paused = True
    return "⏸ <b>Trading paused.</b>\nSend /resume to restart."

def _cmd_resume():
    global _paused
    if not _paused:
        return "▶️ Bot is already running normally."
    _paused = False
    return "▶️ <b>Trading resumed.</b>"

def _cmd_trades():
    if not _open_trades:
        return "📭 <b>No open trades</b> right now."
    now = time.time()
    lines = [f"📋 <b>Open Trades ({len(_open_trades)})</b>", "━━━━━━━━━━━━━━━━━━"]
    for t in _open_trades:
        sym = t.get("symbol", config.SYMBOL)
        remaining = max(0, t["due_at"] - now)
        mins, sec = divmod(int(remaining), 60)
        lines.append(
            f"#<b>{t['entry_id']}</b> | <b>{sym}</b> {t['signal']} @ {_fmt(t['entry_price'])}\n"
            f"  SL: {_fmt(t['stop_loss'])} | TP: {_fmt(t['take_profit'])}\n"
            f"  Expires in: {mins}m {sec}s"
        )
    lines.append("━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

def _cmd_help():
    return (
        "🤖 <b>Available Commands</b>\n━━━━━━━━━━━━━━━━━━\n"
        "/status  — RSI &amp; price for all coins\n"
        "/report  — Full performance report\n"
        "/trades  — Currently open trades\n"
        "/pause   — Pause new trade signals\n"
        "/resume  — Resume trading\n"
        "/help    — This message\n━━━━━━━━━━━━━━━━━━"
    )

_DISPATCH = {
    "/status": _cmd_status, "/report": _cmd_report,
    "/pause": _cmd_pause, "/resume": _cmd_resume,
    "/trades": _cmd_trades, "/help": _cmd_help,
}

async def _get_updates(offset):
    bot = Bot(token=_TOKEN)
    async with bot:
        return await bot.get_updates(offset=offset, timeout=10, limit=20, allowed_updates=["message"])

async def _drain():
    bot = Bot(token=_TOKEN)
    async with bot:
        updates = await bot.get_updates(offset=-1, timeout=1, limit=1)
        return (updates[-1].update_id + 1) if updates else 0

async def _reply(chat_id, text):
    bot = Bot(token=_TOKEN)
    async with bot:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

def _poll_loop():
    try:
        offset = asyncio.run(_drain())
    except Exception:
        offset = 0
    print("[COMMANDS] Command listener ready — polling every 2s")
    while True:
        try:
            updates = asyncio.run(_get_updates(offset))
            for upd in updates:
                offset = upd.update_id + 1
                msg = upd.message or upd.edited_message
                if not msg or not msg.text:
                    continue
                if str(msg.chat_id) != str(_CHAT_ID):
                    continue
                word = msg.text.strip().lower().split()[0]
                if "@" in word:
                    word = word.split("@")[0]
                handler = _DISPATCH.get(word)
                if handler:
                    try:
                        reply_text = handler()
                    except Exception as exc:
                        reply_text = f"❌ Error running {word}: {exc}"
                    try:
                        asyncio.run(_reply(msg.chat_id, reply_text))
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(_POLL_INTERVAL)

def start():
    if not _ENABLED:
        print("[COMMANDS] Telegram not configured — command listener disabled")
        return
    t = threading.Thread(target=_poll_loop, daemon=True, name="cmd-listener")
    t.start()
