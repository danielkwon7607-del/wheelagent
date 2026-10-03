# Research (throwaway)

Quick wheel-strategy studies from 2026-10-03, kept so the numbers can be
reproduced. Not the Phase 2 backtester: it doesn't reuse the bot's own code.

- `wheel_research.py`: day-by-day wheel on REAL Alpaca NVDA option bars
  (June 2024 on, after the 10:1 split). Bars are last trades, not bid/ask,
  so fills are close -/+ an assumed half-spread.
- `bs_research.py`: 2016 on, with MODELLED prices (Black-Scholes, IV =
  calibrated multiple of realized vol). An approximation: no real skew or
  bid/ask before 2024.
- `grid.py`: rule variants on real prices. `report.py`: metric tables.

Setup (separate venv, research deps aren't in the bot's requirements):

    python -m venv research/.venv
    research/.venv/bin/pip install -r research/requirements.txt
    research/.venv/bin/python research/fetch_data.py
    research/.venv/bin/python research/prefetch.py   # ~2 min, ~12k option contracts
    research/.venv/bin/python research/grid.py
