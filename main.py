import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta
from flask import Flask # إضافة Flask

# --- Flask Keep-Alive (لمنع توقف السيرفر) ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!"
def run_flask():
    app.run(host='0.0.0.0', port=10000)
threading.Thread(target=run_flask, daemon=True).start()

import config
import coingecko
from fetcher import fetch_market_data, fetch_mtf_indicators
from strategy import check_signal, evaluate_mtf, tf_labels_to_str
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
)
import commands
import server; server.start_server()

open_trades = []
cooldown_until: float = 0.0
_mtf_cache:  dict = {}
MTF_CACHE_TTL: int = 300
DAILY_MAX_TRADES  = 5
DAILY_LOSS_LIMIT  = -5.0
_day_marker:           str   = ""
_daily_trades:         int   = 0
_daily_pnl:            float = 0.0
_daily_loss_notified:  bool  = False
_daily_trades_notified: bool = False
_consecutive_errors: int = 0
_volume_spike_cooldown: float = 0.0
_doge_mtf_cache:     dict  = {}
_DOGE_MTF_TTL:       int   = 300
_DEBUG_SYM:          str   = "DOGE/USDT"
_consecutive_losses:  int   = 0
_autopause_until:     float = 0.0
_loss_streak_notified: bool = False

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
    global cooldown_until, _daily_pnl, _consecutive_losses, _autopause_until, _loss_streak_notified
    now = time.time()
    still_open = []
    for trade in open_trades:
        sym = trade.get("symbol", config.SYMBOL)
        current_price = prices.get(sym)
        if current_price is None or current_price <= 0:
            still_open.append(trade)
            continue
        exit_reason = None
        signal = trade["signal"]
        if signal == "BUY":
            if current_price <= trade["stop_loss"]:
                exit_reason = "STOP_LOSS"
            elif current_price >= trade["take_profit"]:
                exit_reason = "TAKE_PROFIT"
        else:
            if current_price >= trade["stop_loss"]:
                exit_reason = "STOP_LOSS"
            elif current_price <= trade["take_profit"]:
                exit_reason = "TAKE_PROFIT"
        if exit_reason is None and now >= trade["due_at"]:
            exit_reason = "TIMEOUT"
        if exit_reason:
            outcome = close_trade(trade["entry_id"], current_price, exit_reason)
            if outcome == "ALREADY_CLOSED":
                continue
            pnl_pct = ((current_price - trade["entry_price"]) / trade["entry_price"]) * 100
            if signal == "SELL":
                pnl_pct = -pnl_pct
            exit_icon = {"TAKE_PROFIT": "✓", "STOP_LOSS": "✗", "TIMEOUT": "⏱"}.get(exit_reason, "?")
            ts_close = datetime.now(timezone.utc).strftime("%H:%M:%S")
            print(f"[{ts_close}] [{exit_icon} CLOSED #{trade['entry_id']:>3}]  {sym} {signal} @ {trade['entry_price']}  →  {exit_reason} @ {current_price}  ({pnl_pct:+.2f}%)  {outcome}")
            _daily_pnl += pnl_pct
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
            notify_trade_closed(signal=signal, entry=trade["entry_price"], exit_price=current_price,
                                pnl_pct=pnl_pct, exit_reason=exit_reason, trade_id=trade["entry_id"],
                                outcome=outcome, symbol=sym)
        else:
            still_open.append(trade)
    open_trades.clear()
    open_trades.extend(still_open)

