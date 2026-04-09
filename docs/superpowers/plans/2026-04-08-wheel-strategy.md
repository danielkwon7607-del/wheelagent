# Wheel Strategy Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude-driven wheel strategy bot that sells cash-secured puts and covered calls on NVDA via Alpaca paper trading, runs on a 15-minute schedule during market hours, and generates a daily summary at 4pm ET.

**Architecture:** Claude Code executes Python scripts directly via the `/schedule` command. The bot uses a state machine (no position → short put → long shares → short call) driven by live Alpaca account data. All logic is split into focused modules: a thin Alpaca wrapper, pure strategy functions, and a main orchestrator.

**Tech Stack:** Python 3.10+, `alpaca-py`, `python-dotenv`, `pytz`, `pytest`, `pytest-mock`

---

## File Structure

```
claude trading/
├── .env.paper                  # credentials (already exists)
├── .gitignore                  # (already exists)
├── requirements.txt            # dependencies
├── alpaca_client.py            # thin wrapper around alpaca-py
├── strategy.py                 # pure strategy logic (no API calls)
├── wheel_bot.py                # main orchestrator — Claude runs this
├── summary.py                  # daily P&L summary — Claude runs this
├── tests/
│   ├── __init__.py
│   ├── test_strategy.py
│   ├── test_alpaca_client.py
│   └── test_wheel_bot.py
└── logs/                       # created at runtime by wheel_bot.py
```

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```
alpaca-py==0.38.0
python-dotenv==1.0.1
pytz==2024.1
pytest==8.3.5
pytest-mock==3.14.0
```

- [ ] **Step 2: Install dependencies**

Run:
```bash
pip install -r requirements.txt
```

Expected output: Successfully installed alpaca-py, python-dotenv, pytz, pytest, pytest-mock (and their dependencies). No errors.

- [ ] **Step 3: Create tests/__init__.py**

Create an empty file at `tests/__init__.py`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt tests/__init__.py
git commit -m "chore: add dependencies and test structure"
```

---

## Task 2: Strategy Logic (Pure Functions)

**Files:**
- Create: `strategy.py`
- Create: `tests/test_strategy.py`

These are pure functions with no API calls — easiest to test.

- [ ] **Step 1: Write failing tests**

Create `tests/test_strategy.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd "C:\Users\Daniel\OneDrive\Documents\claude trading" && python -m pytest tests/test_strategy.py -v
```

Expected: All tests FAIL with `ModuleNotFoundError: No module named 'strategy'`

- [ ] **Step 3: Implement strategy.py**

Create `strategy.py`:

```python
from datetime import date, timedelta, datetime
import math
import pytz


def is_market_hours() -> bool:
    """Returns True if current time is within NYSE market hours (9:30am-4pm ET, Mon-Fri)."""
    et = pytz.timezone("US/Eastern")
    now = datetime.now(et)
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
    return float(math.ceil(target))


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd "C:\Users\Daniel\OneDrive\Documents\claude trading" && python -m pytest tests/test_strategy.py -v
```

Expected: All 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add strategy.py tests/test_strategy.py
git commit -m "feat: add pure strategy logic with tests"
```

---

## Task 3: Alpaca Client Wrapper

**Files:**
- Create: `alpaca_client.py`
- Create: `tests/test_alpaca_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_alpaca_client.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from alpaca_client import AlpacaClient


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2")


@pytest.fixture
def client(mock_env):
    with patch("alpaca_client.TradingClient"), patch("alpaca_client.StockHistoricalDataClient"):
        return AlpacaClient()


def test_get_buying_power(client):
    client._trading.get_account.return_value = MagicMock(buying_power="9500.00")
    result = client.get_buying_power()
    assert result == 9500.00


def test_get_nvda_price(client):
    mock_quote = MagicMock()
    mock_quote.ask_price = 125.50
    client._data.get_stock_latest_quote.return_value = {"NVDA": mock_quote}
    result = client.get_nvda_price()
    assert result == 125.50


def test_has_nvda_shares_true(client):
    mock_position = MagicMock()
    mock_position.symbol = "NVDA"
    mock_position.qty = "100"
    mock_position.avg_entry_price = "105.00"
    client._trading.get_all_positions.return_value = [mock_position]
    has_shares, qty, cost_basis = client.get_nvda_stock_position()
    assert has_shares is True
    assert qty == 100
    assert cost_basis == 105.00


def test_has_nvda_shares_false(client):
    client._trading.get_all_positions.return_value = []
    has_shares, qty, cost_basis = client.get_nvda_stock_position()
    assert has_shares is False
    assert qty == 0
    assert cost_basis == 0.0


def test_get_open_nvda_options_empty(client):
    client._trading.get_all_positions.return_value = []
    puts, calls = client.get_open_nvda_options()
    assert puts == []
    assert calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd "C:\Users\Daniel\OneDrive\Documents\claude trading" && python -m pytest tests/test_alpaca_client.py -v
```

