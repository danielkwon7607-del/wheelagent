from dataclasses import dataclass
from datetime import date, timedelta, datetime
import math
import re
import pytz


# Safety limits. Phase 4 moves these into a config file.
CAPITAL_CAP = 25_000.0         # most capital the bot may commit, whatever the account holds
MAX_QUOTE_AGE_SECONDS = 60     # refuse to trade on a quote older than this
MAX_OPTION_SPREAD_PCT = 0.25   # refuse to trade an option whose (ask - bid) / mid is wider
MAX_STOCK_SPREAD_PCT = 0.01    # wider than this, the stock quote is junk; use last trade
STALE_ORDER_MINUTES = 10       # a bot order still open after this long is cancelled and re-priced
BOT_ORDER_PREFIX = "wheelbot-" # client_order_id prefix, so the bot only ever cancels its own orders

# Put strike rule. "otm" is the original rule (10% below the price). "delta"
# picks the put whose delta is closest to PUT_DELTA, worked out from each
# contract's own mid price the same way the Wheel Lab backtests do. Which rule
# runs is Daniel's call: he switched to delta on 2026-10-22.
PUT_STRIKE_METHOD = "delta"
PUT_DELTA = 0.30
DELTA_TOLERANCE = 0.10         # no put within this of PUT_DELTA (e.g. capital too short) -> don't sell
MIN_OPEN_INTEREST = 100        # skip contracts almost nobody holds
RISK_FREE_RATE = 0.04          # for Black-Scholes; a point either way moves a 0.30 delta ~0.003


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    timestamp: datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class ChainOption:
    """One contract from the live option chain."""
    symbol: str
    strike: float
    expiry: date
    quote: Quote
    open_interest: int


def quote_problem(quote: Quote, now: datetime, max_spread_pct: float = MAX_OPTION_SPREAD_PCT) -> str | None:
    """Returns why a quote is unsafe to trade on, or None if it is usable."""
    if quote.bid <= 0 or quote.ask <= 0:
        return f"zero bid/ask ({quote.bid}/{quote.ask})"
    if quote.ask < quote.bid:
        return f"crossed quote ({quote.bid}/{quote.ask})"
    age = (now - quote.timestamp).total_seconds()
    if age > MAX_QUOTE_AGE_SECONDS:
        return f"stale quote ({age:.0f}s old)"
    spread_pct = (quote.ask - quote.bid) / quote.mid
    if spread_pct > max_spread_pct:
        return f"spread too wide ({quote.bid}/{quote.ask}, {spread_pct:.0%} of mid)"
    return None


def underlying_price(quote: Quote, last_price: float, last_time: datetime, now: datetime) -> float | None:
    """Stock price from the quote mid, falling back to the last trade.
    Returns None if neither is fresh and sane — the bot must not trade then."""
    if quote_problem(quote, now, max_spread_pct=MAX_STOCK_SPREAD_PCT) is None:
        return quote.mid
    if last_price > 0 and (now - last_time).total_seconds() <= MAX_QUOTE_AGE_SECONDS:
        return last_price
    return None


def round_to_tick(price: float) -> float:
    """NVDA is in the options Penny Program: $0.01 ticks under $3, $0.05 at $3 and up."""
    tick = 0.01 if price < 3 else 0.05
    return round(round(price / tick) * tick, 2)


def occ_strike(symbol: str) -> float:
    """Strike from an OCC option symbol, e.g. NVDA261016P00207500 -> 207.5."""
    return int(symbol[-8:]) / 1000


def is_nvda_symbol(symbol: str) -> bool:
    """True for NVDA stock or an NVDA option contract."""
    return symbol == "NVDA" or re.fullmatch(r"NVDA\d{6}[CP]\d{8}", symbol) is not None


def available_capital(options_buying_power: float, capital_in_use: float, cap: float = CAPITAL_CAP) -> float:
    """Capital the bot may commit to a new cash-secured put: the account's
    options buying power, but never more than what is left under the cap."""
    return max(0.0, min(options_buying_power, cap - capital_in_use))


def is_bot_order(client_order_id: str | None) -> bool:
    return (client_order_id or "").startswith(BOT_ORDER_PREFIX)


def is_order_stale(submitted_at: datetime, now: datetime) -> bool:
    return now - submitted_at >= timedelta(minutes=STALE_ORDER_MINUTES)


def is_market_hours(_now=None) -> bool:
    """Returns True if current time is within NYSE market hours (9:30am-4pm ET, Mon-Fri)."""
    et = pytz.timezone("US/Eastern")
    now = (_now or datetime.now(et)).astimezone(et)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def get_put_strike(nvda_price: float, buying_power: float) -> float:
    """
    Target strike is 10% below current price.
    Cap at floor(buying_power / 100) so we can always cover assignment.
    Returns whole dollar strike.
    """
    target = nvda_price * 0.90
    max_affordable = math.floor(buying_power / 100)
    strike = min(math.floor(target), max_affordable)
    return float(strike)


