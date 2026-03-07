import asyncio
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from telegram import Bot
import config
import subscribers

_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID",   "")
_ENABLED = bool(_TOKEN and _CHAT_ID)
_POLL_INTERVAL = 2

_open_trades  = []
_last_market  = {}
_last_scan_ts = 0.0

def configure(open_trades):
    global _open_trades
    _open_trades = open_trades

def update_snapshot(market_data):
    global _last_scan_ts
    _last_market.clear()
    _last_market.update(market_data)
    _last_scan_ts = time.time()

def is_paused():
    return False  # pause/resume removed -- VPS runs 24/7

def _fmt(price):
    if price >= 1:       return f"${price:,.2f}"
    elif price >= 0.01:  return f"${price:.4f}"
    elif price >= 0.0001:return f"${price:.6f}"
    return f"${price:.8f}"

# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_status():
    if not _last_market:
        return "⏳ <b>First scan in progress</b> -- please try again in ~20 seconds."
    age = int(time.time() - _last_scan_ts)
    stamp = f"{age}s ago" if age < 120 else f"{age // 60}m ago"
    lines = [f"📊 <b>Market Snapshot</b>  <i>({stamp})</i>", "---"]
    from analyzer import get_rsi_thresholds
    rsi_buy, rsi_sell = get_rsi_thresholds()
    for sym in config.SYMBOLS:
        d = _last_market.get(sym)
        if not d:
            lines.append(f"• {sym} | –")
            continue
        rsi = d.get("rsi")
        price = d.get("price", 0)
        ema = d.get("ema200")
        pos = ("▲" if price > ema else "▼") if ema else "–"
        rsi_str = f"{rsi:.1f}" if rsi is not None else "n/a"
        flag = ""
        if rsi is not None:
            if rsi <= rsi_buy:   flag = " 🟢"
            elif rsi >= rsi_sell: flag = " 🔴"
        lines.append(f"• <b>{sym.replace('/USDT','').replace('/USDC','')}</b>"
                     f" | RSI: <b>{rsi_str}</b>{flag} | {pos} | {_fmt(price)}")
    lines.append("---")
    return "\n".join(lines)


def _cmd_coins():
    if not _last_market:
        return "⏳ <b>Scanning...</b> try again in ~20 seconds."
    from analyzer import get_rsi_thresholds
    rsi_buy, rsi_sell = get_rsi_thresholds()
    buy_cands = []
    sell_cands = []
    for sym, d in _last_market.items():
        rsi = d.get("rsi")
        if rsi is None: continue
        dist_buy  = rsi - rsi_buy
        dist_sell = rsi_sell - rsi
        if dist_buy  >= 0: buy_cands.append((dist_buy,  sym, rsi, d.get("price",0)))
        if dist_sell >= 0: sell_cands.append((dist_sell, sym, rsi, d.get("price",0)))
    buy_cands.sort(key=lambda x: x[0])
    sell_cands.sort(key=lambda x: x[0])
    lines = ["🔍 <b>Nearest Signal Coins</b>", "---"]
    lines.append("🟢 <b>BUY candidates:</b>")
    for dist, sym, rsi, price in buy_cands[:3]:
        short = sym.replace("/USDT","").replace("/USDC","")
        lines.append(f"  • <b>{short}</b> -- RSI: {rsi:.1f}  (Δ{dist:.1f} away)  {_fmt(price)}")
    lines.append("🔴 <b>SELL candidates:</b>")
    for dist, sym, rsi, price in sell_cands[:3]:
        short = sym.replace("/USDT","").replace("/USDC","")
        lines.append(f"  • <b>{short}</b> -- RSI: {rsi:.1f}  (Δ{dist:.1f} away)  {_fmt(price)}")
    lines.append("---")
    return "\n".join(lines)


