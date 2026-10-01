# wheel strategy memory

Kept under 8KB on purpose. Every agent reads this before it works, so
adding something means editing or replacing something — not appending.

## Decisions
<!-- what was chosen and why, so it is not re-litigated -->
- NVDA only. Confirmed by Daniel 2026-10-01. The SOFI / multi-ticker spec
  (docs/superpowers/specs/2026-07-07-...) and its plan are SHELVED, not
  pending. Do not implement them or generalize the bot for other tickers
  unless Daniel asks. A separate "scan other equities for best premium per
  unit of risk" idea exists but is a future, separate version.
- Capital: $25k set aside for the challenge.
- Goal: beat the market, >=8% annual (README). Track record so far:
  3 trades Apr-Jun 2026, +1.21% total, ~4.8% annualized. Bot did not run
  over the summer.
- Current rules (not yet revisited): put strike 10% below spot, call strike
  10% above cost basis, expiry = first Friday >=14 days out (so 14-20 DTE),
  close at 50% profit and roll immediately. Cash-secured only, 1 contract.

## Components
<!-- the parts and what each one owns -->
- wheel_bot.py: state machine (NO_POSITION / SHORT_PUT / LONG_SHARES /
  SHORT_CALL), close-and-roll.
- strategy.py: pure logic (strikes, expiry, 50% check, market hours).
- alpaca_client.py: Alpaca paper API wrapper, NVDA hardcoded.
- summary.py: daily P&L printout.
- .github/workflows/wheel.yml: runs the bot every 15 min on weekdays;
  bot's is_market_hours() decides whether to act. Includes keepalive commit.

## Conventions
<!-- how work is done here: style, workflow, what to never do -->
- Paper trading only. Never switch to live keys.
- Keep strategy.py pure and tested; run pytest before committing.
- Strategy parameter changes (strike method, DTE, earnings policy) are
  Daniel's call. Lay out tradeoffs, don't pick for him.

## Gotchas
<!-- things that will bite: the surprise, and what to do instead -->
- Open orders are not checked. An unfilled DAY sell order still looks like
  NO_POSITION on the next run, so the bot can submit a duplicate. Today
  only buying power prevents it.
- close_option_position uses close_position (market order) and pays the
  full spread. Prefer a limit buy-to-close.
- get_nvda_price uses the ask, not mid/last; can be stale or 0 near open.
- Sizing uses the whole account's options_buying_power, not a $25k cap.
- One NVDA put ties up ~70% of $25k; the rest sits idle.
- No earnings filter. NVDA reports ~late Nov; the bot will sell through it.
- After assignment in a drop, "10% above cost basis" can be far OTM and
  pay ~nothing. No fallback or roll rule exists yet.
- get_target_expiry docstring says 14-28 days; code yields 14-20.
