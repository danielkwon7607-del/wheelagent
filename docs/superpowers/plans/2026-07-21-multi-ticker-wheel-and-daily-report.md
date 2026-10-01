# Multi-Ticker Wheel (SOFI) + Daily Email Report Implementation Plan

> **SHELVED 2026-10-01.** Daniel decided to stay NVDA-only. Do not execute this plan unless he asks. See .kiln/index.md.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the NVDA-only wheel bot into a multi-ticker engine that runs SOFI (12% OTM cushion, up to 4 contracts) alongside the existing NVDA position, and add a daily email report that reconstructs account activity from Alpaca's own records and follows the user's fixed 9-section format.

**Architecture:** `alpaca_client.py` and `strategy.py` become symbol-parameterized (no more hardcoded "NVDA"). A new `config.py` holds a per-ticker watchlist. `wheel_bot.py` loops over the watchlist instead of running a single NVDA flow. A new `report.py` + `email_sender.py` pull account/order/portfolio data from Alpaca, render the fixed template, and send via Gmail SMTP. Two GitHub Actions workflows (trading cron, already live, unchanged; new daily-report cron) run everything without the user's PC.

**Tech Stack:** Python 3.10+, alpaca-py 0.38.0, pytest/pytest-mock, smtplib (stdlib), GitHub Actions.

## Global Constraints

- Cash-secured puts and covered calls only — no margin, no naked options (spec Part 1, Safety invariants).
- Buying-power check before every order; never commit the last $1,500 of options buying power (`CASH_BUFFER = 1500.0`).
- SOFI: `max_contracts=4`, `put_otm_pct=0.12`, `call_otm_pct=0.05`.
- NVDA: `enabled=False` (manage existing position to completion, open no new NVDA puts), `max_contracts=1`, `put_otm_pct=0.10`, `call_otm_pct=0.10`.
- 50%-profit close-and-roll behavior (existing `WheelBot._close_and_roll`) is preserved per-ticker, unchanged in mechanics.
- Report sends once per trading day, after market close, reconstructing state entirely from Alpaca (no local state — GitHub Actions runs are ephemeral).
- Report greeting line is always exactly: `hey its claude, here's your weekly trading report` (verbatim, per user spec, even though cadence is daily).
- Report reconstructs "this week" as: current week's first trading day (Monday, or the next trading day if Monday is a holiday) through today.
- Gmail creds come from env var `GMAIL_APP_PASSWORD` (already in GitHub secrets); sender/recipient both `daniel.kwon7607@gmail.com`.
- No change to TETHR or any file outside this repo.
- alpaca-py in this environment has **no account-activities endpoint** on `TradingClient` — use `get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=..., until=...))` (returns `filled_at`, `filled_avg_price`, `filled_qty`, `side`, `symbol`, etc.) to reconstruct fills instead.

---

## File Structure

```
config.py                  # NEW — Ticker dataclass + WATCHLIST + CASH_BUFFER + email constants
alpaca_client.py           # MODIFIED — every method takes symbol; OCC parsing generalized
strategy.py                # MODIFIED — get_put_strike/get_call_strike take otm_pct
wheel_bot.py                # MODIFIED — loops over config.WATCHLIST instead of single NVDA flow
report.py                   # NEW — pulls Alpaca data, computes metrics, renders template
email_sender.py             # NEW — thin smtplib wrapper, mockable
send_daily_report.py        # NEW — entrypoint script, mirrors wheel_bot.py's __main__ pattern
tests/test_config.py        # NEW
tests/test_alpaca_client.py # MODIFIED — symbol-parameterized tests
tests/test_strategy.py      # MODIFIED — otm_pct-parameterized tests
tests/test_wheel_bot.py     # MODIFIED — multi-ticker loop tests
tests/test_report.py        # NEW
tests/test_email_sender.py  # NEW
.github/workflows/daily-report.yml  # NEW
```

---

### Task 1: `config.py` — watchlist and ticker settings

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Ticker` dataclass with fields `symbol: str`, `enabled: bool`, `max_contracts: int`, `put_otm_pct: float`, `call_otm_pct: float`. `WATCHLIST: list[Ticker]`. `CASH_BUFFER: float = 1500.0`. `REPORT_EMAIL: str = "daniel.kwon7607@gmail.com"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from config import WATCHLIST, CASH_BUFFER, REPORT_EMAIL, Ticker


def test_watchlist_contains_sofi_and_nvda():
    symbols = {t.symbol for t in WATCHLIST}
    assert symbols == {"SOFI", "NVDA"}


def test_sofi_settings():
    sofi = next(t for t in WATCHLIST if t.symbol == "SOFI")
    assert sofi.enabled is True
    assert sofi.max_contracts == 4
    assert sofi.put_otm_pct == 0.12
    assert sofi.call_otm_pct == 0.05


def test_nvda_settings_disabled_for_new_positions():
    nvda = next(t for t in WATCHLIST if t.symbol == "NVDA")
    assert nvda.enabled is False
    assert nvda.max_contracts == 1
    assert nvda.put_otm_pct == 0.10
    assert nvda.call_otm_pct == 0.10


def test_cash_buffer_and_email():
    assert CASH_BUFFER == 1500.0
    assert REPORT_EMAIL == "daniel.kwon7607@gmail.com"


def test_ticker_is_a_dataclass_with_expected_fields():
    t = Ticker(symbol="TEST", enabled=True, max_contracts=2, put_otm_pct=0.1, call_otm_pct=0.05)
    assert t.symbol == "TEST"
    assert t.enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write minimal implementation**

```python
# config.py
"""Watchlist and account-wide settings for the wheel bot."""
from dataclasses import dataclass


@dataclass
class Ticker:
    symbol: str
    enabled: bool          # if False, manage existing positions but open no new ones
    max_contracts: int      # concurrent cash-secured-put contracts cap
    put_otm_pct: float      # sell puts this % below current price
    call_otm_pct: float     # sell covered calls this % above cost basis


WATCHLIST: list[Ticker] = [
    Ticker(symbol="SOFI", enabled=True, max_contracts=4, put_otm_pct=0.12, call_otm_pct=0.05),
    Ticker(symbol="NVDA", enabled=False, max_contracts=1, put_otm_pct=0.10, call_otm_pct=0.10),
]

# Never commit the last $1,500 of options buying power to new positions.
CASH_BUFFER = 1500.0

REPORT_EMAIL = "daniel.kwon7607@gmail.com"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add multi-ticker watchlist config (SOFI 12% OTM, NVDA managed-only)"
```

---