def _cmd_trades():
    if not _open_trades:
        return "📭 <b>No open trades</b> right now."
    now = time.time()
    lines = [f"📋 <b>Open Trades ({len(_open_trades)}/{config.MAX_OPEN_TRADES})</b>",
             "---"]
    for t in _open_trades:
        sym = t.get("symbol", config.SYMBOL)
        remaining = max(0, t["due_at"] - now)
        mins, sec = divmod(int(remaining), 60)
        ep = t["entry_price"]
        cp = _last_market.get(sym, {}).get("price", ep)
        upnl = ((cp - ep) / ep * 100) if t["signal"] == "BUY" else ((ep - cp) / ep * 100)
        upnl_str = f"{upnl:+.2f}%"
        lines.append(
            f"#<b>{t['entry_id']}</b> | <b>{sym}</b> {t['signal']}\n"
            f"  Entry: {_fmt(ep)} | Now: {_fmt(cp)} | uPnL: <b>{upnl_str}</b>\n"
            f"  SL: {_fmt(t['stop_loss'])} | TP: {_fmt(t['take_profit'])}\n"
            f"  Expires: {mins}m {sec}s"
        )
    lines.append("---")
    return "\n".join(lines)


def _cmd_close(args):
    if not args:
        return "⚠️ Usage: /close [trade_id]\nExample: /close 3"
    try:
        trade_id = int(args[0])
    except ValueError:
        return "⚠️ Invalid trade ID. Usage: /close [number]"
    trade = next((t for t in _open_trades if t["entry_id"] == trade_id), None)
    if not trade:
        return f"❌ Trade #{trade_id} not found in open trades."
    from journal import close_trade as _close
    sym = trade.get("symbol", config.SYMBOL)
    cp = _last_market.get(sym, {}).get("price", trade["entry_price"])
    outcome = _close(trade_id, cp, "TIMEOUT")
    _open_trades.remove(trade)
    pnl = ((cp - trade["entry_price"]) / trade["entry_price"] * 100)
    if trade["signal"] == "SELL": pnl = -pnl
    pnl_str = f"{pnl:+.2f}%"
    return (f"✅ <b>Trade #{trade_id} closed manually</b>\n"
            f"Symbol: {sym} | {trade['signal']}\n"
            f"Entry: {_fmt(trade['entry_price'])} → Exit: {_fmt(cp)}\n"
            f"PnL: <b>{pnl_str}</b>")


def _cmd_pnl():
    from journal import load_history
    from datetime import date
    today = date.today().isoformat()
    history = load_history()
    today_trades = [e for e in history
                    if e.get("outcome_timestamp", "").startswith(today)
                    and e["outcome"] in ("SUCCESS", "FAILURE")
                    and e.get("outcome_price") is not None]
    if not today_trades:
        return "📊 <b>Today's PnL</b>\n---\nNo closed trades today yet."
    lines = ["📊 <b>Today's PnL</b>", "---"]
    total = 0.0
    for e in today_trades:
        ep = e["price"]; xp = e["outcome_price"]
        pnl = ((xp - ep) / ep * 100) if e["signal"] == "BUY" else ((ep - xp) / ep * 100)
        total += pnl
        icon = "✅" if pnl > 0 else "❌"
        short = e.get("symbol","").replace("/USDT","").replace("/USDC","")
        lines.append(f"{icon} #{e['id']} {short} {e['signal']} → <b>{pnl:+.2f}%</b>")
    lines.append("---")
    sign = "+" if total >= 0 else ""
    lines.append(f"💰 Total: <b>{sign}{total:.2f}%</b>  ({len(today_trades)} trades)")
    return "\n".join(lines)


def _cmd_history():
    from journal import load_history
    history = load_history()
    closed = [e for e in history
              if e["outcome"] in ("SUCCESS","FAILURE")
              and e.get("outcome_price") is not None]
    if not closed:
        return "📭 <b>No closed trades yet.</b>"
    last5 = closed[-5:][::-1]
    lines = ["📜 <b>Last 5 Trades</b>", "---"]
    for e in last5:
        ep = e["price"]; xp = e["outcome_price"]
        pnl = ((xp - ep) / ep * 100) if e["signal"] == "BUY" else ((ep - xp) / ep * 100)
        icon = "✅" if pnl > 0 else "❌"
        short = e.get("symbol","").replace("/USDT","").replace("/USDC","")
        reason = e.get("exit_reason","?")
        ts = e.get("outcome_timestamp","")[:16].replace("T"," ")
        lines.append(f"{icon} #{e['id']} <b>{short}</b> {e['signal']} <b>{pnl:+.2f}%</b>"
                     f"  [{reason}]  {ts}")
    lines.append("---")
    return "\n".join(lines)


