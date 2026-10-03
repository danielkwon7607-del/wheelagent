"""Long-history wheel simulation (2016-2026) with MODELLED option prices.

APPROXIMATION: no real option prices before 2024. Prices come from
Black-Scholes with IV = multiplier x blend(20d, 60d realized vol),
multipliers calibrated on 2024-26 real NVDA option trades (puts 1.13,
calls 1.00, x1.4 / x1.1 when the option's life spans earnings). Misses
day-to-day skew changes and real bid/ask. Fully invested: position size
is all equity (fractional contracts), so it tests the strategy, not the
one-contract bot.
"""
import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from wheel_research import NVDA, bs_price, bs_delta, earnings_days, tbill_rate

RET = np.log(NVDA / NVDA.shift(1))
RV = 0.5 * RET.rolling(20).std() * math.sqrt(252) + 0.5 * RET.rolling(60).std() * math.sqrt(252)
DAYS = list(NVDA.index)
MA200 = NVDA.rolling(200).mean()


@dataclass
class Sim:
    put_otm: float = 0.10
    dte_min: int = 14
    take_profit: float | None = 0.50
    call_mode: str = "basis"        # "basis" or "spot"
    call_otm: float = 0.10
    skip_earnings: bool = False
    trend_filter: bool = False      # no new puts while NVDA < 200-day average
    put_mult: float = 1.13
    call_mult: float = 1.00
    earn_mult_put: float = 1.40
    earn_mult_call: float = 1.10
    half_spread: float = 0.03
    min_delta: float = 0.02         # deeper OTM than this has no real bid: can't sell
    name: str = ""


def _expiry(d: date, dte_min: int) -> date:
    f = d + timedelta(days=dte_min)
    f += timedelta(days=(4 - f.weekday()) % 7)
    while f not in NVDA.index and f > d:   # holiday Friday -> Thursday
        f -= timedelta(days=1)
    return f


def simulate(cfg: Sim, start: date, end: date, capital: float = 25_000.0):
    days = [d for d in DAYS if start <= d <= end]
    earn = earnings_days(start - timedelta(days=90), end + timedelta(days=90))
    cash, q, basis = capital, 0.0, 0.0
    short = None   # dict(kind, K, exp, entry, qty)
    eq, rows, legs = [], [], []
    prev = None
    interest = 0.0

    def iv(kind, d, exp):
        crosses = any(d < e <= exp for e in earn)
        m = cfg.put_mult * (cfg.earn_mult_put if crosses else 1) if kind == "P" else cfg.call_mult * (cfg.earn_mult_call if crosses else 1)
        return m * float(RV[d]), crosses

    for d in days:
        S = float(NVDA[d]); r = tbill_rate(d)
        if prev is not None:
            gain = cash * tbill_rate(prev) * (d - prev).days / 360
            cash += gain; interest += gain
        prev = d
        if short:
            T = max((short["exp"] - d).days, 0) / 365
            vol, _ = iv(short["kind"], d, short["exp"])
            mark = bs_price(short["kind"], S, short["K"], T, r, vol)
            if d >= short["exp"]:
                intrinsic = max(0.0, short["K"] - S) if short["kind"] == "P" else max(0.0, S - short["K"])
                outcome = "expired"
                if short["kind"] == "P" and S < short["K"]:
                    cash -= short["K"] * short["qty"]; q, basis = short["qty"], short["K"]; outcome = "assigned"
                elif short["kind"] == "C" and S > short["K"]:
                    cash += short["K"] * short["qty"]; legs.append((d, (short["K"] - basis) * q)); q, basis = 0.0, 0.0; outcome = "called_away"
                rows.append(dict(kind=short["kind"], opened=short["opened"], closed=d, pnl=(short["entry"] - intrinsic) * short["qty"],
                                 notional=short["K"] * short["qty"], outcome=outcome, crosses=short["crosses"]))
                short = None
            elif cfg.take_profit is not None and mark <= short["entry"] * (1 - cfg.take_profit):
                cost = mark * (1 + cfg.half_spread)
                cash -= cost * short["qty"]
                rows.append(dict(kind=short["kind"], opened=short["opened"], closed=d, pnl=(short["entry"] - cost) * short["qty"],
                                 notional=short["K"] * short["qty"], outcome="take_profit", crosses=short["crosses"]))
                short = None
            else:
                short["mark"] = mark
        if short is None and d != days[-1]:
            exp = _expiry(d, cfg.dte_min)
            T = max((exp - d).days, 1) / 365
            if q == 0:
                ok = not (cfg.trend_filter and S < float(MA200[d]))
                if cfg.skip_earnings and any(d < e <= exp for e in earn):
                    ok = False
                if ok:
                    K = S * (1 - cfg.put_otm)
                    vol, crosses = iv("P", d, exp)
                    if abs(bs_delta("P", S, K, T, r, vol)) >= cfg.min_delta:
                        px = bs_price("P", S, K, T, r, vol) * (1 - cfg.half_spread)
                        qty = cash / K
                        cash += px * qty
                        short = dict(kind="P", K=K, exp=exp, entry=px, qty=qty, opened=d, mark=px / (1 - cfg.half_spread), crosses=crosses)
            else:
                ref = basis if cfg.call_mode == "basis" else S
                K = ref * (1 + cfg.call_otm)
                vol, crosses = iv("C", d, exp)
                if cfg.skip_earnings and any(d < e <= exp for e in earn):
                    pass
                elif bs_delta("C", S, K, T, r, vol) >= cfg.min_delta:
                    px = bs_price("C", S, K, T, r, vol) * (1 - cfg.half_spread)
                    cash += px * q
                    short = dict(kind="C", K=K, exp=exp, entry=px, qty=q, opened=d, mark=px / (1 - cfg.half_spread), crosses=crosses)
        opt = short["mark"] * short["qty"] if short else 0.0
        state = "SHORT_PUT" if (short and short["kind"] == "P") else ("SHORT_CALL" if short else ("SHARES_NO_CALL" if q else "CASH"))
        eq.append((d, cash + q * S - opt, state, q > 0 and S < basis * 0.8))
    e = pd.DataFrame(eq, columns=["d", "equity", "state", "deep_under"]).set_index("d")
    return e, pd.DataFrame(rows), legs, interest
