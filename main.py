import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta

import config
import coingecko
from fetcher import fetch_market_data, fetch_mtf_indicators
from strategy import check_signal, evaluate_mtf, tf_labels_to_str, calculate_atr_levels, update_trailing_stop
import balance as bal
from journal import log_signal, close_trade, get_pending_trades, load_history
from analyzer import (
    analyze_performance, get_rsi_thresholds, get_check_interval,
    is_defensive_mode, record_exit,
)
from report import generate_silent_report, build_report
from notifier import (
    notify_trade_opened, notify_trade_closed, notify_hourly_report,
    notify_no_trades_yet, notify_weekly_report, send,
    notify_daily_loss_pause, notify_autopause_losses,
    notify_volume_alert, notify_pump_alert, notify_connection_issue,
    notify_market_summary, notify_signal_approaching, notify_btc_big_move,
    notify_btc_dominance_change, notify_daily_confirmation, notify_inactivity,
)
import commands

open_trades = []          # list of active trades (up to MAX_OPEN_TRADES)
cooldown_until: float = 0.0
_mtf_cache:  dict = {}
MTF_CACHE_TTL: int = 300

DAILY_MAX_TRADES  = config.DAILY_MAX_TRADES
DAILY_LOSS_LIMIT  = config.DAILY_LOSS_LIMIT

_day_marker:            str   = ""
_daily_trades:          int   = 0
_daily_pnl:             float = 0.0
_daily_loss_notified:   bool  = False
_daily_trades_notified: bool  = False
_consecutive_errors:    int   = 0
_volume_spike_cooldown: float = 0.0
_consecutive_losses:    int   = 0
_autopause_until:       float = 0.0
_loss_streak_notified:  bool  = False
_last_trade_ts:         float = time.time()   # for inactivity check
_btc_dom_prev:          float = 0.0           # for dominance change alert
_btc_price_prev:        float = 0.0           # for BTC big move alert
_signal_approach_sent:  dict  = {}            # cooldown per symbol


def _check_and_reset_day():
    global _day_marker, _daily_trades, _daily_pnl, _daily_loss_notified, _daily_trades_notified
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _day_marker:
        _day_marker = today
        _daily_trades = 0
        _daily_pnl = 0.0
        _daily_loss_notified = False
        _daily_trades_notified = False


def monitor_open_trades(prices: dict):
    """Check ALL open trades against SL/TP/timeout — runs every tick."""
    global cooldown_until, _daily_pnl, _consecutive_losses, _autopause_until, _loss_streak_notified
    now = time.time()
    still_open = []

    for trade in open_trades:
        sym = trade.get("symbol", config.SYMBOL)
        current_price = prices.get(sym)
        if current_price is None or current_price <= 0:
            still_open.append(trade)
            continue

        # Update trailing stop
        trade = update_trailing_stop(trade, current_price)

        exit_reason = None
        sig = trade["signal"]

        if sig == "BUY":
            if current_price <= trade["stop_loss"]:
                in_profit = current_price > trade["entry_price"]
                exit_reason = "TRAILING_STOP" if in_profit else "STOP_LOSS"
            elif current_price >= trade["take_profit"]: exit_reason = "TAKE_PROFIT"
        else:
            if current_price >= trade["stop_loss"]:
                in_profit = current_price < trade["entry_price"]
                exit_reason = "TRAILING_STOP" if in_profit else "STOP_LOSS"
            elif current_price <= trade["take_profit"]: exit_reason = "TAKE_PROFIT"

        if exit_reason is None and now >= trade["due_at"]:
            exit_reason = "TIMEOUT"

        if exit_reason:
            outcome = close_trade(trade["entry_id"], current_price, exit_reason)
            if outcome == "ALREADY_CLOSED":
                continue

            pnl_pct = ((current_price - trade["entry_price"]) / trade["entry_price"]) * 100
            if sig == "SELL":
                pnl_pct = -pnl_pct

            icon = {"TAKE_PROFIT": "✓", "STOP_LOSS": "✗", "TIMEOUT": "⏱"}.get(exit_reason, "?")
            ts_c = datetime.now(timezone.utc).strftime("%H:%M:%S")
            print(f"[{ts_c}] [{icon} CLOSED #{trade['entry_id']:>3}]  {sym} {sig} @ {trade['entry_price']}"
                  f"  →  {exit_reason} @ {current_price}  ({pnl_pct:+.2f}%)  {outcome}")

            _daily_pnl += pnl_pct
            bal.close_trade(trade.get("entry_id", ""), pnl_pct)
            cooldown_until = time.time() + config.COOLDOWN_MINUTES * 60
            record_exit(exit_reason)

            if exit_reason == "STOP_LOSS":
                _consecutive_losses += 1
                if _consecutive_losses >= config.CONSECUTIVE_LOSS_PAUSE and not _loss_streak_notified:
                    _autopause_until = time.time() + config.AUTO_PAUSE_DURATION
                    _loss_streak_notified = True
                    notify_autopause_losses(config.CONSECUTIVE_LOSS_PAUSE)
            elif exit_reason == "TAKE_PROFIT":
                _consecutive_losses = 0
                _loss_streak_notified = False

            notify_trade_closed(signal=sig, entry=trade["entry_price"], exit_price=current_price,
                                pnl_pct=pnl_pct, exit_reason=exit_reason, trade_id=trade["entry_id"],
                                outcome=outcome, symbol=sym)
        else:
            still_open.append(trade)

    open_trades.clear()
    open_trades.extend(still_open)


