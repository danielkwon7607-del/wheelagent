"""Quick research backtest of the NVDA wheel on real Alpaca option bars.

Throwaway research code (Phase 2 builds the real backtester). Daily
decisions at the close. Option prices are daily bar closes (last trade,
not bid/ask), so fills are close -/+ an assumed half-spread.
"""
import math
import os
import pickle
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
load_dotenv(os.path.join(HERE, "..", ".env.paper"))

# ---------- data ----------
_stock_split = pd.read_pickle(os.path.join(DATA, "stock_split.pkl"))
_stock_all = pd.read_pickle(os.path.join(DATA, "stock_all.pkl"))


def _series(df, sym, col="close"):
    s = df.loc[sym][col].copy()
    s.index = pd.to_datetime(s.index).tz_convert("America/New_York").date
    return s


NVDA = _series(_stock_split, "NVDA")
NVDA_OPEN = _series(_stock_split, "NVDA", "open")
NVDA_TR = _series(_stock_all, "NVDA")
SPY_TR = _series(_stock_all, "SPY")
COST_TR = _series(_stock_all, "COST")
_tb = pd.read_pickle(os.path.join(DATA, "tbill.pkl"))
TBILL = pd.Series(_tb.rate.values / 100, index=pd.to_datetime(_tb.date).dt.date)


def tbill_rate(d):
    s = TBILL.loc[:d]
    return float(s.iloc[-1]) if len(s) else 0.0


# ---------- option chain with disk cache ----------
_CACHE_F = os.path.join(DATA, "opt_cache.pkl")
_cache = pickle.load(open(_CACHE_F, "rb")) if os.path.exists(_CACHE_F) else {"contracts": {}, "bars": {}}
_dirty = [0]
_clients = {}


def _trading():
    if "t" not in _clients:
        from alpaca.trading.client import TradingClient
        _clients["t"] = TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=True)
    return _clients["t"]


def _optdata():
    if "o" not in _clients:
        from alpaca.data.historical.option import OptionHistoricalDataClient
        _clients["o"] = OptionHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
    return _clients["o"]


def save_cache():
    if _dirty[0]:
        pickle.dump(_cache, open(_CACHE_F, "wb"))
        _dirty[0] = 0


def contracts(expiry: date, kind: str) -> dict:
    """{strike: symbol} for NVDA contracts with this expiry (active or expired)."""
    key = (expiry, kind)
    if key not in _cache["contracts"]:
        from alpaca.trading.requests import GetOptionContractsRequest
        from alpaca.trading.enums import ContractType, AssetStatus
        out = {}
        for status in (AssetStatus.INACTIVE, AssetStatus.ACTIVE):
            req = GetOptionContractsRequest(underlying_symbols=["NVDA"], expiration_date=expiry,
                                            type=ContractType.PUT if kind == "P" else ContractType.CALL,
                                            status=status, limit=10000)
            for c in _trading().get_option_contracts(req).option_contracts:
                out[float(c.strike_price)] = c.symbol
        _cache["contracts"][key] = out
        _dirty[0] += 1
    return _cache["contracts"][key]


def bars(symbol: str) -> pd.Series:
    if symbol not in _cache["bars"]:
        from alpaca.data.requests import OptionBarsRequest
        from alpaca.data.timeframe import TimeFrame
        exp = datetime.strptime(symbol[4:10], "%y%m%d")
        df = _optdata().get_option_bars(OptionBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day,
                                                          start=exp - timedelta(days=120),
                                                          end=min(exp + timedelta(days=1), datetime.now() - timedelta(minutes=20)))).df
        if len(df):
            s = df["close"].droplevel(0)
            s.index = pd.to_datetime(s.index).tz_convert("America/New_York").date
        else:
            s = pd.Series(dtype=float)
        _cache["bars"][symbol] = s
        _dirty[0] += 1
        if _dirty[0] % 50 == 0:
            save_cache()
    return _cache["bars"][symbol]


def expiry_on_or_after(d: date, kind: str) -> tuple[date, dict] | tuple[None, None]:
    """First listed NVDA expiry on the Friday on/after d (Thursday if Friday is a holiday)."""
    f = d + timedelta(days=(4 - d.weekday()) % 7)
    for cand in (f, f - timedelta(days=1), f + timedelta(days=7)):
        c = contracts(cand, kind)
        if c:
            return cand, c
    return None, None


