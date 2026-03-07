import math, os
from datetime import datetime, timezone
import config
from journal import load_history

def _mean(v): return sum(v) / len(v)
def _std(v):
    if len(v) < 2: return 0.0
    m = _mean(v)
    return math.sqrt(sum((x-m)**2 for x in v) / (len(v)-1))
def _trade_return_pct(e):
    ep = e["price"]; xp = e["outcome_price"]
    return (xp-ep)/ep*100 if e["signal"]=="BUY" else (ep-xp)/ep*100

def build_report():
    if not os.path.exists(config.HISTORY_FILE): return None
    history = load_history()
    pending = [e for e in history if e["outcome"]=="PENDING"]
    closed  = [e for e in history if e["outcome"] in ("SUCCESS","FAILURE") and e.get("outcome_price") is not None]
    if not closed:
        return {"total_logged": len(history), "total_closed": 0, "pending": len(pending), "no_data": True}
    returns = [_trade_return_pct(e) for e in closed]
    wins    = [r for r in returns if r > 0]
    losses  = [r for r in returns if r <= 0]
    win_rate = len(wins)/len(closed)*100
    cum_pnl  = sum(returns)
    gp = sum(wins) if wins else 0.0
    gl = abs(sum(losses)) if losses else 0.0
    pf = gp/gl if gl > 0 else float("inf")
    mn = _mean(returns); sd = _std(returns)
    sharpe = (mn/sd) if sd > 0 else (float("inf") if mn > 0 else 0.0)
    sl_c = sum(1 for e in closed if e.get("exit_reason")=="STOP_LOSS")
    tp_c = sum(1 for e in closed if e.get("exit_reason")=="TAKE_PROFIT")
    to_c = sum(1 for e in closed if e.get("exit_reason")=="TIMEOUT")
    mcw=mcl=cw=cl=0
    for r in returns:
        if r>0: cw+=1; cl=0; mcw=max(mcw,cw)
        else:   cl+=1; cw=0; mcl=max(mcl,cl)
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "total_logged": len(history), "total_closed": len(closed), "pending": len(pending),
            "no_data": False, "win_count": len(wins), "loss_count": len(losses),
            "win_rate": win_rate, "cumulative_pnl": cum_pnl, "mean_return": mn,
            "std_return": sd, "gross_profit": gp, "gross_loss": gl,
            "profit_factor": pf, "sharpe_ratio": sharpe,
            "best_trade": max(returns), "worst_trade": min(returns),
            "sl_count": sl_c, "tp_count": tp_c, "timeout_count": to_c,
            "max_consec_wins": mcw, "max_consec_losses": mcl}

def generate_silent_report():
    try:
        r   = build_report()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        div = "─"*50
        lines = [div, f"  Snapshot : {now}"]
        if r is None or r.get("no_data"):
            lines.append("  No closed trades yet.")
        else:
            pf_str = "∞  (no losses)" if r["profit_factor"]==float("inf") else f"{r['profit_factor']:.2f}"
            pnl_s  = "+" if r["cumulative_pnl"] >= 0 else ""
            lines += [f"  Win Rate       : {r['win_rate']:.1f}%  ({r['win_count']}W / {r['loss_count']}L of {r['total_closed']} closed)",
                      f"  Profit Factor  : {pf_str}",
                      f"  Total PnL      : {pnl_s}{r['cumulative_pnl']:.2f}%",
                      f"  Pending trades : {r['pending']}"]
        lines.append(div)
        with open("hourly_report.txt","a",encoding="utf-8") as f:
            f.write("\n".join(lines)+"\n\n")
    except Exception:
        pass
