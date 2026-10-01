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
(I have yet to run this script throughout the summer, but when I optimize the script again, we should see a much higher annualzied rate eventually)

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

Runs on GitHub Actions. A free [cron-job.org](https://cron-job.org) job starts the
workflow every 15 minutes, 9:00am–3:45pm New York time (6:00am–12:45pm PT),
Monday–Friday. The bot itself only trades 9:30am–4pm ET. GitHub's built-in
schedule was too unreliable (runs hours late or skipped).

- Logs: the Actions tab on GitHub, timestamps in Pacific time.
- Set up or update the trigger (for example, after renewing the GitHub token):
  fill in `.env.trigger` (gitignored) and run `python setup_trigger.py`.
- Run once by hand: Actions tab → Wheel Bot → Run workflow, or `python wheel_bot.py` locally.

## Stack

- Python 3.10+
- [alpaca-py](https://github.com/alpacahq/alpaca-py)
- pytest