# ---------- Black-Scholes helpers ----------
def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(kind, S, K, T, r, vol):
    if T <= 0 or vol <= 0:
        return max(0.0, (K - S) if kind == "P" else (S - K))
    d1 = (math.log(S / K) + (r + vol * vol / 2) * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    if kind == "C":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def bs_delta(kind, S, K, T, r, vol):
    d1 = (math.log(S / K) + (r + vol * vol / 2) * T) / (vol * math.sqrt(T))
    return _ncdf(d1) - (1 if kind == "P" else 0)


def implied_vol(kind, price, S, K, T, r):
    lo, hi = 0.01, 5.0
    if price <= max(0.0, (K - S) if kind == "P" else (S - K)) + 1e-6:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs_price(kind, S, K, T, r, mid) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


# ---------- strategy ----------
@dataclass
class Rules:
    put_otm: float = 0.10          # put strike <= spot * (1 - put_otm)
    dte_min: int = 14              # first Friday at least this many days out
    take_profit: float | None = 0.50   # close when option <= (1 - tp) * entry; None = hold to expiry
    call_mode: str = "basis"       # "basis": strike >= cost_basis*(1+call_otm); "spot": >= spot*(1+call_otm)
    call_otm: float = 0.10
    half_spread: float = 0.03      # fill = close -/+ this fraction of price (min $0.01)
    fee: float = 0.05              # $ per contract per side, regulatory fees
    cap: float = 25_000.0
    min_premium: float = 0.05
    skip_earnings: bool = False    # don't open if expiry would cross an earnings date
    name: str = ""


@dataclass
class Short:
    symbol: str
    kind: str
    strike: float
    expiry: date
    entry: float
    opened: date
    last: float
    iv: float | None = None
    delta: float | None = None


EARNINGS_8K = pd.read_pickle(os.path.join(DATA, "earnings_8k.pkl"))  # SEC 8-K item 2.02 filing dates


def earnings_days(start: date, end: date) -> list[date]:
    """Earnings reaction days: first trading day after each 8-K 2.02 filing
    (NVDA reports after the close). Next one (~Nov 18 2026) added by hand."""
    out = []
    for f in list(EARNINGS_8K) + [date(2026, 11, 18)]:
        nxt = [d for d in NVDA.index if d > f][:1]
        out.append(nxt[0] if nxt else f + timedelta(days=1))
    return [d for d in out if start <= d <= end]


def run(rules: Rules, start: date, end: date, verbose=False):
    days = [d for d in NVDA.index if start <= d <= end]
    earn = earnings_days(start - timedelta(days=60), end + timedelta(days=60))
    cash = rules.cap
    shares, basis = 0, 0.0
    short: Short | None = None
    equity, states, trades, stuck_days = [], [], [], 0
    prev = None

    def fill_sell(px):
        return max(0.0, px - max(0.01, px * rules.half_spread)) - rules.fee / 100

    def fill_buy(px):
        return px + max(0.01, px * rules.half_spread) + rules.fee / 100

    def pick(kind, d, S, target):
        exp_from = d + timedelta(days=rules.dte_min)
        expiry, chain = expiry_on_or_after(exp_from, kind)
        if not chain:
            return None
        if rules.skip_earnings and any(d < e <= expiry for e in earn):
            return "EARNINGS"
        strikes = sorted(chain)
        if kind == "P":
            cands = [k for k in strikes if k <= target][::-1][:4]
        else:
            cands = [k for k in strikes if k >= target][:4]
        for k in cands:
            b = bars(chain[k])
            if d in b.index and b[d] >= rules.min_premium:
                return chain[k], k, expiry, float(b[d])
        return None

    for d in days:
        S = float(NVDA[d])
        if prev is not None:
            cash *= 1 + tbill_rate(prev) * (d - prev).days / 360
        prev = d
        # manage the open short
        if short is not None:
            b = bars(short.symbol)
            px = float(b[d]) if d in b.index else None
            if px is not None:
                short.last = px
            if d >= short.expiry:
                intrinsic = max(0.0, short.strike - S) if short.kind == "P" else max(0.0, S - short.strike)
                if short.kind == "P" and S < short.strike:
                    cash -= short.strike * 100
                    shares, basis = 100, short.strike
                    outcome = "assigned"
                elif short.kind == "C" and S > short.strike:
                    cash += short.strike * 100
                    trades.append(dict(kind="S", opened=None, closed=d, pnl=(short.strike - basis) * 100, outcome="called_away"))
                    shares, basis = 0, 0.0
                    outcome = "called_away"
                else:
                    outcome = "expired"
                trades.append(dict(kind=short.kind, symbol=short.symbol, opened=short.opened, closed=d, strike=short.strike,
                                   entry=short.entry, exit=intrinsic, pnl=(short.entry - intrinsic) * 100, outcome=outcome,
                                   iv=short.iv, delta=short.delta, spot_open=None,
                                   crossed_earnings=any(short.opened < e <= short.expiry for e in earn)))
                short = None
            elif rules.take_profit is not None and px is not None and px <= short.entry * (1 - rules.take_profit):
                cost = fill_buy(px)
                cash -= cost * 100
                trades.append(dict(kind=short.kind, symbol=short.symbol, opened=short.opened, closed=d, strike=short.strike,
                                   entry=short.entry, exit=cost, pnl=(short.entry - cost) * 100, outcome="take_profit",
                                   iv=short.iv, delta=short.delta,
                                   crossed_earnings=any(short.opened < e <= short.expiry for e in earn)))
                short = None
        # open the next short (same day, like the bot's roll)
        if short is None:
            if shares == 0:
                capital = min(cash, rules.cap)
                target = min(math.floor(S * (1 - rules.put_otm)), math.floor(capital / 100))
                p = pick("P", d, S, target)
                kind = "P"
            else:
                ref = basis if rules.call_mode == "basis" else S
                target = math.ceil(round(ref * (1 + rules.call_otm), 10))
                p = pick("C", d, S, target)
                kind = "C"
                if p is None:
                    stuck_days += 1
            if p and p != "EARNINGS":
                sym, k, expiry, px = p
                prem = fill_sell(px)
                T = max((expiry - d).days, 1) / 365
                iv = implied_vol(kind, px, S, k, T, tbill_rate(d))
                delta = bs_delta(kind, S, k, T, tbill_rate(d), iv) if iv else None
                cash += prem * 100
                short = Short(sym, kind, k, expiry, prem, d, px, iv, delta)
        # mark to market
        opt_val = short.last * 100 if short else 0.0
        equity.append((d, cash + shares * S - opt_val))
        states.append((d, "SHORT_CALL" if (short and short.kind == "C") else "LONG" if shares else "SHORT_PUT" if short else "CASH",
                       shares > 0 and S < basis * 0.8))
    save_cache()
    eq = pd.Series(dict(equity))
    st = pd.DataFrame(states, columns=["d", "state", "deep_under"]).set_index("d")
    return eq, pd.DataFrame(trades), st, stuck_days


# ---------- metrics ----------
def tbill_curve(days, start_value=25_000.0):
    vals, v, prev = [], start_value, None
    for d in days:
        if prev is not None:
            v *= 1 + tbill_rate(prev) * (d - prev).days / 360
        prev = d
        vals.append(v)
    return pd.Series(vals, index=days)


def buy_hold(series, days, start_value=25_000.0):
    s = series.loc[days[0]:days[-1]]
    return start_value * s / s.iloc[0]


def metrics(eq: pd.Series, rf_curve: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    rf = rf_curve.pct_change().reindex(r.index).fillna(0)
    ex = r - rf
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = eq / eq.cummax() - 1
    trough = dd.idxmin()
    peak = eq.loc[:trough].idxmax()
    rec = eq.loc[trough:][eq.loc[trough:] >= eq.loc[peak]]
    rec_days = (rec.index[0] - peak).days if len(rec) else None
    m = eq.copy(); m.index = pd.to_datetime(m.index)
    monthly = m.resample("ME").last().pct_change().dropna()
    downside = ex[ex < 0].std() * math.sqrt(252)
    return dict(
        total=eq.iloc[-1] / eq.iloc[0] - 1, cagr=cagr, vol=r.std() * math.sqrt(252),
        sharpe=ex.mean() / ex.std() * math.sqrt(252) if ex.std() > 0 else float("nan"),
        sortino=ex.mean() * 252 / downside if downside > 0 else float("nan"),
        max_dd=dd.min(), dd_peak=peak, dd_trough=trough, recovery_days=rec_days,
        worst_month=monthly.min(), cvar5_daily=r[r <= r.quantile(0.05)].mean(),
    )
