# wheel strategy memory

Kept under 8KB on purpose. Every agent reads this before it works, so
adding something means editing or replacing something — not appending.

## Decisions
<!-- what was chosen and why, so it is not re-litigated -->
- NVDA only. Confirmed by Daniel 2026-10-01. The SOFI / multi-ticker spec
  (docs/superpowers/specs/2026-07-07-...) and its plan are SHELVED, not
  pending. Do not generalize the live bot for other tickers unless Daniel
  asks. The Wheel Lab can backtest SPY and COST (his ask, 2026-10-05); that
  is research only. A "scan equities for premium per unit of risk" idea is
  a future, separate version.
- Capital: $25k set aside for the challenge. Enforced in code as
  strategy.CAPITAL_CAP (put collateral + share cost basis), whatever the
  paper account balance says.
- Goal: beat the market, >=8% annual (README). No reconciled P&L yet;
  rebuild it from account activities (Phase 5), don't trust old figures.
- Current rules (not yet revisited): put strike 10% below spot (~0.07
  delta in Oct 2026, premiums ~$0.50-1.25), call strike 10% above cost
  basis, expiry = first Friday >=14 days out (14-20 DTE), close at 50%
  profit and roll immediately. Cash-secured only, 1 contract.
- Build plan: docs/kiln-build-prompt.md, phases 0-6, stop for Daniel's
  review after each. Phase 0 (4 bug fixes) done on branch phase0-bug-fixes.
- Research 2026-10-03: the basic wheel kept ~63% of NVDA's CAGR but ~90%
  of its max drawdown; premium was ~18% of 2024-26 profit. A 200-day filter
  on new puts never fires (already assigned). Basis vs spot calls is a
  regime tradeoff.
- Search 2026-10-05: NVDA best = 0.30 delta, 21d, TP 75%, calls 5% above
  price, pricey filter 1.1: real 20.7%/yr Sharpe 1.96 dd -3.9% vs bot 21.5%/
  1.09/-13.2%. No pick on any ticker beats the luck allowance after ~30k
  tries, so the plan is a forward test, not a switch. Daniel likes AMZN.
- Daniel approves rules, not trades: once a rule set is picked the bot
  runs fully automatically. Never add per-trade confirmation steps.

## Components
<!-- the parts and what each one owns -->
- wheel_bot.py: state machine (NO_POSITION / SHORT_PUT / LONG_SHARES /
  SHORT_CALL), close-and-roll. Settles open orders BEFORE reading
  positions; checks every quote before acting on it.
- strategy.py: pure logic and the safety constants (cap, quote age,
  spread limits, stale-order minutes, order-id prefix).
- alpaca_client.py: Alpaca paper API wrapper, NVDA hardcoded. Returns raw
  Quote(bid, ask, timestamp); all orders are DAY limit orders tagged
  client_order_id "wheelbot-<hex>" with an explicit position_intent.
- summary.py: daily P&L printout.
- research/: throwaway study scripts (separate venv, data gitignored).
  Not the Phase 2 backtester: doesn't reuse the bot's own functions.
- lab/: Wheel Lab, a browser backtester (engine.js + index.html). Published
  at https://claude.ai/artifact/LRmdj5dTBN7iruHbzEByP1 (republish from
  lab/dist/wheel-lab.html with data.js + engine.js as files). engine.js must
  match research/ on the original rules: run node lab/parity_test.js after
  any engine change. Tries start at 40 (the research grid + model runs).
  Tickers NVDA/AMZN/WMT/JNJ/XOM/SPY/COST (research/prefetch_ticker.py; non-
  NVDA load lazily from data_<TK>.js). Fits $25k today -> $25k account (strike
  capped like the bot); SPY/COST run $80k/$110k, shown per $25k. Model IV
  uses measured skew curves; NVDA stays flat 1.13 for parity. lab/search.js
  (30,240 combos/ticker, ~2 min each) writes best.js: plateau pick, 30+
  trades, 8%/yr floor, design-only pick + luck check. Red line = that pick.
- logging_setup.py: log/summary timestamps in Pacific (Daniel is on the
  west coast). Display only — market hours stay in New York time; never
  move is_market_hours to Pacific (it would trade 12:30-7pm ET).
