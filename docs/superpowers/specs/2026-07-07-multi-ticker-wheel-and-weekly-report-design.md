# Multi-Ticker Wheel (SOFI) + Weekly Email Report — Design

Date: 2026-07-07
Status: Approved direction, pending user review of this spec

## Goal

Raise strategy ROI toward a 10%+ annual target without unbounded downside, and
prove the system works end-to-end with an automated weekly analyst-style email
report. Everything runs free (GitHub Actions + Gmail SMTP + Alpaca paper).

Two deliverables, built in order:

1. **Strategy engine:** generalize the NVDA-only wheel bot into a multi-ticker
   wheel with SOFI as the primary underlying.
2. **Reporting:** a weekly email report, holiday-aware, sent at the end of each
   trading week, following the user's fixed 9-section format.

## Part 1 — Multi-ticker wheel engine

### Watchlist configuration

New `config.py` holding a `WATCHLIST` of per-ticker settings:

```python
WATCHLIST = [
    Ticker(
        symbol="SOFI",
        enabled=True,            # opens new positions
        max_contracts=4,         # concurrent CSP contracts cap
        put_otm_pct=0.08,        # sell puts ~8% below spot (tunable)
        call_otm_pct=0.05,       # covered calls ~5% above cost basis
    ),
    Ticker(
        symbol="NVDA",
        enabled=False,           # manage existing position; open no new ones
        max_contracts=1,
        put_otm_pct=0.10,
        call_otm_pct=0.10,
    ),
]
CASH_BUFFER = 1500.0             # never commit the last $1,500 of buying power
```

Rationale:
- SOFI at ~$18/share ties up ~$1,600 per safe-strike contract → 4 contracts
  ≈ $6,400 of the ~$8,100 currently free, leaving a buffer.
- `put_otm_pct=0.08` targets roughly 1-in-8/1-in-10 assignment on a high-IV
  name — the agreed tradeoff to reach ~10% annualized. Tunable in one line.
- NVDA `enabled=False`: the open $172.50 put (exp 2026-07-24) is managed to
  completion (hold / 50% close / assignment → covered calls), but no new NVDA
  puts are opened. Re-enable later by flipping the flag. ServiceNow (NOW) can
  be added later as one more entry.

### Engine changes

`wheel_bot.py` loops over the watchlist; all "NVDA" hardcoding is removed:

- `alpaca_client.py`: every method takes a `symbol` parameter
  (`get_price(symbol)`, `get_stock_position(symbol)`,
  `get_open_options(symbol)`, `find_put_contract(symbol, ...)`, etc.).
  Option-symbol parsing generalizes (occ format: `{SYM}{YYMMDD}{P/C}{strike}`,
  parsed from position symbols by regex rather than assuming `NVDA` prefix).
- `strategy.py`: `get_put_strike(price, buying_power, otm_pct)` and
  `get_call_strike(cost_basis, otm_pct)` take the percentage instead of
  hardcoding 10%.
- Per-ticker state machine, same as today: NO_POSITION → SHORT_PUT →
  (assigned) LONG_SHARES → SHORT_CALL → repeat, with 50%-profit
  close-and-roll preserved.
- **Multiple contracts:** when in NO_POSITION (or after a roll), the bot sells
  up to `max_contracts` puts, but only as many as
  `(options_buying_power - CASH_BUFFER)` can secure. One order per contract at
  the same strike/expiry (simpler fills, simpler accounting).
- Capital allocation across tickers is first-come by watchlist order; the
  buying-power check before each order prevents over-commitment. No margin,
  no naked options — cash-secured only, unchanged.

### Safety invariants (unchanged from today)

- Cash-secured puts and covered calls only.
- Buying-power check before every order.
- If a close hasn't filled, defer the roll to the next scheduled run.
- `is_market_hours()` gate on every run.

## Part 2 — Weekly email report

### Data source: Alpaca is the single source of truth

Each GitHub Actions run is ephemeral, so the report never relies on local
state. It reconstructs the week from broker records:

- `get_account()` — equity, cash, buying power.
- `get_all_positions()` — open positions and unrealized P&L.
- Account activities API (`FILL`, `OPASN`, `OPEXP`, etc.) — every fill,
  assignment, expiration, and rejection during the week → activity log,
  premium collected, realized P&L, wheel-phase transitions.
- Portfolio history API — weekly / MTD / YTD / since-inception returns.
- Market calendar API — trading-day awareness.

### Format

`report.py` renders the user's fixed 9-section template exactly
(header, account snapshot, per-ticker wheel mechanics, activity log, income
summary, performance metrics, 10% goal meter with ASCII progress bar, system
health check, next-week outlook), preceded by the greeting line
"hey its claude, here's your weekly trading report" and the SMS-condensed
block at the top. Tone rules honored: exact numbers, no hedging on facts,
negatives stated plainly, every open position mentioned even if "no action,
monitoring".

Goal-meter math, per the user's rules:
- pro-rated target = 10% × (days elapsed in year / 365)
- pace = YTD return − pro-rated target → AHEAD/BEHIND by X.XX pts
- projection = mean weekly return since inception, annualized (flagged noisy
  while the track record is short).

System health check verifies, not assumes:
- market data responded this run,
- positions reconcile against broker records,
- order counts from activities (placed / filled / rejected),
- collateral math consistent with buying power,
- scheduled-run gap detection: if no bot activity happened on a trading day
  this week, flag it (catches silent workflow failures).

### Delivery and scheduling

- Gmail SMTP (SSL, port 465), from and to daniel.kwon7607@gmail.com.
  Credentials from env: `GMAIL_APP_PASSWORD` (already in GitHub secrets),
  address constant in config.
- New workflow `.github/workflows/weekly-report.yml`: cron fires every
  weekday ~21:30 UTC (after market close). The script asks the Alpaca
  calendar: "is today the last trading day of this calendar week?" If yes →
  send; if no → exit quietly. This makes Friday-holiday weeks send on
  Thursday automatically.
- Failure visibility: if report generation itself errors, the workflow fails
  (red X + GitHub email notification) rather than silently skipping.

## Testing

- Unit tests for: multi-ticker config handling, per-ticker state machine,
  contract-count sizing under buying-power limits, OCC symbol parsing,
  strike math with configurable OTM percentages.
- Report tests with mocked Alpaca data: template rendering, goal-meter math,
  last-trading-day-of-week logic (normal week, Friday-holiday week),
  health-check flag paths (rejected order, missed run).
- Email send path tested with a mocked SMTP client; one real end-to-end test
  send before first scheduled run.

## Rollout sequence

1. Engine refactor + tests → deploy → verify SOFI puts sell correctly on
   paper (first market-hours run).
2. Report module + tests → one manual test send → enable weekly schedule.
3. (Later, optional) re-enable NVDA or add NOW once the 7/24 put resolves;
   phase-3 idea: agentic report commentary via Claude Agent SDK.

## Out of scope

- Historical backtesting engine (separate project if ever wanted).
- Live (real-money) trading.
- SMS delivery (email chosen; Twilio only if user later wants to pay).
- Any change to the TETHR project.
