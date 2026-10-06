"""Pack research data into lab/data.js for the Wheel Lab page.

Run after research/fetch_data.py and research/prefetch.py, with the research venv:
    research/.venv/bin/python lab/build_data.py

Writes lab/data.js (gitignored, a few MB): daily stock prices, T-bill
rates, earnings dates, real NVDA option closes since the June 2024 split,
and reference results from the Python research engine, which the page's
JavaScript engine is checked against (lab/parity_test.js).
"""
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd
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

# --- real option chains and bars, per underlying ---
DATA = os.path.join(HERE, "..", "research", "data")
# Stocks a $25k account can wheel.
CACHES = {"NVDA": "opt_cache.pkl", "AMZN": "opt_cache_AMZN.pkl", "WMT": "opt_cache_WMT.pkl",
          "JNJ": "opt_cache_JNJ.pkl", "XOM": "opt_cache_XOM.pkl"}
CACHES = {k: v for k, v in CACHES.items() if os.path.exists(os.path.join(DATA, v))}


def pack_options(cache):
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
    return chains, bars


def closes(sym, frame=None):
    s = (w._stock_split if frame is None else frame).loc[sym]["close"].copy()
    s.index = pd.to_datetime(s.index).tz_convert("America/New_York").date
    return s


def reaction_days(filings):
    out = []
    for f in filings:
        nxt = [d for d in dates if d > f][:1]
        out.append((nxt[0] if nxt else f + timedelta(days=1)).isoformat())
    return out


PUT_BUCKETS, CALL_BUCKETS = [0.85, 0.90, 0.95, 0.98], [1.02, 1.05, 1.10]


def calibrate(sym, cache, px, earn):
    """Ratio of implied vol (from real option closes, 14-20 days out) to the
    20/60-day realized-vol blend, measured at several strike distances so the
    model can follow each stock's skew. Earnings multipliers come from the
    ~10%-out samples whose expiry crossed a report."""
    lr = np.log(px / px.shift(1))
    rv = 0.5 * lr.rolling(20).std() * math.sqrt(252) + 0.5 * lr.rolling(60).std() * math.sqrt(252)
    exps = sorted({e for (e, k) in cache["contracts"] if cache["contracts"][(e, k)]})
    got = {("P", m): [] for m in PUT_BUCKETS} | {("C", m): [] for m in CALL_BUCKETS}
    earn_s = {"P": [], "C": [], "Pn": [], "Cn": []}
    for d in [d for d in px.index if REAL_START <= d <= date(2026, 9, 15)][::3]:
        S, r, vol = float(px[d]), w.tbill_rate(d), float(rv[d])
        f = d + timedelta(days=14); f += timedelta(days=(4 - f.weekday()) % 7)
        exp = next((c for c in (f, f - timedelta(days=1), f + timedelta(days=7)) if c in exps), None)
        if not exp:
            continue
        T = max((exp - d).days, 1) / 365
        crosses = any(d < e <= exp for e in earn)
        for kind, buckets in (("P", PUT_BUCKETS), ("C", CALL_BUCKETS)):
            ch = cache["contracts"].get((exp, kind), {})
            for m in buckets:
                target = m * S
                for k in sorted(ch, key=lambda k: abs(k - target))[:2]:
                    if abs(k / S - m) > 0.02:
                        continue
                    b = cache["bars"].get(ch[k])
                    if b is not None and d in b.index and float(b[d]) >= 0.05:
                        iv = w.implied_vol(kind, float(b[d]), S, k, T, r)
                        if iv:
                            ratio = iv / vol
                            if not crosses:
                                got[(kind, m)].append(ratio)
                            if (kind, m) in (("P", 0.90), ("C", 1.10)):
                                earn_s[kind if crosses else kind + "n"].append(ratio)
                        break
    med = lambda v: float(np.median(v)) if len(v) >= 5 else None
    curve = lambda kind, buckets: [[m, round(med(got[(kind, m)]), 3)] for m in buckets if med(got[(kind, m)])]
    pc, cc = curve("P", PUT_BUCKETS), curve("C", CALL_BUCKETS)
    ratio = lambda a, b: round(med(earn_s[a]) / med(earn_s[b]), 2) if med(earn_s[a]) and med(earn_s[b]) else 1.0
    at = lambda c, m: min(c, key=lambda x: abs(x[0] - m))[1] if c else 1.0
    return {"putMult": round(at(pc, 0.90), 2), "callMult": round(at(cc, 1.10), 2), "putCurve": pc, "callCurve": cc,
            "earnPut": ratio("P", "Pn"), "earnCall": ratio("C", "Cn"),
            "samples": {f"{k}{m}": len(v) for (k, m), v in got.items()}}


tickers = {}
for sym, fname in CACHES.items():
    cache = pickle.load(open(os.path.join(DATA, fname), "rb"))
    chains, bars = pack_options(cache)
    px = closes(sym)
    efile = os.path.join(DATA, f"earnings_8k_{sym}.pkl")
    if sym == "NVDA":
        earn_iso = earnings
    elif os.path.exists(efile):
        earn_iso = reaction_days(pd.read_pickle(efile))
    else:
        earn_iso = []
    earn_d = [date.fromisoformat(e) for e in earn_iso]
    cal = calibrate(sym, cache, px, earn_d)
    # NVDA keeps the research model's calibration so it matches the Python engine
    model = ({"putMult": 1.13, "callMult": 1.0, "earnPut": 1.4, "earnCall": 1.1} if sym == "NVDA"
             else {k: cal[k] for k in ("putMult", "callMult", "putCurve", "callCurve", "earnPut", "earnCall")})
    real_px = px[px.index >= REAL_START]
    # Stocks a $25k account can trade today (a put 5% below the latest price fits)
    # run on $25k exactly like the bot, which caps strikes when the price was
    # higher. Others run on the smallest account that fits one contract at the peak.
    fits_today = float(real_px.iloc[-1]) * 100 * 0.95 <= 25000
    capital = 25000 if fits_today else int(math.ceil(float(real_px.max()) * 100 / 10000) * 10000)
    tickers[sym] = {"close": col(px), "chains": chains, "bars": bars, "earnings": earn_iso, "model": model, "capital": capital}
    print(f"{sym}: {len(chains)} expiries, {len(bars)} contracts, capital ${capital:,}, model {model}, measured {cal}")

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
    "stockTR": {sym: col(closes(sym, w._stock_all)) for sym in tickers},  # total return, for "held" lines
    "tbill": tbill,
    "tickers": {"NVDA": tickers["NVDA"]},
    "tickerList": [{"sym": k, "capital": v["capital"]} for k, v in tickers.items()],
    "reference": reference,
}
out = os.path.join(HERE, "data.js")
with open(out, "w") as f:
    f.write("window.LAB_DATA = ")
    json.dump(data, f, separators=(",", ":"))
    f.write(";\n")
print(f"wrote {out}: {os.path.getsize(out) / 1e6:.1f} MB, {len(dates)} days")
for sym, T in tickers.items():
    if sym == "NVDA":
        continue
    tout = os.path.join(HERE, f"data_{sym}.js")
    with open(tout, "w") as f:
        f.write(f"(window.LAB_TICKERS = window.LAB_TICKERS || {{}})[{json.dumps(sym)}] = ")
        json.dump(T, f, separators=(",", ":"))
        f.write(";\n")
    print(f"wrote {tout}: {os.path.getsize(tout) / 1e6:.1f} MB")
print(json.dumps(reference, indent=1))
