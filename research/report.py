import pandas as pd
from wheel_research import *

def table(curves, rf):
    df = pd.DataFrame({k: metrics(v, rf) for k, v in curves.items()}).T
    for c in ("total", "cagr", "vol", "max_dd", "worst_month", "cvar5_daily"): df[c] = (df[c].astype(float) * 100).round(1)
    for c in ("sharpe", "sortino"): df[c] = df[c].astype(float).round(2)
    return df[["total", "cagr", "vol", "sharpe", "sortino", "max_dd", "recovery_days", "worst_month", "cvar5_daily"]]

def trade_stats(tr):
    opt = tr[tr.kind.isin(["P", "C"])]
    wins, losses = opt[opt.pnl > 0], opt[opt.pnl <= 0]
    return dict(trades=len(opt), win_rate=round((opt.pnl > 0).mean() * 100), avg_win=round(wins.pnl.mean()) if len(wins) else 0,
                avg_loss=round(losses.pnl.mean()) if len(losses) else 0, worst=round(opt.pnl.min()),
                assigned=int((opt.outcome == "assigned").sum()), called=int((opt.outcome == "called_away").sum()),
                put_delta=round(opt[opt.kind == "P"].delta.median(), 3), put_iv=round(opt[opt.kind == "P"].iv.median() * 100))
