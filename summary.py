"""
Daily Summary — run at 4pm ET via /schedule
Prints P&L, positions, and premiums collected today.
"""
import os
import logging
from datetime import date
from alpaca_client import AlpacaClient

LOG_DIR = os.path.join(os.path.expanduser("~"), "wheel_bot_logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "summary.log")),
        logging.StreamHandler(),
    ],
)
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
    print(f"  WHEEL BOT DAILY SUMMARY - {date.today()}")
    print("="*50)
    print(f"  Portfolio Value : ${portfolio_value:,.2f}")
    print(f"  Buying Power    : ${buying_power:,.2f}")
    print(f"  Equity          : ${equity:,.2f}")
    print("-"*50)
    if has_shares:
        nvda_price = client.get_nvda_price()
        unrealized = (nvda_price - cost_basis) * share_qty
        print(f"  NVDA Shares     : {share_qty} @ ${cost_basis:.2f} cost basis")
        print(f"  Unrealized P&L  : ${unrealized:+.2f}")
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
