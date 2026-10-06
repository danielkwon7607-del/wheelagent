// Exhaustive rule search for the Wheel Lab. For every ticker, runs every
// combination on real prices (June 2024 on) and on the 2016-26 model, scores
// each by its percentile rank on Sharpe and yearly return in both, and picks
// the best by its neighborhood (plateau) score, not its raw score.
// Writes lab/best.js. Run: node lab/search.js [TICKER ...]
const fs = require("fs");
const path = require("path");
global.window = {};
eval(fs.readFileSync(path.join(__dirname, "data.js"), "utf8"));
for (const f of fs.readdirSync(__dirname).filter((f) => /^data_[A-Z]+\.js$/.test(f))) eval(fs.readFileSync(path.join(__dirname, f), "utf8"));
const E = require("./engine.js");
const D = E.prepare(window.LAB_DATA);
for (const [tk, T] of Object.entries(window.LAB_TICKERS || {})) E.addTicker(D, tk, T);

const G = require("./grid.js");
const { PUTS, DTES, TPS, LOSSES, CALLS, EARN, VOLS, BOT_G, keyOf } = G;
const cfgFor = (tk, g) => G.cfgFor(D.tickers[tk].model, g);
function measure(tk, cfg, mode) {
  const r = E.simulate(D, cfg, mode, tk), b = E.benchmarks(D, r.i0, r.i1), sp = E.splitIndex(D, r), last = r.len - 1;
  const full = E.metrics(D, r, r.eq, b.tbill), des = E.metrics(D, r, r.eq, b.tbill, 0, sp - 1), tst = E.metrics(D, r, r.eq, b.tbill, sp, last);
  return { sh: full.sharpe, cagr: full.cagr, dd: full.maxDD, dSh: des.sharpe, dCagr: des.cagr, tSh: tst.sharpe, tCagr: tst.cagr, trades: r.trades.length, r, b };
}
const pctRank = (vals) => { const idx = vals.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]), out = new Array(vals.length); idx.forEach(([, i], k) => (out[i] = k / (vals.length - 1))); return out; };
const median = (v) => { const s = v.slice().sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };

function luck(rA, bA, rB, N) { // Sharpe edge of A over B vs the best luck after N tries (Memmel SE)
  const ex = (r, b) => { const o = []; for (let k = 1; k < r.len; k++) o.push(r.eq[k] / r.eq[k - 1] - 1 - (b.tbill[k] / b.tbill[k - 1] - 1)); return o; };
  const xa = ex(rA, bA), xb = ex(rB, bA), n = xa.length, mean = (v) => v.reduce((s, x) => s + x, 0) / v.length;
  const ma = mean(xa), mb = mean(xb); let va = 0, vb = 0, cv = 0;
  for (let i = 0; i < n; i++) { va += (xa[i] - ma) ** 2; vb += (xb[i] - mb) ** 2; cv += (xa[i] - ma) * (xb[i] - mb); }
  va /= n - 1; vb /= n - 1; cv /= n - 1;
  const sa = ma / Math.sqrt(va) * Math.sqrt(252), sb = mb / Math.sqrt(vb) * Math.sqrt(252), rho = cv / Math.sqrt(va * vb), yrs = n / 252;
  const se = Math.sqrt(Math.max((2 - 2 * rho + (sa * sa + sb * sb - 2 * sa * sb * rho * rho) / 2) / yrs, 1e-9)), g = 0.5772156649;
  const emax = (1 - g) * E.ninv(1 - 1 / N) + g * E.ninv(1 - 1 / (N * Math.E));
  return { edge: sa - sb, allowance: se * emax, survives: sa - sb > se * emax, rho };
}