def _cmd_report():
    from report import build_report
    r = build_report()
    if r is None or r.get("no_data"):
        return "📭 <b>No closed trades yet.</b> Bot is active and monitoring."
    pf = r["profit_factor"]
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    pnl_s = "+" if r["cumulative_pnl"] >= 0 else ""
    ts = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d %b %Y  %H:%M AST")
    best_line = (f"\n🥇 Best:  <b>{'+'if r['best_trade']>=0 else ''}{r['best_trade']:.2f}%</b>"
                 if r.get("best_trade") is not None else "")
    worst_line = (f"\n💀 Worst: <b>{r['worst_trade']:.2f}%</b>"
                  if r.get("worst_trade") is not None else "")
    return (f"╔══════════════════╗\n📊  PERFORMANCE REPORT\n╚══════════════════╝\n\n"
            f"🏆 Win Rate:      <b>{r['win_rate']:.1f}%</b>\n"
            f"💰 Total PnL:     <b>{pnl_s}{r['cumulative_pnl']:.2f}%</b>\n"
            f"📈 Profit Factor: <b>{pf_str}</b>\n"
            f"✅ Wins:          <b>{r['win_count']}</b>\n"
            f"❌ Losses:        <b>{r['loss_count']}</b>\n"
            f"⏳ Open Trades:   <b>{r['pending']}</b>"
            f"{best_line}{worst_line}\n"
            f"🎯 TP: {r['tp_count']}  |  🛡 SL: {r['sl_count']}  |  ⏱ Timeout: {r['timeout_count']}\n"
            f"🕐 {ts}\n══════════════════════")


def _cmd_settings():
    from analyzer import get_rsi_thresholds, is_defensive_mode
    rsi_buy, rsi_sell = get_rsi_thresholds()
    defensive = is_defensive_mode()
    mode = "⚠️ DEFENSIVE" if defensive else "✅ Normal"
    return (f"⚙️ <b>Bot Settings</b>\n---\n"
            f"📊 RSI Buy:       ≤ <b>{rsi_buy}</b>\n"
            f"📊 RSI Sell:      ≥ <b>{rsi_sell}</b>\n"
            f"🛡 Stop Loss:     <b>{config.STOP_LOSS_PCT}%</b>\n"
            f"🎯 Take Profit:   <b>{config.TAKE_PROFIT_PCT}%</b>\n"
            f"📋 Max Trades:    <b>{config.MAX_OPEN_TRADES}</b>\n"
            f"⏱ Eval Delay:    <b>{config.EVAL_DELAY//60}min</b>\n"
            f"❄️ Cooldown:      <b>{config.COOLDOWN_MINUTES}min</b>\n"
            f"🧠 MTF Required:  <b>{config.MTF_NORMAL_CONFIRM}/4</b>\n"
            f"🔰 Mode:          <b>{mode}</b>\n"
            f"---\n"
            f"🪙 Symbols: {len(config.SYMBOLS)} pairs")


def _cmd_adx():
    if not _last_market:
        return "⏳ <b>Scanning...</b> try again in ~20 seconds."
    strong = []
    for sym, d in _last_market.items():
        adx = d.get("adx")
        if adx and adx >= 25:
            short = sym.replace("/USDT","").replace("/USDC","")
            strong.append((adx, short, d.get("price",0)))
    strong.sort(reverse=True)
    if not strong:
        return "📊 <b>ADX Trend Strength</b>\nNo strong trends right now (ADX < 25 for all coins)."
    lines = ["📊 <b>Strong Trend Coins (ADX ≥ 25)</b>", "---"]
    for adx, short, price in strong:
        icon = "🔥" if adx >= 40 else "💪"
        lines.append(f"{icon} <b>{short}</b> -- ADX: <b>{adx:.1f}</b>  |  {_fmt(price)}")
    lines.append("---")
    return "\n".join(lines)




def _cmd_help():
    return (
        "🤖 <b>Available Commands</b>\n---\n"
        "/status   -- RSI &amp; price for all coins\n"
        "/coins    -- Nearest BUY/SELL candidates\n"
        "/trades   -- Open trades with uPnL\n"
        "/close [id] -- Close a trade manually\n"
        "/pnl      -- Today's profit &amp; loss\n"
        "/history  -- Last 5 closed trades\n"
        "/report   -- Full performance report\n"
        "/settings -- Bot configuration\n"
        "/adx      -- Strong trend coins\n"
        "/rsi      -- Top 20 coins by RSI\n"
        "/help     -- This message\n"
        "---\n"
        "/join     -- Request full access\n"
        "---\n"
        "Admin only:\n"
        "/addadmin [id] -- Add admin\n"
        "/removeadmin [id] -- Remove admin\n"
        "/admins -- List all admins"
    )