Expected: All tests FAIL with `ModuleNotFoundError: No module named 'alpaca_client'`

- [ ] **Step 3: Implement alpaca_client.py**

Create `alpaca_client.py`:

```python
import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    MarketOrderRequest,
    LimitOrderRequest,
    ClosePositionRequest,
)
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce, ContractType
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from datetime import date


load_dotenv(".env.paper")


class AlpacaClient:
    def __init__(self):
        key = os.environ["ALPACA_API_KEY"]
        secret = os.environ["ALPACA_SECRET_KEY"]
        self._trading = TradingClient(key, secret, paper=True)
        self._data = StockHistoricalDataClient(key, secret)

    def get_buying_power(self) -> float:
        account = self._trading.get_account()
        return float(account.buying_power)

    def get_nvda_price(self) -> float:
        req = StockLatestQuoteRequest(symbol_or_symbols=["NVDA"])
        quotes = self._data.get_stock_latest_quote(req)
        return float(quotes["NVDA"].ask_price)

    def get_nvda_stock_position(self) -> tuple[bool, int, float]:
        """Returns (has_shares, quantity, avg_cost_basis)."""
        positions = self._trading.get_all_positions()
        for p in positions:
            if p.symbol == "NVDA":
                return True, int(float(p.qty)), float(p.avg_entry_price)
        return False, 0, 0.0

    def get_open_nvda_options(self) -> tuple[list, list]:
        """Returns (open_puts, open_calls) — lists of position objects."""
        positions = self._trading.get_all_positions()
        puts = []
        calls = []
        for p in positions:
            symbol = p.symbol or ""
            # Alpaca option symbols look like: NVDA251121P00110000
            if symbol.startswith("NVDA") and len(symbol) > 10:
                if "P" in symbol[10:]:
                    puts.append(p)
                elif "C" in symbol[10:]:
                    calls.append(p)
        return puts, calls

    def find_put_contract(self, strike: float, expiry: date) -> str | None:
        """Find the best available put contract at or below the target strike."""
        req = GetOptionContractsRequest(
            underlying_symbols=["NVDA"],
            expiration_date=expiry,
            type=ContractType.PUT,
            strike_price_lte=str(strike),
        )
        contracts = self._trading.get_option_contracts(req)
        if not contracts.option_contracts:
            return None
        # Pick the highest strike at or below our target
        best = max(contracts.option_contracts, key=lambda c: float(c.strike_price))
        return best.symbol

    def find_call_contract(self, strike: float, expiry: date) -> str | None:
        """Find the best available call contract at or above the target strike."""
        req = GetOptionContractsRequest(
            underlying_symbols=["NVDA"],
            expiration_date=expiry,
            type=ContractType.CALL,
            strike_price_gte=str(strike),
        )
        contracts = self._trading.get_option_contracts(req)
        if not contracts.option_contracts:
            return None
        # Pick the lowest strike at or above our target
        best = min(contracts.option_contracts, key=lambda c: float(c.strike_price))
        return best.symbol

    def sell_option(self, contract_symbol: str, limit_price: float) -> dict:
        """Sell 1 option contract at a limit price."""
        order = LimitOrderRequest(
            symbol=contract_symbol,
            qty=1,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
        )
        result = self._trading.submit_order(order)
        return {"id": str(result.id), "symbol": contract_symbol, "limit_price": limit_price}

    def close_option_position(self, contract_symbol: str) -> dict:
        """Buy to close an option position (close early at 50% profit)."""
        result = self._trading.close_position(contract_symbol)
        return {"id": str(result.id), "symbol": contract_symbol, "action": "closed"}

    def get_option_quote(self, contract_symbol: str) -> float:
        """Get the current mid-price of an option contract."""
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionLatestQuoteRequest
        key = os.environ["ALPACA_API_KEY"]
        secret = os.environ["ALPACA_SECRET_KEY"]
        opt_data = OptionHistoricalDataClient(key, secret)
        req = OptionLatestQuoteRequest(symbol_or_symbols=[contract_symbol])
        quotes = opt_data.get_option_latest_quote(req)
        q = quotes[contract_symbol]
        return (float(q.bid_price) + float(q.ask_price)) / 2
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd "C:\Users\Daniel\OneDrive\Documents\claude trading" && python -m pytest tests/test_alpaca_client.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add alpaca_client.py tests/test_alpaca_client.py
git commit -m "feat: add alpaca client wrapper with tests"
```

