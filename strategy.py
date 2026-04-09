from datetime import date, timedelta, datetime
import math
import pytz


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
    Returns the nearest Friday that is 14-28 days from today.
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