def _cmd_join(chat_id: str, name: str, username: str):
    import os
    from notifier import send
    owner_id = os.getenv("TELEGRAM_CHAT_ID", "")
    u = subscribers.get_user(chat_id)
    if u and u.get("status") == "member":
        return "✅ You already have full access!"
    if u and u.get("status") == "banned":
        return "❌ Your request was rejected."
    uname_str = f"@{username}" if username else "no username"
    # Notify owner
    msg = (f"📨 <b>Join Request</b>\n\n"
           f"👤 Name: {name}\n"
           f"🔗 Username: {uname_str}\n"
           f"🆔 ID: {chat_id}\n\n"
           f"To approve: /approve {chat_id}\n"
           f"To reject:  /reject {chat_id}")
    send(msg)
    return ("📨 <b>Request sent!</b>\n\n"
            "The admin will review your request.\n"
            "You will be notified once approved.")

def _cmd_approve(args, sender_id):
    import os
    from notifier import send as _send
    owner = os.getenv("TELEGRAM_CHAT_ID", "")
    if str(sender_id) != str(owner) and not config.is_admin(str(sender_id)):
        return "❌ Admins only."
    if not args:
        return "⚠️ Usage: /approve [user_id]"
    uid = str(args[0])
    if subscribers.approve_member(uid):
        try:
            asyncio.run(_reply(int(uid), "✅ <b>Access Approved!</b>\nWelcome! You now have full access."))
        except Exception:
            pass
        return f"✅ Approved: {uid}"
    return f"❌ User {uid} not found."

def _cmd_reject(args, sender_id):
    import os
    owner = os.getenv("TELEGRAM_CHAT_ID", "")
    if str(sender_id) != str(owner) and not config.is_admin(str(sender_id)):
        return "❌ Admins only."
    if not args:
        return "⚠️ Usage: /reject [user_id]"
    uid = str(args[0])
    if subscribers.reject_member(uid):
        try:
            asyncio.run(_reply(int(uid), "❌ <b>Request Rejected</b>\nContact the admin for more info."))
        except Exception:
            pass
        return f"✅ Rejected: {uid}"
    return f"❌ User {uid} not found."

def _cmd_kick(args, sender_id):
    import os
    owner = os.getenv("TELEGRAM_CHAT_ID", "")
    if str(sender_id) != str(owner) and not config.is_admin(str(sender_id)):
        return "❌ Admins only."
    if not args:
        return "⚠️ Usage: /kick [user_id]"
    uid = str(args[0])
    subscribers.remove_member(uid)
    return f"✅ Removed: {uid}"

def _cmd_members(sender_id):
    import os
    owner = os.getenv("TELEGRAM_CHAT_ID", "")
    if str(sender_id) != str(owner) and not config.is_admin(str(sender_id)):
        return "❌ Admins only."
    stats = subscribers.total_users()
    members = subscribers.list_members()
    pending = subscribers.list_pending()
    lines = ["👥 <b>Users Overview</b>", "---",
             f"✅ Members:  {stats['members']}",
             f"👀 Trial:    {stats['trial']}",
             f"❌ Banned:   {stats['banned']}",
             f"📊 Total:    {stats['total']}"]
    if pending:
        lines.append("\n⏳ <b>Pending Requests:</b>")
        for cid, u in pending[:5]:
            uname = f"@{u['username']}" if u.get('username') else u.get('name','?')
            lines.append(f"  • {uname}  ID:{cid}  /approve {cid}")
    return "\n".join(lines)


def _cmd_addadmin(args, sender_id):
    owner = os.getenv("TELEGRAM_CHAT_ID", "")
    if str(sender_id) != str(owner):
        return "❌ Only the owner can add admins."
    if not args:
        return "Usage: /addadmin [telegram_id]  Example: /addadmin 123456789"
    try:
        new_id = str(int(args[0]))
    except ValueError:
        return "⚠️ Invalid ID. Must be a number."
    config.add_admin(new_id)
    return f"✅ Admin added: {new_id}"

