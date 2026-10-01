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


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    timestamp: datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


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


def get_target_expiry() -> date:
    """
    Returns the first Friday at least 14 days from today (so 14-20 days out).
    Options expire on Fridays.
    """
    today = date.today()
    # Find the first Friday at least 14 days out
    days_ahead = 14
    candidate = today + timedelta(days=days_ahead)
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
