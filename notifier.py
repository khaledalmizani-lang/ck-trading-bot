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
    return datetime.now(_AST).strftime("%H:%M AST")

def _ast_date() -> str:
    return datetime.now(_AST).strftime("%d %b  •  %H:%M AST")

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
    if price >= 1:        return f"${price:,.2f}"
    elif price >= 0.01:   return f"${price:.4f}"
    elif price >= 0.0001: return f"${price:.6f}"
    else:                 return f"${price:.8f}"

def _short(symbol: str) -> str:
    return symbol.replace("/USDT","").replace("/USDC","").replace("/USD","")

def _trend_label(adx: float | None) -> str:
    if adx is None: return "n/a"
    pct = round(adx)
    if adx >= 40:   return f"{pct}% 🔥 Very Strong  قوي جداً"
    elif adx >= 25: return f"{pct}% 💪 Strong  قوي"
    else:           return f"{pct}% ⚖️ Moderate  متوسط"

# ─────────────────────────────────────────────────────────────────────────────
# Trade notifications
# ─────────────────────────────────────────────────────────────────────────────

def notify_trade_opened(signal, price, sl, tp, trade_id, symbol="BTC/USDT",
                        tf_labels=None, rsi=None, ema_above=None,
                        volume_pct=None, adx=None, signal_score=None):
    coin     = _short(symbol)
    header   = "🟢  BUY SIGNAL  •  إشارة شراء" if signal == "BUY" else "🔴  SELL SIGNAL  •  إشارة بيع"
    if signal == "BUY":
        risk, reward = abs(price - sl), abs(tp - price)
        pct_tp = ((tp - price) / price * 100)
        pct_sl = ((price - sl) / price * 100)
    else:
        risk, reward = abs(sl - price), abs(price - tp)
        pct_tp = ((price - tp) / price * 100)
        pct_sl = ((sl - price) / price * 100)
    rr        = round(reward / risk) if risk > 0 else 2
    ema_str   = "▲ Above  فوق" if ema_above is True else ("▼ Below  تحت" if ema_above is False else "n/a")
    rsi_str   = f"{rsi:.1f}" if rsi is not None else "n/a"
    rsi_icon  = "🟢" if (rsi and rsi <= 38) else ("🔴" if (rsi and rsi >= 62) else "⚪")
    vol_str   = f"{volume_pct:.1f}%" if volume_pct is not None else "n/a"
    from strategy import signal_strength_label
    quality   = signal_strength_label(signal_score) if signal_score is not None else "n/a"
    tf_line   = ""
    if tf_labels:
        tf_str  = "  ".join(f"{tf} {lbl}" for tf, lbl in tf_labels.items())
        tf_line = f"\n🕯 TF:  {tf_str}"

    text = (
        f"╔══════════════════════╗\n"
        f"{header}\n"
        f"╚══════════════════════╝\n\n"
        f"🪙 <b>{coin}</b>  •  Trade #{trade_id}\n\n"
        f"💵 Entry    دخول   ➜  <b>{_fmt_price(price)}</b>\n"
        f"🎯 Target   هدف    ➜  <b>{_fmt_price(tp)}</b>  (+{pct_tp:.1f}%)\n"
        f"🛡 Stop     وقف    ➜  <b>{_fmt_price(sl)}</b>  (-{pct_sl:.1f}%)\n"
        f"⚡ R/R    مخاطرة   ➜  1 : {rr}\n\n"
        f"══════════════════════\n"
        f"📊 RSI          {rsi_str}  {rsi_icon}\n"
        f"📈 EMA 200      {ema_str}\n"
        f"💪 Trend        {_trend_label(adx)}\n"
        f"⭐ Quality      {quality}"
        f"{tf_line}\n"
        f"══════════════════════\n"
        f"🕐 {_ast_now()}"
    )
    send(text, also_channel=True)


