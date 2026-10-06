// The rule grid searched by lab/search.js and replayed by lab/stress_null.js.
// 10 strikes x 6 expiries x 4 take-profits x 3 loss rules x 7 call rules x
// earnings on/off = 10,080 rule sets; the pricey filter doubles it on real prices.
const E = require("./engine.js");

const PUTS = [["otm", 0.05], ["otm", 0.075], ["otm", 0.10], ["otm", 0.125], ["otm", 0.15], ["delta", 0.10], ["delta", 0.15], ["delta", 0.20], ["delta", 0.25], ["delta", 0.30]];
const DTES = [7, 14, 21, 30, 45, 60], TPS = [null, 0.25, 0.5, 0.75], LOSSES = [null, 2, 3];
const CALLS = [["basis", { otm: 0.10 }], ["basis", { otm: 0.05 }], ["spot", { otm: 0.05 }], ["spot", { otm: 0.10 }], ["delta", { delta: 0.20 }], ["delta", { delta: 0.30 }], ["hybrid", { delta: 0.20, under: 0.20, otm: 0.10 }]];
const EARN = [false, true], VOLS = [null, 1.1];
const BOT_G = { p: 2, d: 1, t: 2, l: 0, c: 0, e: 0, v: 0 };

// M = the stock's measured option pricing (putMult, callMult, earnPut, earnCall).
function cfgFor(M, g) {
  const c = JSON.parse(JSON.stringify(E.BOT_RULES));
  Object.assign(c, { putMult: M.putMult, callMult: M.callMult, earnPut: M.earnPut, earnCall: M.earnCall });
  c.put.method = PUTS[g.p][0]; if (c.put.method === "otm") c.put.otm = PUTS[g.p][1]; else c.put.delta = PUTS[g.p][1];
  c.dte = DTES[g.d]; c.tp = TPS[g.t]; c.loss = LOSSES[g.l];
  c.call.method = CALLS[g.c][0]; Object.assign(c.call, CALLS[g.c][1]);
  c.skipEarnings = EARN[g.e]; c.volFilter = VOLS[g.v];
  return c;
}
// Every grid point, in search.js order; withVol adds the pricey-filter dimension.
function allGrid(withVol) {
  const out = [];
  for (let p = 0; p < PUTS.length; p++) for (let d = 0; d < DTES.length; d++) for (let t = 0; t < TPS.length; t++)
    for (let l = 0; l < LOSSES.length; l++) for (let c = 0; c < CALLS.length; c++) for (let e = 0; e < EARN.length; e++)
      for (let v = 0; v < (withVol ? VOLS.length : 1); v++) out.push({ p, d, t, l, c, e, v });
  return out;
}
const keyOf = (g) => [g.p, g.d, g.t, g.l, g.c, g.e, g.v].join(",");

module.exports = { PUTS, DTES, TPS, LOSSES, CALLS, EARN, VOLS, BOT_G, cfgFor, allGrid, keyOf };