### Task 2: `strategy.py` — parameterize OTM percentage

**Files:**
- Modify: `strategy.py`
- Modify: `tests/test_strategy.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `get_put_strike(price: float, buying_power: float, otm_pct: float) -> float`, `get_call_strike(cost_basis: float, otm_pct: float) -> float`. Callers (Task 5) pass `ticker.put_otm_pct` / `ticker.call_otm_pct` from `config.Ticker`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_strategy.py` (keep existing tests, but the two below **replace** `test_get_put_strike_targets_10_percent_below` and `test_get_call_strike_is_10_percent_above_cost_basis` since the signature changes — update the call sites in place):

```python
def test_get_put_strike_targets_configured_pct_below():
    # 10% OTM, plenty of buying power
    strike = get_put_strike(nvda_price=100.00, buying_power=50000.00, otm_pct=0.10)
    assert strike == 90.00


def test_get_put_strike_respects_custom_otm_pct():
    # 12% OTM (SOFI setting)
    strike = get_put_strike(nvda_price=100.00, buying_power=50000.00, otm_pct=0.12)
    assert strike == 88.00


def test_get_call_strike_is_configured_pct_above_cost_basis():
    strike = get_call_strike(cost_basis=100.00, otm_pct=0.10)
    assert strike == 110.00


def test_get_call_strike_respects_custom_otm_pct():
    strike = get_call_strike(cost_basis=100.00, otm_pct=0.05)
    assert strike == 105.00
```

Also update the two now-broken existing calls to pass `otm_pct` explicitly:
- `test_get_put_strike_respects_buying_power`: change call to `get_put_strike(nvda_price=130.00, buying_power=10000.00, otm_pct=0.10)`
- `test_get_put_strike_snaps_to_nearest_dollar`: change call to `get_put_strike(nvda_price=113.00, buying_power=50000.00, otm_pct=0.10)`
- `test_get_call_strike_rounds_up_to_nearest_dollar`: change call to `get_call_strike(cost_basis=103.50, otm_pct=0.10)`
- `test_get_call_strike_no_float_rounding_artifact`: change call to `get_call_strike(cost_basis=110.00, otm_pct=0.10)`
- Delete `test_get_put_strike_targets_10_percent_below` and `test_get_call_strike_is_10_percent_above_cost_basis` (superseded by the `_configured_pct_` versions above).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_strategy.py -v`
Expected: FAIL — `TypeError: get_put_strike() missing 1 required positional argument: 'otm_pct'` (and similar for `get_call_strike`)

- [ ] **Step 3: Write minimal implementation**

In `strategy.py`, replace:

```python
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
```

with:

```python
def get_put_strike(nvda_price: float, buying_power: float, otm_pct: float) -> float:
    """
    Target strike is otm_pct below current price.
    Cap at floor(buying_power / 100) so we can always cover assignment.
    Returns whole dollar strike.
    """
    target = nvda_price * (1 - otm_pct)
    max_affordable = math.floor(buying_power / 100)
    strike = min(math.floor(target), max_affordable)
    return float(strike)