---

## Task 4: Main Orchestrator

**Files:**
- Create: `wheel_bot.py`
- Create: `tests/test_wheel_bot.py`
- Create: `logs/.gitkeep`

- [ ] **Step 1: Write failing tests**

Create `tests/test_wheel_bot.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from wheel_bot import WheelBot


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_buying_power.return_value = 10000.00
    client.get_nvda_price.return_value = 120.00
    client.get_nvda_stock_position.return_value = (False, 0, 0.0)
    client.get_open_nvda_options.return_value = ([], [])
    return client


def test_no_position_sells_put(mock_client):
    """When state is NO_POSITION, bot should sell a put."""
    mock_client.find_put_contract.return_value = "NVDA251121P00108000"
    mock_client.get_option_quote.return_value = 2.50
    mock_client.sell_option.return_value = {"id": "123", "symbol": "NVDA251121P00108000", "limit_price": 2.50}

    bot = WheelBot(mock_client)
    with patch("wheel_bot.is_market_hours", return_value=True):
        result = bot.run()

    mock_client.sell_option.assert_called_once()
    assert result["action"] == "SELL_PUT"


def test_no_action_outside_market_hours(mock_client):
    """Bot should do nothing outside market hours."""
    bot = WheelBot(mock_client)
    with patch("wheel_bot.is_market_hours", return_value=False):
        result = bot.run()

    mock_client.sell_option.assert_not_called()
    assert result["action"] == "MARKET_CLOSED"


def test_long_shares_sells_call(mock_client):
    """When holding shares with no open call, bot should sell a covered call."""
    mock_client.get_nvda_stock_position.return_value = (True, 100, 108.00)
    mock_client.get_open_nvda_options.return_value = ([], [])
    mock_client.find_call_contract.return_value = "NVDA251121C00119000"
    mock_client.get_option_quote.return_value = 1.80
    mock_client.sell_option.return_value = {"id": "456", "symbol": "NVDA251121C00119000", "limit_price": 1.80}

    bot = WheelBot(mock_client)
    with patch("wheel_bot.is_market_hours", return_value=True):
        result = bot.run()

    mock_client.sell_option.assert_called_once()
    assert result["action"] == "SELL_CALL"


def test_short_put_closes_early_at_50_percent(mock_client):
    """When short put hits 50% profit, close it early."""
    mock_put = MagicMock()
    mock_put.symbol = "NVDA251121P00108000"
    mock_put.avg_entry_price = "2.00"  # premium received when we sold
    mock_client.get_open_nvda_options.return_value = ([mock_put], [])
    mock_client.get_option_quote.return_value = 1.00  # now worth $1.00 = 50% profit
    mock_client.close_option_position.return_value = {"id": "789", "symbol": "NVDA251121P00108000", "action": "closed"}

    bot = WheelBot(mock_client)
    with patch("wheel_bot.is_market_hours", return_value=True):
        result = bot.run()

    mock_client.close_option_position.assert_called_once()
    assert result["action"] == "CLOSE_EARLY"


def test_short_put_holds_when_not_50_percent(mock_client):
    """When short put is less than 50% profit, hold."""
    mock_put = MagicMock()
    mock_put.symbol = "NVDA251121P00108000"
    mock_put.avg_entry_price = "2.00"
    mock_client.get_open_nvda_options.return_value = ([mock_put], [])
    mock_client.get_option_quote.return_value = 1.50  # only 25% profit

    bot = WheelBot(mock_client)
    with patch("wheel_bot.is_market_hours", return_value=True):
        result = bot.run()

    mock_client.close_option_position.assert_not_called()
    assert result["action"] == "HOLD"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd "C:\Users\Daniel\OneDrive\Documents\claude trading" && python -m pytest tests/test_wheel_bot.py -v
```

Expected: All tests FAIL with `ModuleNotFoundError: No module named 'wheel_bot'`

- [ ] **Step 3: Create logs directory**

Create an empty file `logs/.gitkeep` so the directory exists.

- [ ] **Step 4: Implement wheel_bot.py**

Create `wheel_bot.py`:

