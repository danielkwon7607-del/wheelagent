"""
Wheel Strategy Bot — NVDA, Alpaca Paper Trading
Run this file directly: python wheel_bot.py
Runs on GitHub Actions every 15 min during market hours (no PC needed).
"""
import logging
import time
from datetime import datetime, timezone

from alpaca_client import AlpacaClient
from strategy import (
    available_capital,
    determine_state,
    get_call_strike,
    get_put_strike,
    get_target_expiry,
    is_bot_order,
    is_market_hours,
    is_order_stale,
    occ_strike,
    quote_problem,
    round_to_tick,
    should_close_early,
    underlying_price,
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
        # How long to wait for a close (or a cancel) to confirm before acting
        # on it. If it doesn't confirm in time, the next scheduled run picks
        # up from whatever state the account is in — no trade is ever lost.
        self.roll_poll_interval = roll_poll_interval
        self.roll_poll_timeout = roll_poll_timeout

    def run(self) -> dict:
        if not is_market_hours():
            log.info("Market closed — no action taken.")
            return {"action": "MARKET_CLOSED", "time": datetime.now().isoformat()}

        # Settle orders from earlier runs before reading positions, so a
        # working order is never mistaken for "no position" and duplicated.
        blocked = self._settle_open_orders()
        if blocked:
            return blocked

        has_shares, _, cost_basis = self.client.get_nvda_stock_position()
        open_puts, open_calls = self.client.get_open_nvda_options()

        state = determine_state(
            has_shares=has_shares,
            has_open_put=len(open_puts) > 0,
            has_open_call=len(open_calls) > 0,
        )
        log.info(f"State={state}")

        # SHORT_PUT / SHORT_CALL: take profit at 50% and immediately roll into the next play
        if state == "SHORT_PUT":
            return self._manage_short(open_puts[0], "put")
        if state == "SHORT_CALL":
            return self._manage_short(open_calls[0], "call")

        # LONG_SHARES: sell a covered call
        if state == "LONG_SHARES":
            return self._sell_covered_call(cost_basis)

        # NO_POSITION: sell a cash-secured put
        if state == "NO_POSITION":
            return self._sell_cash_secured_put()

        return {"action": "UNKNOWN_STATE", "state": state}

    def _settle_open_orders(self) -> dict | None:
        """Returns a result if an open order means this run must not trade.
        A bot order still working is left alone; once stale it is cancelled
        so this run can re-price it. Orders the bot didn't place are never
        touched, and they block the bot until they are gone."""
        orders = self.client.get_open_nvda_orders()
        if not orders:
            return None

        foreign = [o for o in orders if not is_bot_order(o.client_order_id)]
        if foreign:
            log.warning(f"Open NVDA order(s) not placed by the bot: {[o.symbol for o in foreign]} — no action.")
            return {"action": "WAIT_FOREIGN_ORDER", "orders": [str(o.id) for o in foreign]}

        now = datetime.now(timezone.utc)
        working = [o for o in orders if not is_order_stale(o.submitted_at or o.created_at, now)]
        if working:
            log.info(f"Order still working: {[o.symbol for o in working]} — waiting for it.")
            return {"action": "WAIT_OPEN_ORDER", "orders": [str(o.id) for o in working]}

        for o in orders:
            cancelled = self.client.cancel_order(o.id)
            note = "" if cancelled else " — refused, it may have just filled"
            log.info(f"CANCEL stale order {o.id} {o.side} {o.symbol} @ ${o.limit_price}{note}")
        if not self._wait_until(lambda: not self.client.get_open_nvda_orders()):
            log.info("Cancel not confirmed yet — next run will re-check.")
            return {"action": "CANCEL_PENDING", "orders": [str(o.id) for o in orders]}
        return None

    def _manage_short(self, position, kind: str) -> dict:
        quote = self.client.get_option_quote(position.symbol)
        problem = quote_problem(quote, datetime.now(timezone.utc))
        if problem:
            log.warning(f"HOLD {kind} {position.symbol} — can't trust the quote: {problem}")
            return {"action": "HOLD", "symbol": position.symbol, "reason": problem}
        premium_received = float(position.avg_entry_price)
        if should_close_early(premium_received, quote.mid):
            return self._close_and_roll(position, kind, quote.mid)
        log.info(f"HOLD {kind} {position.symbol} — current=${quote.mid:.2f}, received=${premium_received:.2f}")
        return {"action": "HOLD", "symbol": position.symbol}

    def _close_and_roll(self, position, kind: str, mid: float) -> dict:
        """Take profit on a contract at 50%, then immediately deploy the freed
        capital into the next play — higher volume, more premium collected.
        If the close hasn't filled by the time we're ready to roll, the next
        scheduled run opens the play instead (nothing is lost)."""
        limit = round_to_tick(mid)
        qty = abs(int(float(position.qty)))
        result = self.client.buy_to_close(position.symbol, qty, limit_price=limit)
        log.info(f"CLOSE_EARLY {kind} {position.symbol} @ ${limit:.2f} limit — 50% profit reached. Order: {result}")

        if self._wait_until(lambda: not self._is_open(position.symbol)):
            opened = self._open_next_play()
            log.info(f"ROLL into next play: {opened}")
            return {"action": "CLOSE_AND_ROLL", "closed": result, "opened": opened}

        log.info(f"Close of {position.symbol} not confirmed yet — next run will open the next play.")
        return {"action": "CLOSE_EARLY", "detail": result}

    def _is_open(self, symbol: str) -> bool:
        open_puts, open_calls = self.client.get_open_nvda_options()
        return any(p.symbol == symbol for p in [*open_puts, *open_calls])

    def _wait_until(self, condition) -> bool:
        """Poll until condition() is true or the timeout passes."""
        deadline = time.monotonic() + self.roll_poll_timeout
        while True:
            if condition():
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
        return self._sell_cash_secured_put()

    def _nvda_price(self) -> float | None:
        quote = self.client.get_nvda_quote()
        last_price, last_time = self.client.get_nvda_last_trade()
        return underlying_price(quote, last_price, last_time, datetime.now(timezone.utc))

    def _available_capital(self) -> float:
        """Options buying power, capped so the bot never commits more than
        $25k in total (put collateral plus shares held)."""
        options_buying_power = self.client.get_options_buying_power()
        _, share_qty, cost_basis = self.client.get_nvda_stock_position()
        open_puts, _ = self.client.get_open_nvda_options()
        in_use = share_qty * cost_basis + sum(
            occ_strike(p.symbol) * 100 * abs(int(float(p.qty))) for p in open_puts
        )
        return available_capital(options_buying_power, in_use)

    def _sell_cash_secured_put(self) -> dict:
        nvda_price = self._nvda_price()
        if nvda_price is None:
            log.warning("No trustworthy NVDA price (quote and last trade stale, zero, or junk) — not selling a put.")
            return {"action": "SKIP_BAD_QUOTE", "symbol": "NVDA"}
        capital = self._available_capital()
        strike = get_put_strike(nvda_price, capital)
        expiry = get_target_expiry()
        contract = self.client.find_put_contract(strike, expiry)
        if not contract:
            log.warning(f"No put contract found for strike=${strike}, expiry={expiry}, capital=${capital:.2f}")
            return {"action": "NO_CONTRACT", "strike": strike, "expiry": str(expiry)}
        return self._sell(contract, "put", f"strike=${strike}, expiry={expiry}, NVDA=${nvda_price:.2f}, capital=${capital:.2f}")

    def _sell_covered_call(self, cost_basis: float) -> dict:
        strike = get_call_strike(cost_basis)
        expiry = get_target_expiry()
        contract = self.client.find_call_contract(strike, expiry)
        if not contract:
            log.warning(f"No call contract found for strike=${strike}, expiry={expiry}")
            return {"action": "NO_CONTRACT", "strike": strike, "expiry": str(expiry)}
        return self._sell(contract, "call", f"strike=${strike}, expiry={expiry}")

    def _sell(self, contract: str, kind: str, detail: str) -> dict:
        quote = self.client.get_option_quote(contract)
        problem = quote_problem(quote, datetime.now(timezone.utc))
        if problem:
            log.warning(f"Not selling {kind} {contract} — {problem}")
            return {"action": "SKIP_BAD_QUOTE", "symbol": contract, "reason": problem}
        limit = round_to_tick(quote.mid)
        result = self.client.sell_option(contract, limit_price=limit)
        log.info(f"SELL_{kind.upper()} {contract} @ ${limit:.2f} | {detail}")
        return {"action": f"SELL_{kind.upper()}", "detail": result}


if __name__ == "__main__":
    bot = WheelBot()
    result = bot.run()
    print(f"\nResult: {result}")
