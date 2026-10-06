"""Measure option bid/ask spreads from DoltHub's free options database
(post-no-preference/options: end-of-day chains with bid, ask, IV and greeks,
Mon/Wed/Fri, about 11-53 days out, from 2019). Alpaca's free feed is
"indicative" (derived, not the real NBBO); for AMZN it shows spreads 2-4x
wider than this does.

Writes research/data/spreads_<TICKER>.json for the Wheel Lab's cost test:
- buckets: median half-spread in dollars by option price, latest day.
- wild: median half-spread as a share of the price on calm days vs "wild"
  days (20-day volatility in its top 10%, the lab's definition).

Run: python research/dolthub_spreads.py NVDA AMZN
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
API = "https://www.dolthub.com/api/v1alpha1/post-no-preference/options/master"
BUCKETS = [0.10, 0.25, 0.50, 1.00, 2.00, 3.00, 5.00, 8.00, 12.00]  # option mid price edges


def query(sql):
    for attempt in range(4):
        try:
            r = requests.get(API, params={"q": sql}, timeout=90)
            d = r.json()
            if d.get("query_execution_status") == "Success":
                return d.get("rows", [])
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("DoltHub query failed: " + sql[:120])


def chain(ticker, day, lo=0.03, hi=0.45):
    rows = query(f"SELECT expiration, strike, call_put, bid, ask, delta FROM option_chain "
                 f"WHERE date = '{day}' AND act_symbol = '{ticker}'")
    out = []
    for r in rows:
        try:
            bid, ask, dl = float(r["bid"]), float(r["ask"]), abs(float(r["delta"]))
        except (TypeError, ValueError):
            continue
        if bid > 0 and ask > bid and lo <= dl <= hi:
            out.append({"mid": (bid + ask) / 2, "half": (ask - bid) / 2, "kind": r["call_put"][0], "delta": dl,
                        "dte": (date.fromisoformat(r["expiration"]) - date.fromisoformat(day)).days})
    return out


def regimes(ticker):
    """Calm and wild Mon/Wed/Fri dates since mid-2020, as the lab defines them."""
    stock = pd.read_pickle(os.path.join(DATA, "stock_split.pkl"))
    s = stock.loc[ticker]["close"].copy()
    s.index = pd.to_datetime(s.index).tz_convert("America/New_York").date
    lr = np.log(s / s.shift(1))
    s20, s60 = lr.rolling(20).std(), lr.rolling(60).std()
    rv = (0.5 * s20 + 0.5 * s60) * np.sqrt(252)
    hot = s20 >= s20.dropna().quantile(0.9)
    recent = [d for d in s.index if d >= date(2020, 7, 1) and d.weekday() in (0, 2, 4) and not np.isnan(rv[d])]
    med = np.median([rv[d] for d in recent])
    wild = [d for d in recent if hot[d]]
    calm = [d for d in recent if not hot[d] and rv[d] < med]
    pick = lambda a, n: [a[int((j + 0.5) * len(a) / n)] for j in range(n)]
    return pick(calm, 8), pick(wild, 8)


def measure(ticker):
    day = date.today()
    for _ in range(10):
        rows = chain(ticker, day.isoformat())
        if rows:
            break
        day -= timedelta(days=1)
    buckets = []
    for lo, hi in zip([0] + BUCKETS, BUCKETS + [1e9]):
        sel = [r for r in rows if lo <= r["mid"] < hi]
        if len(sel) >= 3:
            buckets.append([round(float(np.median([r["mid"] for r in sel])), 3), round(float(np.median([r["half"] for r in sel])), 4), len(sel)])
    pcts = [r["half"] / r["mid"] for r in rows]
    calm, wild = regimes(ticker)
    per = {}
    for label, days in (("calm", calm), ("wild", wild)):
        per[label] = []
        for d in days:
            rs = chain(ticker, d.isoformat(), 0.05, 0.40)
            if len(rs) >= 5:
                per[label].append([d.isoformat(), round(float(np.median([r["half"] / r["mid"] for r in rs])), 4), len(rs)])
    calm_pct = float(np.median([x[1] for x in per["calm"]])) if per["calm"] else None
    wild_pct = float(np.median([x[1] for x in per["wild"]])) if per["wild"] else None
    out = {"ticker": ticker, "source": "DoltHub post-no-preference/options (end-of-day bid/ask)", "asof": day.isoformat(),
           "quotedTo": day.isoformat(), "n": len(rows), "medianPct": round(float(np.median(pcts)), 4), "buckets": buckets,
           "wild": {"calm": per["calm"], "wild": per["wild"], "calmPct": calm_pct, "wildPct": wild_pct,
                    "ratio": round(wild_pct / calm_pct, 2) if calm_pct and wild_pct else None}}
    with open(os.path.join(DATA, f"spreads_{ticker}.json"), "w") as f:
        json.dump(out, f)
    print(f"{ticker} {day}: {len(rows)} quotes, median half-spread {out['medianPct'] * 100:.1f}% of mid")
    for mid, half, n in buckets:
        print(f"  mid ~${mid:<6} half-spread ${half:.3f} ({half / mid * 100:.1f}%)  n={n}")
    w = out["wild"]
    print(f"  calm days {w['calmPct'] and round(w['calmPct'] * 100, 1)}% vs wild days {w['wildPct'] and round(w['wildPct'] * 100, 1)}% -> x{w['ratio']}")
    print("  calm:", w["calm"]); print("  wild:", w["wild"])


if __name__ == "__main__":
    for t in sys.argv[1:] or ["NVDA", "AMZN"]:
        measure(t)
