"""Read-only preview: which put each strike rule would sell right now.
Places no orders. Assumes the full $25k cap is free (as if no put were open).

Run: python preview_strike.py
"""
import math
from datetime import datetime, timezone

from alpaca_client import AlpacaClient
from strategy import (CAPITAL_CAP, PUT_DELTA, get_put_strike, pick_put_by_delta, put_delta, put_expiry,
                      put_implied_vol, quote_problem, today_et, underlying_price, years_to_expiry)


def main():
    client, now = AlpacaClient(), datetime.now(timezone.utc)
    spot = underlying_price(client.get_nvda_quote(), *client.get_nvda_last_trade(), now)
    if spot is None:
        print("No trustworthy NVDA price right now (market closed or quotes stale).")
        return
    max_strike = math.floor(CAPITAL_CAP / 100)
    print(f"NVDA ${spot:.2f}, capital ${CAPITAL_CAP:,.0f} (max strike ${max_strike})\n")
    for days in (14, 30):
        expiry, why = put_expiry(today_et(), days)
        if expiry is None:
            print(f"{days}+ days: no put — {why}\n")
            continue
        if why != "normal":
            print(f"({why})")
        chain = client.get_put_chain(expiry, math.floor(spot * 0.70), math.ceil(spot))
        if not chain:
            print(f"{days}+ days: no chain found for {expiry}")
            continue
        exp = chain[0].expiry
        print(f"{days}+ days out (expiry {exp}), {len(chain)} puts quoted:")
        # the original rule: highest strike at or below 10% under the price
        target = get_put_strike(spot, CAPITAL_CAP)
        otm = max((o for o in chain if o.strike <= target), key=lambda o: o.strike, default=None)
        if otm:
            years = years_to_expiry(exp, now)
            vol = put_implied_vol(otm.quote.mid, spot, otm.strike, years)
            d = abs(put_delta(spot, otm.strike, years, vol)) if vol else float("nan")
            print(f"  10% rule : ${otm.strike:g} put, mid ${otm.quote.mid:.2f} (${otm.quote.mid * 100:.0f}), delta {d:.2f}, "
                  f"OI {otm.open_interest}, quote {'ok' if not quote_problem(otm.quote, now) else quote_problem(otm.quote, now)}")
        pick, d, why = pick_put_by_delta(chain, spot, max_strike, now)
        if pick:
            print(f"  delta {PUT_DELTA:.2f}: ${pick.strike:g} put, mid ${pick.quote.mid:.2f} (${pick.quote.mid * 100:.0f}), delta {d:.2f}, "
                  f"OI {pick.open_interest}, {(1 - pick.strike / spot) * 100:.1f}% below the price — {why}")
        else:
            print(f"  delta {PUT_DELTA:.2f}: nothing to sell — {why}")
        print()


if __name__ == "__main__":
    main()
