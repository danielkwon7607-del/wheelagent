# Wheel Lab

Interactive backtester for the NVDA wheel: real option prices (June 2024 on)
and modelled prices (2016 on), stress tests, a design/test split with blind
mode, and overfitting guards. Open `lab/index.html` in a browser.

Rebuild the data after refreshing research data:

    research/.venv/bin/python lab/build_data.py   # writes lab/data.js (gitignored)
    node lab/parity_test.js                       # engine must match Python
    python3 lab/make_artifact.py                  # lab/dist/wheel-lab.html for publishing

`engine.js` mirrors `research/wheel_research.py` and `research/bs_research.py`
for the original rules; `parity_test.js` fails if they drift. Levers added
since (delta strikes, loss cuts, hybrid calls, rich-options filter, sizing)
exist only in `engine.js`.
