/* Wheel Lab stress tests, on top of engine.js. Used by the Stress test tab.
 *   Costs  - rerun a strategy at wider and wider spreads and find where it
 *            stops paying (vs the 8% goal, vs T-bills, vs its edge over the stock).
 *   Shocks - drop a gap or a crash into the real price history at hundreds of
 *            different dates and measure the damage. Model prices only: there
 *            are no real option prices for a path that never happened.
 * The luck tests are too heavy for a browser; lab/stress_null.js precomputes
 * them into stress.js.
 */
(function (root) {
  "use strict";
  const S = {};

  // ---------- costs ----------
  // Spread cost per fill, as a share of the option price (what you give up vs
  // the mid). The x-axis of the cost chart.
  S.SPREAD_STEPS = [0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50];
  // How much wider spreads get on wild days (top-10% volatility).
  S.WILD_STEPS = [1, 1.5, 2, 3, 4, 6, 8];

  // Measured half-spread in dollars for an option priced px, from today's
  // quotes bucketed by price ([[typical mid, median half-spread, count], ...]).
  S.halfSpreadAt = function (buckets, px) {
    if (!buckets || !buckets.length) return NaN;
    if (px <= buckets[0][0]) return Math.min(buckets[0][1], px);
    for (let j = 1; j < buckets.length; j++) {
      const [m1, h1] = buckets[j];
      if (px <= m1) { const [m0, h0] = buckets[j - 1]; return h0 + (h1 - h0) * (px - m0) / (m1 - m0); }
    }
    const [mL, hL] = buckets[buckets.length - 1];
    return px * hL / mL;
  };
  // What this strategy would pay at today's measured spreads: the
  // dollar-weighted half-spread of all its fills (every sale and every
  // buy-back; expiry and assignment have no spread), and the dollars that
  // adds up to. Needs a real-prices run.
  S.effectiveSpread = function (run, buckets) {
    let h = 0, p = 0;
    for (const t of run.trades) {
      const fills = [t.entry];
      if (t.outcome === "take_profit" || t.outcome === "loss_cut") fills.push(t.exit);
      for (const px of fills) if (px > 0) { h += S.halfSpreadAt(buckets, px) * t.qty; p += px * t.qty; }
    }
    return { pct: p > 0 ? h / p : NaN, dollars: h };
  };

  // Yearly return, Sharpe and alpha vs the stock at each step of one lever.
  S.costSweep = function (E, D, cfg, mode, tk, lever, steps, base) {
    return steps.map((x) => {
      const c = JSON.parse(JSON.stringify(cfg));
      if (lever === "wild") { c.halfSpread = base; c.stressSpread = x; } else c.halfSpread = x;
      const run = E.simulate(D, c, mode, tk), b = E.benchmarks(D, run.i0, run.i1, tk), last = run.len - 1;
      const m = E.metrics(D, run, run.eq, b.tbill, 0, last), cap = E.capm(run.eq, b.stock, b.tbill, 0, last);
      return { x, cagr: m.cagr, sharpe: m.sharpe, alpha: cap.alpha, trades: run.trades.length, income: (run.cashPremium + run.interest) / (m.years * 12) };
    });
  };
  // The lever value where `key` first falls below `level`, by linear
  // interpolation. 0 if it starts below; null if it never falls below.
  S.crossing = function (pts, key, level) {
    if (!(pts[0][key] >= level)) return 0;
    for (let j = 1; j < pts.length; j++) {
      const a = pts[j - 1], b = pts[j];
      if (b[key] < level) return a.x + (b.x - a.x) * (a[key] - level) / (a[key] - b[key]);
    }
    return null;
  };

  // ---------- shocks ----------
  // f = the extra daily price moves, applied on top of the real path from the
  // shock date on (so the real ups and downs still happen afterwards).
  const spread = (total, days) => Array(days).fill(Math.pow(1 + total, 1 / days));
  S.SHOCKS = [
    { id: "gap10", name: "−10% overnight", short: "−10% gap", f: [0.90], d: "A bad earnings report or downgrade: one overnight drop, no warning." },
    { id: "gap20", name: "−20% overnight", short: "−20% gap", f: [0.80], d: "A disaster earnings night. NVDA has moved −17% on a news day before." },
    { id: "double", name: "−20%, then −15%", short: "Double hit", f: [0.80, ...Array(20).fill(1), 0.85], d: "A gap down, then another one a month later, right after you've been assigned." },
    { id: "crash", name: "−35% in a month", short: "−35% month", f: spread(-0.35, 21), d: "A fast crash like March 2020: a month of steady selling." },
    { id: "bear", name: "−50% over a year", short: "−50% year", f: spread(-0.50, 250), d: "A slow bear market like 2022: down a bit most weeks for a year." },
    { id: "up", name: "+25% overnight", short: "+25% gap", f: [1.25], d: "The other side: a huge rally the covered calls give away." },
  ];
  S.WARMUP = 90;      // trading days the strategy runs before the shock
  S.HORIZON = 378;    // trading days after it (1.5 years) to measure recovery

  // Shock dates to test: every `step` trading days across the model window,
  // leaving room for warm-up and a month after the shock ends.
  S.shockDates = function (E, D, shock, step = 10) {
    const w = E.WINDOWS.model;
    let i0 = 0; while (D.dates[i0] < w.start) i0++;
    let i1 = D.n - 1; while (D.dates[i1] > w.end) i1--;
    const out = [];
    for (let d = i0 + S.WARMUP; d + shock.f.length + 21 <= i1; d += step) out.push(d);
    return { dates: out, last: i1 };
  };
  // One shock at day index d, run for every strategy. base caches the
  // unshocked runs (they don't depend on the scenario).
  S.shockAt = function (E, D, tk, shock, d, last, strategies, base) {
    const T = D.tickers[tk], n = D.n, i0 = d - S.WARMUP, i1 = Math.min(last, d + S.HORIZON);
    const close = Float64Array.from(T.S);
    let mult = 1;
    for (let i = d; i < n; i++) { if (i - d < shock.f.length) mult *= shock.f[i - d]; close[i] *= mult; }
    const key = "SHOCK_" + tk;
    E.pathTicker(D, tk, key, close, { from: d, to: i1 });
    const kEnd = Math.min(i1, d + shock.f.length - 1 + 21) - i0, kPre = d - 1 - i0, kYear = Math.min(i1, d + 252) - i0;
    // hit: how much lower it is a month after the shock ends than it would
    // have been without it. low: its worst point in the year after, vs the
    // day before. rec: trading days until it's back above that day's value
    // after its low (0 if it never fell below; null if not within 1.5 years).
    const measure = (eq, eqBase) => {
      let low = 0, kLow = kPre, rec = null;
      for (let k = kPre + 1; k <= kYear; k++) if (eq[k] / eq[kPre] - 1 < low) { low = eq[k] / eq[kPre] - 1; kLow = k; }
      if (kLow === kPre) rec = 0;
      else for (let k = kLow + 1; k <= i1 - i0; k++) if (eq[k] >= eq[kPre]) { rec = k - kPre; break; }
      return { hit: eq[kEnd] / eqBase[kEnd] - 1, low, rec };
    };
    const out = {};
    for (const s of strategies) {
      const bk = s.key + "|" + d;
      let b = base.get(bk);
      if (!b) { b = E.simulate(D, s.cfg, "model", tk, { i0, i1 }); base.set(bk, { eq: b.eq, state: b.state[kPre] }); b = base.get(bk); }
      const run = E.simulate(D, s.cfg, "model", key, { i0, i1 });
      out[s.key] = { ...measure(run.eq, b.eq), state: b.state };
    }
    const held = close.subarray(i0, i1 + 1), heldBase = T.S.subarray(i0, i1 + 1);
    out.held = { ...measure(held, heldBase), state: null };
    delete D.tickers[key];
    return out;
  };
  // Summary of one strategy's results across all shock dates.
  S.summarize = function (rows) {
    const q = (arr, p) => { const s = arr.slice().sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(p * (s.length - 1) + 0.5))] : NaN; };
    const hits = rows.map((r) => r.hit), lows = rows.map((r) => r.low), recs = rows.map((r) => r.rec == null ? Infinity : r.rec);
    return {
      n: rows.length, hit: q(hits, 0.5), hitBad: q(hits, 0.1), hitWorst: Math.min(...hits), hitBest: Math.max(...hits),
      low: q(lows, 0.5), lowBad: q(lows, 0.1), rec: q(recs, 0.5), noRecYear: recs.filter((r) => r > 252).length / recs.length,
      inShares: rows.filter((r) => r.state >= 2).length / rows.length, inPut: rows.filter((r) => r.state === 1).length / rows.length,
    };
  };

  if (typeof module !== "undefined" && module.exports) module.exports = S; else root.WheelStress = S;
})(typeof window !== "undefined" ? window : globalThis);