def _cmd_removeadmin(args, sender_id):
    owner = os.getenv("TELEGRAM_CHAT_ID", "")
    if str(sender_id) != str(owner):
        return "❌ Only the owner can remove admins."
    if not args:
        return "⚠️ Usage: /removeadmin [telegram_id]"
    try:
        rem_id = str(int(args[0]))
    except ValueError:
        return "⚠️ Invalid ID."
    if not config.remove_admin(rem_id):
        return "❌ Cannot remove the owner."
    return f"✅ Admin removed: {rem_id}"

def _cmd_admins(sender_id):
    owner = os.getenv("TELEGRAM_CHAT_ID", "")
    if str(sender_id) != str(owner):
        return "❌ Only the owner can view admins."
    admins = config.list_admins()
    if not admins:
        return "No admins yet."
    lines = ["👥 <b>Admins List</b>", "---"]
    for a in admins:
        tag = "  👑 Owner" if str(a) == str(owner) else ""
        lines.append(f"• {a}{tag}")
    return "\n".join(lines)


_DISPATCH = {
    "/status":  (lambda args: _cmd_status()),
    "/coins":   (lambda args: _cmd_coins()),
    "/trades":  (lambda args: _cmd_trades()),
    "/close":   _cmd_close,
    "/pnl":     (lambda args: _cmd_pnl()),
    "/history": (lambda args: _cmd_history()),
    "/report":  (lambda args: _cmd_report()),
    "/settings":(lambda args: _cmd_settings()),
    "/adx":     (lambda args: _cmd_adx()),
    "/rsi":     (lambda args: _cmd_rsi()),
    "/help":    (lambda args: _cmd_help()),
    "/addadmin":    lambda args: None,
    "/removeadmin": lambda args: None,
    "/admins":      lambda args: None,
    "/join":        lambda args: None,
    "/approve":     lambda args: None,
    "/reject":      lambda args: None,
    "/kick":        lambda args: None,
    "/members":     lambda args: None,
}

# ─────────────────────────────────────────────────────────────────────────────
# Telegram polling
# ─────────────────────────────────────────────────────────────────────────────

async def _get_updates(offset):
    bot = Bot(token=_TOKEN)
    async with bot:
        return await bot.get_updates(offset=offset, timeout=10, limit=20,
                                     allowed_updates=["message"])

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
    print("[COMMANDS] Command listener ready -- polling every 2s")
    while True:
        try:
            updates = asyncio.run(_get_updates(offset))
            for upd in updates:
                offset = upd.update_id + 1
                msg = upd.message or upd.edited_message
                if not msg or not msg.text:
                    continue
                cid  = str(msg.chat_id)
                name = msg.from_user.first_name if msg.from_user else ""
                uname = msg.from_user.username  if msg.from_user else ""

                # Register new user automatically
                subscribers.register_user(cid, name, uname)

                parts = msg.text.strip().split()
                word  = parts[0].lower().split("@")[0]
                args  = parts[1:]

                # /join is always allowed
                if word == "/join":
                    reply_text = _cmd_join(cid, name, uname)
                    try:
                        asyncio.run(_reply(msg.chat_id, reply_text))
                    except Exception:
                        pass
                    continue

                # Owner / admin = full access
                if config.is_admin(cid):
                    pass  # allow all
                # Member = allow non-admin commands
                elif subscribers.is_member(cid):
                    if word in ("/addadmin", "/removeadmin", "/admins", "/approve", "/reject", "/members", "/kick"):
                        try:
                            asyncio.run(_reply(msg.chat_id, "❌ This command is for admins only."))
                        except Exception:
                            pass
                        continue
                # Trial user
                elif subscribers.can_use(cid):
                    if word in ("/addadmin", "/removeadmin", "/admins", "/approve", "/reject", "/members", "/kick"):
                        try:
                            asyncio.run(_reply(msg.chat_id, "❌ This command is for admins only."))
                        except Exception:
                            pass
                        continue
                    rem = subscribers.trial_remaining(cid)
                    if rem <= 0:
                        try:
                            asyncio.run(_reply(msg.chat_id,
                                "⏳ <b>Trial ended</b>\n\n"
                                "You have used all 5 free signals.\n"
                                "Type /join to request full access."))
                        except Exception:
                            pass
                        continue
                    subscribers.increment_signals(cid)
                # Blocked / trial expired
                else:
                    if not subscribers.is_banned(cid):
                        try:
                            asyncio.run(_reply(msg.chat_id,
                                "🔒 <b>Access Required</b>\n\n"
                                "Type /join to request full access."))
                        except Exception:
                            pass
                    continue
                if "@" in word:
                    word = word.split("@")[0]
                # Member management commands
                if word == "/approve":
                    reply_text = _cmd_approve(args, msg.chat_id)
                    try: asyncio.run(_reply(msg.chat_id, reply_text))
                    except Exception: pass
                    continue
                elif word == "/reject":
                    reply_text = _cmd_reject(args, msg.chat_id)
                    try: asyncio.run(_reply(msg.chat_id, reply_text))
                    except Exception: pass
                    continue
                elif word == "/kick":
                    reply_text = _cmd_kick(args, msg.chat_id)
                    try: asyncio.run(_reply(msg.chat_id, reply_text))
                    except Exception: pass
                    continue
                elif word == "/members":
                    reply_text = _cmd_members(msg.chat_id)
                    try: asyncio.run(_reply(msg.chat_id, reply_text))
                    except Exception: pass
                    continue

                # Admin commands need sender_id
                if word == "/addadmin":
                    reply_text = _cmd_addadmin(args, msg.chat_id)
                    try:
                        asyncio.run(_reply(msg.chat_id, reply_text))
                    except Exception:
                        pass
                    continue
                elif word == "/removeadmin":
                    reply_text = _cmd_removeadmin(args, msg.chat_id)
                    try:
                        asyncio.run(_reply(msg.chat_id, reply_text))
                    except Exception:
                        pass
                    continue
                elif word == "/admins":
                    reply_text = _cmd_admins(msg.chat_id)
                    try:
                        asyncio.run(_reply(msg.chat_id, reply_text))
                    except Exception:
                        pass
                    continue

                handler = _DISPATCH.get(word)
                if handler:
                    try:
                        reply_text = handler(args)
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
        print("[COMMANDS] Telegram not configured -- command listener disabled")
        return
    t = threading.Thread(target=_poll_loop, daemon=True, name="cmd-listener")
    t.start()

