import os
import uuid
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    GetOrdersRequest,
    LimitOrderRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    OrderType,
    PositionIntent,
    QueryOrderStatus,
    TimeInForce,
    ContractType,
)
from alpaca.common.exceptions import APIError
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import (
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
    OptionLatestQuoteRequest,
)
from datetime import date, datetime, timedelta

from strategy import BOT_ORDER_PREFIX, Quote, is_nvda_symbol


load_dotenv(".env.paper")


class AlpacaClient:
    def __init__(self):
        key = os.environ["ALPACA_API_KEY"]
        secret = os.environ["ALPACA_SECRET_KEY"]
        self._trading = TradingClient(key, secret, paper=True)
        self._data = StockHistoricalDataClient(key, secret)
        self._option_data = OptionHistoricalDataClient(key, secret)

    def get_buying_power(self) -> float:
        account = self._trading.get_account()
        return float(account.buying_power)

    def get_options_buying_power(self) -> float:
        """Returns options-specific buying power — used to size cash-secured puts correctly."""
        account = self._trading.get_account()
        return float(account.options_buying_power)

    def get_nvda_quote(self) -> Quote:
        req = StockLatestQuoteRequest(symbol_or_symbols=["NVDA"])
        q = self._data.get_stock_latest_quote(req)["NVDA"]
        return Quote(float(q.bid_price), float(q.ask_price), q.timestamp)

    def get_nvda_last_trade(self) -> tuple[float, datetime]:
        """Returns (price, timestamp) of the latest NVDA trade."""
        req = StockLatestTradeRequest(symbol_or_symbols=["NVDA"])
        t = self._data.get_stock_latest_trade(req)["NVDA"]
        return float(t.price), t.timestamp

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
                underlying_symbols=["NVDA"],
                expiration_date=candidate_expiry,
                type=ContractType.PUT,
                strike_price_gte=str(min_strike),
                strike_price_lte=str(strike),
            )
            contracts = self._trading.get_option_contracts(req)
            if contracts.option_contracts:
                # Pick the highest strike at or below our target
                best = max(contracts.option_contracts, key=lambda c: float(c.strike_price))
                return best.symbol
        return None

    def find_call_contract(self, strike: float, expiry: date) -> str | None:
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
                underlying_symbols=["NVDA"],
                expiration_date=candidate_expiry,
                type=ContractType.CALL,
                strike_price_gte=str(strike),
                strike_price_lte=str(max_strike),
            )
            contracts = self._trading.get_option_contracts(req)
            if contracts.option_contracts:
                # Pick the lowest strike at or above our target
                best = min(contracts.option_contracts, key=lambda c: float(c.strike_price))
                return best.symbol
        return None

    def sell_option(self, contract_symbol: str, limit_price: float) -> dict:
        """Sell to open 1 option contract at a limit price."""
        return self._submit_limit(contract_symbol, 1, OrderSide.SELL, PositionIntent.SELL_TO_OPEN, limit_price)

    def buy_to_close(self, contract_symbol: str, qty: int, limit_price: float) -> dict:
        """Buy to close a short option at a limit price (never at market)."""
        return self._submit_limit(contract_symbol, qty, OrderSide.BUY, PositionIntent.BUY_TO_CLOSE, limit_price)

    def _submit_limit(self, symbol: str, qty: int, side: OrderSide, intent: PositionIntent, limit_price: float) -> dict:
        # Tagged so the bot can tell its own orders from manual ones.
        client_order_id = f"{BOT_ORDER_PREFIX}{uuid.uuid4().hex}"
        order = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
            position_intent=intent,
            client_order_id=client_order_id,
        )
        result = self._trading.submit_order(order)
        return {"id": str(result.id), "client_order_id": client_order_id, "symbol": symbol,
                "side": side.value, "limit_price": limit_price}

    def get_open_nvda_orders(self) -> list:
        """All open (unfilled, uncancelled) orders on NVDA stock or NVDA options."""
        orders = self._trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        return [o for o in orders if is_nvda_symbol(o.symbol or "")]

    def cancel_order(self, order_id) -> bool:
        """Returns False if Alpaca refused the cancel, e.g. the order just filled."""
        try:
            self._trading.cancel_order_by_id(order_id)
            return True
        except APIError:
            return False

    def get_option_quote(self, contract_symbol: str) -> Quote:
        req = OptionLatestQuoteRequest(symbol_or_symbols=[contract_symbol])
        q = self._option_data.get_option_latest_quote(req)[contract_symbol]
        return Quote(float(q.bid_price), float(q.ask_price), q.timestamp)
