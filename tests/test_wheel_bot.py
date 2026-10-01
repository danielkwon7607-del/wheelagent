import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from strategy import BOT_ORDER_PREFIX, Quote
from wheel_bot import WheelBot


def quote(bid, ask, age_seconds=0):
    return Quote(bid, ask, datetime.now(timezone.utc) - timedelta(seconds=age_seconds))


def order(client_order_id=BOT_ORDER_PREFIX + "abc", age_minutes=0, symbol="NVDA251121P00108000"):
    submitted = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return SimpleNamespace(id=f"id-{age_minutes}", client_order_id=client_order_id, symbol=symbol,
                           side="sell", limit_price=2.50, submitted_at=submitted, created_at=submitted)


def short_put(entry="2.00"):
    return SimpleNamespace(symbol="NVDA251121P00108000", qty="-1", avg_entry_price=entry)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_options_buying_power.return_value = 10000.00
    client.get_nvda_quote.return_value = quote(119.99, 120.01)
    client.get_nvda_last_trade.return_value = (120.00, datetime.now(timezone.utc))
    client.get_nvda_stock_position.return_value = (False, 0, 0.0)
    client.get_open_nvda_options.return_value = ([], [])
    client.get_open_nvda_orders.return_value = []
    client.get_option_quote.return_value = quote(2.45, 2.55)
    return client


def run(bot):
    with patch("wheel_bot.is_market_hours", return_value=True):
        return bot.run()


def test_no_position_sells_put(mock_client):
    """When state is NO_POSITION, bot should sell a put."""
    mock_client.find_put_contract.return_value = "NVDA251121P00108000"
    mock_client.sell_option.return_value = {"id": "123", "symbol": "NVDA251121P00108000", "limit_price": 2.50}

    result = run(WheelBot(mock_client))

    mock_client.sell_option.assert_called_once_with("NVDA251121P00108000", limit_price=2.50)  # at mid
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
    mock_client.find_call_contract.return_value = "NVDA251121C00119000"
    mock_client.get_option_quote.return_value = quote(1.75, 1.85)
    mock_client.sell_option.return_value = {"id": "456", "symbol": "NVDA251121C00119000", "limit_price": 1.80}

    result = run(WheelBot(mock_client))

    mock_client.sell_option.assert_called_once()
    assert result["action"] == "SELL_CALL"


def test_short_put_closes_and_rolls_at_50_percent(mock_client):
    """When short put hits 50% profit: take profit AND immediately roll into
    the next play (sell a fresh put) in the same run."""
    put = short_put()
    # First read shows the put open (triggers close); after the close fills
    # the position is gone, so the bot rolls into the next play.
    mock_client.get_open_nvda_options.side_effect = [([put], []), ([], []), ([], [])]
    mock_client.get_option_quote.return_value = quote(0.98, 1.02)  # mid $1.00 = 50% profit
    mock_client.buy_to_close.return_value = {"id": "789", "symbol": put.symbol}
    mock_client.find_put_contract.return_value = "NVDA251205P00108000"
    mock_client.sell_option.return_value = {"id": "999", "symbol": "NVDA251205P00108000", "limit_price": 1.00}

    result = run(WheelBot(mock_client, roll_poll_interval=0))

    mock_client.buy_to_close.assert_called_once_with(put.symbol, 1, limit_price=1.00)  # limit at mid
    mock_client.sell_option.assert_called_once()  # rolled into the next play
    assert result["action"] == "CLOSE_AND_ROLL"


def test_short_put_closes_but_defers_roll_if_not_filled(mock_client):
    """If the profit-taking close hasn't filled yet, don't force a roll —
    the next scheduled run opens the play. No trade is lost."""
    mock_client.get_open_nvda_options.return_value = ([short_put()], [])  # never clears
    mock_client.get_option_quote.return_value = quote(0.98, 1.02)
    mock_client.buy_to_close.return_value = {"id": "789"}

    # timeout=0 → give up waiting immediately, defer the roll
    result = run(WheelBot(mock_client, roll_poll_interval=0, roll_poll_timeout=0))

    mock_client.buy_to_close.assert_called_once()
    mock_client.sell_option.assert_not_called()
    assert result["action"] == "CLOSE_EARLY"


def test_short_put_holds_when_not_50_percent(mock_client):
    """When short put is less than 50% profit, hold."""
    mock_client.get_open_nvda_options.return_value = ([short_put()], [])
    mock_client.get_option_quote.return_value = quote(1.45, 1.55)  # only 25% profit

    result = run(WheelBot(mock_client))

    mock_client.buy_to_close.assert_not_called()
    assert result["action"] == "HOLD"


# --- open orders: never stack a second order on top of a working one ---

def test_working_bot_order_blocks_new_orders(mock_client):
    mock_client.get_open_nvda_orders.return_value = [order(age_minutes=2)]

    result = run(WheelBot(mock_client))

    assert result["action"] == "WAIT_OPEN_ORDER"
    mock_client.cancel_order.assert_not_called()
    mock_client.sell_option.assert_not_called()


