import itertools, os, sys, traceback
from datetime import date
import pandas as pd
from report import *
start, end = date(2024, 6, 10), date(2026, 10, 2)
variants = []
for otm, dte, tp in itertools.product([0.05, 0.10, 0.15], [7, 14, 30, 45], [0.5, None]):
    variants.append(Rules(put_otm=otm, dte_min=dte, take_profit=tp, name=f"otm{int(otm*100)}_dte{dte}_tp{'50' if tp else 'hold'}"))
variants += [
    Rules(call_mode="spot", call_otm=0.10, name="otm10_dte14_tp50_callspot10"),
    Rules(call_mode="spot", call_otm=0.05, name="otm10_dte14_tp50_callspot5"),
    Rules(skip_earnings=True, name="otm10_dte14_tp50_skipearn"),
    Rules(put_otm=0.05, dte_min=30, skip_earnings=True, name="otm5_dte30_tp50_skipearn"),
]
rows = []
for r in variants:
    try:
        eq, tr, st, stuck = run(r, start, end)
        days = list(eq.index); rf = tbill_curve(days)
        m = metrics(eq, rf); ts = trade_stats(tr)
        share_days = int((st.state != "SHORT_PUT").sum() - (st.state == "CASH").sum())
        rows.append(dict(name=r.name, **{k: m[k] for k in ("total", "cagr", "vol", "sharpe", "sortino", "max_dd", "worst_month", "cvar5_daily")},
                         **ts, share_days=share_days, stuck=stuck))
        eq.to_pickle(os.path.join(DATA, f"eq_{r.name}.pkl")); tr.to_pickle(os.path.join(DATA, f"tr_{r.name}.pkl"))
        print("done", r.name, round(m["cagr"] * 100, 1), round(m["max_dd"] * 100, 1), flush=True)
    except Exception:
        print("FAIL", r.name, traceback.format_exc()[-300:], flush=True)
    pd.DataFrame(rows).to_pickle(os.path.join(DATA, "grid_results.pkl"))
print("ALL DONE", flush=True)