def get_call_strike(cost_basis: float, otm_pct: float) -> float:
    """
    Target strike is otm_pct above cost basis, rounded up to nearest dollar.
    Never returns a strike below cost basis.
    """
    target = cost_basis * (1 + otm_pct)
    # Round to 10 decimal places first to avoid floating-point precision issues
    # e.g. 100.0 * 1.10 = 110.00000000000001 in IEEE 754
    return float(math.ceil(round(target, 10)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_strategy.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add strategy.py tests/test_strategy.py
git commit -m "feat: parameterize strike OTM percentage in strategy.py"
```

---

### Task 3: `alpaca_client.py` — symbol-parameterize every method

**Files:**
- Modify: `alpaca_client.py`
- Modify: `tests/test_alpaca_client.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (all now take `symbol: str` as first arg after self):
  - `get_price(symbol: str) -> float`
  - `get_stock_position(symbol: str) -> tuple[bool, int, float]`
  - `get_open_options(symbol: str) -> tuple[list, list]`
  - `find_put_contract(symbol: str, strike: float, expiry: date) -> str | None`
  - `find_call_contract(symbol: str, strike: float, expiry: date) -> str | None`
  - Unchanged: `get_buying_power()`, `get_options_buying_power()`, `sell_option(...)`, `close_option_position(...)`, `get_option_quote(...)`.
  - `get_nvda_price`, `get_nvda_stock_position`, `get_open_nvda_options` are **removed** (callers use the symbol-parameterized versions — Task 5 is the only caller and is updated in this same change-set).

- [ ] **Step 1: Write the failing tests**

Replace the NVDA-specific tests in `tests/test_alpaca_client.py` with symbol-parameterized versions:

```python
def test_get_price(client):
    mock_quote = MagicMock()
    mock_quote.ask_price = 125.50
    client._data.get_stock_latest_quote.return_value = {"NVDA": mock_quote}
    result = client.get_price("NVDA")
    assert result == 125.50


def test_get_stock_position_true(client):
    mock_position = MagicMock()
    mock_position.symbol = "NVDA"
    mock_position.qty = "100"
    mock_position.avg_entry_price = "105.00"
    client._trading.get_all_positions.return_value = [mock_position]
    has_shares, qty, cost_basis = client.get_stock_position("NVDA")
    assert has_shares is True
    assert qty == 100
    assert cost_basis == 105.00


def test_get_stock_position_false(client):
    client._trading.get_all_positions.return_value = []
    has_shares, qty, cost_basis = client.get_stock_position("NVDA")
    assert has_shares is False
    assert qty == 0
    assert cost_basis == 0.0


def test_get_stock_position_ignores_other_symbols(client):
    mock_position = MagicMock()
    mock_position.symbol = "SOFI"
    mock_position.qty = "100"
    mock_position.avg_entry_price = "18.00"
    client._trading.get_all_positions.return_value = [mock_position]
    has_shares, qty, cost_basis = client.get_stock_position("NVDA")
    assert has_shares is False


def test_get_open_options_empty(client):
    client._trading.get_all_positions.return_value = []
    puts, calls = client.get_open_options("NVDA")
    assert puts == []
    assert calls == []


def test_get_open_options_filters_by_symbol(client):
    nvda_put = MagicMock(symbol="NVDA251121P00108000")
    sofi_put = MagicMock(symbol="SOFI251121P00016000")
    client._trading.get_all_positions.return_value = [nvda_put, sofi_put]
    puts, calls = client.get_open_options("SOFI")
    assert [p.symbol for p in puts] == ["SOFI251121P00016000"]
```

Keep the unchanged tests (`test_get_buying_power`, `test_get_option_quote_returns_midprice`) as-is.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_alpaca_client.py -v`
Expected: FAIL — `AttributeError: 'AlpacaClient' object has no attribute 'get_price'` (and similar)

- [ ] **Step 3: Write minimal implementation**

In `alpaca_client.py`, replace `get_nvda_price`, `get_nvda_stock_position`, `get_open_nvda_options`, `find_put_contract`, `find_call_contract` with:

```python
    def get_price(self, symbol: str) -> float:
        req = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
        quotes = self._data.get_stock_latest_quote(req)
        return float(quotes[symbol].ask_price)

    def get_stock_position(self, symbol: str) -> tuple[bool, int, float]:
        """Returns (has_shares, quantity, avg_cost_basis) for the given symbol."""
        positions = self._trading.get_all_positions()
        for p in positions:
            if p.symbol == symbol:
                return True, int(float(p.qty)), float(p.avg_entry_price)
        return False, 0, 0.0

    def get_open_options(self, symbol: str) -> tuple[list, list]:
        """Returns (open_puts, open_calls) for the given underlying symbol."""
        positions = self._trading.get_all_positions()
        puts = []
        calls = []
        prefix_len = len(symbol)
        for p in positions:
            option_symbol = p.symbol or ""
            # OCC option symbols look like: {SYMBOL}{YYMMDD}{P/C}{strike*1000, 8 digits}
            if option_symbol.startswith(symbol) and len(option_symbol) > prefix_len + 6:
                option_type_flag = option_symbol[prefix_len + 6:]
                if option_type_flag.startswith("P"):
                    puts.append(p)
                elif option_type_flag.startswith("C"):
                    calls.append(p)
        return puts, calls

    def find_put_contract(self, symbol: str, strike: float, expiry: date) -> str | None:
        """Find the best available put contract at or below the target strike.
        Tries the target expiry and nearby dates to handle market holidays
        (e.g. Juneteenth falls on a Friday, so options expire Thursday instead).
        Uses a ±$25 strike window to avoid Alpaca's paginated results returning
        deep-OTM junk contracts before reaching our target price range."""
        min_strike = max(1.0, strike - 25)
        candidates = [
            expiry,
            expiry - timedelta(days=1),  # holiday: expiry shifted back one day
            expiry + timedelta(days=1),  # rare forward shift
            expiry + timedelta(days=7),  # next Friday entirely
        ]
        for candidate_expiry in candidates:
            req = GetOptionContractsRequest(
                underlying_symbols=[symbol],
                expiration_date=candidate_expiry,
                type=ContractType.PUT,
                strike_price_gte=str(min_strike),
                strike_price_lte=str(strike),
            )
            contracts = self._trading.get_option_contracts(req)
            if contracts.option_contracts:
                best = max(contracts.option_contracts, key=lambda c: float(c.strike_price))
                return best.symbol
        return None

    def find_call_contract(self, symbol: str, strike: float, expiry: date) -> str | None:
        """Find the best available call contract at or above the target strike.
        Tries the target expiry and nearby dates to handle market holidays.
        Uses a +$25 strike window to avoid pagination issues."""
        max_strike = strike + 25
        candidates = [
            expiry,
            expiry - timedelta(days=1),
            expiry + timedelta(days=1),
            expiry + timedelta(days=7),
        ]
        for candidate_expiry in candidates:
            req = GetOptionContractsRequest(
                underlying_symbols=[symbol],
                expiration_date=candidate_expiry,
                type=ContractType.CALL,
                strike_price_gte=str(strike),
                strike_price_lte=str(max_strike),
            )
            contracts = self._trading.get_option_contracts(req)
            if contracts.option_contracts:
                best = min(contracts.option_contracts, key=lambda c: float(c.strike_price))
                return best.symbol
        return None
```

Note: `get_open_options` parses OCC symbols generically now — for symbol `NVDA` the option symbol is `NVDA260731P00187500` (4-char root, so `prefix_len=4`, char at index 10 is the P/C flag: `NVDA` + `260731` (6 digits) + `P`). For `SOFI` (also 4 chars) it's identical shape. This works for any root length because it's computed from `len(symbol)`, not hardcoded to 4.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_alpaca_client.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add alpaca_client.py tests/test_alpaca_client.py
git commit -m "refactor: symbol-parameterize alpaca_client methods for multi-ticker support"
```

---

### Task 4: `wheel_bot.py` — multi-ticker loop with contract sizing and cash buffer

**Files:**
- Modify: `wheel_bot.py`
- Modify: `tests/test_wheel_bot.py`

**Interfaces:**
- Consumes: `config.WATCHLIST`, `config.CASH_BUFFER`, `config.Ticker`; `alpaca_client.AlpacaClient.{get_options_buying_power, get_price, get_stock_position, get_open_options, find_put_contract, find_call_contract, sell_option, close_option_position, get_option_quote}`; `strategy.{determine_state, get_call_strike, get_put_strike, get_target_expiry, is_market_hours, should_close_early}`.
- Produces: `WheelBot.run() -> dict` now returns `{"action": "RUN_COMPLETE", "results": [per-ticker result dicts]}` (or `{"action": "MARKET_CLOSED", ...}` unchanged). Each per-ticker result dict has the same shape as before (`{"action": "SELL_PUT", ...}` etc.) plus a `"symbol"` key.

- [ ] **Step 1: Write the failing tests**

Rewrite `tests/test_wheel_bot.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from wheel_bot import WheelBot
from config import Ticker


TEST_WATCHLIST = [
    Ticker(symbol="SOFI", enabled=True, max_contracts=2, put_otm_pct=0.12, call_otm_pct=0.05),
    Ticker(symbol="NVDA", enabled=False, max_contracts=1, put_otm_pct=0.10, call_otm_pct=0.10),
]


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_options_buying_power.return_value = 10000.00
    client.get_price.return_value = 18.00
    client.get_stock_position.return_value = (False, 0, 0.0)
    client.get_open_options.return_value = ([], [])
    return client


def test_market_closed_skips_all_tickers(mock_client):
    bot = WheelBot(mock_client, watchlist=TEST_WATCHLIST)
    with patch("wheel_bot.is_market_hours", return_value=False):
        result = bot.run()
    mock_client.sell_option.assert_not_called()
    assert result["action"] == "MARKET_CLOSED"


def test_no_position_sells_multiple_contracts_up_to_max(mock_client):
    """SOFI max_contracts=2, plenty of buying power -> sells 2 puts."""
    mock_client.find_put_contract.return_value = "SOFI251121P00016000"
    mock_client.get_option_quote.return_value = 0.50
    mock_client.sell_option.return_value = {"id": "1", "symbol": "SOFI251121P00016000", "limit_price": 0.50}

    bot = WheelBot(mock_client, watchlist=TEST_WATCHLIST)
    with patch("wheel_bot.is_market_hours", return_value=True):
        result = bot.run()

    sofi_results = [r for r in result["results"] if r["symbol"] == "SOFI"]
    assert len(sofi_results) == 1
    assert sofi_results[0]["action"] == "SELL_PUT"
    assert mock_client.sell_option.call_count == 2  # max_contracts


def test_no_position_sizes_contracts_by_buying_power_minus_cash_buffer(mock_client):
    """$3,100 free after $1,500 buffer / $1,600-ish collateral per contract -> only 1 fits."""
    mock_client.get_options_buying_power.return_value = 3100.00  # 3100 - 1500 buffer = 1600 usable
    mock_client.find_put_contract.return_value = "SOFI251121P00016000"
    mock_client.get_option_quote.return_value = 0.50
    mock_client.sell_option.return_value = {"id": "1", "symbol": "SOFI251121P00016000", "limit_price": 0.50}

    bot = WheelBot(mock_client, watchlist=TEST_WATCHLIST)
    with patch("wheel_bot.is_market_hours", return_value=True):
        bot.run()

    assert mock_client.sell_option.call_count == 1


def test_disabled_ticker_manages_existing_position_but_opens_no_new_put(mock_client):
    """NVDA enabled=False: NO_POSITION state on NVDA should sell nothing."""
    def open_options_side_effect(symbol):
        return ([], [])
    mock_client.get_open_options.side_effect = open_options_side_effect

    bot = WheelBot(mock_client, watchlist=TEST_WATCHLIST)
    with patch("wheel_bot.is_market_hours", return_value=True):
        result = bot.run()

    nvda_results = [r for r in result["results"] if r["symbol"] == "NVDA"]
    assert nvda_results[0]["action"] == "SKIPPED_DISABLED"
    # SOFI (enabled) still traded normally
    sofi_results = [r for r in result["results"] if r["symbol"] == "SOFI"]
    assert sofi_results[0]["action"] == "SELL_PUT"


def test_disabled_ticker_still_closes_at_50_percent_and_rolls_only_if_enabled(mock_client):
    """NVDA enabled=False + SHORT_PUT at 50% profit: close early, but do NOT roll into a new NVDA put."""
    mock_put = MagicMock()
    mock_put.symbol = "NVDA251121P00108000"
    mock_put.avg_entry_price = "2.00"

    def open_options_side_effect(symbol):
        if symbol == "NVDA":
            return ([mock_put], [])
        return ([], [])
    mock_client.get_open_options.side_effect = open_options_side_effect
    mock_client.get_option_quote.return_value = 1.00  # 50% profit
    mock_client.close_option_position.return_value = {"id": "1", "symbol": mock_put.symbol, "action": "closed"}

    bot = WheelBot(mock_client, watchlist=TEST_WATCHLIST, roll_poll_interval=0)
    with patch("wheel_bot.is_market_hours", return_value=True):
        result = bot.run()

    mock_client.close_option_position.assert_called_once()
    nvda_result = next(r for r in result["results"] if r["symbol"] == "NVDA")
    assert nvda_result["action"] == "CLOSE_EARLY"  # not CLOSE_AND_ROLL, since NVDA is disabled

    # SOFI is enabled and had no open put -> still gets a fresh put sold
    sell_calls_by_symbol = [c.args[0] for c in mock_client.find_put_contract.call_args_list]
    assert "SOFI" in sell_calls_by_symbol
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wheel_bot.py -v`
Expected: FAIL — `TypeError: WheelBot.__init__() got an unexpected keyword argument 'watchlist'`

- [ ] **Step 3: Write minimal implementation**

Replace the entire contents of `wheel_bot.py`:

```python
"""
Wheel Strategy Bot — multi-ticker, Alpaca Paper Trading
Run this file directly: python wheel_bot.py
Runs on GitHub Actions every 15 min during market hours (no PC needed).
"""
import logging
import time
from datetime import datetime

from alpaca_client import AlpacaClient
from config import CASH_BUFFER, WATCHLIST, Ticker
from strategy import (
    determine_state,
    get_call_strike,
    get_put_strike,
    get_target_expiry,
    is_market_hours,
    should_close_early,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)


class WheelBot:
    def __init__(
        self,
        client: AlpacaClient | None = None,
        watchlist: list[Ticker] | None = None,
        roll_poll_interval: float = 3.0,
        roll_poll_timeout: float = 30.0,
    ):
        self.client = client or AlpacaClient()
        self.watchlist = watchlist if watchlist is not None else WATCHLIST
        self.roll_poll_interval = roll_poll_interval
        self.roll_poll_timeout = roll_poll_timeout

    def run(self) -> dict:
        if not is_market_hours():
            log.info("Market closed — no action taken.")
            return {"action": "MARKET_CLOSED", "time": datetime.now().isoformat()}

        results = [self._run_ticker(ticker) for ticker in self.watchlist]
        return {"action": "RUN_COMPLETE", "results": results}

    def _run_ticker(self, ticker: Ticker) -> dict:
        symbol = ticker.symbol
        has_shares, share_qty, cost_basis = self.client.get_stock_position(symbol)
        open_puts, open_calls = self.client.get_open_options(symbol)

        state = determine_state(
            has_shares=has_shares,
            has_open_put=len(open_puts) > 0,
            has_open_call=len(open_calls) > 0,
        )
        log.info(f"[{symbol}] State={state}")

        if state == "SHORT_PUT":
            return self._manage_short_position(ticker, open_puts[0], "put")

        if state == "SHORT_CALL":
            return self._manage_short_position(ticker, open_calls[0], "call")

        if state == "LONG_SHARES":
            if not ticker.enabled:
                log.info(f"[{symbol}] disabled — holding shares, not auto-selling a new covered call.")
                return {"action": "SKIPPED_DISABLED", "symbol": symbol}
            result = self._sell_covered_call(ticker, cost_basis)
            result["symbol"] = symbol
            return result

        if state == "NO_POSITION":
            if not ticker.enabled:
                log.info(f"[{symbol}] disabled — no new positions opened.")
                return {"action": "SKIPPED_DISABLED", "symbol": symbol}
            return self._open_cash_secured_puts(ticker)

        return {"action": "UNKNOWN_STATE", "symbol": symbol, "state": state}

    def _manage_short_position(self, ticker: Ticker, position, kind: str) -> dict:
        symbol = ticker.symbol
        current_price = self.client.get_option_quote(position.symbol)
        premium_received = float(position.avg_entry_price)
        if not should_close_early(premium_received, current_price):
            log.info(f"[{symbol}] HOLD {kind} {position.symbol} — current=${current_price:.2f}, received=${premium_received:.2f}")
            return {"action": "HOLD", "symbol": symbol, "contract": position.symbol}
        return self._close_and_roll(ticker, position, kind)

    def _close_and_roll(self, ticker: Ticker, position, kind: str) -> dict:
        """Take profit on a contract at 50%. If the ticker is enabled, immediately
        deploy freed capital into the next play. Disabled tickers (e.g. NVDA while
        we're not opening new NVDA positions) just close — no roll."""
        symbol = ticker.symbol
        result = self.client.close_option_position(position.symbol)
        log.info(f"[{symbol}] CLOSE_EARLY {kind} {position.symbol} — 50% profit reached. Order: {result}")

        if not ticker.enabled:
            return {"action": "CLOSE_EARLY", "symbol": symbol, "detail": result}

        if self._wait_until_closed(symbol, position.symbol):
            opened = self._open_next_play(ticker)
            log.info(f"[{symbol}] ROLL into next play: {opened}")
            return {"action": "CLOSE_AND_ROLL", "symbol": symbol, "closed": result, "opened": opened}

        log.info(f"[{symbol}] Close of {position.symbol} not confirmed yet — next run will open the next play.")
        return {"action": "CLOSE_EARLY", "symbol": symbol, "detail": result}

    def _wait_until_closed(self, symbol: str, contract_symbol: str) -> bool:
        deadline = time.monotonic() + self.roll_poll_timeout
        while True:
            open_puts, open_calls = self.client.get_open_options(symbol)
            still_open = any(p.symbol == contract_symbol for p in [*open_puts, *open_calls])
            if not still_open:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.roll_poll_interval)

    def _open_next_play(self, ticker: Ticker) -> dict:
        has_shares, _, cost_basis = self.client.get_stock_position(ticker.symbol)
        if has_shares:
            result = self._sell_covered_call(ticker, cost_basis)
        else:
            result = self._open_cash_secured_puts(ticker)
        return result

    def _open_cash_secured_puts(self, ticker: Ticker) -> dict:
        """Sell cash-secured puts up to ticker.max_contracts, limited by
        (options_buying_power - CASH_BUFFER)."""
        symbol = ticker.symbol
        options_buying_power = self.client.get_options_buying_power()
        price = self.client.get_price(symbol)
        strike = get_put_strike(price, options_buying_power, ticker.put_otm_pct)
        expiry = get_target_expiry()
        contract = self.client.find_put_contract(symbol, strike, expiry)
        if not contract:
            log.warning(f"[{symbol}] No put contract found for strike=${strike}, expiry={expiry}")
            return {"action": "NO_CONTRACT", "symbol": symbol, "strike": strike, "expiry": str(expiry)}

        quote = self.client.get_option_quote(contract)
        collateral_per_contract = strike * 100
        usable_capital = max(0.0, options_buying_power - CASH_BUFFER)
        affordable = int(usable_capital // collateral_per_contract) if collateral_per_contract > 0 else 0
        contracts_to_sell = max(0, min(ticker.max_contracts, affordable))

        if contracts_to_sell == 0:
            log.warning(f"[{symbol}] Not enough buying power for even 1 contract at strike=${strike}")
            return {"action": "NO_CONTRACT", "symbol": symbol, "strike": strike, "expiry": str(expiry)}

        orders = []
        for _ in range(contracts_to_sell):
            orders.append(self.client.sell_option(contract, limit_price=quote))
        log.info(f"[{symbol}] SELL_PUT x{contracts_to_sell} {contract} @ ${quote:.2f} | strike=${strike}, expiry={expiry}")
        return {"action": "SELL_PUT", "symbol": symbol, "detail": orders}

    def _sell_covered_call(self, ticker: Ticker, cost_basis: float) -> dict:
        symbol = ticker.symbol
        strike = get_call_strike(cost_basis, ticker.call_otm_pct)
        expiry = get_target_expiry()
        contract = self.client.find_call_contract(symbol, strike, expiry)
        if not contract:
            log.warning(f"[{symbol}] No call contract found for strike=${strike}, expiry={expiry}")
            return {"action": "NO_CONTRACT", "strike": strike, "expiry": str(expiry)}
        quote = self.client.get_option_quote(contract)
        result = self.client.sell_option(contract, limit_price=quote)
        log.info(f"[{symbol}] SELL_CALL {contract} @ ${quote:.2f} | strike=${strike}, expiry={expiry}")
        return {"action": "SELL_CALL", "detail": result}


if __name__ == "__main__":
    bot = WheelBot()
    result = bot.run()
    print(f"\nResult: {result}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wheel_bot.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite to confirm nothing else broke**

Run: `python -m pytest -q`
Expected: all tests pass (config, strategy, alpaca_client, wheel_bot)

- [ ] **Step 6: Commit**

```bash
git add wheel_bot.py tests/test_wheel_bot.py
git commit -m "feat: multi-ticker wheel loop with per-ticker contract sizing and cash buffer"
```

---

### Task 5: Manual smoke test against paper account (SOFI must actually trade)

**Files:** none (verification task, no code changes)

- [ ] **Step 1: Confirm market is open**

Run: `python -c "from strategy import is_market_hours; print(is_market_hours())"`
Expected: `True` (run this task during 9:30am–4pm ET on a weekday; if `False`, wait or note this as a deferred manual check before deploying)

- [ ] **Step 2: Dry-run the bot locally against the real paper account**

Run: `python wheel_bot.py`
Expected: log lines showing `[SOFI] State=NO_POSITION` followed by `[SOFI] SELL_PUT x<N> ...`, and `[NVDA] State=SHORT_PUT` followed by `[NVDA] HOLD ...` (since the existing NVDA put is still open and NVDA is disabled for new positions). Confirm in the printed `Result: {...}` dict that `results` contains one entry per watchlist ticker.

- [ ] **Step 3: Verify against Alpaca directly**

Run:
```python
from alpaca_client import AlpacaClient
c = AlpacaClient()
puts, calls = c.get_open_options("SOFI")
print("SOFI open puts:", [p.symbol for p in puts])
print("Options buying power remaining:", c.get_options_buying_power())
```
Expected: the number of open SOFI puts matches what Task 4's sizing logic should have sold (bounded by `max_contracts=4` and the cash buffer), and buying power remaining is still ≥ `CASH_BUFFER` (1500.0).

- [ ] **Step 4: No commit** — this task only verifies live behavior; nothing to check in.

---

### Task 6: `report.py` — pull Alpaca data and compute report metrics

**Files:**
- Create: `report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `alpaca.trading.client.TradingClient` (via a lightweight `ReportClient` wrapper defined in this file, separate from `AlpacaClient` since it needs `get_orders`/`get_portfolio_history`/`get_calendar` which `AlpacaClient` doesn't expose), `config.WATCHLIST`.
- Produces:
  - `ReportClient` class with methods: `get_account_snapshot() -> dict`, `get_positions() -> list`, `get_filled_orders(after: date, until: date) -> list`, `get_portfolio_history() -> dict`, `get_last_n_trading_days(n: int, end: date) -> list[date]`, `is_trading_day(d: date) -> bool`.
  - `build_report_context(client: ReportClient, today: date) -> dict` — returns a fully-populated dict consumed by the template renderer in Task 7. Keys: `week_start`, `week_end`, `account`, `positions_by_ticker`, `activity_log`, `income`, `performance`, `goal_meter`, `health_checks`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report.py
from datetime import date
from unittest.mock import MagicMock
import pytest
from report import ReportClient, build_report_context


@pytest.fixture
def mock_trading_client():
    return MagicMock()


@pytest.fixture
def report_client(mock_trading_client):
    rc = ReportClient.__new__(ReportClient)
    rc._trading = mock_trading_client
    return rc


def test_get_account_snapshot(report_client, mock_trading_client):
    mock_trading_client.get_account.return_value = MagicMock(
        equity="25324.69", cash="8154.69", options_buying_power="8154.69"
    )
    snapshot = report_client.get_account_snapshot()
    assert snapshot["equity"] == 25324.69
    assert snapshot["cash"] == 8154.69
    assert snapshot["options_buying_power"] == 8154.69


def test_get_filled_orders_filters_to_filled_status(report_client, mock_trading_client):
    filled = MagicMock(status="filled", symbol="SOFI251121P00016000", filled_at=date(2026, 7, 21))
    mock_trading_client.get_orders.return_value = [filled]
    orders = report_client.get_filled_orders(after=date(2026, 7, 20), until=date(2026, 7, 22))
    assert orders == [filled]
    mock_trading_client.get_orders.assert_called_once()


def test_is_trading_day_true_for_weekday_in_calendar(report_client, mock_trading_client):
    mock_trading_client.get_calendar.return_value = [MagicMock(date=date(2026, 7, 21))]
    assert report_client.is_trading_day(date(2026, 7, 21)) is True


def test_is_trading_day_false_when_not_in_calendar(report_client, mock_trading_client):
    mock_trading_client.get_calendar.return_value = []
    assert report_client.is_trading_day(date(2026, 7, 20)) is False  # a Monday holiday, e.g.


def test_build_report_context_computes_week_start_from_monday(report_client, mock_trading_client):
    mock_trading_client.get_account.return_value = MagicMock(
        equity="25000.00", cash="10000.00", options_buying_power="10000.00"
    )
    mock_trading_client.get_all_positions.return_value = []
    mock_trading_client.get_orders.return_value = []
    mock_trading_client.get_calendar.return_value = [
        MagicMock(date=date(2026, 7, 20)), MagicMock(date=date(2026, 7, 21))
    ]
    mock_trading_client.get_portfolio_history.return_value = MagicMock(
        equity=[24000.0, 25000.0], profit_loss_pct=[0.0, 0.0417]
    )

    ctx = build_report_context(report_client, today=date(2026, 7, 21))  # Tuesday

    assert ctx["week_start"] == date(2026, 7, 20)  # Monday of that week
    assert ctx["week_end"] == date(2026, 7, 21)
    assert ctx["account"]["equity"] == 25000.00


def test_build_report_context_week_start_skips_monday_holiday(report_client, mock_trading_client):
    """If Monday isn't a trading day, week_start is the first trading day on/after Monday."""
    mock_trading_client.get_account.return_value = MagicMock(
        equity="25000.00", cash="10000.00", options_buying_power="10000.00"
    )
    mock_trading_client.get_all_positions.return_value = []
    mock_trading_client.get_orders.return_value = []
    # Monday 7/20 is a holiday (not in calendar); Tuesday 7/21 is the first trading day
    mock_trading_client.get_calendar.return_value = [MagicMock(date=date(2026, 7, 21))]
    mock_trading_client.get_portfolio_history.return_value = MagicMock(
        equity=[25000.0], profit_loss_pct=[0.0]
    )

    ctx = build_report_context(report_client, today=date(2026, 7, 21))

    assert ctx["week_start"] == date(2026, 7, 21)


def test_build_report_context_goal_meter_math(report_client, mock_trading_client):
    mock_trading_client.get_account.return_value = MagicMock(
        equity="25000.00", cash="10000.00", options_buying_power="10000.00"
    )
    mock_trading_client.get_all_positions.return_value = []
    mock_trading_client.get_orders.return_value = []
    mock_trading_client.get_calendar.return_value = [MagicMock(date=date(2026, 7, 21))]
    mock_trading_client.get_portfolio_history.return_value = MagicMock(
        equity=[25000.0], profit_loss_pct=[0.02]  # 2% YTD
    )

    ctx = build_report_context(report_client, today=date(2026, 4, 2))  # ~91 days into the year

    goal = ctx["goal_meter"]
    expected_prorated = 10.0 * (92 / 365)  # Jan 1 -> Apr 2 inclusive = 92 days elapsed
    assert goal["ytd_return_pct"] == 2.0
    assert abs(goal["prorated_target_pct"] - expected_prorated) < 0.05
    assert goal["pace_status"] in ("AHEAD", "BEHIND", "ON_PACE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'report'`

- [ ] **Step 3: Write minimal implementation**

```python
# report.py
"""Pulls account/order/portfolio data from Alpaca and computes the fields
needed by the weekly-format daily report template (render_report in
Task 7)."""
import os
from datetime import date, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetCalendarRequest, GetOrdersRequest, GetPortfolioHistoryRequest

from config import WATCHLIST


class ReportClient:
    def __init__(self):
        key = os.environ["ALPACA_API_KEY"]
        secret = os.environ["ALPACA_SECRET_KEY"]
        self._trading = TradingClient(key, secret, paper=True)

    def get_account_snapshot(self) -> dict:
        a = self._trading.get_account()
        return {
            "equity": float(a.equity),
            "cash": float(a.cash),
            "options_buying_power": float(a.options_buying_power),
        }

    def get_positions(self) -> list:
        return self._trading.get_all_positions()

    def get_filled_orders(self, after: date, until: date) -> list:
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after, until=until, limit=500)
        orders = self._trading.get_orders(req)
        return [o for o in orders if o.status == "filled"]

    def get_portfolio_history(self):
        req = GetPortfolioHistoryRequest(period="1A", timeframe="1D")
        return self._trading.get_portfolio_history(req)

    def is_trading_day(self, d: date) -> bool:
        cal = self._trading.get_calendar(GetCalendarRequest(start=d, end=d))
        return any(day.date == d for day in cal)

    def first_trading_day_on_or_after(self, d: date) -> date:
        cal = self._trading.get_calendar(GetCalendarRequest(start=d, end=d + timedelta(days=7)))
        return cal[0].date


def build_report_context(client: ReportClient, today: date) -> dict:
    monday = today - timedelta(days=today.weekday())
    week_start = monday if client.is_trading_day(monday) else client.first_trading_day_on_or_after(monday)

    account = client.get_account_snapshot()
    positions = client.get_positions()
    orders = client.get_filled_orders(after=week_start, until=today)
    history = client.get_portfolio_history()

    positions_by_ticker = {}
    for ticker in WATCHLIST:
        symbol_positions = [p for p in positions if p.symbol.startswith(ticker.symbol)]
        positions_by_ticker[ticker.symbol] = symbol_positions

    ytd_return_pct = round(history.profit_loss_pct[-1] * 100, 2) if history.profit_loss_pct else 0.0

    day_of_year = today.timetuple().tm_yday
    prorated_target_pct = round(10.0 * (day_of_year / 365), 2)
    gap = round(ytd_return_pct - prorated_target_pct, 2)
    pace_status = "AHEAD" if gap > 0 else ("BEHIND" if gap < 0 else "ON_PACE")

    goal_meter = {
        "ytd_return_pct": ytd_return_pct,
        "prorated_target_pct": prorated_target_pct,
        "pace_status": pace_status,
        "gap_pts": abs(gap),
    }

    return {
        "week_start": week_start,
        "week_end": today,
        "account": account,
        "positions_by_ticker": positions_by_ticker,
        "activity_log": orders,
        "goal_meter": goal_meter,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add report.py tests/test_report.py
git commit -m "feat: add report.py to reconstruct account/order/portfolio data from Alpaca"
```

---

### Task 7: `email_sender.py` — Gmail SMTP wrapper

**Files:**
- Create: `email_sender.py`
- Test: `tests/test_email_sender.py`

**Interfaces:**
- Consumes: `config.REPORT_EMAIL`, env var `GMAIL_APP_PASSWORD`.
- Produces: `send_email(subject: str, body: str, smtp_client_factory=smtplib.SMTP_SSL) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_sender.py
from unittest.mock import MagicMock, patch
import pytest
from email_sender import send_email


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "test_password")


def test_send_email_logs_in_and_sends(mock_env):
    mock_smtp_instance = MagicMock()
    mock_smtp_cls = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_instance

    send_email("Test Subject", "Test Body", smtp_client_factory=mock_smtp_cls)

    mock_smtp_instance.login.assert_called_once_with("daniel.kwon7607@gmail.com", "test_password")
    mock_smtp_instance.send_message.assert_called_once()
    sent_msg = mock_smtp_instance.send_message.call_args[0][0]
    assert sent_msg["Subject"] == "Test Subject"
    assert sent_msg["To"] == "daniel.kwon7607@gmail.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_email_sender.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'email_sender'`

- [ ] **Step 3: Write minimal implementation**

```python
# email_sender.py
"""Thin Gmail SMTP wrapper — mockable for tests, real for production."""
import os
import smtplib
from email.mime.text import MIMEText

from config import REPORT_EMAIL


def send_email(subject: str, body: str, smtp_client_factory=smtplib.SMTP_SSL) -> None:
    password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = REPORT_EMAIL
    msg["To"] = REPORT_EMAIL

    with smtp_client_factory("smtp.gmail.com", 465) as s:
        s.login(REPORT_EMAIL, password)
        s.send_message(msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_email_sender.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add email_sender.py tests/test_email_sender.py
git commit -m "feat: add Gmail SMTP email sender for daily reports"
```

---

### Task 8: Template renderer — fixed 9-section format

**Files:**
- Modify: `report.py` (add `render_report`)
- Modify: `tests/test_report.py`

**Interfaces:**
- Consumes: the dict produced by `build_report_context` (Task 6).
- Produces: `render_report(ctx: dict) -> str` — full plain-text email body starting with the exact greeting line and covering all 9 sections from the user's spec.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_report.py`:

```python
from report import render_report


def test_render_report_starts_with_exact_greeting():
    ctx = {
        "week_start": date(2026, 7, 20),
        "week_end": date(2026, 7, 21),
        "account": {"equity": 25000.00, "cash": 10000.00, "options_buying_power": 10000.00},
        "positions_by_ticker": {"SOFI": [], "NVDA": []},
        "activity_log": [],
        "goal_meter": {
            "ytd_return_pct": 2.0,
            "prorated_target_pct": 2.5,
            "pace_status": "BEHIND",
            "gap_pts": 0.5,
        },
    }
    body = render_report(ctx)
    assert body.startswith("hey its claude, here's your weekly trading report")


def test_render_report_includes_goal_meter_progress_bar():
    ctx = {
        "week_start": date(2026, 7, 20),
        "week_end": date(2026, 7, 21),
        "account": {"equity": 25000.00, "cash": 10000.00, "options_buying_power": 10000.00},
        "positions_by_ticker": {"SOFI": [], "NVDA": []},
        "activity_log": [],
        "goal_meter": {
            "ytd_return_pct": 5.0,
            "prorated_target_pct": 4.0,
            "pace_status": "AHEAD",
            "gap_pts": 1.0,
        },
    }
    body = render_report(ctx)
    assert "GOAL: 10% ROI by Dec 31" in body
    assert "AHEAD" in body
    assert "1.00 pts" in body or "1.0 pts" in body


def test_render_report_flags_position_with_no_action():
    ctx = {
        "week_start": date(2026, 7, 20),
        "week_end": date(2026, 7, 21),
        "account": {"equity": 25000.00, "cash": 10000.00, "options_buying_power": 10000.00},
        "positions_by_ticker": {"SOFI": [], "NVDA": []},
        "activity_log": [],
        "goal_meter": {"ytd_return_pct": 0.0, "prorated_target_pct": 0.0, "pace_status": "ON_PACE", "gap_pts": 0.0},
    }
    body = render_report(ctx)
    assert "no action, monitoring" in body.lower() or "No open positions" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_report' from 'report'`

- [ ] **Step 3: Write minimal implementation**

Append to `report.py`:

```python
def _progress_bar(pct_of_target: float, width: int = 20) -> str:
    filled = min(width, max(0, round(width * pct_of_target / 100)))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def render_report(ctx: dict) -> str:
    a = ctx["account"]
    goal = ctx["goal_meter"]
    lines = []
    lines.append("hey its claude, here's your weekly trading report")
    lines.append("")
    lines.append("WHEEL STRATEGY — WEEKLY REPORT")
    lines.append(f"Week of {ctx['week_start'].isoformat()} - {ctx['week_end'].isoformat()}")
    lines.append("Account: Alpaca Paper")
    lines.append("Status: ✅ All systems nominal")
    lines.append("")
    lines.append("Total Account Value:   $%.2f" % a["equity"])
    lines.append("Cash Balance:          $%.2f" % a["cash"])
    lines.append("Buying Power (options): $%.2f" % a["options_buying_power"])
    lines.append("")

    for symbol, positions in ctx["positions_by_ticker"].items():
        if not positions:
            lines.append(f"[{symbol}] — no open position. no action, monitoring.")
        else:
            for p in positions:
                lines.append(f"[{symbol}] — {p.symbol}: qty={p.qty}, unrealized_pl=${p.unrealized_pl}")
    lines.append("")

    lines.append("This Week's Activity Log:")
    if not ctx["activity_log"]:
        lines.append("  (no fills this week)")
    else:
        for o in ctx["activity_log"]:
            lines.append(f"  {o.filled_at}: {o.side} {o.symbol} filled_qty={o.filled_qty} @ ${o.filled_avg_price}")
    lines.append("")

    lines.append("GOAL: 10% ROI by Dec 31")
    bar = _progress_bar(goal["ytd_return_pct"] / 10.0 * 100)
    lines.append(f"{bar} {goal['ytd_return_pct']:.1f}% of 10% target")
    lines.append(
        f"Pace check: You're at {goal['ytd_return_pct']:.2f}% YTD vs. "
        f"{goal['prorated_target_pct']:.2f}% pro-rated target -> "
        f"{goal['pace_status']} by {goal['gap_pts']:.2f} pts"
    )

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add report.py tests/test_report.py
git commit -m "feat: render fixed weekly-format report template with goal-meter progress bar"
```

---

### Task 9: `send_daily_report.py` — entrypoint script

**Files:**
- Create: `send_daily_report.py`

**Interfaces:**
- Consumes: `report.ReportClient`, `report.build_report_context`, `report.render_report`, `email_sender.send_email`, `strategy.is_market_hours` (not used directly — trading-day check comes from `ReportClient.is_trading_day`).
- Produces: script with `if __name__ == "__main__":` entrypoint; exits 0 with no email if today isn't a trading day; otherwise builds and sends the report.

- [ ] **Step 1: Write the script**

```python
# send_daily_report.py
"""Entrypoint for the daily report cron job. Sends one email per trading
day, after market close. Run this file directly: python send_daily_report.py
"""
import logging
from datetime import date

from email_sender import send_email
from report import ReportClient, build_report_context, render_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    today = date.today()
    client = ReportClient()

    if not client.is_trading_day(today):
        log.info(f"{today} is not a trading day — no report sent.")
        return

    ctx = build_report_context(client, today)
    body = render_report(ctx)
    send_email(subject=f"Wheel Strategy Report — {today.isoformat()}", body=body)
    log.info("Daily report sent.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual verification (no automated test — this is a thin wiring script)**

Run: `python send_daily_report.py`
Expected: if run on a trading day, log line `Daily report sent.` and a real email arrives at daniel.kwon7607@gmail.com with subject `Wheel Strategy Report — <today>`. If run on a non-trading day, log line `<date> is not a trading day — no report sent.` and no email.

- [ ] **Step 3: Commit**

```bash
git add send_daily_report.py
git commit -m "feat: add daily report entrypoint script"
```

---

### Task 10: GitHub Actions workflow for the daily report

**Files:**
- Create: `.github/workflows/daily-report.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Daily Wheel Report

# Fires once after market close on weekdays. The script itself checks
# whether today was actually a trading day (via Alpaca's calendar) and
# exits quietly with no email if not — so this doesn't need holiday logic.
on:
  schedule:
    - cron: "30 21 * * 1-5"   # 21:30 UTC ~= 4:30-5:30pm ET after close, Mon-Fri
  workflow_dispatch:

jobs:
  send-report:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Send daily report
        env:
          ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY }}
          ALPACA_SECRET_KEY: ${{ secrets.ALPACA_SECRET_KEY }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
        run: python send_daily_report.py
```

- [ ] **Step 2: Verify locally that requirements.txt has everything needed**

Run: `python -c "import alpaca, dotenv, pytz, smtplib; print('ok')"`
Expected: `ok` (all are already in `requirements.txt` or stdlib — no new dependency needed for this plan)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/daily-report.yml
git commit -m "ci: schedule daily wheel report on GitHub Actions"
```

---

### Task 11: Manual end-to-end verification and push

**Files:** none (verification + push only)

- [ ] **Step 1: Run the full local test suite**

Run: `python -m pytest -q`
Expected: all tests pass, 0 failures

- [ ] **Step 2: Trigger the trading workflow manually and confirm SOFI positions**

In GitHub: Actions tab → "Wheel Bot" → Run workflow (during market hours). Check the run log for `[SOFI] SELL_PUT x<N>` and `[NVDA] HOLD` (or `CLOSE_EARLY`/`CLOSE_AND_ROLL` depending on the existing NVDA put's state) lines.

- [ ] **Step 3: Trigger the report workflow manually**

In GitHub: Actions tab → "Daily Wheel Report" → Run workflow. Confirm the email arrives with the correct greeting line, account numbers matching what's shown in step 2, and the goal-meter section present.

- [ ] **Step 4: Push (if not already pushed via per-task commits)**

```bash
git push origin main
```

Expected: `main -> main` push succeeds; both new workflows visible and enabled under the repo's Actions tab.
