"""
CK Crypto Bot — Main Loop
Binance Spot | MTF + EMA + RSI + MACD + AI
"""
import time, json, os, sys
import config
import binance_client as bc
import strategy
import ai_analyst
import risk_manager as risk
import notifier

# ── State ─────────────────────────────────────────────────────────────────────
_open_trades: dict[str, dict] = {}   # symbol → trade info
_cooldowns:   dict[str, float] = {}
_loop_count   = 0


def _ts():
    return time.strftime("%H:%M:%S", time.gmtime(time.time() + 10800))


def _in_cooldown(symbol: str) -> bool:
    return time.time() < _cooldowns.get(symbol, 0)


def _set_cooldown(symbol: str):
    _cooldowns[symbol] = time.time() + config.COOLDOWN_SECONDS


def _save_trades():
    json.dump(list(_open_trades.values()), open(config.TRADES_FILE, "w"), indent=2)


def _load_trades():
    if not os.path.exists(config.TRADES_FILE):
        return
    try:
        saved = json.load(open(config.TRADES_FILE))
        for t in saved:
            _open_trades[t["symbol"]] = t
        print(f"[{_ts()}] [TRADES] Restored {len(_open_trades)} open trades")
    except Exception as e:
        print(f"[TRADES] Load error: {e}")


def monitor_open_trades():
    """يراقب الصفقات المفتوحة ويتحقق من TP/SL"""
    for symbol in list(_open_trades.keys()):
        trade = _open_trades[symbol]
        price = bc.get_price(symbol)
        if not price:
            continue

        entry    = trade["entry_price"]
        pnl_pct  = ((price - entry) / entry) * 100
        pnl_usdt = round((price - entry) / entry * trade["usdt_amount"], 2)

        print(f"[{_ts()}] [OPEN] {symbol} Entry:{entry:.4f} Now:{price:.4f} PnL:{pnl_pct:+.2f}%")

        exit_reason = strategy.check_exit(trade, price)
        if exit_reason:
            # بيع
            result = bc.sell_market(symbol, trade["qty"])
            if result:
                exit_price = result["exit_price"]
                actual_pnl_pct  = ((exit_price - entry) / entry) * 100
                actual_pnl_usdt = round((exit_price - entry) / entry * trade["usdt_amount"], 2)
                won = actual_pnl_usdt > 0
                risk.record_result(won, actual_pnl_pct)
                notifier.notify_close(
                    symbol=symbol,
                    entry=entry,
                    exit_price=exit_price,
                    pnl_pct=actual_pnl_pct,
                    pnl_usdt=actual_pnl_usdt,
                    reason=exit_reason,
                    balance=bc.get_balance(),
                )
                risk.save_history({**trade, "exit_price": exit_price,
                                   "pnl_pct": actual_pnl_pct, "pnl_usdt": actual_pnl_usdt,
                                   "close_reason": exit_reason})
                _open_trades.pop(symbol, None)
                _save_trades()
                print(f"[{_ts()}] [CLOSED] {symbol} {exit_reason} PnL:{actual_pnl_pct:+.2f}%")
            _set_cooldown(symbol)


def scan_signals():
    """يفحص العملات ويدخل صفقات"""
    can, reason = risk.can_trade(len(_open_trades))
    if not can:
        print(f"[{_ts()}] [SKIP] {reason}")
        return

    for symbol in config.SYMBOLS:
        if _in_cooldown(symbol) or symbol in _open_trades:
            continue

        # فحص الإشارة
        try:
            sig = strategy.check_signal(symbol)
        except Exception as e:
            print(f"[{_ts()}] [ERROR] {symbol}: {e}")
            continue

        if sig["signal"] != "BUY":
            continue

        print(f"[{_ts()}] [SIGNAL] {symbol} BUY — {sig['reason']}")

        # AI
        ai = ai_analyst.analyze_signal(
            symbol=symbol,
            direction="BUY",
            rsi=sig["rsi"] or 50,
            confirmations=sig["confirmations"],
            mtf_signals=sig["mtf_signals"],
        )

        if ai["verdict"] == "REJECT":
            print(f"[{_ts()}] [AI REJECT] {symbol} — {ai['reason']}")
            _set_cooldown(symbol)
            continue

        # احسب الكمية
        usdt_amount = risk.get_risk_usdt()
        price = bc.get_price(symbol)
        if not price:
            continue

        # افتح الصفقة
        result = bc.buy_market(symbol, usdt_amount)
        if not result:
            _set_cooldown(symbol)
            continue

        entry = result["entry_price"]
        qty   = result["qty"]
        tp    = round(entry * (1 + config.TAKE_PROFIT_PCT / 100), 8)
        sl    = round(entry * (1 - config.STOP_LOSS_PCT / 100), 8)

        trade_info = {
            "symbol":      symbol,
            "entry_price": entry,
            "qty":         qty,
            "usdt_amount": usdt_amount,
            "tp":          tp,
            "sl":          sl,
            "rsi":         sig["rsi"],
            "confirmations": sig["confirmations"],
            "mtf_signals": sig["mtf_signals"],
            "opened_at":   int(time.time()),
        }
        _open_trades[symbol] = trade_info
        _save_trades()

        notifier.notify_open(
            symbol=symbol,
            entry=entry,
            qty=qty,
            tp=tp,
            sl=sl,
            usdt_amount=usdt_amount,
            rsi=sig["rsi"] or 0,
            confirmations=sig["confirmations"],
            mtf_signals=sig["mtf_signals"],
            balance=bc.get_balance(),
        )

        _set_cooldown(symbol)
        time.sleep(1)

        # تحقق من الحد
        can, reason = risk.can_trade(len(_open_trades))
        if not can:
            break


def main():
    print("=" * 55)
    print("  CK Crypto Bot — Binance Spot")
    print("=" * 55)

    if not config.BINANCE_API_KEY:
        print("[ERROR] BINANCE_API_KEY not set!")
        sys.exit(1)

    risk.initialize()
    _load_trades()

    balance = bc.get_balance()
    print(f"[{_ts()}] Balance: ${balance:.2f} USDT")
    print(f"[{_ts()}] Symbols: {len(config.SYMBOLS)}")
    print(f"[{_ts()}] Max trades: {config.MAX_OPEN_TRADES} | Risk: {config.RISK_PER_TRADE}%")
    print(f"[{_ts()}] TP: {config.TAKE_PROFIT_PCT}% | SL: {config.STOP_LOSS_PCT}%")

    notifier.notify_online(balance, len(config.SYMBOLS))

    global _loop_count

    while True:
        try:
            _loop_count += 1

            if _open_trades:
                monitor_open_trades()

            scan_signals()

            if _loop_count % 100 == 0:
                s = risk.get_summary()
                print(f"[{_ts()}] 💰${s['balance']:.2f} | W:{s['daily_wins']} L:{s['daily_losses']} | Open:{len(_open_trades)}")

            if _loop_count % 2160 == 0:  # ~12 ساعة
                notifier.notify_daily(risk.get_summary())

        except KeyboardInterrupt:
            print(f"\n[{_ts()}] Stopped")
            break
        except Exception as e:
            print(f"[{_ts()}] [ERROR] {e}")
            notifier.notify_error(str(e))
            time.sleep(30)

        time.sleep(config.LOOP_INTERVAL)


if __name__ == "__main__":
    main()
