# Build prompt: professional NVDA wheel system

Paste everything below the line into the kiln session.

---

You are working on Daniel's NVDA wheel bot in this repo. Read `.kiln/index.md`
first. It holds settled decisions (NVDA only, $25k, paper trading, SOFI plan
shelved) and known bugs. Do not reopen settled decisions.

## The goal

Turn this bot from a fixed-rule script into a system built the way a
professional options quant would build it: rules are hypotheses, every rule is
a parameter, every parameter is tested on historical data with realistic costs,
and nothing goes to paper trading until the backtest says it beats simple
alternatives after costs.

"Maximize gains" means the best return for the risk taken, not the biggest
raw number. The way to make a short-option strategy show huge returns is to
sell closer strikes with more size, and that is also how accounts blow up.
Every result you report must show return AND risk side by side.

Daniel picks the final parameters. Your job is to build the tools, run the
tests, and lay out the tradeoffs clearly. Do not choose for him.

## Ground rules

- Paper trading only. Never touch live keys.
- Hard capital cap of $25,000, enforced in code, no matter what the account
  balance says.
- Cash-secured puts and covered calls only. No naked options, no margin.
  (Spreads are a possible later question for Daniel, not something to build
  now.)
- Keep `strategy.py`-style pure logic separate from API code. Everything
  pure gets unit tests. Run `pytest` before every commit.
- Small commits, one phase at a time. At the end of each phase, update
  `.kiln/index.md` (edit and replace, stay under 8KB) and stop for Daniel's
  review.

## Phase 0: Fix the known bugs

These are in `.kiln/index.md` under Gotchas. Fix them before building
anything new:

1. Check open orders, not just positions, before placing any order. Cancel
   stale unfilled orders before replacing them. Running the bot twice in a
   row must never create two orders (idempotency test).
2. Buy-to-close with a limit order, not `close_position` at market.
3. Price the underlying from mid or last trade, not the ask. Refuse to trade
   if the quote is stale, zero, or the option spread is wider than a set
   limit.
4. Size against `min(options_buying_power, 25000 - capital_in_use)`.

## Phase 1: Data

Find out what data is actually available and write it down before
building on it.

- Live: Alpaca's option chain snapshot endpoint returns IV and greeks
  (delta, gamma, theta, vega). Confirm what this account gets and use it
  for strike selection instead of "10% below spot."
- Historical: check what Alpaca's historical option data covers (bars
  vs quotes, how far back). If it's not enough for a real backtest, list
  the alternatives with cost and coverage (for example ThetaData, Polygon,
  ORATS, CBOE DataShop) and ask Daniel before paying for anything.
- Also needed: NVDA daily price history, NVDA earnings dates (past and
  next), ex-dividend dates, risk-free rate (T-bill yield) so idle cash and
  benchmarks are measured fairly, and VIX for regime context.
- Store data locally in a simple format (parquet or sqlite) with a script
  that rebuilds it. Do not commit large data files.

If only underlying prices are available, a Black-Scholes model priced off
historical IV is a fallback. It must be clearly labeled as an approximation
in every report, because it misses real bid/ask spreads and skew.

## Phase 2: Backtester

