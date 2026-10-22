from datetime import date, timedelta, datetime, timezone
import pytz
import pytest
from strategy import (
    CAPITAL_CAP,
    ChainOption,
    crosses_earnings,
    earnings_calendar_stale,
    occ_expiry,
    put_expiry,
    today_et,
    Quote,
    bs_put_price,
    pick_put_by_delta,
    put_delta,
    put_implied_vol,
    years_to_expiry,
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


def test_get_call_strike_defaults_to_cost_basis():
    assert get_call_strike(cost_basis=212.50) == 212.50   # $212.50 strike itself qualifies


def test_get_call_strike_can_still_ask_10_percent_above():
    assert get_call_strike(cost_basis=100.00, above=0.10) == 110.00


def test_get_call_strike_rounds_up_never_below_basis():
    assert get_call_strike(cost_basis=103.457) == 103.46
    assert get_call_strike(cost_basis=103.457) >= 103.457


def test_get_call_strike_no_float_rounding_artifact():
    # Without the fix, 110.0 * 1.10 = 121.00000000000001 rounds up to 121.01
    assert get_call_strike(cost_basis=110.00, above=0.10) == 121.00


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


# --- strike selection by delta ---

def test_put_delta_matches_textbook_value():
    # S = K = 100, one year, 20% vol, no interest: d1 = 0.1, delta = N(0.1) - 1
    assert put_delta(100, 100, 1.0, 0.20, rate=0) == pytest.approx(-0.4602, abs=1e-4)


@pytest.mark.parametrize("vol", [0.20, 0.45, 0.90])
@pytest.mark.parametrize("strike", [80, 95, 100])
def test_put_implied_vol_round_trips(vol, strike):
    price = bs_put_price(100, strike, 30 / 365, vol)
    assert put_implied_vol(price, 100, strike, 30 / 365) == pytest.approx(vol, abs=1e-4)


def test_put_implied_vol_none_at_or_below_intrinsic():
    assert put_implied_vol(9.0, 100, 110, 30 / 365) is None   # worth at least ~$10 exercised
    assert put_implied_vol(0.0, 100, 90, 30 / 365) is None


def test_get_target_expiry_takes_a_minimum_days_out():
    expiry = get_target_expiry(30)
    assert expiry.weekday() == 4
    assert 30 <= (expiry - date.today()).days <= 36


EXPIRY = date(2026, 10, 23)   # 4pm ET close, NOW is 2026-10-01 11am ET: ~22 days


def chain(spot=200.0, vol=0.45, strikes=range(150, 201, 5), oi=500, **quote_kw):
    """Puts priced by Black-Scholes, quoted a penny either side of fair value."""
    years = years_to_expiry(EXPIRY, NOW)
    out = []
    for k in strikes:
        fair = bs_put_price(spot, k, years, vol)
        q = quote_kw.get("q", {}).get(k) or quote(fair - 0.01, fair + 0.01)
        out.append(ChainOption(f"NVDA261023P{k * 1000:08d}", float(k), EXPIRY, q, oi))
    return out


def true_delta(k, spot=200.0, vol=0.45):
    return abs(put_delta(spot, k, years_to_expiry(EXPIRY, NOW), vol))


def test_pick_put_by_delta_picks_the_closest_strike():
    opts = chain()
    pick, delta, _ = pick_put_by_delta(opts, 200.0, max_strike=250, now=NOW)
    best = min((o.strike for o in opts if o.strike < 200), key=lambda k: abs(true_delta(k) - 0.30))
    assert pick.strike == best
    assert delta == pytest.approx(true_delta(best), abs=0.01)


def test_pick_put_by_delta_stays_under_the_capital_cap():
    pick, _, _ = pick_put_by_delta(chain(), 200.0, max_strike=185, now=NOW)
    assert pick.strike <= 185


def test_pick_put_by_delta_refuses_far_strikes_when_capital_is_short():
    # Only $165 strikes and below are affordable: deltas there are far below 0.30.
    pick, delta, why = pick_put_by_delta(chain(), 200.0, max_strike=165, now=NOW)
    assert pick is None
    assert delta < 0.20 and "too far" in why


def test_pick_put_by_delta_rejects_cheap_puts_with_wide_spreads():
    # $150 and $155 puts cost a few cents, so a 2-cent spread is 30%+ of the price.
    pick, _, why = pick_put_by_delta(chain(strikes=[150, 155]), 200.0, max_strike=250, now=NOW)
    assert pick is None and "2 bad quote" in why


def test_pick_put_by_delta_skips_thin_and_badly_quoted_contracts():
    opts = chain(oi=20)
    pick, _, why = pick_put_by_delta(opts, 200.0, max_strike=250, now=NOW)
    assert pick is None and "low open interest" in why
    stale = chain(q={k: quote(1.00, 1.02, age_seconds=600) for k in range(150, 201, 5)})
    pick, _, why = pick_put_by_delta(stale, 200.0, max_strike=250, now=NOW)
    assert pick is None and "bad quote" in why


def test_pick_put_by_delta_ignores_puts_at_or_above_the_price():
    pick, _, _ = pick_put_by_delta(chain(strikes=[200, 205, 210]), 200.0, max_strike=250, now=NOW)
    assert pick is None


def test_pick_put_by_delta_handles_an_empty_chain():
    pick, delta, why = pick_put_by_delta([], 200.0, max_strike=250, now=NOW)
    assert pick is None and delta is None and "empty chain" in why


# --- earnings ---

NOV = [(date(2026, 11, 17), date(2026, 11, 25))]   # estimated report window
CONFIRMED = [(date(2026, 11, 18), date(2026, 11, 18))]


def test_put_expiry_is_normal_when_no_report_is_near():
    assert put_expiry(date(2026, 10, 22), windows=NOV) == (date(2026, 11, 6), "normal")


def test_put_expiry_uses_the_friday_before_earnings():
    expiry, why = put_expiry(date(2026, 11, 2), windows=NOV)   # normal target Nov 20 spans the report
    assert expiry == date(2026, 11, 13) and "last Friday before" in why and "estimated" in why


def test_put_expiry_waits_when_the_friday_before_is_too_close():
    expiry, why = put_expiry(date(2026, 11, 10), windows=NOV)   # Nov 13 is only 3 days out
    assert expiry is None and "no new put until after" in why


def test_put_expiry_resumes_after_the_report():
    assert put_expiry(date(2026, 11, 26), windows=NOV)[0] == date(2026, 12, 11)
    assert put_expiry(date(2026, 11, 19), windows=CONFIRMED) == (date(2026, 12, 4), "normal")


def test_crosses_earnings():
    assert crosses_earnings(date(2026, 11, 20), date(2026, 11, 2), CONFIRMED)
    assert not crosses_earnings(date(2026, 11, 13), date(2026, 11, 2), CONFIRMED)
    assert not crosses_earnings(date(2026, 11, 18), date(2026, 11, 2), CONFIRMED)   # report is after that day's close
    assert not crosses_earnings(date(2026, 12, 4), date(2026, 11, 19), CONFIRMED)   # already reported


def test_earnings_calendar_stale():
    assert not earnings_calendar_stale(date(2026, 11, 1), NOV)
    assert earnings_calendar_stale(date(2026, 11, 26), NOV)


def test_occ_expiry():
    assert occ_expiry("NVDA261106P00197500") == date(2026, 11, 6)


def test_today_et_uses_new_york_date():
    # 11pm Pacific on Oct 22 is already Oct 23 in New York
    late = pytz.timezone("US/Pacific").localize(datetime(2026, 10, 22, 23, 0))
    assert today_et(late) == date(2026, 10, 23)