def notify_trade_closed(signal, entry, exit_price, pnl_pct, exit_reason,
                        trade_id, outcome, symbol="BTC/USDT"):
    coin     = _short(symbol)
    pnl_sign = "+" if pnl_pct >= 0 else ""
    pnl_str  = f"{pnl_sign}{pnl_pct:.1f}%"
    pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
    if exit_reason == "TAKE_PROFIT":
        header = "✅  TARGET REACHED  •  تم الهدف"
    elif exit_reason == "STOP_LOSS":
        header = "❌  STOP LOSS HIT  •  وقف الخسارة"
    else:
        header = "⏱  TIME LIMIT  •  انتهى الوقت"
    text = (
        f"╔══════════════════════╗\n"
        f"{header}\n"
        f"╚══════════════════════╝\n\n"
        f"🪙 <b>{coin}</b>  •  Trade #{trade_id}\n\n"
        f"📈 {signal}\n"
        f"💵 Entry  دخول   ➜  <b>{_fmt_price(entry)}</b>\n"
        f"🏁 Exit   خروج   ➜  <b>{_fmt_price(exit_price)}</b>\n"
        f"💰 PnL    ربح    ➜  <b>{pnl_str}</b>  {pnl_icon}\n\n"
        f"🕐 {_ast_now()}"
    )
    send(text, also_channel=True)


# ─────────────────────────────────────────────────────────────────────────────
# Market summary
# ─────────────────────────────────────────────────────────────────────────────

def notify_market_summary(market_data: dict, btc_dominance: float | None,
                          stablecoin_change_pct: float | None,
                          rsi_buy: int, rsi_sell: int):
    """Sent twice daily — 09:00 and 21:00 AST"""
    if not market_data:
        return

    btc  = market_data.get("BTC/USDT", {})
    eth  = market_data.get("ETH/USDT", {})

    btc_price = btc.get("price", 0)
    eth_price = eth.get("price", 0)

    # Count market states
    bullish = neutral = bearish = 0
    near_buy = []
    near_sell = []

    for sym, d in market_data.items():
        rsi = d.get("rsi")
        if rsi is None:
            continue
        short = _short(sym)
        if rsi <= rsi_buy:
            bullish += 1
            near_buy.append((rsi, short))
        elif rsi >= rsi_sell:
            bearish += 1
            near_sell.append((rsi, short))
        else:
            neutral += 1
            dist_buy  = rsi - rsi_buy
            dist_sell = rsi_sell - rsi
            if dist_buy  <= 3: near_buy.append((rsi, short))
            if dist_sell <= 3: near_sell.append((rsi, short))

    # Average RSI
    rsi_vals = [d["rsi"] for d in market_data.values() if d.get("rsi")]
    avg_rsi  = sum(rsi_vals) / len(rsi_vals) if rsi_vals else 50
    rsi_mood = "ذعر  Panic 😱" if avg_rsi < 30 else \
               "تشاؤم  Bearish 🔴" if avg_rsi < 45 else \
               "محايد  Neutral ⚪" if avg_rsi < 55 else \
               "تفاؤل  Bullish 🟢" if avg_rsi < 70 else \
               "جشع  Greed 🔥"

    dom_str = f"{btc_dominance:.1f}%" if btc_dominance else "n/a"
    sc_str  = (f"+{stablecoin_change_pct:.1f}% 🟢" if stablecoin_change_pct and stablecoin_change_pct > 0
               else (f"{stablecoin_change_pct:.1f}% 🔴" if stablecoin_change_pct else "n/a"))

    near_buy.sort(key=lambda x: x[0])
    near_sell.sort(key=lambda x: x[0], reverse=True)

    signal_lines = ""
    if near_buy:
        top = near_buy[0]
        signal_lines += f"\n🟢 {top[1]}  RSI {top[0]:.1f}  ← قريب شراء"
    if near_sell:
        top = near_sell[0]
        signal_lines += f"\n🔴 {top[1]}  RSI {top[0]:.1f}  ← قريب بيع"

    text = (
        f"╔══════════════════════╗\n"
        f"🌍  Market Summary  •  ملخص السوق\n"
        f"       {_ast_date()}\n"
        f"╚══════════════════════╝\n\n"
        f"₿ BTC    <b>{_fmt_price(btc_price)}</b>    Dom {dom_str}\n"
        f"Ξ ETH    <b>{_fmt_price(eth_price)}</b>\n\n"
        f"━━━━━━ حالة السوق ━━━━━━\n"
        f"🟢 صاعد    <b>{bullish}</b> عملة\n"
        f"🔴 هابط    <b>{bearish}</b> عملة\n"
        f"⚪ محايد   <b>{neutral}</b> عملة\n\n"
        f"━━━━━━ مؤشرات ━━━━━━\n"
        f"📊 RSI عام     {rsi_mood}  ({avg_rsi:.0f})\n"
        f"₿ BTC Dom      {dom_str}\n"
        f"💵 تدفق USDT   {sc_str}\n"
        f"\n━━━━━━ أقرب إشارة ━━━━━━"
        f"{signal_lines}\n\n"
        f"🕐 {_ast_now()}"
    )
    send(text, also_channel=True)