- Trigger: cron-job.org job 8559901 "wheel bot trigger" (Daniel's account)
  POSTs workflow_dispatch on main every 15 min, 9:00-15:45 America/New_York,
  Mon-Fri; emails Daniel after 2 failures. It holds a fine-grained GitHub
  token (this repo, Actions r/w; expiry unknown). setup_trigger.py creates
  or updates it from gitignored .env.trigger (token + cron-job.org API key).
- .github/workflows/wheel.yml: workflow_dispatch only, concurrency group
  wheel-bot (runs queue, never overlap). The bot's is_market_hours()
  decides whether to act.

## Conventions
<!-- how work is done here: style, workflow, what to never do -->
- Paper trading only. Never switch to live keys.
- Keep strategy.py pure and tested; run pytest before committing.
- Strategy parameter changes (strike method, DTE, earnings policy) are
  Daniel's call. Lay out tradeoffs, don't pick for him.
- Bot code goes live on the next cron run after it reaches main. Work on a
  branch; merge outside market hours and only after Daniel's review.
- Wheel Lab look is Daniel's pick (2026-10-05): Robinhood/TradingView stock
  page, neutral ink/paper, green/pink only for up/down, calm, no blue
  chrome. Lines (his pick): NVDA forest green, SPY black (white in dark),
  T-bills dotted gold, bot's rules blue everywhere, COST brown dash-dot.
  Gold vs green fails CVD in dark mode: keep dashes + legend + price tags.
  Alpha vs COST is inflated (beta ~0.1): judge edge vs the stock wheeled.
  He rejected a terminal look and a bubbly glass look before this.
- The bot only cancels its own (wheelbot-) orders. Any other open NVDA
  order blocks it until gone — never auto-cancel manual orders.

## Gotchas
<!-- things that will bite: the surprise, and what to do instead -->
- Don't re-add a GitHub `schedule:` trigger. It was throttled to 2-4
  runs/day (hours late) and stopped entirely after 2026-09-25. If runs
  stop, check the cron-job.org job history and whether the token expired.
- is_market_hours ignores holidays and early closes. On those days only
  the quote-staleness checks stop trades; Alpaca get_clock() knows the
  real calendar.
- Option data is the free "indicative" feed only (OPRA agreement not
  signed). Quotes ~0-5s old; snapshots include IV and greeks. Its prices
  can be non-monotonic across strikes — sanity-check before trusting.
- Historical option bars (free): from ~2024-01, trade-based OHLC (no
  bid/ask), illiquid strikes skip days, pre-2024-06-10 under pre-split
  symbols. A request whose end is within ~15 min of now gets 403 "OPRA
  agreement is not signed". Expired contracts: GetOptionContractsRequest
  status=INACTIVE. Fetch 100 symbols per request (12k contracts ~2 min).
- Earnings dates: SEC EDGAR 8-K item 2.02 filings (research/fetch_data.py);
  NVDA reports after the close, so the reaction is the next trading day.
- get_put_strike silently lowers the strike to whatever capital allows.
  With capital short (e.g. a put already open), it targets junk far-OTM
  strikes; today only the zero-bid / wide-spread checks stop a sale.
- Limit orders sit at mid. An unfilled order is cancelled after 10 min and
  re-priced at the new mid on the next run; there is no stepping toward
  bid/ask yet (Phase 4), so a close may never fill and ride to expiry.
- "10% below spot" is ~0.07-0.10 delta on NVDA but ~0.02 on SPY and ~0.03
  on COST (tiny premium, never assigned). Compare stocks by delta.
- No earnings filter. NVDA reports ~late Nov; the bot will sell through it.
- After assignment in a drop, "10% above cost basis" can be far OTM and
  pay ~nothing. No fallback or roll rule exists yet.
- lab/index.html is a full document for local use; the artifact host adds
  its own wrapper, so publish lab/dist/ from make_artifact.py. Locally there
  is no [hidden] reset, so the page's CSS carries its own. uPlot charts need
  explicit padding or a short chart gets a zero-height plot.
- Alpaca rejects a cancel on an order that just filled; cancel_order
  returns False then, and the bot re-reads state instead of failing.
