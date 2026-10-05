/* Wheel Lab engine: a day-by-day wheel backtest that runs in the browser.
 * Two price sources:
 *   real  - actual NVDA option closes from Alpaca, June 2024 on. One contract
 *           per $25k like the live bot. Fills = close -/+ an assumed half-spread.
 *   model - 2016 on, Black-Scholes with IV = multiple of realized vol,
 *           calibrated on the real trades. Fully invested (fractional contracts).
 * For the original rules it mirrors research/wheel_research.py and
 * research/bs_research.py; lab/parity_test.js checks the numbers match.
 */
(function (root) {
  "use strict";
  const E = {};
  const SQ252 = Math.sqrt(252);

  // ---------- math ----------
  function erf(x) { // Abramowitz-Stegun 7.1.26, |error| < 1.5e-7
    const s = x < 0 ? -1 : 1;
    x = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * x);
    const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
  }
  const ncdf = (x) => 0.5 * (1 + erf(x / Math.SQRT2));

  function ninv(p) { // Acklam's inverse normal CDF
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const pl = 0.02425;
    let q, r;
    if (p < pl) {
      q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    if (p > 1 - pl) {
      q = Math.sqrt(-2 * Math.log(1 - p));
      return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    q = p - 0.5; r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  function bsPrice(kind, S, K, T, r, vol) {
    if (T <= 0 || vol <= 0) return Math.max(0, kind === "P" ? K - S : S - K);
    const sd = vol * Math.sqrt(T);
    const d1 = (Math.log(S / K) + (r + vol * vol / 2) * T) / sd;
    const d2 = d1 - sd;
    return kind === "C" ? S * ncdf(d1) - K * Math.exp(-r * T) * ncdf(d2)
                        : K * Math.exp(-r * T) * ncdf(-d2) - S * ncdf(-d1);
  }
  function bsDelta(kind, S, K, T, r, vol) {
    const d1 = (Math.log(S / K) + (r + vol * vol / 2) * T) / (vol * Math.sqrt(T));
    return ncdf(d1) - (kind === "P" ? 1 : 0);
  }
  function impliedVol(kind, price, S, K, T, r) {
    if (price <= Math.max(0, kind === "P" ? K - S : S - K) + 1e-6) return null;
    let lo = 0.01, hi = 5.0;
    for (let i = 0; i < 80; i++) {
      const mid = (lo + hi) / 2;
      if (bsPrice(kind, S, K, T, r, mid) > price) hi = mid; else lo = mid;
    }
    return (lo + hi) / 2;
  }
  // Strike with a given |delta|, from the Black-Scholes delta formula.
  function strikeForDelta(kind, absDelta, S, T, r, vol) {
    const d1 = kind === "P" ? ninv(1 - absDelta) : ninv(absDelta);
    return S * Math.exp(-(d1 * vol * Math.sqrt(T) - (r + vol * vol / 2) * T));
  }
  Object.assign(E, { bsPrice, bsDelta, impliedVol, strikeForDelta, ncdf, ninv });

  // ---------- dates ----------
  const epochDay = (iso) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000;
  const isoOf = (ed) => new Date(ed * 86400000).toISOString().slice(0, 10);
  const pyWeekday = (ed) => (new Date(ed * 86400000).getUTCDay() + 6) % 7; // Mon=0 like Python
  E.epochDay = epochDay; E.isoOf = isoOf;

  // ---------- data prep ----------
  // Shared calendar and benchmarks, plus one price set per underlying
  // (closes, realized vol, option chains and bars, earnings, model pricing).
  E.prepare = function (L) {
    const n = L.dates.length, day = new Int32Array(n), dayIndex = new Map();
    for (let i = 0; i < n; i++) { day[i] = epochDay(L.dates[i]); dayIndex.set(day[i], i); }
    const rollStd = (lr, w) => {
      const out = new Float64Array(n).fill(NaN);
      for (let i = w; i < n; i++) { // window lr[i-w+1..i], all valid once i >= w
        let m = 0; for (let j = i - w + 1; j <= i; j++) m += lr[j]; m /= w;
        let v = 0; for (let j = i - w + 1; j <= i; j++) v += (lr[j] - m) ** 2;
        out[i] = Math.sqrt(v / (w - 1));
      }
      return out;
    };
    const tickers = {};
    for (const [tk, T] of Object.entries(L.tickers)) {
      const S = Float64Array.from(T.close), lr = new Float64Array(n); lr[0] = NaN;
      for (let i = 1; i < n; i++) lr[i] = Math.log(S[i] / S[i - 1]);
      const s20 = rollStd(lr, 20), s60 = rollStd(lr, 60), rv = new Float64Array(n);
      for (let i = 0; i < n; i++) rv[i] = 0.5 * s20[i] * SQ252 + 0.5 * s60[i] * SQ252;
      const chains = new Map();
      for (const [iso, ch] of Object.entries(T.chains || {})) {
        chains.set(epochDay(iso), { P: ch.P.slice().sort((a, b) => a[0] - b[0]), C: ch.C.slice().sort((a, b) => a[0] - b[0]) });
      }
      tickers[tk] = { ticker: tk, S, rv, chains, bars: T.bars, earnings: T.earnings.map(epochDay), barCache: new Map(), model: T.model, capital: T.capital };
    }
    const D = {
      L, n, day, dayIndex, tickers, dates: L.dates,
      nvdaTR: Float64Array.from(L.nvdaTR), spyTR: Float64Array.from(L.spyTR), costTR: Float64Array.from(L.costTR || L.spyTR), tbill: Float64Array.from(L.tbill),
    };
    return Object.assign(D, tickers.NVDA);
  };
  // The dataset seen by one simulation: shared calendar + that ticker's prices.
  const viewOf = (D, tk) => Object.assign(Object.create(D), D.tickers[tk]);

  function bar(D, cid, i) { // real option close on day index i, or NaN
    let b = D.barCache.get(cid);
    if (!b) {
      const flat = D.bars[cid];
      let di = 0; const pts = [];
      for (let k = 0; k < flat.length; k += 2) { di += flat[k]; pts.push([di, flat[k + 1] / 100]); }
      const i0 = pts[0][0], arr = new Float64Array(pts[pts.length - 1][0] - i0 + 1).fill(NaN);
      for (const [d, v] of pts) arr[d - i0] = v;
      b = { i0, arr }; D.barCache.set(cid, b);
    }
    const j = i - b.i0;
    return j >= 0 && j < b.arr.length ? b.arr[j] : NaN;
  }

  const crossesEarnings = (D, d, exp) => D.earnings.some((e) => d < e && e <= exp);

  function realExpiry(D, d, dte) { // Friday on/after d+dte; Thursday if a holiday; else next Friday
    let f = d + dte; f += (4 - pyWeekday(f) + 7) % 7;
    for (const c of [f, f - 1, f + 7]) if (D.chains.has(c)) return c;
    return null;
  }
  function modelExpiry(D, d, dte) {
    let f = d + dte; f += (4 - pyWeekday(f) + 7) % 7;
    while (!D.dayIndex.has(f) && f > d) f -= 1;
    return f;
  }

  // ---------- config ----------
  E.BOT_RULES = {
    put: { method: "otm", otm: 0.10, delta: 0.20 },
    dte: 14, tp: 0.5, loss: null,
    call: { method: "basis", otm: 0.10, delta: 0.25, under: 0.20 },
    skipEarnings: false, volFilter: null, sizing: "one",
    putMult: 1.13, callMult: 1.0, earnPut: 1.4, earnCall: 1.1, halfSpread: 0.03,
  };
  E.WINDOWS = {
    real: { start: "2024-06-10", end: "2026-10-02", split: "2025-07-01" },
    model: { start: "2016-04-01", end: "2026-10-02", split: "2022-01-01" },
  };
  const FEE = 0.05, MIN_PREMIUM = 0.05, MIN_DELTA = 0.02, CAP = 25000;

  // ---------- simulation ----------
  E.simulate = function (D0, cfg, mode, ticker = "NVDA") {
    const D = viewOf(D0, ticker);
    // Real prices: the smallest account that fits one contract ($25k for NVDA),
    // with results scaled to $25k so every ticker reads the same way.
    const CAPX = mode === "real" ? D.capital : CAP, scale = CAP / CAPX;
    const win = E.WINDOWS[mode];
    let i0 = 0; while (D.dates[i0] < win.start) i0++;
    let i1 = D.n - 1; while (D.dates[i1] > win.end) i1--;
    const len = i1 - i0 + 1, real = mode === "real", hs = cfg.halfSpread;
    const eq = new Float64Array(len), state = new Uint8Array(len);
    const trades = [], events = [];
    let cash = CAPX, q = 0, basis = 0, short = null, interest = 0, shareGains = 0, stuckLogged = false;
    const tb = (i) => D.tbill[i];
    const fillSell = (px) => real ? Math.max(0, px - Math.max(0.01, px * hs)) - FEE / 100 : px * (1 - hs);
    const fillBuy = (px) => real ? px + Math.max(0.01, px * hs) + FEE / 100 : px * (1 + hs);
    // Model IV = realized vol x a multiplier. NVDA uses one calibrated number
    // (as in the research engine); SPY and COST follow a curve measured at
    // several strike distances, scaled by the pricing lever.
    const interp = (curve, x) => {
      if (x <= curve[0][0]) return curve[0][1];
      for (let j = 1; j < curve.length; j++) if (x <= curve[j][0]) { const [a, fa] = curve[j - 1], [b, fb] = curve[j]; return fa + (fb - fa) * (x - a) / (b - a); }
      return curve[curve.length - 1][1];
    };
    const modelIv = (kind, i, exp, moneyness = null) => {
      const x = crossesEarnings(D, D.day[i], exp), M = D.model || {};
      const curve = kind === "P" ? M.putCurve : M.callCurve;
      let m = kind === "P" ? cfg.putMult : cfg.callMult;
      if (curve && curve.length && moneyness != null) m = interp(curve, moneyness) * m / (kind === "P" ? M.putMult : M.callMult);
      return m * (x ? (kind === "P" ? cfg.earnPut : cfg.earnCall) : 1) * D.rv[i];
    };
    // Strike for a target delta when vol depends on the strike: a few fixed-point steps.
    const solveStrike = (kind, want, S, T, r, i, exp) => {
      let K = S * (kind === "P" ? 0.95 : 1.05);
      for (let it = 0; it < 4; it++) K = strikeForDelta(kind, want, S, T, r, modelIv(kind, i, exp, K / S));
      return K;
    };
    const ev = (k, type, text) => events.push({ k, type, text });

    function closeShort(k, exitPx, outcome) {
      const pnl = (short.entry - exitPx) * short.qty;
      trades.push({ kind: short.kind, k0: short.k, k1: k, K: short.K, entry: short.entry, exit: exitPx, pnl, outcome,
                    iv: short.iv, delta: short.delta, earn: short.earn, qty: short.qty });
      short = null;
      return pnl;
    }

    function pickReal(kind, i, S, d, target, capital) {
      const exp = realExpiry(D, d, cfg.dte);
      if (exp === null) return null;
      if (cfg.skipEarnings && crossesEarnings(D, d, exp)) return { skip: "earnings" };
      const chain = D.chains.get(exp)[kind];
      const T = Math.max(exp - d, 1) / 365, r = tb(i);
      const legMethod = kind === "P" ? cfg.put.method : callMethod(S);
      let pick = null;
      if (legMethod === "delta") {
        const want = kind === "P" ? cfg.put.delta : cfg.call.delta;
        // Only price strikes near a first guess; inverting IV for the whole chain is slow.
        const guess = strikeForDelta(kind, want, S, T, r, Math.max(0.15, 1.13 * D.rv[i]));
        const scan = (near) => {
          let best = null;
          for (const [K, cid] of chain) {
            if (near && (K < guess * 0.85 || K > guess * 1.15)) continue;
            if (kind === "P" && (K > S || K > Math.floor(capital / 100) || K < 0.5 * S)) continue;
            if (kind === "C" && (K < 0.95 * S || K > 1.6 * S)) continue;
            const px = bar(D, cid, i);
            if (!(px >= MIN_PREMIUM)) continue;
            const iv = impliedVol(kind, px, S, K, T, r);
            if (!iv) continue;
            const dl = Math.abs(bsDelta(kind, S, K, T, r, iv));
            if (!best || Math.abs(dl - want) < Math.abs(best.dl - want)) best = { K, cid, px, dl };
          }
          return best;
        };
        const best = scan(true) || scan(false);
        if (best) pick = { K: best.K, cid: best.cid, px: best.px };
      } else {
        const cands = kind === "P" ? chain.filter((c) => c[0] <= target).reverse().slice(0, 4)
                                   : chain.filter((c) => c[0] >= target).slice(0, 4);
        for (const [K, cid] of cands) {
          const px = bar(D, cid, i);
          if (px >= MIN_PREMIUM) { pick = { K, cid, px }; break; }
        }
      }
      if (!pick) return null;
      const iv = impliedVol(kind, pick.px, S, pick.K, T, r);
      return { ...pick, exp, iv, delta: iv ? bsDelta(kind, S, pick.K, T, r, iv) : null, earn: crossesEarnings(D, d, exp) };
    }

    function callMethod(S) {
      if (cfg.call.method === "hybrid") return S < basis * (1 - cfg.call.under) ? "delta" : "basis";
      return cfg.call.method;
    }

    for (let k = 0; k < len; k++) {
      const i = i0 + k, d = D.day[i], S = D.S[i];
      if (k > 0) { const g = cash * tb(i - 1) * (d - D.day[i - 1]) / 360; cash += g; interest += g; }

      // manage the open short
      if (short) {
        let px;
        if (real) { px = bar(D, short.cid, i); if (!isNaN(px)) short.last = px; }
        else {
          const T = Math.max(short.exp - d, 0) / 365;
          px = bsPrice(short.kind, S, short.K, T, tb(i), modelIv(short.kind, i, short.exp, short.K / S));
        }
        if (d >= short.exp) {
          const kind = short.kind, K = short.K, qty = short.qty;
          const intrinsic = Math.max(0, kind === "P" ? K - S : S - K);
          let outcome = "expired";
          if (kind === "P" && S < K) { cash -= K * qty; q = qty; basis = K; outcome = "assigned"; }
          else if (kind === "C" && S > K) { cash += K * qty; shareGains += (K - basis) * q; q = 0; basis = 0; outcome = "called_away"; }
          const pnl = closeShort(k, intrinsic, outcome);
          if (outcome === "assigned") ev(k, "assign", `Put assigned at $${K.toFixed(2)}: bought ${fmtQty(qty)} shares (NVDA $${S.toFixed(2)})`);
          else if (outcome === "called_away") ev(k, "called", `Shares called away at $${K.toFixed(2)} (NVDA $${S.toFixed(2)})`);
          else ev(k, "expire", `${kind === "P" ? "Put" : "Call"} $${K.toFixed(2)} expired worthless, kept $${pnl.toFixed(0)}`);
          stuckLogged = false;
        } else if (cfg.tp != null && !isNaN(px) && px <= short.entry * (1 - cfg.tp)) {
          const kind = short.kind, K = short.K, cost = fillBuy(px);
          cash -= cost * short.qty;
          const pnl = closeShort(k, cost, "take_profit");
          ev(k, "tp", `Took profit on ${kind === "P" ? "put" : "call"} $${K.toFixed(2)}: +$${pnl.toFixed(0)}`);
        } else if (cfg.loss != null && !isNaN(px) && px >= short.entry * cfg.loss) {
          const kind = short.kind, K = short.K, cost = fillBuy(px);
          cash -= cost * short.qty;
          const pnl = closeShort(k, cost, "loss_cut");
          ev(k, "stop", `Cut loss on ${kind === "P" ? "put" : "call"} $${K.toFixed(2)} at ${cfg.loss}x credit: $${pnl.toFixed(0)}`);
        } else if (!real) short.mark = px;
      }

      // open the next short (same day, like the bot's roll)
      if (!short && (real || k !== len - 1)) {
        if (q === 0) openPut(k, i, d, S); else openCall(k, i, d, S);
      }

      const optVal = short ? (real ? short.last : short.mark) * short.qty : 0;
      eq[k] = cash + q * S - optVal;
      state[k] = short && short.kind === "P" ? 1 : q > 0 ? (short ? 2 : 3) : 0;
    }

    function openPut(k, i, d, S) {
      if (real) {
        const capital = Math.min(cash, CAPX);
        const target = Math.min(Math.floor(S * (1 - cfg.put.otm)), Math.floor(capital / 100));
        const p = pickReal("P", i, S, d, target, capital);
        if (!p) return;
        if (p.skip) { if (!events.length || events[events.length - 1].type !== "skip") ev(k, "skip", "Skipped a put: expiry would cross earnings"); return; }
        if (cfg.volFilter && !(p.iv >= cfg.volFilter * D.rv[i])) {
          if (!events.length || events[events.length - 1].type !== "cheap") ev(k, "cheap", `Waited: put IV ${(100 * (p.iv || 0)).toFixed(0)}% below ${cfg.volFilter}x realized ${(100 * D.rv[i]).toFixed(0)}%`);
          return;
        }
        const contracts = cfg.sizing === "max" ? Math.max(1, Math.floor(capital / (p.K * 100))) : 1;
        if (p.K * 100 * contracts > capital) return;
        const prem = fillSell(p.px);
        cash += prem * 100 * contracts;
        short = { kind: "P", K: p.K, exp: p.exp, entry: prem, last: p.px, qty: 100 * contracts, k, cid: p.cid, iv: p.iv, delta: p.delta, earn: p.earn };
        ev(k, "put", `Sold ${contracts > 1 ? contracts + "x " : ""}$${p.K} put exp ${isoOf(p.exp)} for $${prem.toFixed(2)} (delta ${p.delta ? Math.abs(p.delta).toFixed(2) : "?"})`);
      } else {
        const exp = modelExpiry(D, d, cfg.dte);
        if (cfg.skipEarnings && crossesEarnings(D, d, exp)) return;
        const T = Math.max(exp - d, 1) / 365, r = tb(i);
        const K = cfg.put.method === "delta" ? solveStrike("P", cfg.put.delta, S, T, r, i, exp) : S * (1 - cfg.put.otm);
        const vol = modelIv("P", i, exp, K / S);
        const delta = bsDelta("P", S, K, T, r, vol);
        if (Math.abs(delta) < MIN_DELTA) return;
        const bs = bsPrice("P", S, K, T, r, vol), px = bs * (1 - hs), qty = cash / K;
        cash += px * qty;
        short = { kind: "P", K, exp, entry: px, qty, k, mark: bs, iv: vol, delta, earn: crossesEarnings(D, d, exp) };
        ev(k, "put", `Sold put ${((1 - K / S) * 100).toFixed(1)}% below NVDA, exp ${isoOf(exp)}, delta ${Math.abs(delta).toFixed(2)}`);
      }
    }

    function openCall(k, i, d, S) {
      const method = callMethod(S);
      if (real) {
        const ref = method === "spot" ? S : basis;
        const target = Math.ceil(Math.round(ref * (1 + cfg.call.otm) * 1e10) / 1e10);
        const p = pickReal("C", i, S, d, target, 0);
        if (!p || p.skip) { if (!stuckLogged) { ev(k, "stuck", `No call to sell: holding shares (basis $${basis.toFixed(2)}, NVDA $${S.toFixed(2)})`); stuckLogged = true; } return; }
        const prem = fillSell(p.px);
        cash += prem * q;
        short = { kind: "C", K: p.K, exp: p.exp, entry: prem, last: p.px, qty: q, k, cid: p.cid, iv: p.iv, delta: p.delta, earn: p.earn };
        ev(k, "call", `Sold $${p.K} call exp ${isoOf(p.exp)} for $${prem.toFixed(2)} (basis $${basis.toFixed(2)})`);
        stuckLogged = false;
      } else {
        const exp = modelExpiry(D, d, cfg.dte);
        const T = Math.max(exp - d, 1) / 365, r = tb(i);
        const K = method === "delta" ? solveStrike("C", cfg.call.delta, S, T, r, i, exp)
                                     : (method === "spot" ? S : basis) * (1 + cfg.call.otm);
        const vol = modelIv("C", i, exp, K / S);
        const delta = bsDelta("C", S, K, T, r, vol);
        if ((cfg.skipEarnings && crossesEarnings(D, d, exp)) || delta < MIN_DELTA) {
          if (!stuckLogged) { ev(k, "stuck", `No call worth selling: shares ${((1 - S / basis) * 100).toFixed(0)}% under basis`); stuckLogged = true; }
          return;
        }
        const bs = bsPrice("C", S, K, T, r, vol), px = bs * (1 - hs);
        cash += px * q;
        short = { kind: "C", K, exp, entry: px, qty: q, k, mark: bs, iv: vol, delta, earn: crossesEarnings(D, d, exp) };
        ev(k, "call", `Sold call ${((K / S - 1) * 100).toFixed(1)}% above NVDA (basis ${((basis / S - 1) * 100).toFixed(0)}% away), delta ${delta.toFixed(2)}`);
        stuckLogged = false;
      }
    }

    function fmtQty(x) { return Number.isInteger(x) ? String(x) : x.toFixed(1); }

    const premium = trades.reduce((s, t) => s + t.pnl, 0);
    if (scale !== 1) for (let k = 0; k < len; k++) eq[k] *= scale;
    return { mode, ticker, i0, i1, len, eq, state, trades, events, interest: interest * scale, shareGains: shareGains * scale, premium: premium * scale,
             endCash: cash, endShares: q, capital: CAPX };
  };

  // ---------- benchmarks & metrics ----------
  E.benchmarks = function (D, i0, i1) {
    const len = i1 - i0 + 1, nv = new Float64Array(len), sp = new Float64Array(len), co = new Float64Array(len), tbc = new Float64Array(len);
    let v = CAP;
    for (let k = 0; k < len; k++) {
      const i = i0 + k;
      nv[k] = CAP * D.nvdaTR[i] / D.nvdaTR[i0];
      sp[k] = CAP * D.spyTR[i] / D.spyTR[i0];
      co[k] = CAP * D.costTR[i] / D.costTR[i0];
      if (k > 0) v *= 1 + D.tbill[i - 1] * (D.day[i] - D.day[i - 1]) / 360;
      tbc[k] = v;
    }
    return { nvda: nv, spy: sp, cost: co, tbill: tbc };
  };

  function mean(a) { let s = 0; for (const x of a) s += x; return s / a.length; }
  function std(a) { const m = mean(a); let v = 0; for (const x of a) v += (x - m) ** 2; return Math.sqrt(v / (a.length - 1)); }
  function quantile(sorted, p) { const h = (sorted.length - 1) * p, lo = Math.floor(h); return sorted[lo] + (h - lo) * ((sorted[lo + 1] ?? sorted[lo]) - sorted[lo]); }

  // Metrics over eq[a..b] (indices into the run), excess returns vs the T-bill curve.
  E.metrics = function (D, run, eq, rf, a = 0, b = eq.length - 1) {
    const r = [], ex = [];
    for (let k = a + 1; k <= b; k++) { const x = eq[k] / eq[k - 1] - 1; r.push(x); ex.push(x - (rf[k] / rf[k - 1] - 1)); }
    const days = D.day[run.i0 + b] - D.day[run.i0 + a], years = days / 365.25;
    const total = eq[b] / eq[a] - 1, cagr = Math.pow(eq[b] / eq[a], 1 / years) - 1;
    let peak = eq[a], peakK = a, maxDD = 0, ddPeak = a, ddTrough = a;
    for (let k = a; k <= b; k++) {
      if (eq[k] > peak) { peak = eq[k]; peakK = k; }
      const dd = eq[k] / peak - 1;
      if (dd < maxDD) { maxDD = dd; ddPeak = peakK; ddTrough = k; }
    }
    let recovery = null;
    for (let k = ddTrough; k <= b; k++) if (eq[k] >= eq[ddPeak]) { recovery = D.day[run.i0 + k] - D.day[run.i0 + ddPeak]; break; }
    // month-end returns
    const monthEnds = [];
    for (let k = a; k <= b; k++) {
      const m = D.dates[run.i0 + k].slice(0, 7), next = k < b ? D.dates[run.i0 + k + 1].slice(0, 7) : null;
      if (m !== next) monthEnds.push(eq[k]);
    }
    let worstMonth = 0;
    for (let j = 1; j < monthEnds.length; j++) worstMonth = Math.min(worstMonth, monthEnds[j] / monthEnds[j - 1] - 1);
    const sr = std(ex) > 0 ? mean(ex) / std(ex) * SQ252 : NaN;
    const neg = ex.filter((x) => x < 0), dstd = neg.length > 1 ? std(neg) * SQ252 : NaN;
    const sorted = r.slice().sort((x, y) => x - y), q5 = quantile(sorted, 0.05);
    const tail = r.filter((x) => x <= q5);
    return {
      total, cagr, vol: std(r) * SQ252, sharpe: sr, sortino: dstd > 0 ? mean(ex) * 252 / dstd : NaN,
      maxDD, ddPeak, ddTrough, recovery, worstMonth, cvar5: mean(tail), years,
    };
  };

  E.tradeStats = function (run) {
    const t = run.trades, wins = t.filter((x) => x.pnl > 0), losses = t.filter((x) => x.pnl <= 0);
    const share = run.state.reduce((s, x) => s + (x >= 2 ? 1 : 0), 0), stuck = run.state.reduce((s, x) => s + (x === 3 ? 1 : 0), 0);
    return {
      trades: t.length, winRate: t.length ? wins.length / t.length : NaN,
      avgWin: wins.length ? mean(wins.map((x) => x.pnl)) : 0, avgLoss: losses.length ? mean(losses.map((x) => x.pnl)) : 0,
      worst: t.length ? Math.min(...t.map((x) => x.pnl)) : 0,
      assigned: t.filter((x) => x.outcome === "assigned").length, called: t.filter((x) => x.outcome === "called_away").length,
      shareDays: share / run.len, stuckDays: stuck / run.len,
      putDelta: (() => { const ds = t.filter((x) => x.kind === "P" && x.delta != null).map((x) => Math.abs(x.delta)).sort((a, b) => a - b); return ds.length ? ds[Math.floor(ds.length / 2)] : NaN; })(),
    };
  };

  // CAPM regression of daily excess returns on a benchmark's: beta is the
  // sensitivity, alpha the yearly return left over, t its signal-to-noise.
  E.capm = function (curve, bench, rf, a, b) {
    const x = [], y = [];
    for (let k = a + 1; k <= b; k++) {
      const r0 = rf[k] / rf[k - 1] - 1;
      y.push(curve[k] / curve[k - 1] - 1 - r0); x.push(bench[k] / bench[k - 1] - 1 - r0);
    }
    const n = x.length, mx = mean(x), my = mean(y);
    let sxx = 0, sxy = 0, syy = 0;
    for (let i = 0; i < n; i++) { sxx += (x[i] - mx) ** 2; sxy += (x[i] - mx) * (y[i] - my); syy += (y[i] - my) ** 2; }
    const beta = sxy / sxx, alphaD = my - beta * mx;
    let sse = 0;
    for (let i = 0; i < n; i++) sse += (y[i] - alphaD - beta * x[i]) ** 2;
    const s2 = sse / (n - 2), seAlpha = Math.sqrt(s2 * (1 / n + mx * mx / sxx));
    return { beta, alpha: alphaD * 252, t: alphaD / seAlpha, corr: sxy / Math.sqrt(sxx * syy) };
  };

  // Expected value per option trade, overall and split into wins and losses.
  // pnlPct is relative to the capital at risk (strike x shares).
  E.tradeEV = function (trades) {
    if (!trades.length) return null;
    const pct = trades.map((t) => t.pnl / (t.K * t.qty)), wins = trades.filter((t) => t.pnl > 0), losses = trades.filter((t) => t.pnl <= 0);
    const winPct = pct.filter((_, i) => trades[i].pnl > 0), lossPct = pct.filter((_, i) => trades[i].pnl <= 0);
    return {
      ev: mean(trades.map((t) => t.pnl)), evPct: mean(pct), winRate: wins.length / trades.length,
      avgWin: wins.length ? mean(wins.map((t) => t.pnl)) : 0, avgLoss: losses.length ? mean(losses.map((t) => t.pnl)) : 0,
      avgWinPct: winPct.length ? mean(winPct) : 0, avgLossPct: lossPct.length ? mean(lossPct) : 0,
    };
  };

  // Sharpe after accounting for how many configurations were tried: the
  // expected best of N lucky draws is subtracted (deflated-Sharpe style).
  E.luckAdjusted = function (sr, years, trials) {
    const se = Math.sqrt((1 + sr * sr / 2) / years);
    if (trials <= 1) return { adjusted: sr, haircut: 0, se };
    const g = 0.5772156649, emax = (1 - g) * ninv(1 - 1 / trials) + g * ninv(1 - 1 / (trials * Math.E));
    return { adjusted: sr - se * emax, haircut: se * emax, se };
  };

  E.REGIMES = {
    model: [["2018 Q4 crash", "2018-10-01", "2018-12-24"], ["Covid crash", "2020-02-19", "2020-03-16"],
            ["2022 bear market", "2021-11-29", "2022-10-13"], ["2023 rally", "2023-01-03", "2023-12-29"],
            ["2025 tariff drop", "2025-01-06", "2025-04-04"], ["2025-26 recovery", "2025-04-07", "2026-10-02"]],
    real: [["Summer 2024 pullback", "2024-06-18", "2024-08-07"], ["DeepSeek + tariff drop", "2025-01-06", "2025-04-04"],
           ["2025-26 recovery", "2025-04-07", "2026-10-02"]],
  };
  E.sliceReturn = function (D, run, curve, from, to) {
    let a = -1, b = -1;
    for (let k = 0; k < run.len; k++) { const iso = D.dates[run.i0 + k]; if (a < 0 && iso >= from) a = k; if (iso <= to) b = k; }
    return a >= 0 && b > a ? curve[b] / curve[a] - 1 : NaN;
  };
  E.splitIndex = function (D, run) {
    const s = E.WINDOWS[run.mode].split;
    for (let k = 0; k < run.len; k++) if (D.dates[run.i0 + k] >= s) return k;
    return Math.floor(run.len / 2);
  };

  if (typeof module !== "undefined" && module.exports) module.exports = E; else root.WheelEngine = E;
})(typeof window !== "undefined" ? window : globalThis);
