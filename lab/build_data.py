"""Pack research data into lab/data.js for the Wheel Lab page.

Run after research/fetch_data.py and research/prefetch.py, with the research venv:
    research/.venv/bin/python lab/build_data.py

Writes lab/data.js (gitignored, a few MB): daily NVDA/SPY prices, T-bill
rates, earnings dates, real NVDA option closes since the June 2024 split,
and reference results from the Python research engine, which the page's
JavaScript engine is checked against (lab/parity_test.js).
"""
import json
import math
import os
import pickle
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "research"))

import wheel_research as w  # noqa: E402
from bs_research import Sim, simulate  # noqa: E402

START = date(2016, 1, 4)
REAL_START = date(2024, 6, 10)

dates = [d for d in w.NVDA.index if d >= START]
idx = {d: i for i, d in enumerate(dates)}


def col(series):
    return [round(float(series[d]), 4) for d in dates]


tbill = [round(w.tbill_rate(d), 5) for d in dates]
earnings = [d.isoformat() for d in w.earnings_days(START, date(2027, 1, 31))]

# --- real option chains and bars ---
cache = pickle.load(open(os.path.join(HERE, "..", "research", "data", "opt_cache.pkl"), "rb"))
chains, bars, cid_of = {}, [], {}
for (expiry, kind), strikes in sorted(cache["contracts"].items()):
    if expiry < REAL_START:
        continue
    for strike, sym in sorted(strikes.items()):
        s = cache["bars"].get(sym)
        if s is None or not len(s):
            continue
        lo = expiry - timedelta(days=75)
        pts = [(idx[d], int(round(float(v) * 100))) for d, v in s.items() if d in idx and lo <= d <= expiry]
        if not pts:
            continue
        if sym not in cid_of:
            cid_of[sym] = len(bars)
            flat, prev = [], None
            for i, c in sorted(pts):
                flat += [i - (prev if prev is not None else 0), c]
                prev = i
            bars.append(flat)
        chains.setdefault(expiry.isoformat(), {"P": [], "C": []})[kind].append([strike, cid_of[sym]])


# --- reference results from the Python research engines (parity targets) ---
def ref_metrics(eq):
    days = list(eq.index)
    m = w.metrics(eq, w.tbill_curve(days))
    return {k: round(float(m[k]), 6) for k in ("total", "cagr", "vol", "sharpe", "max_dd")}


reference = {}
real_end = date(2026, 10, 2)
for name, rules in (("real_current", w.Rules()), ("real_otm5_dte45_tp50", w.Rules(put_otm=0.05, dte_min=45)),
                    ("real_callspot5", w.Rules(call_mode="spot", call_otm=0.05))):
    eq, tr, st, stuck = w.run(rules, REAL_START, real_end)
    reference[name] = {**ref_metrics(eq), "trades": int(tr.kind.isin(["P", "C"]).sum())}
for name, cfg in (("model_current", Sim()), ("model_dte45", Sim(dte_min=45)), ("model_callspot5", Sim(call_mode="spot", call_otm=0.05))):
    e, tr, legs, interest = simulate(cfg, date(2016, 4, 1), real_end)
    reference[name] = {**ref_metrics(e.equity), "trades": len(tr)}

data = {
    "built": datetime.now().isoformat(timespec="minutes"),
    "dates": [d.isoformat() for d in dates],
    "nvda": col(w.NVDA),
    "nvdaTR": col(w.NVDA_TR),
    "spyTR": col(w.SPY_TR),
    "tbill": tbill,
    "earnings": earnings,
    "chains": chains,
    "bars": bars,
    "reference": reference,
}
out = os.path.join(HERE, "data.js")
with open(out, "w") as f:
    f.write("window.LAB_DATA = ")
    json.dump(data, f, separators=(",", ":"))
    f.write(";\n")
print(f"wrote {out}: {os.path.getsize(out) / 1e6:.1f} MB, {len(dates)} days, {len(chains)} expiries, {len(bars)} contracts")
print(json.dumps(reference, indent=1))