# ─────────────────────────────────────────────────────────────────────────────
# Signal approaching alert
# ─────────────────────────────────────────────────────────────────────────────

def notify_signal_approaching(symbol: str, rsi: float, direction: str,
                               distance: float, price: float):
    coin = _short(symbol)
    side_ar = "شراء" if direction == "BUY" else "بيع"
    icon    = "🟡" if direction == "BUY" else "🟠"
    text = (
        f"{icon} <b>Signal Approaching  •  إشارة قريبة</b>\n\n"
        f"🪙 <b>{coin}</b>\n"
        f"📊 RSI:  <b>{rsi:.1f}</b>  (Δ{distance:.1f} → {direction} {side_ar})\n"
        f"💵 Price: {_fmt_price(price)}\n"
        f"🕐 {_ast_now()}"
    )
    send(text, also_channel=True)


# ─────────────────────────────────────────────────────────────────────────────
# BTC big move alert
# ─────────────────────────────────────────────────────────────────────────────

def notify_btc_big_move(change_pct: float, price: float):
    direction = "ارتفع  Pumped 🚀" if change_pct > 0 else "انخفض  Dumped 📉"
    icon      = "🚀" if change_pct > 0 else "📉"
    text = (
        f"╔══════════════════════╗\n"
        f"{icon}  BTC Big Move  •  حركة كبيرة\n"
        f"╚══════════════════════╝\n\n"
        f"₿ BTC  {direction}\n"
        f"📈 Change:  <b>{change_pct:+.1f}%</b> في ساعة\n"
        f"💵 Price:   <b>{_fmt_price(price)}</b>\n\n"
        f"⚠️ قد يؤثر على السوق\n"
        f"🕐 {_ast_now()}"
    )
    send(text, also_channel=True)


# ─────────────────────────────────────────────────────────────────────────────
# BTC dominance change alert
# ─────────────────────────────────────────────────────────────────────────────

def notify_btc_dominance_change(old_dom: float, new_dom: float):
    change = new_dom - old_dom
    icon   = "📈" if change > 0 else "📉"
    ar     = "ارتفع" if change > 0 else "انخفض"
    text = (
        f"{icon} <b>BTC Dominance  •  هيمنة BTC</b>\n\n"
        f"₿ {ar} من <b>{old_dom:.1f}%</b> إلى <b>{new_dom:.1f}%</b>\n"
        f"تغيير: <b>{change:+.1f}%</b>\n"
        f"🕐 {_ast_now()}"
    )
    send(text, also_channel=True)


# ─────────────────────────────────────────────────────────────────────────────
# Daily confirmation
# ─────────────────────────────────────────────────────────────────────────────