Event-driven, one step per trading day, replaying the same state machine
the live bot uses (ideally the same pure functions, so backtest and live
can't drift apart).

Must model:
- Fills at mid minus a configurable slice of the spread (default: half the
  spread against us). Alpaca option fees and regulatory fees per contract.
- Assignment at expiry when ITM, and early assignment risk on ITM calls
  before ex-dividend dates.
- Cash earning the T-bill rate while it sits as collateral or idle.
- Earnings gaps (this is where short puts lose the most money).

Outputs per run: total and annualized return, Sharpe, Sortino, max
drawdown and how long it took to recover, worst month, CVaR 5% (average of
the worst 5% of periods), win rate, average win vs average loss, assignment
rate, capital utilization, number of trades, and an equity curve chart.

Always compare against these benchmarks over the same window:
1. Buy and hold NVDA with the same $25k
2. Buy and hold SPY
3. T-bills only
4. The current bot rules (10% OTM, 14-20 DTE, 50% take profit)

A rule set that can't beat T-bills on Sharpe, or that matches NVDA buy and
hold with a worse drawdown, is not worth running. Say so plainly.

## Phase 3: Rules to test

Make each of these a config parameter and test the ranges listed. These
are the levers professionals actually use on a wheel.

| Lever | What to test |
|---|---|
| Put strike | Delta 0.15, 0.20, 0.25, 0.30, 0.35 vs current fixed 10% OTM |
| Days to expiry | ~7, ~14-20 (current), ~30, ~45 |
| Profit take | 25%, 50% (current), 75%, hold to expiry |
| Time exit | Close or roll at 21 DTE vs hold |
| Loss rule | None vs close/roll when option is worth 2x or 3x the credit |
| Roll when tested | When delta passes ~0.50, roll down and out for a net credit vs take assignment |
| Earnings | Skip any expiry that crosses earnings vs sell through it on purpose |
| Volatility filter | Only sell when IV rank or IV vs realized vol is above a threshold vs always sell |
| Trend filter | Skip new puts when NVDA is below its 200-day average vs no filter |
| Covered call after assignment | Delta 0.20-0.30 with strike floored at cost basis vs allow below cost basis vs current 10% above cost basis |
| Entry timing | Avoid first and last 15 minutes of the session |

Avoid overfitting:
- Split history into in-sample and out-of-sample. Pick on in-sample,
  report on out-of-sample. Better: walk-forward.
- Report how many combinations were tried. With hundreds of combos, the
  best one is partly luck.
- Prefer a parameter region that works broadly over one sharp peak.
- Show the top 5 rule sets in a table with their tradeoffs. Do not crown
  one. Daniel chooses.

## Phase 4: Live engine upgrades

Once Daniel picks rules:
- Config file holds every parameter from Phase 3. No magic numbers in
  code.
- Strike selection by delta from the live chain, with minimum open
  interest, minimum volume, and maximum spread filters.
- Limit orders at mid, then step toward the bid in small increments over
  a few runs if not filled, with a floor below which we don't sell.
- Earnings blackout read from the calendar, not hardcoded.
- Circuit breakers: stop opening new positions if drawdown from peak
  passes a set limit, if data looks wrong, or if 3 orders in a row are
  rejected. Log why and alert.
- Reconcile every run: positions, open orders, and cash must agree with
  what the bot expects. If not, do nothing and alert.

## Phase 5: Records and reporting

GitHub Actions runs are ephemeral, so the record must live somewhere
durable. Rebuild history from Alpaca account activities (fills,
assignments, expirations) and keep a trade journal (CSV or sqlite)
committed or stored outside the runner.

Each trade record: entry and exit time, contract, delta and IV at entry,
credit, fill vs mid at the time (slippage), exit reason, P&L, days held.

Daily report: account value vs $25k start, YTD return vs the 8% target
pro-rated, open positions with current delta and P&L, days to next
earnings, and live results vs what the backtest predicted. If live is
running worse than backtest, flag it and say why if you can tell.

## Phase 6: Forward test

Run the chosen rules in paper for a set number of trades (agree the
number with Daniel up front, at least 10-15 cycles) before calling
anything proven. Three trades is not a track record.

## What to tell Daniel honestly

- Selling options has a high win rate but the losses are large and rare.
  One bad earnings gap can erase months of premium. Short puts on one
  stock carry nearly the same downside as owning that stock.
- With $25k at NVDA's current price, one contract uses most of the
  capital, so the bot can only hold one at a time. That
  limits diversification and sizing no matter how good the rules are.
- If the backtest says the best wheel rules don't beat simply holding
  NVDA or SPY after risk, report that. It's a useful answer.
