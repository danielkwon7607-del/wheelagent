# Wheel Lab

Interactive backtester for the NVDA wheel: real option prices (June 2024 on)
and modelled prices (2016 on), a design/test split with blind mode, and
overfitting guards. Open `lab/index.html` in a browser (`#stress` opens the
Stress test tab).

Rebuild the data after refreshing research data:

    research/.venv/bin/python research/prefetch_ticker.py AMZN
    research/.venv/bin/python lab/build_data.py   # lab/data.js (NVDA) + lab/data_<TICKER>.js, gitignored
    node lab/parity_test.js                       # engine must match Python
    node lab/search.js                            # ~2 min per ticker: every rule combination -> lab/best.js
    python research/spreads.py NVDA AMZN          # today's bid/ask spreads (run near the close)
    node lab/stress_null.js --worlds 300          # luck tests, ~30 min per ticker on all cores -> lab/stress.js
    python3 lab/make_artifact.py                  # lab/dist/wheel-lab.html for publishing

Publish with data.js, engine.js, best.js, stresstests.js, stress.js and every
data_<TICKER>.js as files.
Other tickers load on demand when picked. search.js picks the "best" rule
set per ticker by its neighborhood score (rank on Sharpe and yearly return,
real and model) and reports a design-only pick and a luck check with it.

`engine.js` mirrors `research/wheel_research.py` and `research/bs_research.py`
for the original rules; `parity_test.js` fails if they drift. Levers added
since (delta strikes, loss cuts, hybrid calls, rich-options filter, sizing)
exist only in `engine.js`.

The Stress test tab (`stresstests.js`) runs three checks on the bot's rules,
the basic wheel, the ★ best combo and your rules:

- Costs: reruns each at wider spreads (and wider spreads on the most volatile
  10% of days) and compares the break-even with what today's measured quotes
  say it would pay.
- Luck: `stress_null.js` reruns the whole model search on shuffled no-edge
  histories (stationary bootstrap, 20-day blocks, drift removed, fair option
  prices) and runs White's Reality Check on every rule set's real results.
- Shocks: adds a gap or crash to the real 2016-26 path at ~250 dates (model
  prices) and measures the hit, the worst point after, and the recovery.
