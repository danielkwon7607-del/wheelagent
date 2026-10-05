// Checks the browser engine against the Python research engine.
// Run: node lab/parity_test.js   (after lab/build_data.py)
const fs = require("fs");
const path = require("path");
global.window = {};
eval(fs.readFileSync(path.join(__dirname, "data.js"), "utf8"));
const E = require("./engine.js");
const D = E.prepare(window.LAB_DATA);
const ref = window.LAB_DATA.reference;

const variant = (over) => {
  const c = JSON.parse(JSON.stringify(E.BOT_RULES));
  for (const [k, v] of Object.entries(over)) if (typeof v === "object" && v && !Array.isArray(v)) Object.assign(c[k], v); else c[k] = v;
  return c;
};
const cases = {
  real_current: ["real", variant({})],
  real_otm5_dte45_tp50: ["real", variant({ put: { otm: 0.05 }, dte: 45 })],
  real_callspot5: ["real", variant({ call: { method: "spot", otm: 0.05 } })],
  model_current: ["model", variant({})],
  model_dte45: ["model", variant({ dte: 45 })],
  model_callspot5: ["model", variant({ call: { method: "spot", otm: 0.05 } })],
};
let fails = 0;
for (const [name, [mode, cfg]] of Object.entries(cases)) {
  const run = E.simulate(D, cfg, mode);
  const b = E.benchmarks(D, run.i0, run.i1);
  const m = E.metrics(D, run, run.eq, b.tbill);
  const r = ref[name];
  const diffs = {
    cagr: m.cagr - r.cagr, sharpe: m.sharpe - r.sharpe, max_dd: m.maxDD - r.max_dd, trades: run.trades.length - r.trades,
  };
  const ok = Math.abs(diffs.cagr) < 0.002 && Math.abs(diffs.sharpe) < 0.02 && Math.abs(diffs.max_dd) < 0.002 && Math.abs(diffs.trades) <= 1;
  if (!ok) fails++;
  console.log(`${ok ? "PASS" : "FAIL"} ${name.padEnd(22)} cagr ${(m.cagr * 100).toFixed(2)} vs ${(r.cagr * 100).toFixed(2)} | sharpe ${m.sharpe.toFixed(3)} vs ${r.sharpe.toFixed(3)} | maxDD ${(m.maxDD * 100).toFixed(2)} vs ${(r.max_dd * 100).toFixed(2)} | trades ${run.trades.length} vs ${r.trades}`);
}
process.exit(fails ? 1 : 0);
