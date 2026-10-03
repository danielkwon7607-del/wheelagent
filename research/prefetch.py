from datetime import date, datetime, timedelta
import pandas as pd
import wheel_research as w
from alpaca.data.requests import OptionBarsRequest
from alpaca.data.timeframe import TimeFrame
fri = date(2024, 6, 14)
expiries = []
while fri <= date(2026, 11, 27):
    for cand in (fri, fri - timedelta(days=1)):
        if w.contracts(cand, "P"):
            expiries.append(cand); break
    fri += timedelta(days=7)
w.save_cache()
todo = 0
for E in expiries:
    win = w.NVDA[(w.NVDA.index >= E - timedelta(days=60)) & (w.NVDA.index <= min(E, date(2026, 10, 2)))]
    if not len(win): continue
    lo, hi = float(win.min()), float(win.max())
    syms = [s for k, s in w.contracts(E, "P").items() if 0.75 * lo <= k <= hi]
    syms += [s for k, s in w.contracts(E, "C").items() if 0.9 * lo <= k <= 1.4 * hi]
    syms = [s for s in syms if s not in w._cache["bars"]]
    for i in range(0, len(syms), 100):
        batch = syms[i:i + 100]
        exp = datetime.combine(E, datetime.min.time())
        df = w._optdata().get_option_bars(OptionBarsRequest(symbol_or_symbols=batch, timeframe=TimeFrame.Day, start=exp - timedelta(days=120),
                                                            end=min(exp + timedelta(days=1), datetime.now() - timedelta(minutes=20)))).df
        got = {}
        if len(df):
            for sym, g in df["close"].groupby(level=0):
                s = g.droplevel(0); s.index = pd.to_datetime(s.index).tz_convert("America/New_York").date; got[sym] = s
        for sym in batch:
            w._cache["bars"][sym] = got.get(sym, pd.Series(dtype=float))
        todo += len(batch); w._dirty[0] += 1
    w.save_cache()
print("expiries", len(expiries), "| fetched", todo, "| cached contracts", len(w._cache["bars"]))
