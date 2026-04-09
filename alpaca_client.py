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