def get_call_strike(cost_basis: float) -> float:
    """
    Target strike is 10% above cost basis, rounded up to nearest dollar.
    Never returns a strike below cost basis.
    """
    target = cost_basis * 1.10
    # Round to 10 decimal places first to avoid floating-point precision issues
    # e.g. 100.0 * 1.10 = 110.00000000000001 in IEEE 754
    return float(math.ceil(round(target, 10)))


def get_target_expiry(min_days: int = 14) -> date:
    """
    Returns the first Friday at least min_days from today (14 -> 14-20 days out).
    Options expire on Fridays.
    """
    today = date.today()
    candidate = today + timedelta(days=min_days)
    # Advance to Friday (weekday 4)
    while candidate.weekday() != 4:
        candidate += timedelta(days=1)
    return candidate


def should_close_early(premium_received: float, current_price: float) -> bool:
    """
    Returns True if the contract has reached 50% of max profit.
    When we sold for $2.00 and it's now $1.00, profit = $1.00 = 50% of $2.00.
    """
    profit = premium_received - current_price
    return profit >= (premium_received * 0.50)


def determine_state(has_shares: bool, has_open_put: bool, has_open_call: bool) -> str:
    """
    Returns current wheel state based on account positions.
    States: NO_POSITION, SHORT_PUT, LONG_SHARES, SHORT_CALL
    """
    if has_shares and has_open_call:
        return "SHORT_CALL"
    if has_shares:
        return "LONG_SHARES"
    if has_open_put:
        return "SHORT_PUT"
    return "NO_POSITION"


# ---------- strike selection by delta ----------

def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_put_price(spot: float, strike: float, years: float, vol: float, rate: float = RISK_FREE_RATE) -> float:
    """Black-Scholes price of a European put."""
    if years <= 0 or vol <= 0:
        return max(0.0, strike - spot)
    sd = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + vol * vol / 2) * years) / sd
    return strike * math.exp(-rate * years) * _ncdf(-(d1 - sd)) - spot * _ncdf(-d1)


def put_implied_vol(price: float, spot: float, strike: float, years: float, rate: float = RISK_FREE_RATE) -> float | None:
    """The volatility at which Black-Scholes gives this put price, or None if
    no volatility can (the price is at or below intrinsic value, or absurd)."""
    if years <= 0 or price <= max(0.0, strike * math.exp(-rate * years) - spot) + 1e-6 or price >= strike:
        return None
    lo, hi = 0.01, 5.0
    if bs_put_price(spot, strike, years, hi, rate) < price:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs_put_price(spot, strike, years, mid, rate) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def put_delta(spot: float, strike: float, years: float, vol: float, rate: float = RISK_FREE_RATE) -> float:
    """Black-Scholes delta of a put (negative, between -1 and 0)."""
    d1 = (math.log(spot / strike) + (rate + vol * vol / 2) * years) / (vol * math.sqrt(years))
    return _ncdf(d1) - 1


def years_to_expiry(expiry: date, now: datetime) -> float:
    """Time left until the 4pm ET close on expiry day, in years."""
    et = pytz.timezone("US/Eastern")
    close = et.localize(datetime(expiry.year, expiry.month, expiry.day, 16, 0))
    return max((close - now).total_seconds(), 60.0) / (365 * 24 * 3600)


def pick_put_by_delta(options: list[ChainOption], spot: float, max_strike: float, now: datetime,
                      target: float = PUT_DELTA) -> tuple[ChainOption | None, float | None, str]:
    """The out-of-the-money put whose delta is closest to target, among
    contracts the capital covers, with enough open interest and a quote fit
    to trade on. Returns (option, its delta, why).
    Returns no option if the closest one is more than DELTA_TOLERANCE away,
    so a short capital cap can't push it into far-out junk strikes."""
    best, best_delta = None, None
    skipped = {"over capital": 0, "low open interest": 0, "bad quote": 0, "no implied vol": 0}
    for o in options:
        if o.strike >= spot:
            continue
        if o.strike > max_strike:
            skipped["over capital"] += 1
            continue
        if o.open_interest < MIN_OPEN_INTEREST:
            skipped["low open interest"] += 1
            continue
        if quote_problem(o.quote, now):
            skipped["bad quote"] += 1
            continue
        years = years_to_expiry(o.expiry, now)
        vol = put_implied_vol(o.quote.mid, spot, o.strike, years)
        if vol is None:
            skipped["no implied vol"] += 1
            continue
        d = abs(put_delta(spot, o.strike, years, vol))
        # closest delta wins; on a tie, the lower (safer) strike
        if best is None or (abs(d - target), o.strike) < (abs(best_delta - target), best.strike):
            best, best_delta = o, d
    skips = ", ".join(f"{n} {k}" for k, n in skipped.items() if n)
    if best is None:
        return None, None, f"no usable put ({skips or 'empty chain'})"
    if abs(best_delta - target) > DELTA_TOLERANCE:
        return None, best_delta, f"closest usable put is {best_delta:.2f} delta, too far from {target:.2f} ({skips or 'none skipped'})"
    return best, best_delta, f"closest to {target:.2f} delta" + (f" (skipped: {skips})" if skips else "")