def test_stale_bot_order_is_cancelled_then_replaced(mock_client):
    mock_client.get_open_nvda_orders.side_effect = [[order(age_minutes=11)], []]
    mock_client.find_put_contract.return_value = "NVDA251121P00108000"
    mock_client.sell_option.return_value = {"id": "123"}

    result = run(WheelBot(mock_client, roll_poll_interval=0))

    mock_client.cancel_order.assert_called_once_with("id-11")
    mock_client.sell_option.assert_called_once()
    assert result["action"] == "SELL_PUT"


def test_unconfirmed_cancel_places_nothing(mock_client):
    mock_client.get_open_nvda_orders.return_value = [order(age_minutes=11)]  # never clears

    result = run(WheelBot(mock_client, roll_poll_interval=0, roll_poll_timeout=0))

    assert result["action"] == "CANCEL_PENDING"
    mock_client.sell_option.assert_not_called()


def test_foreign_order_is_never_cancelled_and_blocks(mock_client):
    mock_client.get_open_nvda_orders.return_value = [order(client_order_id="manual-1", age_minutes=60)]

    result = run(WheelBot(mock_client))

    assert result["action"] == "WAIT_FOREIGN_ORDER"
    mock_client.cancel_order.assert_not_called()
    mock_client.sell_option.assert_not_called()


class FakeAccount:
    """Just enough of Alpaca to run the bot several times in a row: sell
    orders stay open (unfilled) until cancelled."""

    def __init__(self):
        self.open_orders = []
        self.submitted = []

    def get_open_nvda_orders(self):
        return list(self.open_orders)

    def cancel_order(self, order_id):
        self.open_orders = [o for o in self.open_orders if o.id != order_id]
        return True

    def sell_option(self, contract_symbol, limit_price):
        o = order(symbol=contract_symbol)
        o.id = f"order-{len(self.submitted)}"
        self.open_orders.append(o)
        self.submitted.append(o)
        return {"id": o.id}

    def get_nvda_stock_position(self):
        return False, 0, 0.0

    def get_open_nvda_options(self):
        return [], []

    def get_options_buying_power(self):
        return 50_000.0

    def get_nvda_quote(self):
        return quote(229.99, 230.01)

    def get_nvda_last_trade(self):
        return 230.00, datetime.now(timezone.utc)

    def find_put_contract(self, strike, expiry):
        return "NVDA251121P00207000"

    def get_option_quote(self, contract_symbol):
        return quote(0.55, 0.60)


def test_running_twice_never_creates_two_orders():
    account = FakeAccount()
    bot = WheelBot(account, roll_poll_interval=0)

    first, second = run(bot), run(bot)

    assert first["action"] == "SELL_PUT"
    assert second["action"] == "WAIT_OPEN_ORDER"
    assert len(account.submitted) == 1


def test_stale_order_is_replaced_not_duplicated():
    account = FakeAccount()
    bot = WheelBot(account, roll_poll_interval=0)
    run(bot)
    account.open_orders[0].submitted_at -= timedelta(minutes=15)  # unfilled for a while

    result = run(bot)

    assert result["action"] == "SELL_PUT"
    assert len(account.submitted) == 2
    assert [o.id for o in account.open_orders] == ["order-1"]  # old one cancelled


# --- bad prices: refuse to trade ---

def test_put_strike_uses_mid_not_ask(mock_client):
    # mid $111 → 10% below = $99.90 → $99. The ask ($111.50) would give $100.
    mock_client.get_nvda_quote.return_value = quote(110.50, 111.50)
    mock_client.find_put_contract.return_value = None

    run(WheelBot(mock_client))

    assert mock_client.find_put_contract.call_args.args[0] == 99.0


def test_no_put_when_nvda_price_is_stale(mock_client):
    mock_client.get_nvda_quote.return_value = quote(0.0, 0.0)
    mock_client.get_nvda_last_trade.return_value = (120.00, datetime.now(timezone.utc) - timedelta(hours=17))

    result = run(WheelBot(mock_client))

    assert result["action"] == "SKIP_BAD_QUOTE"
    mock_client.sell_option.assert_not_called()


def test_no_sale_when_option_spread_is_too_wide(mock_client):
    mock_client.find_put_contract.return_value = "NVDA251121P00108000"
    mock_client.get_option_quote.return_value = quote(0.30, 0.90)

    result = run(WheelBot(mock_client))

    assert result["action"] == "SKIP_BAD_QUOTE"
    mock_client.sell_option.assert_not_called()


def test_no_close_on_a_stale_option_quote(mock_client):
    mock_client.get_open_nvda_options.return_value = ([short_put()], [])
    mock_client.get_option_quote.return_value = quote(0.98, 1.02, age_seconds=900)

    result = run(WheelBot(mock_client))

    assert result["action"] == "HOLD"
    mock_client.buy_to_close.assert_not_called()


# --- $25k cap ---

def test_put_size_capped_at_25k_even_with_more_buying_power(mock_client):
    # NVDA $300 → 10% below = $270, but $25k only covers a $250 strike
    mock_client.get_options_buying_power.return_value = 100_000.00
    mock_client.get_nvda_quote.return_value = quote(299.99, 300.01)
    mock_client.find_put_contract.return_value = None

    run(WheelBot(mock_client))

    assert mock_client.find_put_contract.call_args.args[0] == 250.0
