# Multi-Ticker Wheel (SOFI) + Daily Email Report — Design

Date: 2026-07-07
Status: Approved direction, pending user review of this spec
Revised: bumped SOFI put cushion 8% → 12% OTM after pulling 2yr SOFI
volatility data (3-week windows ended down ≥8% in 22% of cases historically —
too aggressive for the agreed ~1-in-8/10 assignment rate); report cadence
changed from weekly-only to every trading day per user request.

## Goal

Raise strategy ROI toward a 10%+ annual target without unbounded downside, and
prove the system works end-to-end with an automated daily analyst-style email
report. Everything runs free (GitHub Actions + Gmail SMTP + Alpaca paper).

Two deliverables, built in order:

1. **Strategy engine:** generalize the NVDA-only wheel bot into a multi-ticker
   wheel with SOFI as the primary underlying.
2. **Reporting:** an email report sent after close every trading day,
   following the user's fixed 9-section format (with the reporting window
   rolling from the current week's Monday through today, so weekly aggregates
   still make sense on a Tuesday as well as a Friday).

## Part 1 — Multi-ticker wheel engine

### Watchlist configuration

New `config.py` holding a `WATCHLIST` of per-ticker settings:

```python
WATCHLIST = [
    Ticker(
        symbol="SOFI",
        enabled=True,            # opens new positions
        max_contracts=4,         # concurrent CSP contracts cap
        put_otm_pct=0.12,        # sell puts ~12% below spot (tunable)
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
- SOFI at ~$17.75/share, 12% OTM → strike ~$15.50, ties up ~$1,550 per
  contract → 4 contracts ≈ $6,200 of the ~$8,100 currently free, leaving a
  buffer.
- `put_otm_pct=0.12` is calibrated against 2 years of actual SOFI daily bars
  (501 trading days): 3-week rolling windows (the life of one contract) ended
  down ≥8% in 22.0% of cases and ≥10% in 17.5% — an 8% cushion would have
  meant assignment roughly 1-in-4/5, not the agreed 1-in-8/10. A 12% cushion
  targets that agreed rate more realistically. SOFI's daily range over the
  period was $6.32–$32.21 and it has had six single days of ≥10% drawdown, so
  this remains a materially more volatile underlying than NVDA — the richer
  premium is the direct trade for that risk, and assignment is the accepted,
  bounded downside (own the shares, sell calls against them), not a tail risk
  to be engineered away entirely.
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

## Part 2 — Daily email report

### Data source: Alpaca is the single source of truth

Each GitHub Actions run is ephemeral, so the report never relies on local
state. It reconstructs the current reporting window from broker records —
"this week" always means the current calendar week's Monday (or the first
trading day of the week, on a Monday holiday) through today, so the same
9-section format is sensible whether it's sent on a Tuesday or a Friday:

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
- New workflow `.github/workflows/daily-report.yml`: cron fires every weekday
  ~21:30 UTC (after market close). The script asks the Alpaca calendar
  whether today was a trading day; if not (weekend edge case in the cron, or
  an unexpected market holiday) it exits quietly with no email. Otherwise it
  sends — one email per trading day, every trading day.
- The fixed template's greeting line stays exactly
  "hey its claude, here's your weekly trading report" per the user's format,
  even though delivery is now daily — the report content itself still covers
  the rolling week-to-date window described above.
- Failure visibility: if report generation itself errors, the workflow fails
  (red X + GitHub email notification) rather than silently skipping.

## Testing

- Unit tests for: multi-ticker config handling, per-ticker state machine,
  contract-count sizing under buying-power limits, OCC symbol parsing,
  strike math with configurable OTM percentages.
- Report tests with mocked Alpaca data: template rendering, goal-meter math,
  rolling week-to-date window logic (mid-week send, Monday-holiday week),
  health-check flag paths (rejected order, missed run).
- Email send path tested with a mocked SMTP client; one real end-to-end test
  send before first scheduled run.

## Rollout sequence

1. Engine refactor + tests → deploy → verify SOFI puts sell correctly on
   paper (first market-hours run).
2. Report module + tests → one manual test send → enable daily schedule.
3. (Later, optional) re-enable NVDA or add NOW once the 7/24 put resolves;
   phase-3 idea: agentic report commentary via Claude Agent SDK.

## Out of scope

- Historical backtesting engine (separate project if ever wanted).
- Live (real-money) trading.
- SMS delivery (email chosen; Twilio only if user later wants to pay).
- Any change to the TETHR project.