const out = { generated: new Date().toISOString().slice(0, 16), method: "percentile rank on Sharpe and yearly return, real and model; best by neighborhood median", tickers: {} };
const only = process.argv.slice(2);
for (const tk of Object.keys(D.tickers).filter((t) => !only.length || only.includes(t))) {
  const t0 = Date.now(), grid = [];
  for (let p = 0; p < PUTS.length; p++) for (let d = 0; d < DTES.length; d++) for (let t = 0; t < TPS.length; t++)
    for (let l = 0; l < LOSSES.length; l++) for (let c = 0; c < CALLS.length; c++) for (let e = 0; e < EARN.length; e++) {
      const gm = { p, d, t, l, c, e, v: 0 }, model = measure(tk, cfgFor(tk, gm), "model");
      delete model.r; delete model.b;
      for (let v = 0; v < VOLS.length; v++) {
        const g = { p, d, t, l, c, e, v }, real = measure(tk, cfgFor(tk, g), "real");
        delete real.r; delete real.b;
        grid.push({ g, real, model });
      }
    }
  const ok = (x) => Number.isFinite(x) ? x : -9;
  const score = (sel) => {
    const ranks = [pctRank(grid.map((x) => ok(sel(x).rSh))), pctRank(grid.map((x) => ok(sel(x).rC))), pctRank(grid.map((x) => ok(sel(x).mSh))), pctRank(grid.map((x) => ok(sel(x).mC)))];
    return grid.map((_, i) => (ranks[0][i] + ranks[1][i] + ranks[2][i] + ranks[3][i]) / 4);
  };
  const full = score((x) => ({ rSh: x.real.sh, rC: x.real.cagr, mSh: x.model.sh, mC: x.model.cagr }));
  const design = score((x) => ({ rSh: x.real.dSh, rC: x.real.dCagr, mSh: x.model.dSh, mC: x.model.dCagr }));
  const byKey = new Map(grid.map((x, i) => [keyOf(x.g), i]));
  const robust = (sc) => grid.map((x, i) => {
    const vals = [sc[i]], g = x.g;
    const tryN = (dim, delta, max) => { const h = { ...g, [dim]: g[dim] + delta }; if (h[dim] < 0 || h[dim] >= max) return; if (dim === "p" && (PUTS[h.p][0] !== PUTS[g.p][0])) return; const j = byKey.get(keyOf(h)); if (j != null) vals.push(sc[j]); };
    for (const [dim, max] of [["p", PUTS.length], ["d", DTES.length], ["t", TPS.length], ["l", LOSSES.length]]) { tryN(dim, -1, max); tryN(dim, 1, max); }
    return median(vals);
  });
  // ~1 trade a month (enough to forward-test) and the project goal of 8%+ a year on real prices
  const eligible = (x) => x.real.trades >= 30 && x.real.cagr >= 0.08;
  const pick = (sc) => { let bi = -1; sc.forEach((s, i) => { if (eligible(grid[i]) && (bi < 0 || s > sc[bi])) bi = i; }); return bi; };
  const robFull = robust(full), robDes = robust(design);
  const iBest = pick(robFull), iRaw = pick(full), iDes = pick(robDes);
  const botG = BOT_G, iBot = byKey.get(keyOf(botG));
  const N = grid.length + grid.length / 2;
  const bestCfg = cfgFor(tk, grid[iBest].g), botCfg = cfgFor(tk, botG);
  const rb = measure(tk, bestCfg, "real"), rbot = measure(tk, botCfg, "real");
  const lk = luck(rb.r, rb.b, rbot.r, N);
  const summarize = (i) => ({ g: grid[i].g, cfg: cfgFor(tk, grid[i].g), real: grid[i].real, model: grid[i].model, score: +full[i].toFixed(3), robust: +robFull[i].toFixed(3),
    rankRaw: 1 + full.filter((s) => s > full[i]).length });
  const top = full.map((s, i) => [robFull[i], i]).filter(([, i]) => eligible(grid[i])).sort((a, b) => b[0] - a[0]).slice(0, 10).map(([, i]) => summarize(i));
  out.tickers[tk] = {
    nConfigs: N, best: summarize(iBest), rawTop: summarize(iRaw), bot: summarize(iBot), designPick: summarize(iDes),
    luck: lk, top10: top, seconds: Math.round((Date.now() - t0) / 1000),
  };
  const b = out.tickers[tk].best;
  console.log(`${tk}: ${N} configs in ${out.tickers[tk].seconds}s | best real ${(b.real.cagr * 100).toFixed(1)}%/yr sh ${b.real.sh.toFixed(2)} dd ${(b.real.dd * 100).toFixed(1)}% | model ${(b.model.cagr * 100).toFixed(1)}% sh ${b.model.sh.toFixed(2)} | rank ${b.rankRaw} | luck edge ${lk.edge.toFixed(2)} vs ${lk.allowance.toFixed(2)}`);
}
let prev = {};
if (fs.existsSync(path.join(__dirname, "best.js"))) { const txt = fs.readFileSync(path.join(__dirname, "best.js"), "utf8"); prev = JSON.parse(txt.slice(txt.indexOf("=") + 1).trim().replace(/;$/, "")).tickers || {}; }
out.tickers = { ...prev, ...out.tickers };
fs.writeFileSync(path.join(__dirname, "best.js"), "window.LAB_BEST = " + JSON.stringify(out) + ";\n");
console.log("wrote lab/best.js");
