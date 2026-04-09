from datetime import date, timedelta
import pytest
from strategy import (
    is_market_hours,
    get_put_strike,
    get_call_strike,
    get_target_expiry,
    should_close_early,
    determine_state,
)


# --- is_market_hours ---

def test_market_hours_returns_bool():
    result = is_market_hours()
    assert isinstance(result, bool)


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


def test_get_target_expiry_is_14_to_28_days_out():
    expiry = get_target_expiry()
    today = date.today()
    assert timedelta(days=14) <= (expiry - today) <= timedelta(days=28)


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
