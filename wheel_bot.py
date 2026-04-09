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
