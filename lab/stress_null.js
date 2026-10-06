// Luck tests for the Wheel Lab's Stress test tab. Writes lab/stress.js.
//
// 1. Shuffled worlds (the "search on random data" check). Build fake price
//    histories from the stock's own daily moves, reshuffled in blocks
//    (stationary bootstrap, ~20-day blocks so calm and wild stretches stay
//    together) and re-centred so the stock earns only the T-bill rate. Options
//    are priced at fair value (implied vol = realized vol) with no spread, so
//    no rule set has an edge there. Rerun the whole model-price search (10,080
//    rule sets) on each world and record how far the best one beat the bot's
//    rules by luck alone. A real edge has to clear that distribution.
// 2. Resampled history (White's Reality Check). Keep the real daily results of
//    every rule set, resample the days in blocks (the same days for every rule
//    set), and record the largest Sharpe edge over the bot's rules after
//    removing each rule set's actual edge, so that on average nothing beats
//    the bot. This one also works on real option prices.
//
// Run: node lab/stress_null.js [--worlds 1000] [--boots 1000] [TICKER ...]
//      node lab/stress_null.js --spreads-only   (refresh the measured spreads)
const { Worker, isMainThread, parentPort } = require("worker_threads");
const fs = require("fs");
const path = require("path");
const os = require("os");

const BLOCK = 20;
const NULL_MODEL = { putMult: 1, callMult: 1, earnPut: 1, earnCall: 1 };

function loadAll() {
  global.window = {};
  eval(fs.readFileSync(path.join(__dirname, "data.js"), "utf8"));
  for (const f of fs.readdirSync(__dirname).filter((f) => /^data_[A-Z]+\.js$/.test(f))) eval(fs.readFileSync(path.join(__dirname, f), "utf8"));
  const E = require("./engine.js"), D = E.prepare(window.LAB_DATA);
  for (const [tk, T] of Object.entries(window.LAB_TICKERS || {})) E.addTicker(D, tk, T);
  return { E, D, G: require("./grid.js") };
}
function rng(seed) { // mulberry32
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
// Daily returns above T-bills for one run.
function excess(D, run) {
  const out = new Float64Array(run.len - 1);
  for (let k = 1; k < run.len; k++) {
    const i = run.i0 + k, rf = D.tbill[i - 1] * (D.day[i] - D.day[i - 1]) / 360;
    out[k - 1] = run.eq[k] / run.eq[k - 1] - 1 - rf;
  }
  return out;
}
function sharpe(x) {
  let m = 0; for (const v of x) m += v; m /= x.length;
  let s = 0; for (const v of x) s += (v - m) ** 2;
  const sd = Math.sqrt(s / (x.length - 1));
  return sd > 0 ? m / sd * Math.sqrt(252) : NaN;
}
// Stationary bootstrap: runs of consecutive days (mean length BLOCK), wrapping
// around the end. Each resample is a flat list of [start, length] pairs.
function bootBlocks(n, boots, seed) {
  const r = rng(seed), out = [];
  for (let b = 0; b < boots; b++) {
    const blocks = [];
    let t = 0;
    while (t < n) {
      const start = Math.floor(r() * n);
      let len = 1; while (r() >= 1 / BLOCK) len++;
      len = Math.min(len, n - t);
      blocks.push(start, len); t += len;
    }
    out.push(Int32Array.from(blocks));
  }
  return out;
}
function bootSharpes(x, blocks) { // Sharpe of each resample, via prefix sums over the doubled series
  const n = x.length, p1 = new Float64Array(2 * n + 1), p2 = new Float64Array(2 * n + 1);
  for (let t = 0; t < 2 * n; t++) { const v = x[t % n]; p1[t + 1] = p1[t] + v; p2[t + 1] = p2[t] + v * v; }
  const out = new Float64Array(blocks.length);
  for (let b = 0; b < blocks.length; b++) {
    const bl = blocks[b]; let s1 = 0, s2 = 0;
    for (let j = 0; j < bl.length; j += 2) { const a = bl[j], e = a + bl[j + 1]; s1 += p1[e] - p1[a]; s2 += p2[e] - p2[a]; }
    const m = s1 / n, v = (s2 - n * m * m) / (n - 1);
    out[b] = v > 0 ? m / Math.sqrt(v) * Math.sqrt(252) : NaN;
  }
  return out;
}
// A fake history built from the stock's own daily moves, reshuffled in blocks
// and re-centred to earn the T-bill rate on average.
function shuffledPath(D, tk, i1, seed) {
  const S = D.tickers[tk].S, r = rng(seed), pool = new Float64Array(i1);
  let rf = 0, m = 0;
  for (let t = 1; t <= i1; t++) { pool[t - 1] = S[t] / S[t - 1] - 1; m += pool[t - 1]; rf += D.tbill[t - 1] * (D.day[t] - D.day[t - 1]) / 360; }
  m /= i1; rf /= i1;
  for (let j = 0; j < i1; j++) pool[j] += rf - m;
  const out = new Float64Array(D.n); out[0] = S[0];
  let j = Math.floor(r() * i1);
  for (let t = 1; t < D.n; t++) {
    j = r() < 1 / BLOCK ? Math.floor(r() * i1) : (j + 1) % i1;
    out[t] = out[t - 1] * (1 + pool[j]);
  }
  return out;
}
const windowEnd = (D, E, mode) => { let i1 = D.n - 1; while (D.dates[i1] > E.WINDOWS[mode].end) i1--; return i1; };

// ---------------- worker ----------------
if (!isMainThread) {
  const { E, D, G } = loadAll();
  const gridModel = G.allGrid(false), gridReal = G.allGrid(true);
  parentPort.on("message", (task) => {
    if (task.type === "world") { // whole model search on one shuffled world
      const tk = task.tk, key = "W_" + tk;
      E.pathTicker(D, tk, key, shuffledPath(D, tk, windowEnd(D, E, "model"), task.seed), { model: NULL_MODEL });
      let best = -Infinity, bestI = -1, bot = NaN;
      gridModel.forEach((g, i) => {
        const cfg = G.cfgFor(NULL_MODEL, g); cfg.halfSpread = 0;
        const sh = sharpe(excess(D, E.simulate(D, cfg, "model", key)));
        if (sh > best) { best = sh; bestI = i; }
        if (G.keyOf(g) === G.keyOf(G.BOT_G)) bot = sh;
      });
      parentPort.postMessage({ best, bestI, bot });
    } else if (task.type === "realgrid") { // the same search on the real history
      const M = D.tickers[task.tk].model;
      parentPort.postMessage({ sh: Float64Array.from(gridModel, (g) => sharpe(excess(D, E.simulate(D, G.cfgFor(M, g), "model", task.tk)))) });
    } else if (task.type === "rc") { // Reality Check over a slice of the grid
      const grid = task.mode === "real" ? gridReal : gridModel, M = D.tickers[task.tk].model, B = task.blocks.length;
      const maxC = new Float64Array(B).fill(-Infinity), obs = new Float64Array(task.to - task.from), trades = new Int32Array(task.to - task.from);
      for (let i = task.from; i < task.to; i++) {
        const run = E.simulate(D, G.cfgFor(M, grid[i]), task.mode, task.tk), x = excess(D, run), sh = sharpe(x);
        obs[i - task.from] = sh; trades[i - task.from] = run.trades.length;
        // Only rule sets the search could pick (30+ trades) count toward the luck maximum.
        if (!Number.isFinite(sh) || run.trades.length < 30) continue;
        const star = bootSharpes(x, task.blocks), edge = sh - task.botSh;
        for (let b = 0; b < B; b++) { const c = star[b] - task.botStar[b] - edge; if (c > maxC[b]) maxC[b] = c; }
      }
      parentPort.postMessage({ maxC, obs, trades });
    }
  });
  return;
}

// ---------------- main ----------------
const args = process.argv.slice(2), flag = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? +args.splice(i, 2)[1] : dflt; };
const WORLDS = flag("--worlds", 1000), BOOTS = flag("--boots", 1000);
const { E, D, G } = loadAll();
const only = args.filter((a) => /^[A-Z]+$/.test(a));
const tickers = Object.keys(D.tickers).filter((t) => !only.length || only.includes(t));
const bestFile = path.join(__dirname, "best.js"), outFile = path.join(__dirname, "stress.js");
const readJs = (f) => { const t = fs.readFileSync(f, "utf8"); return JSON.parse(t.slice(t.indexOf("=") + 1).trim().replace(/;$/, "")); };
const BEST = readJs(bestFile).tickers;