```python
"""
Wheel Strategy Bot — NVDA, Alpaca Paper Trading
Run this file directly: python wheel_bot.py
Claude also runs this on a /schedule every 15 minutes during market hours.
"""
import logging
import os
from datetime import datetime

from alpaca_client import AlpacaClient
from strategy import (
    determine_state,
    get_call_strike,
    get_put_strike,
    get_target_expiry,
    is_market_hours,
    should_close_early,
)

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("logs/wheel.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


class WheelBot:
    def __init__(self, client: AlpacaClient | None = None):
        self.client = client or AlpacaClient()

    def run(self) -> dict:
        if not is_market_hours():
            log.info("Market closed — no action taken.")
            return {"action": "MARKET_CLOSED", "time": datetime.now().isoformat()}

        buying_power = self.client.get_buying_power()
        nvda_price = self.client.get_nvda_price()
        has_shares, share_qty, cost_basis = self.client.get_nvda_stock_position()
        open_puts, open_calls = self.client.get_open_nvda_options()

        state = determine_state(
            has_shares=has_shares,
            has_open_put=len(open_puts) > 0,
            has_open_call=len(open_calls) > 0,
        )
        log.info(f"State={state} | NVDA=${nvda_price:.2f} | BuyingPower=${buying_power:.2f}")

        # SHORT_PUT: check if we should close early
        if state == "SHORT_PUT":
            put = open_puts[0]
            current_price = self.client.get_option_quote(put.symbol)
            premium_received = float(put.avg_entry_price)
            if should_close_early(premium_received, current_price):
                result = self.client.close_option_position(put.symbol)
                log.info(f"CLOSE_EARLY put {put.symbol} — 50% profit reached. Order: {result}")
                return {"action": "CLOSE_EARLY", "detail": result}
            log.info(f"HOLD put {put.symbol} — current=${current_price:.2f}, received=${premium_received:.2f}")
            return {"action": "HOLD", "symbol": put.symbol}

        # SHORT_CALL: check if we should close early
        if state == "SHORT_CALL":
            call = open_calls[0]
            current_price = self.client.get_option_quote(call.symbol)
            premium_received = float(call.avg_entry_price)
            if should_close_early(premium_received, current_price):
                result = self.client.close_option_position(call.symbol)
                log.info(f"CLOSE_EARLY call {call.symbol} — 50% profit reached. Order: {result}")
                return {"action": "CLOSE_EARLY", "detail": result}
            log.info(f"HOLD call {call.symbol} — current=${current_price:.2f}, received=${premium_received:.2f}")
            return {"action": "HOLD", "symbol": call.symbol}

        # LONG_SHARES: sell a covered call
        if state == "LONG_SHARES":
            strike = get_call_strike(cost_basis)
            expiry = get_target_expiry()
            contract = self.client.find_call_contract(strike, expiry)
            if not contract:
                log.warning(f"No call contract found for strike=${strike}, expiry={expiry}")
                return {"action": "NO_CONTRACT", "strike": strike, "expiry": str(expiry)}
            quote = self.client.get_option_quote(contract)
            result = self.client.sell_option(contract, limit_price=quote)
            log.info(f"SELL_CALL {contract} @ ${quote:.2f} | strike=${strike}, expiry={expiry}")
            return {"action": "SELL_CALL", "detail": result}

        # NO_POSITION: sell a cash-secured put
        if state == "NO_POSITION":
            strike = get_put_strike(nvda_price, buying_power)
            expiry = get_target_expiry()
            contract = self.client.find_put_contract(strike, expiry)
            if not contract:
                log.warning(f"No put contract found for strike=${strike}, expiry={expiry}")
                return {"action": "NO_CONTRACT", "strike": strike, "expiry": str(expiry)}
            quote = self.client.get_option_quote(contract)
            result = self.client.sell_option(contract, limit_price=quote)
            log.info(f"SELL_PUT {contract} @ ${quote:.2f} | strike=${strike}, expiry={expiry}")
            return {"action": "SELL_PUT", "detail": result}

        return {"action": "UNKNOWN_STATE", "state": state}


if __name__ == "__main__":
    bot = WheelBot()
    result = bot.run()
    print(f"\nResult: {result}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd "C:\Users\Daniel\OneDrive\Documents\claude trading" && python -m pytest tests/test_wheel_bot.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add wheel_bot.py tests/test_wheel_bot.py logs/.gitkeep
git commit -m "feat: add wheel bot orchestrator with tests"
```

---

## Task 5: Daily Summary

**Files:**
- Create: `summary.py`

- [ ] **Step 1: Create summary.py**

