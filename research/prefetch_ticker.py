"""Download real option chains and daily bars for other underlyings (SPY, COST)
into research/data/opt_cache_<TICKER>.pkl, plus COST earnings dates.

Same shape as the NVDA cache: {"contracts": {(expiry, kind): {strike: symbol}},
"bars": {symbol: Series of closes}}. Friday expiries only, June 2024 on.
SPY strikes are limited to multiples of $5 to keep the file small.

Run: research/.venv/bin/python research/prefetch_ticker.py SPY COST
"""
import os
import pickle
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
load_dotenv(os.path.join(HERE, "..", ".env.paper"))

from alpaca.data.historical.option import OptionHistoricalDataClient  # noqa: E402
from alpaca.data.requests import OptionBarsRequest  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402
from alpaca.trading.client import TradingClient  # noqa: E402
from alpaca.trading.enums import AssetStatus, ContractType  # noqa: E402
from alpaca.trading.requests import GetOptionContractsRequest  # noqa: E402

KEY, SECRET = os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
trading, optdata = TradingClient(KEY, SECRET, paper=True), OptionHistoricalDataClient(KEY, SECRET)
stock = pd.read_pickle(os.path.join(DATA, "stock_split.pkl"))
CIK = {"COST": "0000909832"}


def closes(sym):
    s = stock.loc[sym]["close"].copy()
    s.index = pd.to_datetime(s.index).tz_convert("America/New_York").date
    return s


def chain(ticker, expiry, kind):
    out = {}
    for status in (AssetStatus.INACTIVE, AssetStatus.ACTIVE):
        req = GetOptionContractsRequest(underlying_symbols=[ticker], expiration_date=expiry, status=status, limit=10000,
                                        type=ContractType.PUT if kind == "P" else ContractType.CALL)
        for c in trading.get_option_contracts(req).option_contracts:
            out[float(c.strike_price)] = c.symbol
    return out


def fetch(ticker):
    path = os.path.join(DATA, f"opt_cache_{ticker}.pkl")
    cache = pickle.load(open(path, "rb")) if os.path.exists(path) else {"contracts": {}, "bars": {}}
    px = closes(ticker)
    fri, fetched = date(2024, 6, 14), 0
    while fri <= date(2026, 11, 27):
        for cand in (fri, fri - timedelta(days=1)):
            if (cand, "P") not in cache["contracts"]:
                cache["contracts"][(cand, "P")] = chain(ticker, cand, "P")
                cache["contracts"][(cand, "C")] = chain(ticker, cand, "C")
            if cache["contracts"][(cand, "P")]:
                break
        E = cand
        win = px[(px.index >= E - timedelta(days=75)) & (px.index <= min(E, px.index[-1]))]
        if len(win) and cache["contracts"][(E, "P")]:
            lo, hi = float(win.min()), float(win.max())
            keep = (lambda k: k % 5 == 0) if ticker == "SPY" else (lambda k: True)
            syms = [s for k, s in cache["contracts"][(E, "P")].items() if 0.78 * lo <= k <= hi and keep(k)]
            syms += [s for k, s in cache["contracts"][(E, "C")].items() if 0.95 * lo <= k <= 1.3 * hi and keep(k)]
            syms = [s for s in syms if s not in cache["bars"]]
            exp = datetime.combine(E, datetime.min.time())
            for i in range(0, len(syms), 100):
                batch = syms[i:i + 100]
                df = optdata.get_option_bars(OptionBarsRequest(symbol_or_symbols=batch, timeframe=TimeFrame.Day, start=exp - timedelta(days=80),
                                                               end=min(exp + timedelta(days=1), datetime.now() - timedelta(minutes=20)))).df
                got = {}
                if len(df):
                    for sym, g in df["close"].groupby(level=0):
                        s = g.droplevel(0); s.index = pd.to_datetime(s.index).tz_convert("America/New_York").date; got[sym] = s
                for sym in batch:
                    cache["bars"][sym] = got.get(sym, pd.Series(dtype=float))
                fetched += len(batch)
        fri += timedelta(days=7)
    pickle.dump(cache, open(path, "wb"))
    with_bars = sum(1 for s in cache["bars"].values() if len(s))
    print(f"{ticker}: {len(cache['contracts']) // 2} expiries, {fetched} contracts fetched, {with_bars} with bars")


def earnings(ticker):
    H = {"User-Agent": "wheel-research research@example.com"}
    base = requests.get(f"https://data.sec.gov/submissions/CIK{CIK[ticker]}.json", headers=H, timeout=30).json()
    frames = [pd.DataFrame(base["filings"]["recent"])]
    frames += [pd.DataFrame(requests.get("https://data.sec.gov/submissions/" + f["name"], headers=H, timeout=30).json())
               for f in base["filings"].get("files", [])]
    f = pd.concat(frames)
    f = f[(f.form == "8-K") & f["items"].fillna("").str.contains("2.02")]
    dates = sorted(d for d in set(pd.to_datetime(f.filingDate).dt.date) if d.year >= 2015)
    pd.to_pickle(dates, os.path.join(DATA, f"earnings_8k_{ticker}.pkl"))
    print(f"{ticker} earnings filings: {len(dates)}, last {dates[-1]}")


if __name__ == "__main__":
    for t in sys.argv[1:] or ["SPY", "COST"]:
        fetch(t)
        if t in CIK:
            earnings(t)