const nWorkers = Math.max(1, os.cpus().length - 1), workers = [], idle = [], queue = [];
for (let w = 0; w < nWorkers; w++) { const wk = new Worker(__filename); workers.push(wk); idle.push(wk); }
function run(task) {
  return new Promise((resolve) => { queue.push({ task, resolve }); pump(); });
}
function pump() {
  while (idle.length && queue.length) {
    const wk = idle.pop(), { task, resolve } = queue.shift();
    wk.once("message", (msg) => { idle.push(wk); resolve(msg); pump(); });
    wk.postMessage(task);
  }
}
const r3 = (x) => Math.round(x * 1000) / 1000;
const countAtLeast = (arr, x) => arr.filter((v) => v >= x).length;
const q = (arr, p) => { const s = arr.slice().sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };

async function realityCheck(tk, mode) {
  const grid = G.allGrid(mode === "real"), byKey = new Map(grid.map((g, i) => [G.keyOf(g), i]));
  const botX = excess(D, E.simulate(D, G.cfgFor(D.tickers[tk].model, G.BOT_G), mode, tk));
  const blocks = bootBlocks(botX.length, BOOTS, 7919 + (mode === "real" ? 1 : 2)), botStar = bootSharpes(botX, blocks), botSh = sharpe(botX);
  const chunk = 600, parts = [];
  for (let from = 0; from < grid.length; from += chunk) parts.push(run({ type: "rc", tk, mode, from, to: Math.min(grid.length, from + chunk), blocks, botStar, botSh }));
  const res = await Promise.all(parts), nullMax = new Float64Array(BOOTS).fill(-Infinity), obs = [], trades = [];
  for (const r of res) { for (let b = 0; b < BOOTS; b++) nullMax[b] = Math.max(nullMax[b], r.maxC[b]); obs.push(...r.obs); trades.push(...r.trades); }
  let maxI = -1; obs.forEach((s, i) => { if (trades[i] >= 30 && (maxI < 0 || s > obs[maxI])) maxI = i; });
  const pg = { ...BEST[tk].best.g }; if (mode === "model") pg.v = 0;
  const pickEdge = obs[byKey.get(G.keyOf(pg))] - botSh, maxEdge = obs[maxI] - botSh, nm = Array.from(nullMax);
  return { boots: BOOTS, block: BLOCK, configs: grid.length, eligible: trades.filter((t) => t >= 30).length, days: botX.length, botSharpe: r3(botSh), pickEdge: r3(pickEdge), maxEdge: r3(maxEdge), maxG: grid[maxI],
           beatPick: countAtLeast(nm, pickEdge), beatMax: countAtLeast(nm, maxEdge), q95: r3(q(nm, 0.95)), nullMax: nm.map(r3) };
}
async function shuffledWorlds(tk) {
  const grid = G.allGrid(false), real = await run({ type: "realgrid", tk });
  const botI = grid.findIndex((g) => G.keyOf(g) === G.keyOf(G.BOT_G)), pg = { ...BEST[tk].best.g, v: 0 }, pickI = grid.findIndex((g) => G.keyOf(g) === G.keyOf(pg));
  let maxI = 0; real.sh.forEach((s, i) => { if (s > real.sh[maxI]) maxI = i; });
  let done = 0;
  const worlds = await Promise.all(Array.from({ length: WORLDS }, (_, w) => run({ type: "world", tk, seed: 1000 + w }).then((r) => {
    if (++done % 50 === 0) console.log(`  ${tk} shuffled worlds: ${done}/${WORLDS}`);
    return r;
  })));
  const edges = worlds.map((w) => w.best - w.bot), pickEdge = real.sh[pickI] - real.sh[botI], maxEdge = real.sh[maxI] - real.sh[botI];
  return { worlds: WORLDS, block: BLOCK, configs: grid.length, botSharpe: r3(real.sh[botI]), pickSharpe: r3(real.sh[pickI]), maxSharpe: r3(real.sh[maxI]), maxG: grid[maxI],
           pickEdge: r3(pickEdge), maxEdge: r3(maxEdge), beatPick: countAtLeast(edges, pickEdge), beatMax: countAtLeast(edges, maxEdge), q95: r3(q(edges, 0.95)),
           nullEdge: edges.map(r3), nullBest: worlds.map((w) => r3(w.best)), nullBot: worlds.map((w) => r3(w.bot)) };
}
function spreads() {
  const out = {};
  for (const tk of Object.keys(D.tickers)) {
    const f = path.join(__dirname, "..", "research", "data", `spreads_${tk}.json`);
    if (!fs.existsSync(f)) continue;
    const s = JSON.parse(fs.readFileSync(f, "utf8"));
    out[tk] = { source: s.source || "Alpaca indicative feed", asof: s.asof, n: s.n, medianPct: s.medianPct, buckets: s.buckets, wild: s.wild || null };
  }
  return out;
}

