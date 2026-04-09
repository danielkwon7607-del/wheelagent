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
