import math
import os
import sys
from datetime import datetime, timezone
import config
from journal import load_history

def _mean(values):
    return sum(values) / len(values)

def _std(values):
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))

def _trade_return_pct(entry):
    ep = entry["price"]
    xp = entry["outcome_price"]
    if entry["signal"] == "BUY":
        return (xp - ep) / ep * 100
    else:
        return (ep - xp) / ep * 100

def build_report():
    if not os.path.exists(config.HISTORY_FILE):
        return None
    history = load_history()
    total_logged = len(history)
    pending = [e for e in history if e["outcome"] == "PENDING"]
    closed = [e for e in history if e["outcome"] in ("SUCCESS", "FAILURE") and e.get("outcome_price") is not None]
    if not closed:
        return {"total_logged": total_logged, "total_closed": 0, "pending": len(pending), "no_data": True}
    returns = [_trade_return_pct(e) for e in closed]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    total_closed = len(closed)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total_closed * 100
    cumulative_pnl = sum(returns)
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    mean_ret = _mean(returns)
    std_ret = _std(returns)
    if std_ret > 0:
        sharpe = mean_ret / std_ret
    elif mean_ret > 0:
        sharpe = float("inf")
    else:
        sharpe = 0.0
    sl_count = sum(1 for e in closed if e.get("exit_reason") == "STOP_LOSS")
    tp_count = sum(1 for e in closed if e.get("exit_reason") == "TAKE_PROFIT")
    timeout_count = sum(1 for e in closed if e.get("exit_reason") == "TIMEOUT")
    best = max(returns)
    worst = min(returns)
    max_consec_wins = max_consec_losses = cur_w = cur_l = 0
    for r in returns:
        if r > 0:
            cur_w += 1; cur_l = 0
            max_consec_wins = max(max_consec_wins, cur_w)
        else:
            cur_l += 1; cur_w = 0
            max_consec_losses = max(max_consec_losses, cur_l)
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "total_logged": total_logged, "total_closed": total_closed, "pending": len(pending),
            "no_data": False, "win_count": win_count, "loss_count": loss_count,
            "win_rate": win_rate, "cumulative_pnl": cumulative_pnl, "mean_return": mean_ret,
            "std_return": std_ret, "gross_profit": gross_profit, "gross_loss": gross_loss,
            "profit_factor": profit_factor, "sharpe_ratio": sharpe,
            "best_trade": best, "worst_trade": worst,
            "sl_count": sl_count, "tp_count": tp_count, "timeout_count": timeout_count,
            "max_consec_wins": max_consec_wins, "max_consec_losses": max_consec_losses}

def generate_silent_report():
    try:
        r = build_report()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        div = "─" * 50
        lines = [div, f"  Snapshot : {now}"]
        if r is None or r.get("no_data"):
            lines.append("  No closed trades yet.")
        else:
            pnl_sign = "+" if r["cumulative_pnl"] >= 0 else ""
            pf = r["profit_factor"]
            pf_str = "∞  (no losses)" if pf == float("inf") else f"{pf:.2f}"
            lines += [f"  Win Rate       : {r['win_rate']:.1f}%  ({r['win_count']}W / {r['loss_count']}L of {r['total_closed']} closed)",
                      f"  Profit Factor  : {pf_str}",
                      f"  Total PnL      : {pnl_sign}{r['cumulative_pnl']:.2f}%",
                      f"  Pending trades : {r['pending']}"]
        lines.append(div)
        with open("hourly_report.txt", "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
    except Exception:
        pass

if __name__ == "__main__":
    r = build_report()
    if r:
        print(r)
