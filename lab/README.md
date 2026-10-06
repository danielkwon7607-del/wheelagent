# Wheel Lab

Interactive backtester for the NVDA wheel: real option prices (June 2024 on)
and modelled prices (2016 on), stress tests, a design/test split with blind
mode, and overfitting guards. Open `lab/index.html` in a browser.

Rebuild the data after refreshing research data:

    research/.venv/bin/python research/prefetch_ticker.py SPY COST AMZN WMT JNJ XOM
    research/.venv/bin/python lab/build_data.py   # lab/data.js (NVDA) + lab/data_<TICKER>.js, gitignored
    node lab/parity_test.js                       # engine must match Python
    node lab/search.js                            # ~2 min per ticker: every rule combination -> lab/best.js
    python3 lab/make_artifact.py                  # lab/dist/wheel-lab.html for publishing

Publish with data.js, engine.js, best.js and every data_<TICKER>.js as files.
Other tickers load on demand when picked. search.js picks the "best" rule
set per ticker by its neighborhood score (rank on Sharpe and yearly return,
real and model) and reports a design-only pick and a luck check with it.

`engine.js` mirrors `research/wheel_research.py` and `research/bs_research.py`
for the original rules; `parity_test.js` fails if they drift. Levers added
since (delta strikes, loss cuts, hybrid calls, rich-options filter, sizing)
exist only in `engine.js`.
