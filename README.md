# NVDA Wheel Strategy Bot

An automated options wheel strategy bot running on NVDA via Alpaca paper trading.

## What it does

Runs the wheel strategy autonomously every 15 minutes during market hours:

1. **NO_POSITION** → sells a cash-secured put 10% below current price
2. **SHORT_PUT** → monitors for 50% profit, closes early if hit
3. **LONG_SHARES** (if assigned) → sells a covered call 10% above cost basis
4. **SHORT_CALL** → monitors for 50% profit, closes early if hit
5. Repeats

## Live results (paper trading)

**Goal: consistently beat the market — targeting ≥8% annual portfolio growth (S&P 500 historical average).**

| # | Contract | Return | Outcome |
|---|----------|--------|---------|
| 1 | NVDA260424P00169000 | +0.20% | Expired worthless ✅ |
| 2 | NVDA260522P00175000 | +0.62% | Expired worthless ✅ |
| 3 | NVDA260618P00187000 | +0.40% | Expired worthless ✅ |

**Total: +1.21% in ~3 months** — on track for ~4.8% annualized, approaching the 8% target as trade frequency increases

## Structure

```
wheel_bot.py        # Main bot — orchestrates state machine
strategy.py         # Pure logic — strike selection, expiry, state, early close
alpaca_client.py    # Alpaca API wrapper — quotes, orders, positions
summary.py          # Daily P&L summary printer
tests/              # Full test suite (pytest)
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env.paper
# Add your Alpaca API keys to .env.paper
python wheel_bot.py
```

## Scheduling

Runs silently via Windows Task Scheduler using `run_silent.vbs` every 15 minutes, 9:30am–4pm ET. Logs to `C:\Users\<you>\wheel_bot_logs\wheel.log`.

## Stack

- Python 3.10+
- [alpaca-py](https://github.com/alpacahq/alpaca-py)
- pytest