```python
"""
Daily Summary — run at 4pm ET via /schedule
Prints P&L, positions, and premiums collected today.
"""
import os
import logging
from datetime import date, datetime
from alpaca_client import AlpacaClient

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler("logs/summary.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def run_summary():
    client = AlpacaClient()
    account = client._trading.get_account()
    positions = client._trading.get_all_positions()

    buying_power = float(account.buying_power)
    portfolio_value = float(account.portfolio_value)
    equity = float(account.equity)

    has_shares, share_qty, cost_basis = client.get_nvda_stock_position()
    open_puts, open_calls = client.get_open_nvda_options()

    print("\n" + "="*50)
    print(f"  WHEEL BOT DAILY SUMMARY — {date.today()}")
    print("="*50)
    print(f"  Portfolio Value : ${portfolio_value:,.2f}")
    print(f"  Buying Power    : ${buying_power:,.2f}")
    print(f"  Equity          : ${equity:,.2f}")
    print("-"*50)
    if has_shares:
        nvda_price = client.get_nvda_price()
        unrealized = (nvda_price - cost_basis) * share_qty
        print(f"  NVDA Shares     : {share_qty} @ ${cost_basis:.2f} cost basis")
        print(f"  Unrealized P&L  : ${unrealized:+.2f}")
    else:
        print("  NVDA Shares     : None")
    print("-"*50)
    if open_puts:
        for p in open_puts:
            print(f"  Open Put        : {p.symbol} | sold @ ${float(p.avg_entry_price):.2f}")
    if open_calls:
        for c in open_calls:
            print(f"  Open Call       : {c.symbol} | sold @ ${float(c.avg_entry_price):.2f}")
    if not open_puts and not open_calls:
        print("  Open Options    : None")
    print("="*50 + "\n")

    log.info(f"Daily summary complete. Portfolio=${portfolio_value:.2f}, BuyingPower=${buying_power:.2f}")


if __name__ == "__main__":
    run_summary()
```

- [ ] **Step 2: Verify it runs without error (dry run against real API)**

Run:
```bash
cd "C:\Users\Daniel\OneDrive\Documents\claude trading" && python summary.py
```

Expected: Prints a formatted summary table with your Alpaca paper account balance ($10,000) and no open positions. No errors.

- [ ] **Step 3: Commit**

```bash
git add summary.py
git commit -m "feat: add daily summary script"
```

---

## Task 6: Connection Test & First Run

**Files:** No new files

- [ ] **Step 1: Verify Alpaca connection**

Run:
```bash
cd "C:\Users\Daniel\OneDrive\Documents\claude trading" && python -c "
from alpaca_client import AlpacaClient
c = AlpacaClient()
print('Buying power:', c.get_buying_power())
print('NVDA price:', c.get_nvda_price())
print('NVDA position:', c.get_nvda_stock_position())
print('Open options:', c.get_open_nvda_options())
print('Connection OK')
"
```

Expected output:
```
Buying power: 10000.0
NVDA price: <current price>
NVDA position: (False, 0, 0.0)
Open options: ([], [])
Connection OK
```

- [ ] **Step 2: Dry run the bot**

Run:
```bash
cd "C:\Users\Daniel\OneDrive\Documents\claude trading" && python wheel_bot.py
```

Expected (if market is open): Bot logs state, finds a put contract, places a sell order. Output includes `SELL_PUT` with contract symbol and limit price.

Expected (if market is closed): `Market closed — no action taken.`

- [ ] **Step 3: Set up the 15-minute schedule**

In Claude Code, run this command to create the recurring schedule:

```
/schedule --cron "*/15 9-16 * * 1-5" python wheel_bot.py
```

Then set up the daily summary:

```
/schedule --cron "0 16 * * 1-5" python summary.py
```

- [ ] **Step 4: Verify schedules are active**

Click the clock icon in the Claude Code sidebar. You should see two scheduled tasks:
- `wheel_bot.py` — every 15 minutes, Mon-Fri
- `summary.py` — 4pm ET, Mon-Fri

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: wheel strategy bot complete — NVDA paper trading"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Market hours ✓ | Cash-secured put ✓ | 10% strike rule ✓ | Cost basis protection ✓ | 50% early close ✓ | Covered call ✓ | Daily summary ✓ | Schedule ✓
- [x] **No placeholders:** All steps have complete code
- [x] **Type consistency:** `AlpacaClient` used consistently across all tasks. `is_market_hours`, `determine_state`, `get_put_strike`, `get_call_strike`, `get_target_expiry`, `should_close_early` all match their test usages exactly.
