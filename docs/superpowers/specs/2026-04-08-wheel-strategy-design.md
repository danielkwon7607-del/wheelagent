# Wheel Strategy Bot — Design Spec
**Date:** 2026-04-08
**Stock:** NVDA
**Account:** Alpaca Paper Trading
**Approach:** Claude-driven (Claude Code + alpaca-py + /schedule)

---

## Overview

An automated wheel strategy bot that runs on NVDA in an Alpaca paper trading account. Claude Code connects directly to Alpaca, executes trades via Python scripts using `alpaca-py`, and schedules itself to check positions every 15 minutes during market hours. The user checks their Alpaca dashboard once a day to review premiums collected and current position.

---

## Strategy Logic

### Stage 1: Sell Cash-Secured Put
- Sell 1 put contract (100 shares) on NVDA
- Strike price: ~10% below current market price
- Expiration: 2–4 weeks out (14–28 DTE)
- Collect premium upfront — visible immediately in Alpaca account

**Outcome A — Put expires worthless:**
- Keep the full premium
- Sell another put → repeat Stage 1

**Outcome B — Put is assigned (NVDA drops to strike):**
- Buy 100 shares of NVDA at strike price
- Effective cost basis = strike price − premium collected
- Move to Stage 2

### Stage 2: Sell Covered Call
- Sell 1 call contract against the 100 shares held
- Strike price: ~10% above cost basis (never below cost basis)
- Expiration: 2–4 weeks out (14–28 DTE)
- Collect premium upfront

**Outcome A — Call expires worthless:**
- Keep the full premium
- Sell another call → repeat Stage 2

**Outcome B — Call is assigned (NVDA rises above strike):**
- Shares get called away (sold at strike price)
- Collect stock appreciation + premium
- Return to Stage 1

---

## Rules

| Rule | Detail |
|------|--------|
| Cash check | Never sell a put unless account has enough buying power to cover 100 shares at the strike price. Strike is capped at floor(buying_power / 100) so the bot never overcommits the $10k account. |
| Cost basis protection | Never sell a covered call with a strike below cost basis |
| Early exit | If a contract reaches 50% of max profit before expiration, close it and redeploy |
| Market hours only | All trading activity strictly between 9:30am–4:00pm ET, Mon–Fri |
| No action after hours | Bot checks schedule but takes no action outside market hours |

---

## Schedule

| Task | Frequency | Time |
|------|-----------|------|
| Position check + action | Every 15 minutes | 9:30am–4:00pm ET, Mon–Fri |
| Daily summary | Once daily | 4:00pm ET |

---

## Components

### `wheel_bot.py`
Core logic script. Claude executes this directly. Responsibilities:
- Load credentials from `.env.paper`
- Connect to Alpaca via `alpaca-py`
- Check current position state (no position / holding put / holding shares)
- Determine correct action based on state and rules
- Execute trades
- Log all actions to `logs/wheel.log`

### `summary.py`
Generates daily summary. Responsibilities:
- Pull open positions, P&L, premiums collected this cycle
- Print summary to terminal (visible in Claude's output)
- Log to `logs/summary.log`

### `.env.paper`
Credentials file (already created, never committed to git).

### `logs/`
Directory for trade logs and daily summaries. Human-readable, one line per event.

---

## Data Flow

```
Claude Code
    └── reads .env.paper
    └── runs wheel_bot.py every 15 min (via /schedule)
            └── alpaca-py → Alpaca Paper API
                    └── check positions
                    └── place orders if needed
                    └── write to logs/wheel.log
    └── runs summary.py at 4pm ET
            └── pulls P&L from Alpaca
            └── writes to logs/summary.log
```

---

## Dependencies

- Python 3.10+
- `alpaca-py` (official Alpaca SDK)
- `python-dotenv` (load .env.paper)

---

## Out of Scope

- Live trading (paper only for now)
- Multiple simultaneous wheel cycles
- Options Greeks-based strike selection (use fixed 10% rule for now)
- Trailing stop / copy trading strategies
