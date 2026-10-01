from datetime import date, timedelta, datetime, timezone
import pytz
import pytest
from strategy import (
    CAPITAL_CAP,
    Quote,
    available_capital,
    is_bot_order,
    is_market_hours,
    is_nvda_symbol,
    is_order_stale,
    get_put_strike,
    get_call_strike,
    get_target_expiry,
    occ_strike,
    quote_problem,
    round_to_tick,
    should_close_early,
    determine_state,
    underlying_price,
)

NOW = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


def quote(bid, ask, age_seconds=0):
    return Quote(bid, ask, NOW - timedelta(seconds=age_seconds))


# --- is_market_hours ---

def test_market_hours_open():
    et = pytz.timezone("US/Eastern")
    # Monday 10am ET — should be open
    monday_10am = datetime(2026, 4, 6, 10, 0, 0, tzinfo=et)
    assert is_market_hours(_now=monday_10am) is True

def test_market_hours_before_open():
    et = pytz.timezone("US/Eastern")
    # Monday 9:00am ET — before open
    monday_9am = datetime(2026, 4, 6, 9, 0, 0, tzinfo=et)
    assert is_market_hours(_now=monday_9am) is False

def test_market_hours_after_close():
    et = pytz.timezone("US/Eastern")
    # Monday 4:01pm ET — after close
    monday_after_close = datetime(2026, 4, 6, 16, 1, 0, tzinfo=et)
    assert is_market_hours(_now=monday_after_close) is False

def test_market_hours_weekend():
    et = pytz.timezone("US/Eastern")
    # Saturday 11am ET
    saturday = datetime(2026, 4, 11, 11, 0, 0, tzinfo=et)
    assert is_market_hours(_now=saturday) is False


def test_get_put_strike_respects_buying_power():
    # With $10,000 buying power and NVDA at $130, max affordable strike is $100
    strike = get_put_strike(nvda_price=130.00, buying_power=10000.00)
    assert strike * 100 <= 10000.00


def test_get_put_strike_targets_10_percent_below():
    # With plenty of buying power, target 10% below
    strike = get_put_strike(nvda_price=100.00, buying_power=50000.00)
    assert strike == 90.00


def test_get_put_strike_snaps_to_nearest_dollar():
    # Strikes are whole dollars
    strike = get_put_strike(nvda_price=113.00, buying_power=50000.00)
    assert strike == int(strike)


def test_get_call_strike_is_10_percent_above_cost_basis():
    strike = get_call_strike(cost_basis=100.00)
    assert strike == 110.00


def test_get_call_strike_rounds_up_to_nearest_dollar():
    strike = get_call_strike(cost_basis=103.50)
    assert strike == int(strike)
    assert strike >= 103.50


def test_get_call_strike_no_float_rounding_artifact():
    # Without IEEE 754 fix, 110.0 * 1.10 = 121.00000000000001 -> ceil = 122
    assert get_call_strike(cost_basis=110.00) == 121.00


def test_get_target_expiry_is_14_to_20_days_out():
    expiry = get_target_expiry()
    today = date.today()
    assert timedelta(days=14) <= (expiry - today) <= timedelta(days=20)


def test_get_target_expiry_is_a_friday():
    expiry = get_target_expiry()
    assert expiry.weekday() == 4  # Friday


def test_should_close_early_at_50_percent():
    # Sold put for $2.00, now worth $1.00 — 50% profit
    assert should_close_early(premium_received=2.00, current_price=1.00) is True


def test_should_not_close_early_below_50_percent():
    # Sold put for $2.00, now worth $1.20 — only 40% profit
    assert should_close_early(premium_received=2.00, current_price=1.20) is False


def test_determine_state_no_position():
    state = determine_state(has_shares=False, has_open_put=False, has_open_call=False)
    assert state == "NO_POSITION"


def test_determine_state_short_put():
    state = determine_state(has_shares=False, has_open_put=True, has_open_call=False)
    assert state == "SHORT_PUT"


def test_determine_state_long_shares_no_call():
    state = determine_state(has_shares=True, has_open_put=False, has_open_call=False)
    assert state == "LONG_SHARES"


def test_determine_state_short_call():
    state = determine_state(has_shares=True, has_open_put=False, has_open_call=True)
    assert state == "SHORT_CALL"


# --- quotes ---

def test_quote_problem_accepts_fresh_tight_quote():
    assert quote_problem(quote(0.54, 0.59), NOW) is None

@pytest.mark.parametrize("q, reason", [
    (quote(0.0, 0.59), "zero"),
    (quote(0.54, 0.0), "zero"),
    (quote(0.60, 0.55), "crossed"),
    (quote(0.54, 0.59, age_seconds=61), "stale"),
    (quote(0.30, 0.50), "spread too wide"),  # 50% of mid
])
def test_quote_problem_rejects_bad_quotes(q, reason):
    assert reason in quote_problem(q, NOW)

def test_underlying_price_uses_mid_not_ask():
    assert underlying_price(quote(230.00, 230.10), 229.00, NOW, NOW) == pytest.approx(230.05)

def test_underlying_price_falls_back_to_last_trade_when_quote_is_bad():
    # Near the open the ask can be zero or the quote junk-wide
    assert underlying_price(quote(0.0, 231.0), 230.50, NOW, NOW) == 230.50
    assert underlying_price(quote(200.0, 260.0), 230.50, NOW, NOW) == 230.50

def test_underlying_price_none_when_nothing_is_fresh():
    stale = NOW - timedelta(minutes=10)
    assert underlying_price(quote(230.0, 230.1, age_seconds=600), 230.0, stale, NOW) is None
    assert underlying_price(quote(0.0, 0.0), 0.0, NOW, NOW) is None


# --- order pricing and symbols ---

@pytest.mark.parametrize("price, expected", [
    (0.565, 0.56), (0.5651, 0.57), (2.999, 3.0), (3.27, 3.25), (3.28, 3.3), (12.02, 12.0),
])
def test_round_to_tick(price, expected):
    assert round_to_tick(price) == expected

def test_occ_strike():
    assert occ_strike("NVDA261016P00207500") == 207.5
    assert occ_strike("NVDA251121C00110000") == 110.0

def test_is_nvda_symbol():
    assert is_nvda_symbol("NVDA")
    assert is_nvda_symbol("NVDA261016P00207500")
    assert not is_nvda_symbol("AAPL")
    assert not is_nvda_symbol("NVDL")
    assert not is_nvda_symbol("NVDAX")


# --- capital cap ---

def test_available_capital_cap_binds_when_account_is_bigger():
    assert available_capital(options_buying_power=100_000, capital_in_use=0) == CAPITAL_CAP

def test_available_capital_buying_power_binds_when_smaller():
    assert available_capital(options_buying_power=5_000, capital_in_use=0) == 5_000

def test_available_capital_subtracts_capital_in_use():
    assert available_capital(options_buying_power=100_000, capital_in_use=20_750) == 4_250

def test_available_capital_never_negative():
    assert available_capital(options_buying_power=100_000, capital_in_use=30_000) == 0.0


# --- order bookkeeping ---

def test_is_bot_order():
    assert is_bot_order("wheelbot-abc123")
    assert not is_bot_order("695b87ea-770")
    assert not is_bot_order(None)

def test_is_order_stale():
    assert not is_order_stale(NOW - timedelta(minutes=9), NOW)
    assert is_order_stale(NOW - timedelta(minutes=10), NOW)
