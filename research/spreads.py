"""Measure today's option bid/ask spreads for the Wheel Lab's cost stress test.

Pulls the indicative-feed chain snapshot for each ticker, keeps the options a
wheel actually trades (puts and calls 5-65 days out, |delta| 0.03-0.45, a live
two-sided quote), and writes research/data/spreads_<TICKER>.json:
half-spread in dollars by option price bucket, plus the raw rows.

Run: python research/spreads.py NVDA AMZN
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, "..", ".env.paper"))

from alpaca.data.enums import OptionsFeed  # noqa: E402
from alpaca.data.historical.option import OptionHistoricalDataClient  # noqa: E402
from alpaca.data.historical.stock import StockHistoricalDataClient  # noqa: E402
from alpaca.data.requests import OptionChainRequest, StockLatestTradeRequest  # noqa: E402

KEY, SECRET = os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
opt, stk = OptionHistoricalDataClient(KEY, SECRET), StockHistoricalDataClient(KEY, SECRET)
BUCKETS = [0.10, 0.25, 0.50, 1.00, 2.00, 3.00, 5.00, 8.00, 12.00]  # option mid price edges


def measure(ticker):
    spot = float(stk.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=ticker))[ticker].price)
    today = date.today()
    snaps = opt.get_option_chain(OptionChainRequest(underlying_symbol=ticker, feed=OptionsFeed.INDICATIVE,
                                                    expiration_date_gte=today + timedelta(days=5),
                                                    expiration_date_lte=today + timedelta(days=65)))
    rows = []
    for sym, s in snaps.items():
        q, g = s.latest_quote, s.greeks
        if not q or not g or g.delta is None or not (q.bid_price and q.ask_price) or q.ask_price <= q.bid_price:
            continue
        kind = sym[-9]
        exp = datetime.strptime(sym[-15:-9], "%y%m%d").date()
        strike = int(sym[-8:]) / 1000
        if not 0.03 <= abs(g.delta) <= 0.45:
            continue
        mid = (q.bid_price + q.ask_price) / 2
        rows.append({"kind": kind, "strike": strike, "dte": (exp - today).days, "bid": q.bid_price, "ask": q.ask_price,
                     "mid": round(mid, 4), "half": round((q.ask_price - q.bid_price) / 2, 4), "delta": round(g.delta, 3),
                     "iv": round(s.implied_volatility or 0, 4), "quoted": q.timestamp.isoformat()})
    rows.sort(key=lambda r: (r["kind"], r["dte"], r["strike"]))
    buckets = []
    for lo, hi in zip([0] + BUCKETS, BUCKETS + [1e9]):
        sel = sorted(r["half"] for r in rows if lo <= r["mid"] < hi)
        if len(sel) >= 5:
            mids = sorted(r["mid"] for r in rows if lo <= r["mid"] < hi)
            buckets.append([round(mids[len(mids) // 2], 3), round(sel[len(sel) // 2], 4), len(sel)])
    pcts = sorted(r["half"] / r["mid"] for r in rows)
    out = {"ticker": ticker, "asof": today.isoformat(), "spot": spot, "n": len(rows),
           "quotedFrom": min(r["quoted"] for r in rows), "quotedTo": max(r["quoted"] for r in rows),
           "medianPct": round(pcts[len(pcts) // 2], 4), "buckets": buckets, "rows": rows}
    with open(os.path.join(HERE, "data", f"spreads_{ticker}.json"), "w") as f:
        json.dump(out, f)
    print(f"{ticker} ${spot:.2f}: {len(rows)} quotes, median half-spread {out['medianPct'] * 100:.1f}% of mid; "
          f"quoted {out['quotedFrom'][:16]} to {out['quotedTo'][:16]}")
    for mid, half, n in buckets:
        print(f"  mid ~${mid:<6} half-spread ${half:.3f} ({half / mid * 100:.1f}%)  n={n}")


if __name__ == "__main__":
    for t in sys.argv[1:] or ["NVDA", "AMZN"]:
        measure(t)
