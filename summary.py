"""
Daily Summary — run after the close (1pm PT / 4pm ET)
Prints P&L, positions, and premiums collected today.
"""
import logging
from datetime import datetime, timezone
from alpaca_client import AlpacaClient
from logging_setup import now_pacific, setup_logging
from strategy import underlying_price

setup_logging("%(asctime)s %(message)s")
log = logging.getLogger(__name__)


def run_summary():
    client = AlpacaClient()
    account = client._trading.get_account()

    buying_power = float(account.buying_power)
    portfolio_value = float(account.portfolio_value)
    equity = float(account.equity)

    has_shares, share_qty, cost_basis = client.get_nvda_stock_position()
    open_puts, open_calls = client.get_open_nvda_options()

    print("\n" + "="*50)
    print(f"  WHEEL BOT DAILY SUMMARY - {now_pacific():%Y-%m-%d %I:%M%p %Z}")
    print("="*50)
    print(f"  Portfolio Value : ${portfolio_value:,.2f}")
    print(f"  Buying Power    : ${buying_power:,.2f}")
    print(f"  Equity          : ${equity:,.2f}")
    print("-"*50)
    if has_shares:
        last_price, last_time = client.get_nvda_last_trade()
        nvda_price = underlying_price(client.get_nvda_quote(), last_price, last_time, datetime.now(timezone.utc))
        print(f"  NVDA Shares     : {share_qty} @ ${cost_basis:.2f} cost basis")
        if nvda_price is None:
            print("  Unrealized P&L  : n/a (no fresh NVDA price)")
        else:
            print(f"  Unrealized P&L  : ${(nvda_price - cost_basis) * share_qty:+.2f}")
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