def notify_daily_confirmation(open_trades: int, daily_trades: int,
                               daily_pnl: float, symbols_count: int):
    pnl_s    = "+" if daily_pnl >= 0 else ""
    pnl_icon = "🟢" if daily_pnl >= 0 else "🔴"
    text = (
        f"✅ <b>Bot Active  •  البوت يعمل</b>\n\n"
        f"🪙 Monitoring  <b>{symbols_count}</b> pairs  •  عملة\n"
        f"📋 Open Trades  <b>{open_trades}</b>\n"
        f"📊 Today Trades  <b>{daily_trades}</b>\n"
        f"💰 Today PnL  <b>{pnl_s}{daily_pnl:.2f}%</b>  {pnl_icon}\n\n"
        f"🕐 {_ast_now()}"
    )
    send(text, also_channel=False)


# ─────────────────────────────────────────────────────────────────────────────
# Inactivity alert
# ─────────────────────────────────────────────────────────────────────────────

def notify_inactivity(hours: int):
    text = (
        f"⚠️ <b>No Trades  •  لا توجد صفقات</b>\n\n"
        f"البوت لم يفتح أي صفقة منذ <b>{hours}</b> ساعة\n"
        f"Bot has not opened a trade in <b>{hours}h</b>\n\n"
        f"السوق في وضع انتظار أو الشروط غير متوفرة\n"
        f"🕐 {_ast_now()}"
    )
    send(text)


# ─────────────────────────────────────────────────────────────────────────────
# Existing notifications
# ─────────────────────────────────────────────────────────────────────────────

def notify_hourly_report(win_rate, profit_factor, cumulative_pnl, closed,
                         wins, losses, pending, best_trade=None,
                         worst_trade=None, btc_dominance=None):
    pf_str   = "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}"
    pnl_s    = "+" if cumulative_pnl >= 0 else ""
    pnl_icon = "🟢" if cumulative_pnl >= 0 else "🔴"
    best_line  = (f"\n🥇 Best   أفضل   ➜  <b>{'+'if best_trade>=0 else ''}{best_trade:.2f}%</b>"
                  if best_trade is not None else "")
    worst_line = (f"\n💀 Worst  أسوأ   ➜  <b>{worst_trade:.2f}%</b>"
                  if worst_trade is not None else "")
    dom_line   = (f"\n₿ BTC Dom  ➜  <b>{btc_dominance:.1f}%</b>"
                  if btc_dominance is not None else "")
    text = (
        f"╔══════════════════════╗\n"
        f"📊  Performance Report  •  تقرير الأداء\n"
        f"╚══════════════════════╝\n\n"
        f"🏆 Win Rate   نسبة الفوز  ➜  <b>{win_rate:.1f}%</b>\n"
        f"💰 Total PnL  إجمالي     ➜  <b>{pnl_s}{cumulative_pnl:.2f}%</b>  {pnl_icon}\n"
        f"📈 Profit Factor         ➜  <b>{pf_str}</b>\n"
        f"✅ Wins   فوز            ➜  <b>{wins}</b>\n"
        f"❌ Losses  خسارة         ➜  <b>{losses}</b>\n"
        f"⏳ Open  مفتوح           ➜  <b>{pending}</b>"
        f"{best_line}{worst_line}{dom_line}\n\n"
        f"🕐 {_ast_now()}"
    )
    send(text, also_channel=True)


def notify_no_trades_yet():
    send(
        f"📭 <b>No Trades Yet  •  لا توجد صفقات بعد</b>\n"
        f"البوت يراقب السوق  •  Bot is monitoring\n"
        f"🕐 {_ast_now()}"
    )