def main():
    global _daily_trades, _daily_trades_notified, _daily_loss_notified, \
           _consecutive_errors, _volume_spike_cooldown, \
           _consecutive_losses, _autopause_until, _loss_streak_notified

    rsi_buy, rsi_sell = get_rsi_thresholds()
    defensive = is_defensive_mode()
    interval = get_check_interval()
    mode_tag = " [DEFENSIVE]" if defensive else ""
    sym_list = ", ".join(config.SYMBOLS)
    print(f"[EXECUTION MODE{mode_tag}] Monitoring {len(config.SYMBOLS)} symbols: {sym_list} | RSI ≤{rsi_buy}/≥{rsi_sell} | EMA 200 | SL {config.STOP_LOSS_PCT}% / TP {config.TAKE_PROFIT_PCT}% | {interval}s interval")

    # --- LOADING TRADES & MOCK TRADES ---
    _pending = get_pending_trades()
    if _pending:
        open_trades.extend(_pending)
        now_ts = time.time()
        for _t in _pending:
            _remaining = max(0, _t["due_at"] - now_ts)
            print(f"[STARTUP] Restored #{_t['entry_id']:>3} {_t['symbol']} {_t['signal']}  timeout in {_remaining/60:.1f}min  SL={_t['stop_loss']}  TP={_t['take_profit']}")
        print(f"[STARTUP] Total restored: {len(_pending)} open trade(s)")

    # إضافة 3 صفقات تجريبية للاختبار
    open_trades.append({"entry_id": 999, "symbol": "BTC/USDT", "signal": "BUY", "entry_price": 50000.0, "stop_loss": 49000.0, "take_profit": 52000.0, "due_at": time.time() + 3600})
    open_trades.append({"entry_id": 998, "symbol": "ETH/USDT", "signal": "SELL", "entry_price": 3000.0, "stop_loss": 3100.0, "take_profit": 2900.0, "due_at": time.time() + 3600})
    open_trades.append({"entry_id": 997, "symbol": "SOL/USDT", "signal": "BUY", "entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "due_at": time.time() + 3600})
    print(f"[STARTUP] Mock trades added. Total open: {len(open_trades)}")

    # (بقية كود الـ main كما هو في ملفك الأصلي)
    def _hourly_report_loop():
        try:
            _sc_seed = coingecko.fetch_stablecoin_volumes()
            prev_stablecoin_volume = _sc_seed["combined"] if _sc_seed else 0.0
        except Exception:
            prev_stablecoin_volume = 0.0
        first_run = True
        while True:
            sleep_secs = 1800 if first_run else 43200
            time.sleep(sleep_secs)
            first_run = False
            try:
                ts_rep = datetime.now(timezone.utc).strftime("%H:%M:%S")
                print(f"[{ts_rep}] [REPORT] Generating 12-hour report…")
                generate_silent_report()
                r = build_report()
                btc_dom = coingecko.fetch_btc_dominance()
                if r is None or r.get("no_data"):
                    notify_no_trades_yet()
                else:
                    notify_hourly_report(win_rate=r["win_rate"], profit_factor=r["profit_factor"],
                        cumulative_pnl=r["cumulative_pnl"], closed=r["total_closed"],
                        wins=r["win_count"], losses=r["loss_count"], pending=r["pending"],
                        best_trade=r.get("best_trade"), worst_trade=r.get("worst_trade"), btc_dominance=btc_dom)
                sc = coingecko.fetch_stablecoin_volumes()
                if sc:
                    combined = sc["combined"]
                    if prev_stablecoin_volume > 0 and combined > prev_stablecoin_volume * 1.20:
                        send("💵 Stablecoin Inflow Detected – Possible Market Pump Incoming", also_channel=True)
                    prev_stablecoin_volume = combined
            except Exception as exc:
                print(f"[REPORT ERROR] {exc}")

    threading.Thread(target=_hourly_report_loop, daemon=True).start()
    print("[STARTUP] Hourly report thread started — first report in ~30 minutes")

    def _seconds_until_sunday_midnight():
        now = datetime.now(timezone.utc)
        days_ahead = (6 - now.weekday()) % 7
        candidate = (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        if candidate <= now:
            candidate += timedelta(weeks=1)
        return (candidate - now).total_seconds()

    def _trade_pnl(entry):
        ep = entry.get("price", 0)
        xp = entry.get("outcome_price", 0)
        if ep <= 0 or xp is None:
            return 0.0
        return (xp - ep) / ep * 100 if entry["signal"] == "BUY" else (ep - xp) / ep * 100

    def _weekly_report_loop():
        while True:
            secs = _seconds_until_sunday_midnight()
            print(f"[WEEKLY] Next report in {secs/3600:.1f}h (Sunday 00:00 UTC)")
            time.sleep(secs)
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
                        worst_trade=min(returns), timeouts=sum(1 for e in closed if e.get("exit_reason")=="TIMEOUT"),
                        tp_count=sum(1 for e in closed if e.get("exit_reason")=="TAKE_PROFIT"),
                        sl_count=sum(1 for e in closed if e.get("exit_reason")=="STOP_LOSS"), total_closed=len(closed))
            except Exception as exc:
                print(f"[WEEKLY ERROR] {exc}")

    threading.Thread(target=_weekly_report_loop, daemon=True, name="weekly-report").start()
    print(f"[STARTUP] Weekly report thread started — next report in ~{_seconds_until_sunday_midnight()/3600:.1f}h (Sunday 00:00 UTC)")

    def _pump_alert_loop():
        pump_sent = {}
        while True:
            time.sleep(900)
            now = time.time()
            pump_sent = {k: v for k, v in pump_sent.items() if v > now}
            coins = coingecko.fetch_top200_1h_changes()
            if not coins:
                continue
            for coin in coins:
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
    send(f"🟢 <b>Bot Online</b> — {_ast_now}\nMonitoring {len(config.SYMBOLS)} pairs | RSI ≤{rsi_buy}/{rsi_sell}≥ | MTF {config.MTF_NORMAL_CONFIRM}/4 | SL {config.STOP_LOSS_PCT}%  TP {config.TAKE_PROFIT_PCT}%", also_channel=True)

    _live_test_sent = False

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

        if not _live_test_sent and market_data:
            _live_test_sent = True
            _best_dist = float("inf")
            _best_coin = None
            _best_side = ""
            _rsi_buy_t, _rsi_sell_t = get_rsi_thresholds()
            for _s, _d in market_data.items():
                _rv = _d.get("rsi")
                if _rv is None: continue
                _dist = min(abs(_rv - _rsi_buy_t), abs(_rv - _rsi_sell_t))
                if _dist < _best_dist:
                    _best_dist = _dist
                    _best_coin = (_s, _d)
                    _best_side = "BUY" if abs(_rv - _rsi_buy_t) <= abs(_rv - _rsi_sell_t) else "SELL"
            if _best_coin:
                _sc, _dc = _best_coin
                _rv = _dc.get("rsi")
                _ev = _dc.get("ema200")
                _av = _dc.get("adx")
                _pv = _dc.get("price", 0)
                _ep = ("▲ABV" if _pv > _ev else "▼BLW") if _ev else "n/a"
                _ast = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%H:%M AST")
                send(f"📡 <b>Live Market Test — {_ast}</b>\nNearest signal: <b>{_sc}</b> → {_best_side}\nRSI: <b>{_rv:.1f}</b> (threshold ≤{_rsi_buy_t}/≥{_rsi_sell_t})  Δ{_best_dist:.1f} away\nEMA 200: {_ep}  |  ADX: {f'{_av:.1f}' if _av is not None else 'n/a'}\nPrice: {_pv}\n✅ Telegram notifications working", also_channel=True)

        try:
            prices_now = {sym: d["price"] for sym, d in market_data.items()}
            monitor_open_trades(prices_now)
            commands.update_snapshot(market_data)

            now_ts = time.time()
            if now_ts >= _volume_spike_cooldown:
                for _sym, _d in market_data.items():
                    _cv = _d.get("candle_volume", 0)
                    _avg = _d.get("avg_volume_20", 0)
                    if _avg <= 0: continue
                    _pct = (_cv / _avg - 1) * 100
                    if _pct >= 500: notify_volume_alert("extreme"); _volume_spike_cooldown = now_ts + 3600; break
                    elif _pct >= 300: notify_volume_alert("strong"); _volume_spike_cooldown = now_ts + 3600; break
                    elif _pct >= 150: notify_volume_alert("high"); _volume_spike_cooldown = now_ts + 3600; break

            defensive = is_defensive_mode()
            now = time.time()

            if open_trades:
                trade = open_trades[0]
                sym = trade.get("symbol", config.SYMBOL)
                ep = trade["entry_price"]
                cp = prices_now.get(sym, ep)
                upnl = ((cp - ep) / ep * 100) if trade["signal"] == "BUY" else ((ep - cp) / ep * 100)
                print(f"[{ts}] [OPEN #{trade['entry_id']:>3}]  {sym} {trade['signal']}  Entry: {ep}  Now: {cp}  uPnL: {upnl:+.2f}%")
            elif now < cooldown_until:
                print(f"[{ts}] [COOLDOWN] {int(cooldown_until - now)}s remaining before next signal")
            elif now < _autopause_until:
                remaining = int(_autopause_until - now)
                print(f"[{ts}] [AUTO-PAUSE] {remaining}s remaining ({remaining//60}m)")
            elif _daily_pnl <= DAILY_LOSS_LIMIT:
                if not _daily_loss_notified:
                    notify_daily_loss_pause()
                    _daily_loss_notified = True
            elif _daily_trades >= DAILY_MAX_TRADES:
                if not _daily_trades_notified:
                    send(f"📊 Daily Trade Limit Reached ({DAILY_MAX_TRADES}/{DAILY_MAX_TRADES}) – Bot Paused Until Tomorrow")
                    _daily_trades_notified = True
            elif commands.is_paused():
                pass
            else:
                rsi_buy_max, rsi_sell_min = get_rsi_thresholds()
                mtf_required = (config.MTF_CAUTIOUS_CONFIRM if _consecutive_losses >= config.CONSECUTIVE_LOSS_CAUTION else config.MTF_NORMAL_CONFIRM)
                best_sym = None; best_signal = None; best_score = -1.0; best_data = None
                diag = []; n_rsi_pass = 0; n_ema_pass = 0; n_candidates = 0

                for sym, d in market_data.items():
                    short = sym.replace("/USDT","").replace("/USDC","")
                    price = d.get("price", 0)
                    rsi_v = d.get("rsi")
                    ema_v = d.get("ema200")
                    adx_v = d.get("adx")
                    rsi_s = f"{rsi_v:.1f}" if rsi_v is not None else "n/a"
                    adx_s = f"{adx_v:.1f}" if adx_v is not None else "n/a"
                    pos_s = ("▲ABV" if price > ema_v else "▼BLW") if ema_v is not None else "EMA:n/a"
                    sig = check_signal(price, rsi_v, ema_v)
                    if sig in ("TREND_BLOCK_BUY","TREND_BLOCK_SELL"):
                        n_rsi_pass += 1; diag.append(f"{short}[RSI:{rsi_s}✓ {pos_s}✗]"); continue
                    elif sig not in ("BUY","SELL"):
                        diag.append(f"{short}[RSI:{rsi_s} {pos_s} ADX:{adx_s}]"); continue
                    if rsi_v is None:
                        diag.append(f"{short}[RSI:n/a]"); continue
                    n_rsi_pass += 1; n_ema_pass += 1; n_candidates += 1
                    score = (rsi_buy_max - rsi_v) if sig == "BUY" else (rsi_v - rsi_sell_min)
                    diag.append(f"{short}[{sig} RSI:{rsi_s} {pos_s} ADX:{adx_s} ✅]")
                    if score > best_score:
                        best_score = score; best_sym = sym; best_signal = sig; best_data = d

                if best_sym is None:
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
                    print(f"[{ts}] [HOLD]{near_str}  [RSI✓:{n_rsi_pass} EMA✓:{n_ema_pass} cand:{n_candidates}/13]")
                    print(f"         " + " | ".join(diag))
                else:
                    sym_cache = _mtf_cache.get(best_sym, {})
                    if now - sym_cache.get("ts", 0) >= MTF_CACHE_TTL:
                        try:
                            sym_cache = {"data": fetch_mtf_indicators(best_sym), "ts": now}
                            _mtf_cache[best_sym] = sym_cache
                        except Exception as exc:
                            print(f"[{ts}] [MTF ERROR] {best_sym}: {exc}")
                    confirmed_count, tf_labels = evaluate_mtf(best_data["price"], sym_cache.get("data", {}), best_signal)
                    tf_str = tf_labels_to_str(tf_labels)
                    rsi_str = f"{best_data['rsi']:.1f}" if best_data.get("rsi") else "n/a"
                    if confirmed_count < mtf_required:
                        print(f"[{ts}] [MTF BLOCK] {best_sym} {best_signal} RSI {rsi_str}: {confirmed_count}/{mtf_required} TF confirmed — {tf_str}")
                    else:
                        price = best_data["price"]; rsi = best_data.get("rsi"); volume = best_data.get("volume", 0)
                        atr = best_data.get("atr"); volume_pct = best_data.get("volume_pct"); adx_val = best_data.get("adx")
                        sl_min_dist = price * config.STOP_LOSS_PCT / 100
                        tp_min_dist = price * config.TAKE_PROFIT_PCT / 100
                        if atr:
                            sl_dist = max(config.STOP_LOSS_PCT * atr, sl_min_dist)
                            tp_dist = max(config.TAKE_PROFIT_PCT * atr, tp_min_dist)
                        else:
                            sl_dist = sl_min_dist; tp_dist = tp_min_dist
                        if best_signal == "BUY":
                            sl_price = price - sl_dist; tp_price = price + tp_dist
                        else:
                            sl_price = price + sl_dist; tp_price = price - tp_dist
                        trade_info = log_signal(best_signal, price, rsi, volume, best_sym, sl_price=sl_price, tp_price=tp_price)
                        if trade_info:
                            sl = trade_info["stop_loss"]; tp = trade_info["take_profit"]
                            print(f"[{ts}] [{best_signal} SIGNAL] {best_sym} = {price}  RSI: {rsi_str}  SL: {sl}  TP: {tp}  TF: {tf_str}")
                            open_trades.append({"entry_id": trade_info["id"], "symbol": best_sym, "signal": best_signal,
                                                "entry_price": price, "stop_loss": sl, "take_profit": tp,
                                                "due_at": time.time() + config.EVAL_DELAY})
                            _daily_trades += 1
                            analyze_performance()
                            ema200 = best_data.get("ema200")
                            ema_above = (price > ema200) if ema200 is not None else None
                            notify_trade_opened(signal=best_signal, price=price, sl=sl, tp=tp,
                                                trade_id=trade_info["id"], symbol=best_sym, tf_labels=tf_labels,
                                                rsi=rsi, ema_above=ema_above, volume_pct=volume_pct, adx=adx_val)

            try:
                _dd = market_data.get(_DEBUG_SYM)
                if _dd:
                    _dp = _dd.get("price", 0); _drsi = _dd.get("rsi"); _dema = _dd.get("ema200")
                    _drsi_s = f"{_drsi:.1f}" if _drsi is not None else "n/a"
                    _dpos_s = ("▲ABV" if _dp > _dema else "▼BLW") if _dema else "n/a"
                    _dsig = check_signal(_dp, _drsi, _dema)
                    _dnow = time.time()
                    if _dnow - _doge_mtf_cache.get("ts", 0) >= _DOGE_MTF_TTL:
                        _doge_mtf_cache["data"] = fetch_mtf_indicators(_DEBUG_SYM)
                        _doge_mtf_cache["ts"] = _dnow
                    _dmtf = _doge_mtf_cache.get("data", {})
                    _rsi_buy_d, _rsi_sell_d = get_rsi_thresholds()
                    _tf_parts = []
                    for _dtf, _dlbl in [("15m","15m"),("1h","1H"),("4h","4H"),("1d","1D")]:
                        _dr = _dmtf.get(_dtf, {}); _drv = _dr.get("rsi"); _dev = _dr.get("ema200")
                        _drv_s = f"{_drv:.1f}" if _drv is not None else "n/a"
                        _dpos = ("ABV" if _dp > _dev else "BLW") if _dev is not None else "n/a"
                        _bok = _drv is not None and _drv <= _rsi_buy_d and (_dev is None or _dp > _dev)
                        _sok = _drv is not None and _drv >= _rsi_sell_d
                        _dicon = "✅" if _bok or _sok else "⚠️"
                        _tf_parts.append(f"{_dlbl} RSI:{_drv_s}({_dpos}){_dicon}")
                    print(f"[{ts}] [DOGE DEBUG] base={_dsig}  RSI:{_drsi_s}  {_dpos_s}  |  " + "  ".join(_tf_parts))
            except Exception as _de:
                print(f"[{ts}] [DOGE DEBUG ERROR] {_de}")

        except Exception as e:
            print(f"[{ts}] [ERROR] {e}")

        time.sleep(get_check_interval())

if __name__ == "__main__":
    main()