if (args.includes("--spreads-only")) {
  const prev = fs.existsSync(outFile) ? readJs(outFile) : { tickers: {} };
  fs.writeFileSync(outFile, "window.LAB_STRESS = " + JSON.stringify({ ...prev, spreads: spreads() }) + ";\n");
  console.log("refreshed spreads in lab/stress.js");
  process.exit(0);
}
(async () => {
  const prev = fs.existsSync(outFile) ? readJs(outFile) : { tickers: {} };
  const out = { generated: new Date().toISOString().slice(0, 16), spreads: spreads(), tickers: { ...prev.tickers } };
  for (const tk of tickers) {
    const t0 = Date.now();
    const rcReal = await realityCheck(tk, "real"), rcModel = await realityCheck(tk, "model");
    console.log(`${tk} reality check: real pick edge ${rcReal.pickEdge} beaten by luck in ${rcReal.beatPick}/${BOOTS}; model pick edge ${rcModel.pickEdge} in ${rcModel.beatPick}/${BOOTS} (${Math.round((Date.now() - t0) / 1000)}s)`);
    const sh = await shuffledWorlds(tk);
    console.log(`${tk} shuffled worlds: pick edge ${sh.pickEdge} beaten in ${sh.beatPick}/${WORLDS}; grid max ${sh.maxEdge} in ${sh.beatMax}; null 95% ${sh.q95} (${Math.round((Date.now() - t0) / 1000)}s)`);
    out.tickers[tk] = { shuffle: sh, rc: { real: rcReal, model: rcModel }, seconds: Math.round((Date.now() - t0) / 1000) };
    fs.writeFileSync(outFile, "window.LAB_STRESS = " + JSON.stringify(out) + ";\n");
  }
  console.log("wrote lab/stress.js");
  for (const w of workers) w.terminate();
})();