def notify_weekly_report(win_rate, cumulative_pnl, profit_factor, wins, losses,
                         best_trade, worst_trade, timeouts, tp_count,
                         sl_count, total_closed):
    pf_str   = "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}"
    pnl_s    = "+" if cumulative_pnl >= 0 else ""
    pnl_icon = "🟢" if cumulative_pnl >= 0 else "🔴"
    bs       = "+" if best_trade >= 0 else ""
    text = (
        f"╔══════════════════════╗\n"
        f"📅  Weekly Report  •  التقرير الأسبوعي\n"
        f"╚══════════════════════╝\n\n"
        f"🏆 Win Rate   نسبة الفوز  ➜  <b>{win_rate:.1f}%</b>\n"
        f"💰 Total PnL  إجمالي     ➜  <b>{pnl_s}{cumulative_pnl:.2f}%</b>  {pnl_icon}\n"
        f"📈 Profit Factor         ➜  <b>{pf_str}</b>\n"
        f"✅ Wins                  ➜  <b>{wins}</b>\n"
        f"❌ Losses                ➜  <b>{losses}</b>\n"
        f"🥇 Best   أفضل          ➜  <b>{bs}{best_trade:.2f}%</b>\n"
        f"💀 Worst  أسوأ          ➜  <b>{worst_trade:.2f}%</b>\n"
        f"🎯 TP Hit               ➜  <b>{tp_count}</b>\n"
        f"🛡 SL Hit               ➜  <b>{sl_count}</b>\n"
        f"⏱ Timeout              ➜  <b>{timeouts}</b>\n\n"
        f"🕐 {_ast_now()}"
    )
    send(text, also_channel=True)


def notify_daily_loss_pause():
    send(
        f"╔══════════════════════╗\n"
        f"⚠️  Trading Paused  •  إيقاف التداول\n"
        f"╚══════════════════════╝\n\n"
        f"📛 Daily Loss Limit  •  حد الخسارة اليومي\n"
        f"🔄 Resumes Tomorrow  •  يستأنف غداً\n\n"
        f"🕐 {_ast_now()}",
        also_channel=True
    )


def notify_autopause_losses(count=4):
    send(
        f"╔══════════════════════╗\n"
        f"⚠️  Trading Paused  •  إيقاف التداول\n"
        f"╚══════════════════════╝\n\n"
        f"📛 {count} Consecutive Losses  •  خسائر متتالية\n"
        f"🔄 Resumes in 2 hours  •  يستأنف بعد ساعتين\n\n"
        f"🕐 {_ast_now()}",
        also_channel=True
    )


def notify_volume_alert(level):
    if level == "extreme":
        header = "⚡  Extreme Volume  •  حجم ضخم جداً"
        body   = "Massive trading activity  •  نشاط تداول هائل"
    elif level == "strong":
        header = "🔥  Strong Volume  •  حجم قوي"
        body   = "Heavy activity – big move incoming  •  تحرك كبير محتمل"
    else:
        header = "📈  High Volume  •  حجم مرتفع"
        body   = "Unusual activity detected  •  نشاط غير عادي"
    send(
        f"╔══════════════════════╗\n{header}\n╚══════════════════════╝\n\n"
        f"{body}\n🕐 {_ast_now()}",
        also_channel=True
    )


def notify_pump_alert(symbol: str, change: float, price_str: str):
    coin = _short(symbol)
    send(
        f"╔══════════════════════╗\n"
        f"🚀  Pump Alert  •  ارتفاع مفاجئ\n"
        f"╚══════════════════════╝\n\n"
        f"🪙 <b>{coin}/USDT</b>\n"
        f"📈 Up  <b>{change:.1f}%</b>  في ساعة  in 1h\n"
        f"💵 Price: {price_str}\n\n"
        f"🕐 {_ast_now()}",
        also_channel=True
    )


def notify_connection_issue():
    send(
        f"╔══════════════════════╗\n"
        f"🔌  Connection Issue  •  مشكلة اتصال\n"
        f"╚══════════════════════╝\n\n"
        f"Retrying in 60s  •  إعادة المحاولة\n"
        f"🕐 {_ast_now()}",
        also_channel=True
    )