# ── /rsi command -- Top 20 coins by RSI ───────────────────────────────────────
def _cmd_rsi():
    if not _last_market:
        return "⏳ <b>Scanning...</b> try again in ~20 seconds."
    from analyzer import get_rsi_thresholds
    rsi_buy, rsi_sell = get_rsi_thresholds()

    coins = []
    for sym, d in _last_market.items():
        rsi = d.get("rsi")
        if rsi is None:
            continue
        short = sym.replace("/USDT","").replace("/USDC","")
        coins.append((rsi, short, d.get("price", 0)))

    coins.sort(key=lambda x: x[0])  # sort by RSI ascending

    lines = [f"📊 <b>Top 20 Coins by RSI</b>  <i>({len(coins)} scanned)</i>",
             "---",
             "🟢 <b>Oversold (BUY zone):</b>"]

    oversold  = [(r,s,p) for r,s,p in coins if r <= rsi_buy]
    neutral   = [(r,s,p) for r,s,p in coins if rsi_buy < r < rsi_sell]
    overbought= [(r,s,p) for r,s,p in coins if r >= rsi_sell]

    if oversold:
        for rsi, short, price in oversold[:5]:
            lines.append(f"  🟢 <b>{short}</b> -- RSI: <b>{rsi:.1f}</b>  |  {_fmt(price)}")
    else:
        lines.append("  None in buy zone")

    lines.append("🔴 <b>Overbought (SELL zone):</b>")
    if overbought:
        for rsi, short, price in sorted(overbought, reverse=True)[:5]:
            lines.append(f"  🔴 <b>{short}</b> -- RSI: <b>{rsi:.1f}</b>  |  {_fmt(price)}")
    else:
        lines.append("  None in sell zone")

    lines.append("⚪ <b>Top 10 Nearest to Signal:</b>")
    neutral_sorted = sorted(neutral, key=lambda x: min(x[0]-rsi_buy, rsi_sell-x[0]))
    for rsi, short, price in neutral_sorted[:10]:
        dist_buy  = rsi - rsi_buy
        dist_sell = rsi_sell - rsi
        side = "BUY" if dist_buy <= dist_sell else "SELL"
        dist = min(dist_buy, dist_sell)
        lines.append(f"  ⚪ <b>{short}</b> -- RSI: <b>{rsi:.1f}</b>  Δ{dist:.1f}→{side}  |  {_fmt(price)}")

    lines.append("---")
    return "\n".join(lines)
