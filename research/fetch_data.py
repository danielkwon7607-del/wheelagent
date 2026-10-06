"""Download the inputs the research scripts need into research/data/ (gitignored).
Run from the repo root: python research/fetch_data.py, then python research/prefetch.py."""
import io
import os
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
load_dotenv(os.path.join(HERE, "..", ".env.paper"))

from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

client = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
for adj in ("split", "all"):  # split-adjusted for the wheel, total return for benchmarks
    df = client.get_stock_bars(StockBarsRequest(symbol_or_symbols=["NVDA", "SPY", "COST", "AMZN", "WMT", "JNJ", "XOM"], timeframe=TimeFrame.Day,
                                                start=datetime(2015, 6, 1), end=datetime.now(), adjustment=adj,
                                                feed=DataFeed.SIP)).df
    df.to_pickle(os.path.join(DATA, f"stock_{adj}.pkl"))

# 3-month T-bill rate (FRED DTB3), for interest on cash and the T-bill benchmark
tb = pd.read_csv(io.StringIO(requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3", timeout=30).text))
tb.columns = ["date", "rate"]
tb["rate"] = pd.to_numeric(tb.rate, errors="coerce")
tb.dropna().to_pickle(os.path.join(DATA, "tbill.pkl"))

# NVDA earnings dates: SEC 8-K filings with item 2.02 (results of operations)
H = {"User-Agent": "wheel-research research@example.com"}
base = requests.get("https://data.sec.gov/submissions/CIK0001045810.json", headers=H, timeout=30).json()
frames = [pd.DataFrame(base["filings"]["recent"])]
frames += [pd.DataFrame(requests.get("https://data.sec.gov/submissions/" + f["name"], headers=H, timeout=30).json())
           for f in base["filings"].get("files", [])]
f = pd.concat(frames)
f = f[(f.form == "8-K") & f["items"].fillna("").str.contains("2.02")]
pd.to_pickle(sorted(d for d in set(pd.to_datetime(f.filingDate).dt.date) if d.year >= 2015), os.path.join(DATA, "earnings_8k.pkl"))
print("done")