def _open_slots() -> int:
    """How many more trades can we open right now."""
    return config.MAX_OPEN_TRADES - len(open_trades)


def _symbol_already_open(sym: str) -> bool:
    """True if we already have an open trade on this symbol."""
    return any(t["symbol"] == sym for t in open_trades)


def main():
    global _daily_trades, _daily_trades_notified, _daily_loss_notified, \
           _consecutive_errors, _volume_spike_cooldown, \
           _consecutive_losses, _autopause_until, _loss_streak_notified

    rsi_buy, rsi_sell = get_rsi_thresholds()
    defensive = is_defensive_mode()
    interval = get_check_interval()
    mode_tag = " [DEFENSIVE]" if defensive else ""
    sym_list = ", ".join(config.SYMBOLS)
    print(f"[EXECUTION MODE{mode_tag}] Monitoring {len(config.SYMBOLS)} symbols: {sym_list}"
          f" | RSI ≤{rsi_buy}/≥{rsi_sell} | EMA 200"
          f" | SL {config.STOP_LOSS_PCT}% / TP {config.TAKE_PROFIT_PCT}%"
          f" | Max trades: {config.MAX_OPEN_TRADES} | {interval}s interval")

    _pending = get_pending_trades()
    if _pending:
        open_trades.extend(_pending)
        now_ts = time.time()
        for _t in _pending:
            _remaining = max(0, _t["due_at"] - now_ts)
            print(f"[STARTUP] Restored #{_t['entry_id']:>3} {_t['symbol']} {_t['signal']}"
                  f"  timeout in {_remaining/60:.1f}min"
                  f"  SL={_t['stop_loss']}  TP={_t['take_profit']}")
        print(f"[STARTUP] Total restored: {len(_pending)} open trade(s)")

    # ── Hourly report thread ───────────────────────────────────────────────
    def _hourly_report_loop():
        try:
            _sc_seed = coingecko.fetch_stablecoin_volumes()
            prev_sc = _sc_seed["combined"] if _sc_seed else 0.0
        except Exception:
            prev_sc = 0.0
        first_run = True
        while True:
            time.sleep(1800 if first_run else 43200)
            first_run = False
            try:
                generate_silent_report()
                r = build_report()
                btc_dom = coingecko.fetch_btc_dominance()
                # BTC dominance change alert
                global _btc_dom_prev
                if btc_dom and _btc_dom_prev > 0 and abs(btc_dom - _btc_dom_prev) >= 2:
                    notify_btc_dominance_change(_btc_dom_prev, btc_dom)
                if btc_dom:
                    _btc_dom_prev = btc_dom
                if r is None or r.get("no_data"):
                    notify_no_trades_yet()
                else:
                    notify_hourly_report(win_rate=r["win_rate"], profit_factor=r["profit_factor"],
                        cumulative_pnl=r["cumulative_pnl"], closed=r["total_closed"],
                        wins=r["win_count"], losses=r["loss_count"], pending=r["pending"],
                        best_trade=r.get("best_trade"), worst_trade=r.get("worst_trade"),
                        btc_dominance=btc_dom)
                sc = coingecko.fetch_stablecoin_volumes()
                if sc:
                    combined = sc["combined"]
                    if prev_sc > 0 and combined > prev_sc * 1.20:
                        send("💵 Stablecoin Inflow Detected – Possible Market Pump Incoming", also_channel=True)
                    prev_sc = combined
            except Exception as exc:
                print(f"[REPORT ERROR] {exc}")

    threading.Thread(target=_hourly_report_loop, daemon=True).start()

    # ── Weekly report thread ───────────────────────────────────────────────
    def _seconds_until_sunday_midnight():
        now = datetime.now(timezone.utc)
        days_ahead = (6 - now.weekday()) % 7
        candidate = (now + timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        if candidate <= now:
            candidate += timedelta(weeks=1)
        return (candidate - now).total_seconds()

    def _trade_pnl(entry):
        ep = entry.get("price", 0); xp = entry.get("outcome_price", 0)
        if ep <= 0 or xp is None: return 0.0
        return (xp - ep) / ep * 100 if entry["signal"] == "BUY" else (ep - xp) / ep * 100

    def _weekly_report_loop():
        while True:
            time.sleep(_seconds_until_sunday_midnight())
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(weeks=1)
                history = load_history()
                closed = [e for e in history if e["outcome"] in ("SUCCESS","FAILURE")
                          and e.get("outcome_price") is not None and e.get("outcome_timestamp")
                          and datetime.fromisoformat(e["outcome_timestamp"]).replace(tzinfo=timezone.utc) >= cutoff]
                if not closed:
                    send("📅 <b>Weekly Report</b> — No trades closed this week.")
                else:
                    returns = [_trade_pnl(e) for e in closed]
                    wins = [r for r in returns if r > 0]
                    losses = [r for r in returns if r <= 0]
                    gross_l = abs(sum(losses))
                    pf = (sum(wins) / gross_l) if gross_l > 0 else float("inf")
                    notify_weekly_report(win_rate=len(wins)/len(returns)*100, cumulative_pnl=sum(returns),
                        profit_factor=pf, wins=len(wins), losses=len(losses), best_trade=max(returns),
                        worst_trade=min(returns),
                        timeouts=sum(1 for e in closed if e.get("exit_reason")=="TIMEOUT"),
                        tp_count=sum(1 for e in closed if e.get("exit_reason")=="TAKE_PROFIT"),
                        sl_count=sum(1 for e in closed if e.get("exit_reason")=="STOP_LOSS"),
                        total_closed=len(closed))
            except Exception as exc:
                print(f"[WEEKLY ERROR] {exc}")

    threading.Thread(target=_weekly_report_loop, daemon=True, name="weekly-report").start()

    # ── Market summary loop (09:00 and 21:00 AST) ─────────────────────────
    def _market_summary_loop():
        while True:
            now_ast = datetime.now(timezone(timedelta(hours=3)))
            # Next 09:00 or 21:00 AST
            target_hours = [9, 21]
            secs_to_wait = 86400
            for h in target_hours:
                candidate = now_ast.replace(hour=h, minute=0, second=0, microsecond=0)
                if candidate <= now_ast:
                    candidate = candidate + timedelta(days=1)
                diff = (candidate - now_ast).total_seconds()
                if diff < secs_to_wait:
                    secs_to_wait = diff
            time.sleep(secs_to_wait)
            try:
                from analyzer import get_rsi_thresholds as _get_rsi
                _rb, _rs = _get_rsi()
                btc_dom = coingecko.fetch_btc_dominance()
                sc = coingecko.fetch_stablecoin_volumes()
                sc_change = None
                if sc:
                    sc_change = ((sc["combined"] - sc.get("combined", 0)) / max(sc.get("combined", 1), 1)) * 100
                notify_market_summary(
                    market_data=_last_market_snapshot,
                    btc_dominance=btc_dom,
                    stablecoin_change_pct=sc_change,
                    rsi_buy=_rb, rsi_sell=_rs,
                )
            except Exception as exc:
                print(f"[MARKET SUMMARY ERROR] {exc}")

    threading.Thread(target=_market_summary_loop, daemon=True, name="market-summary").start()

    # ── Daily confirmation (every 24h at 08:00 AST) ───────────────────────
    def _daily_confirm_loop():
        while True:
            now_ast = datetime.now(timezone(timedelta(hours=3)))
            candidate = now_ast.replace(hour=8, minute=0, second=0, microsecond=0)
            if candidate <= now_ast:
                candidate += timedelta(days=1)
            time.sleep((candidate - now_ast).total_seconds())
            try:
                notify_daily_confirmation(
                    open_trades=len(open_trades),
                    daily_trades=_daily_trades,
                    daily_pnl=_daily_pnl,
                    symbols_count=len(config.SYMBOLS),
                )
            except Exception as exc:
                print(f"[DAILY CONFIRM ERROR] {exc}")

    threading.Thread(target=_daily_confirm_loop, daemon=True, name="daily-confirm").start()

    # ── Inactivity check (every hour) ─────────────────────────────────────
    def _inactivity_loop():
        while True:
            time.sleep(3600)
            try:
                hours_inactive = int((time.time() - _last_trade_ts) / 3600)
                if hours_inactive >= 24:
                    notify_inactivity(hours_inactive)
            except Exception as exc:
                print(f"[INACTIVITY ERROR] {exc}")

    threading.Thread(target=_inactivity_loop, daemon=True, name="inactivity").start()

    # ── Pump alert thread ──────────────────────────────────────────────────
    def _pump_alert_loop():
        pump_sent = {}
        while True:
            time.sleep(900)
            now = time.time()
            pump_sent = {k: v for k, v in pump_sent.items() if v > now}
            coins = coingecko.fetch_top50_1h_changes()
            if not coins:
                continue
            # ── Filter: only top-50 by market cap (higher liquidity) ──
            top50 = coins[:50]
            for coin in top50:
                sym = coin["symbol"]
                change = coin["change_1h"]
                price = coin.get("price", 0)
                if change > 5.0 and sym not in pump_sent:
                    if price >= 1: price_str = f"${price:,.2f}"
                    elif price >= 0.01: price_str = f"${price:.4f}"
                    elif price >= 0.0001: price_str = f"${price:.6f}"
                    else: price_str = f"${price:.8f}"
                    notify_pump_alert(coin["name"], change, price_str)
                    pump_sent[sym] = now + 3600

    threading.Thread(target=_pump_alert_loop, daemon=True).start()

    commands.configure(open_trades)
    commands.start()

    _ast_now = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d %b %Y %H:%M AST")
    send(f"🟢 <b>Bot Online</b> — {_ast_now}\n"
         f"Monitoring {len(config.SYMBOLS)} pairs | RSI ≤{rsi_buy}/{rsi_sell}≥ | "
         f"MTF {config.MTF_NORMAL_CONFIRM}/4 | Max Trades: {config.MAX_OPEN_TRADES} | "
         f"SL {config.STOP_LOSS_PCT}%  TP {config.TAKE_PROFIT_PCT}%", also_channel=True)

    _live_test_sent = False
    _last_market_snapshot: dict = {}

    while True:
        _check_and_reset_day()
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

        market_data: dict = {}
        for sym in config.SYMBOLS:
            try:
                market_data[sym] = fetch_market_data(sym)
            except Exception as fetch_err:
                print(f"[{ts}] [ERROR] {sym}: {fetch_err}")
            time.sleep(1)

        if not market_data:
            _consecutive_errors += 1
            if _consecutive_errors >= 3:
                notify_connection_issue()
                time.sleep(60)
                _consecutive_errors = 0
            time.sleep(get_check_interval())
            continue

        if len(market_data) == len(config.SYMBOLS):
            _consecutive_errors = 0

        # ── Live test (once) ───────────────────────────────────────────────
        if not _live_test_sent and market_data:
            _live_test_sent = True
            _best_dist = float("inf"); _best_coin = None; _best_side = ""
            _rsi_buy_t, _rsi_sell_t = get_rsi_thresholds()
            for _s, _d in market_data.items():
                _rv = _d.get("rsi")
                if _rv is None: continue
                _dist = min(abs(_rv - _rsi_buy_t), abs(_rv - _rsi_sell_t))
                if _dist < _best_dist:
                    _best_dist = _dist; _best_coin = (_s, _d)
                    _best_side = "BUY" if abs(_rv - _rsi_buy_t) <= abs(_rv - _rsi_sell_t) else "SELL"
            if _best_coin:
                _sc, _dc = _best_coin
                _rv = _dc.get("rsi"); _ev = _dc.get("ema200"); _av = _dc.get("adx"); _pv = _dc.get("price", 0)
                _ep = ("▲ABV" if _pv > _ev else "▼BLW") if _ev else "n/a"
                _ast = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%H:%M AST")
                send(f"📡 <b>Live Market Test — {_ast}</b>\n"
                     f"Nearest signal: <b>{_sc}</b> → {_best_side}\n"
                     f"RSI: <b>{_rv:.1f}</b> (threshold ≤{_rsi_buy_t}/≥{_rsi_sell_t})  Δ{_best_dist:.1f} away\n"
                     f"EMA 200: {_ep}  |  ADX: {f'{_av:.1f}' if _av is not None else 'n/a'}\n"
                     f"Price: {_pv}\n✅ Telegram notifications working", also_channel=True)

        try:
            prices_now = {sym: d["price"] for sym, d in market_data.items()}
            monitor_open_trades(prices_now)
            commands.update_snapshot(market_data)
            _last_market_snapshot.clear()
            _last_market_snapshot.update(market_data)

            # ── Signal approaching check ──────────────────────────────────────
            from analyzer import get_rsi_thresholds as _grt
            _rb, _rs = _grt()
            _approach_now = time.time()
            for _sym, _d in market_data.items():
                _rv = _d.get("rsi")
                _pv = _d.get("price", 0)
                if _rv is None: continue
                _dist_buy  = _rv - _rb
                _dist_sell = _rs - _rv
                _approach_key = None
                _approach_dir = None
                if 0 < _dist_buy <= 3:
                    _approach_key = f"{_sym}_BUY"
                    _approach_dir = "BUY"
                    _approach_dist = _dist_buy
                elif 0 < _dist_sell <= 3:
                    _approach_key = f"{_sym}_SELL"
                    _approach_dir = "SELL"
                    _approach_dist = _dist_sell
                if _approach_key and _approach_now - _signal_approach_sent.get(_approach_key, 0) >= 3600:
                    notify_signal_approaching(_sym, _rv, _approach_dir, _approach_dist, _pv)
                    _signal_approach_sent[_approach_key] = _approach_now

            # ── BTC big move check ────────────────────────────────────────────────
            global _btc_price_prev
            _btc_d = market_data.get("BTC/USDT", {})
            _btc_now_price = _btc_d.get("price", 0)
            if _btc_price_prev > 0 and _btc_now_price > 0:
                _btc_chg = (_btc_now_price - _btc_price_prev) / _btc_price_prev * 100
                if abs(_btc_chg) >= 5:
                    notify_btc_big_move(_btc_chg, _btc_now_price)
                    _btc_price_prev = _btc_now_price
            elif _btc_now_price > 0:
                _btc_price_prev = _btc_now_price

            # ── Volume spike check ─────────────────────────────────────────
            now_ts = time.time()
            if now_ts >= _volume_spike_cooldown:
                for _sym, _d in market_data.items():
                    _cv = _d.get("candle_volume", 0); _avg = _d.get("avg_volume_20", 0)
                    if _avg <= 0: continue
                    _pct = (_cv / _avg - 1) * 100
                    if _pct >= 500:   notify_volume_alert("extreme"); _volume_spike_cooldown = now_ts + 3600; break
                    elif _pct >= 300: notify_volume_alert("strong");  _volume_spike_cooldown = now_ts + 3600; break
                    elif _pct >= 150: notify_volume_alert("high");    _volume_spike_cooldown = now_ts + 3600; break

            defensive = is_defensive_mode()
            now = time.time()

            # ── Show all open trades status ────────────────────────────────
            if open_trades:
                for trade in open_trades:
                    sym = trade.get("symbol", config.SYMBOL)
                    ep = trade["entry_price"]; cp = prices_now.get(sym, ep)
                    upnl = ((cp - ep) / ep * 100) if trade["signal"] == "BUY" else ((ep - cp) / ep * 100)
                    print(f"[{ts}] [OPEN #{trade['entry_id']:>3}]  {sym} {trade['signal']}"
                          f"  Entry: {ep}  Now: {cp}  uPnL: {upnl:+.2f}%")

            # ── Gate checks ────────────────────────────────────────────────
            if now < cooldown_until and _open_slots() == 0:
                remaining = int(cooldown_until - now)
                print(f"[{ts}] [COOLDOWN] {remaining}s remaining before next signal")
            elif now < _autopause_until:
                remaining = int(_autopause_until - now)
                print(f"[{ts}] [AUTO-PAUSE] {remaining}s remaining ({remaining//60}m)")
            elif _daily_pnl <= DAILY_LOSS_LIMIT:
                if not _daily_loss_notified:
                    notify_daily_loss_pause(); _daily_loss_notified = True
            elif _daily_trades >= DAILY_MAX_TRADES:
                if not _daily_trades_notified:
                    send(f"📊 Daily Trade Limit Reached ({DAILY_MAX_TRADES}) – Bot Paused Until Tomorrow")
                    _daily_trades_notified = True
            elif commands.is_paused():
                pass
            elif _open_slots() <= 0:
                print(f"[{ts}] [FULL] {config.MAX_OPEN_TRADES}/{config.MAX_OPEN_TRADES} trades open — waiting for slot")
            else:
                # ── Scan for signals ───────────────────────────────────────
                rsi_buy_max, rsi_sell_min = get_rsi_thresholds()
                mtf_required = (config.MTF_CAUTIOUS_CONFIRM
                                if _consecutive_losses >= config.CONSECUTIVE_LOSS_CAUTION
                                else config.MTF_NORMAL_CONFIRM)

                # Collect ALL qualified candidates (not just best one)
                candidates = []
                diag = []; n_rsi_pass = 0; n_ema_pass = 0; n_candidates = 0

                for sym, d in market_data.items():
                    if _symbol_already_open(sym):
                        continue   # skip symbols with open trade
                    short = sym.replace("/USDT","").replace("/USDC","")
                    price = d.get("price", 0)
                    rsi_v = d.get("rsi"); ema_v = d.get("ema200"); adx_v = d.get("adx")
                    rsi_s = f"{rsi_v:.1f}" if rsi_v is not None else "n/a"
                    adx_s = f"{adx_v:.1f}" if adx_v is not None else "n/a"
                    pos_s = ("▲ABV" if price > ema_v else "▼BLW") if ema_v is not None else "EMA:n/a"
                    macd_h = d.get("macd_hist")
                    sk = d.get("stoch_k"); sd = d.get("stoch_d")
                    vol_pct = d.get("volume_pct")
                    sig = check_signal(price, rsi_v, ema_v, macd_h, sk, sd, volume_pct=vol_pct)

                    if sig == "LOW_VOLUME":
                        diag.append(f"{short}[RSI:{rsi_s} LOW_VOL:{vol_pct:.0f}%]" if vol_pct else f"{short}[LOW_VOL]"); continue
                    if sig in ("TREND_BLOCK_BUY","TREND_BLOCK_SELL"):
                        n_rsi_pass += 1; diag.append(f"{short}[RSI:{rsi_s}✓ {pos_s}✗]"); continue
                    elif sig not in ("BUY","SELL"):
                        diag.append(f"{short}[RSI:{rsi_s} {pos_s} ADX:{adx_s}]"); continue
                    if rsi_v is None:
                        diag.append(f"{short}[RSI:n/a]"); continue

                    n_rsi_pass += 1; n_ema_pass += 1; n_candidates += 1
                    score = (rsi_buy_max - rsi_v) if sig == "BUY" else (rsi_v - rsi_sell_min)
                    diag.append(f"{short}[{sig} RSI:{rsi_s} {pos_s} ADX:{adx_s} ✅]")
                    candidates.append((score, sym, sig, d))

                # Sort by strongest signal first
                candidates.sort(key=lambda x: x[0], reverse=True)

                if not candidates:
                    closest_sym = None; closest_dist = float("inf"); closest_side = ""
                    for sym in config.SYMBOLS:
                        d = market_data.get(sym, {}); rsi_v = d.get("rsi")
                        if rsi_v is None: continue
                        dist = min(rsi_v - rsi_buy_max, rsi_sell_min - rsi_v)
                        if dist < closest_dist:
                            closest_dist = dist
                            closest_sym = sym.replace("/USDT","").replace("/USDC","")
                            closest_side = "BUY" if (rsi_v - rsi_buy_max) <= (rsi_sell_min - rsi_v) else "SELL"
                    near_str = f"  →  Nearest: {closest_sym} {closest_side} (Δ{closest_dist:.1f})" if closest_sym else ""
                    slots = _open_slots()
                    print(f"[{ts}] [HOLD]{near_str}  [slots:{slots}/{config.MAX_OPEN_TRADES}  RSI✓:{n_rsi_pass} cand:{n_candidates}/13]")
                    print(f"         " + " | ".join(diag))
                else:
                    # Try to fill open slots with best candidates
                    slots_filled = 0
                    for score, best_sym, best_signal, best_data in candidates:
                        if _open_slots() <= 0:
                            break
                        if _symbol_already_open(best_sym):
                            continue

                        # MTF check
                        sym_cache = _mtf_cache.get(best_sym, {})
                        if now - sym_cache.get("ts", 0) >= MTF_CACHE_TTL:
                            try:
                                sym_cache = {"data": fetch_mtf_indicators(best_sym), "ts": now}
                                _mtf_cache[best_sym] = sym_cache
                            except Exception as exc:
                                print(f"[{ts}] [MTF ERROR] {best_sym}: {exc}")

                        confirmed_count, tf_labels = evaluate_mtf(
                            best_data["price"], sym_cache.get("data", {}), best_signal)
                        tf_str = tf_labels_to_str(tf_labels)
                        rsi_str = f"{best_data['rsi']:.1f}" if best_data.get("rsi") else "n/a"

                        if confirmed_count < mtf_required:
                            print(f"[{ts}] [MTF BLOCK] {best_sym} {best_signal} RSI {rsi_str}:"
                                  f" {confirmed_count}/{mtf_required} TF — {tf_str}")
                            continue

                        # Open trade
                        price = best_data["price"]; rsi = best_data.get("rsi")
                        volume = best_data.get("volume", 0); atr = best_data.get("atr")
                        volume_pct = best_data.get("volume_pct"); adx_val = best_data.get("adx")

                        sl_min_dist = price * config.STOP_LOSS_PCT / 100
                        tp_min_dist = price * config.TAKE_PROFIT_PCT / 100
                        atr_levels = calculate_atr_levels(price, atr)
                        if True:  # always use ATR levels (falls back to config if atr=None)
                            sl_dist = abs(price - atr_levels["sl"])
                            tp_dist = abs(atr_levels["tp"] - price)
                        else:
                            sl_dist = sl_min_dist; tp_dist = tp_min_dist

                        if best_signal == "BUY":
                            sl_price = price - sl_dist; tp_price = price + tp_dist
                        else:
                            sl_price = price + sl_dist; tp_price = price - tp_dist

                        trade_info = log_signal(best_signal, price, rsi, volume, best_sym,
                                                sl_price=sl_price, tp_price=tp_price)
                        if trade_info is None:
                            continue  # duplicate guard

                        sl = trade_info["stop_loss"]; tp = trade_info["take_profit"]
                        print(f"[{ts}] [{best_signal} SIGNAL] {best_sym} = {price}"
                              f"  RSI: {rsi_str}  SL: {sl}  TP: {tp}  TF: {tf_str}")

                        pos_size = bal.calculate_position_size()
                        bal.allocate_trade(trade_info["id"], pos_size)
                        open_trades.append({
                            "entry_id": trade_info["id"], "symbol": best_sym,
                            "signal": best_signal, "entry_price": price,
                            "stop_loss": sl, "take_profit": tp,
                            "peak_price": price,
                            "due_at": time.time() + config.EVAL_DELAY,
                            "position_size": pos_size,
                        })
                        _daily_trades += 1
                        _last_trade_ts = time.time()
                        slots_filled += 1
                        analyze_performance()

                        ema200 = best_data.get("ema200")
                        ema_above = (price > ema200) if ema200 is not None else None
                        from strategy import signal_strength, signal_strength_label
                        str_score = signal_strength(price, rsi, ema200,
                                                    best_data.get("macd_hist"),
                                                    best_data.get("stoch_k"),
                                                    best_data.get("stoch_d"), best_signal)
                        notify_trade_opened(signal=best_signal, price=price, sl=sl, tp=tp,
                                            trade_id=trade_info["id"], symbol=best_sym,
                                            tf_labels=tf_labels, rsi=rsi, ema_above=ema_above,
                                            volume_pct=volume_pct, adx=adx_val,
                                            signal_score=str_score)

        except Exception as e:
            print(f"[{ts}] [ERROR] {e}")

        time.sleep(get_check_interval())


def _enforce_single_instance():
    my_pid = os.getpid()
    killed = []
    try:
        result = subprocess.run(["pgrep", "-f", "python main.py"], capture_output=True, text=True)
        for pid_str in result.stdout.strip().splitlines():
            try:
                pid = int(pid_str)
                if pid != my_pid:
                    os.kill(pid, signal.SIGTERM)
                    killed.append(pid)
                    print(f"[STARTUP] Sent SIGTERM to old instance PID {pid}")
            except (ValueError, ProcessLookupError, PermissionError):
                pass
    except Exception as exc:
        print(f"[STARTUP] Error: {exc}")
    if not killed:
        return
    deadline = time.time() + 5.0
    remaining = list(killed)
    while remaining and time.time() < deadline:
        time.sleep(0.25)
        still = []
        for pid in remaining:
            try: os.kill(pid, 0); still.append(pid)
            except ProcessLookupError: pass
            except PermissionError: still.append(pid)
        remaining = still
    for pid in remaining:
        try: os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError): pass
    time.sleep(0.5)


if __name__ == "__main__":
    _enforce_single_instance()
    main()
