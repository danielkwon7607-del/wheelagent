import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderSide, PositionIntent
from alpaca_client import AlpacaClient
from strategy import BOT_ORDER_PREFIX, Quote

NOW = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2")


@pytest.fixture
def client(mock_env):
    with patch("alpaca_client.TradingClient"), \
         patch("alpaca_client.StockHistoricalDataClient"), \
         patch("alpaca_client.OptionHistoricalDataClient"):
        return AlpacaClient()


def test_get_buying_power(client):
    client._trading.get_account.return_value = MagicMock(buying_power="9500.00")
    result = client.get_buying_power()
    assert result == 9500.00


def test_get_nvda_quote(client):
    mock_quote = MagicMock(bid_price=125.40, ask_price=125.50, timestamp=NOW)
    client._data.get_stock_latest_quote.return_value = {"NVDA": mock_quote}
    assert client.get_nvda_quote() == Quote(125.40, 125.50, NOW)


def test_get_nvda_last_trade(client):
    client._data.get_stock_latest_trade.return_value = {"NVDA": MagicMock(price=125.45, timestamp=NOW)}
    assert client.get_nvda_last_trade() == (125.45, NOW)


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


def test_get_option_quote_returns_bid_ask_and_time(client):
    mock_quote = MagicMock(bid_price=1.80, ask_price=2.20, timestamp=NOW)
    client._option_data.get_option_latest_quote.return_value = {"NVDA251121P00108000": mock_quote}
    result = client.get_option_quote("NVDA251121P00108000")
    assert result == Quote(1.80, 2.20, NOW)
    assert result.mid == 2.00


def test_buy_to_close_is_a_tagged_limit_order(client):
    client._trading.submit_order.return_value = MagicMock(id="789")
    result = client.buy_to_close("NVDA251121P00108000", 1, limit_price=0.27)
    order = client._trading.submit_order.call_args.args[0]
    assert order.side == OrderSide.BUY
    assert order.limit_price == 0.27
    assert order.position_intent == PositionIntent.BUY_TO_CLOSE
    assert order.client_order_id.startswith(BOT_ORDER_PREFIX)
    assert result["client_order_id"] == order.client_order_id
    client._trading.close_position.assert_not_called()  # never a market close


def test_sell_option_is_a_tagged_sell_to_open(client):
    client._trading.submit_order.return_value = MagicMock(id="123")
    client.sell_option("NVDA251121P00108000", limit_price=0.55)
    order = client._trading.submit_order.call_args.args[0]
    assert order.side == OrderSide.SELL
    assert order.position_intent == PositionIntent.SELL_TO_OPEN
    assert order.client_order_id.startswith(BOT_ORDER_PREFIX)


def test_get_open_nvda_orders_ignores_other_symbols(client):
    orders = [MagicMock(symbol=s) for s in ("NVDA", "NVDA261016P00207500", "AAPL", "NVDL")]
    client._trading.get_orders.return_value = orders
    assert [o.symbol for o in client.get_open_nvda_orders()] == ["NVDA", "NVDA261016P00207500"]


def test_cancel_order_returns_false_when_refused(client):
    client._trading.cancel_order_by_id.side_effect = APIError('{"message": "order is not cancelable"}')
    assert client.cancel_order("abc") is False
