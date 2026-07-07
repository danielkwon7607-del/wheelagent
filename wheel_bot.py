"""
Wheel Strategy Bot — NVDA, Alpaca Paper Trading
Run this file directly: python wheel_bot.py
Runs on GitHub Actions every 15 min during market hours (no PC needed).
"""
import logging
import time
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
        roll_poll_interval: float = 3.0,
        roll_poll_timeout: float = 30.0,
    ):
        self.client = client or AlpacaClient()
        # How long to wait for a profit-taking close to fill before rolling
        # into the next play. If it doesn't confirm in time, the next
        # scheduled run opens the play instead — no trade is ever lost.
        self.roll_poll_interval = roll_poll_interval
        self.roll_poll_timeout = roll_poll_timeout

    def run(self) -> dict:
        if not is_market_hours():
            log.info("Market closed — no action taken.")
            return {"action": "MARKET_CLOSED", "time": datetime.now().isoformat()}

        options_buying_power = self.client.get_options_buying_power()
        nvda_price = self.client.get_nvda_price()
        has_shares, share_qty, cost_basis = self.client.get_nvda_stock_position()
        open_puts, open_calls = self.client.get_open_nvda_options()

        state = determine_state(
            has_shares=has_shares,
            has_open_put=len(open_puts) > 0,
            has_open_call=len(open_calls) > 0,
        )
        log.info(f"State={state} | NVDA=${nvda_price:.2f} | OptionsBuyingPower=${options_buying_power:.2f}")

        # SHORT_PUT: take profit at 50% and immediately roll into the next play
        if state == "SHORT_PUT":
            put = open_puts[0]
            current_price = self.client.get_option_quote(put.symbol)
            premium_received = float(put.avg_entry_price)
            if should_close_early(premium_received, current_price):
                return self._close_and_roll(put, "put")
            log.info(f"HOLD put {put.symbol} — current=${current_price:.2f}, received=${premium_received:.2f}")
            return {"action": "HOLD", "symbol": put.symbol}

        # SHORT_CALL: take profit at 50% and immediately roll into the next play
        if state == "SHORT_CALL":
            call = open_calls[0]
            current_price = self.client.get_option_quote(call.symbol)
            premium_received = float(call.avg_entry_price)
            if should_close_early(premium_received, current_price):
                return self._close_and_roll(call, "call")
            log.info(f"HOLD call {call.symbol} — current=${current_price:.2f}, received=${premium_received:.2f}")
            return {"action": "HOLD", "symbol": call.symbol}

        # LONG_SHARES: sell a covered call
        if state == "LONG_SHARES":
            return self._sell_covered_call(cost_basis)

        # NO_POSITION: sell a cash-secured put
        if state == "NO_POSITION":
            return self._sell_cash_secured_put(nvda_price, options_buying_power)

        return {"action": "UNKNOWN_STATE", "state": state}

    def _close_and_roll(self, position, kind: str) -> dict:
        """Take profit on a contract at 50%, then immediately deploy the freed
        capital into the next play — higher volume, more premium collected.
        If the close hasn't filled by the time we're ready to roll, the next
        scheduled run opens the play instead (nothing is lost)."""
        result = self.client.close_option_position(position.symbol)
        log.info(f"CLOSE_EARLY {kind} {position.symbol} — 50% profit reached. Order: {result}")

        if self._wait_until_closed(position.symbol):
            opened = self._open_next_play()
            log.info(f"ROLL into next play: {opened}")
            return {"action": "CLOSE_AND_ROLL", "closed": result, "opened": opened}

        log.info(f"Close of {position.symbol} not confirmed yet — next run will open the next play.")
        return {"action": "CLOSE_EARLY", "detail": result}

    def _wait_until_closed(self, symbol: str) -> bool:
        """Poll until the given option position is gone (buy-to-close filled)."""
        deadline = time.monotonic() + self.roll_poll_timeout
        while True:
            open_puts, open_calls = self.client.get_open_nvda_options()
            still_open = any(p.symbol == symbol for p in [*open_puts, *open_calls])
            if not still_open:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.roll_poll_interval)

    def _open_next_play(self) -> dict:
        """Open the next wheel play based on current position:
        holding shares → sell a covered call; otherwise → sell a cash-secured put."""
        has_shares, _, cost_basis = self.client.get_nvda_stock_position()
        if has_shares:
            return self._sell_covered_call(cost_basis)
        nvda_price = self.client.get_nvda_price()
        options_buying_power = self.client.get_options_buying_power()
        return self._sell_cash_secured_put(nvda_price, options_buying_power)

    def _sell_cash_secured_put(self, nvda_price: float, options_buying_power: float) -> dict:
        strike = get_put_strike(nvda_price, options_buying_power)
        expiry = get_target_expiry()
        contract = self.client.find_put_contract(strike, expiry)
        if not contract:
            log.warning(f"No put contract found for strike=${strike}, expiry={expiry}")
            return {"action": "NO_CONTRACT", "strike": strike, "expiry": str(expiry)}
        quote = self.client.get_option_quote(contract)
        result = self.client.sell_option(contract, limit_price=quote)
        log.info(f"SELL_PUT {contract} @ ${quote:.2f} | strike=${strike}, expiry={expiry}")
        return {"action": "SELL_PUT", "detail": result}

    def _sell_covered_call(self, cost_basis: float) -> dict:
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


if __name__ == "__main__":
    bot = WheelBot()
    result = bot.run()
    print(f"\nResult: {result}")
