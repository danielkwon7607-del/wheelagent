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
