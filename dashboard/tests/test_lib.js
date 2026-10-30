"use strict";
const assert = require("assert");
const path = require("path");
const { execFileSync } = require("child_process");
const L = require("../lib.js");

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; console.log("ok   " + name); }
  catch (e) { failed++; console.log("FAIL " + name + "\n     " + e.message); }
}
const near = (a, b, eps = 1e-9) => Math.abs(a - b) < eps;

/* README worked example: TSLA, Oct 19 2026 */
t("plan: TSLA or-mid stop rounds down to 358.32", () => {
  const p = L.computePlan({ entry: 364.18, stopRule: "or_mid", orHigh: 362.18, orLow: 354.47, targetRule: "r", targetParam: 1 });
  assert.strictEqual(p.stop, 358.32);
  assert.ok(near(p.risk, 5.86));
  assert.strictEqual(p.target, 370.04);
  assert.strictEqual(p.rr, 1);
});
t("size: TSLA $5,000 / $50 max loss = 8 shares, $2,913.44, loss $46.88", () => {
  const s = L.sizeTrade({ entry: 364.18, stop: 358.32, target: 370.04 }, { budget: 5000, max_loss_per_trade_usd: 50 });
  assert.strictEqual(s.qty, 8);
  assert.ok(near(s.cost, 2913.44));
  assert.ok(near(s.maxLoss, 46.88));
  assert.strictEqual(s.boundBy, "Max loss");
  assert.strictEqual(s.refusal, null);
});
t("plan: 2R default target", () => {
  const p = L.computePlan({ entry: 100, stopRule: "price", stopParam: 98, targetRule: "r", targetParam: 2 });
  assert.strictEqual(p.target, 104); assert.strictEqual(p.rr, 2);
});
t("plan: pct stop and atr stop", () => {
  assert.strictEqual(L.computePlan({ entry: 100, stopRule: "pct", stopParam: 2, targetRule: "r", targetParam: 2 }).stop, 98);
  assert.strictEqual(L.computePlan({ entry: 100, stopRule: "atr", stopParam: 1.5, atr: 0.8, targetRule: "r", targetParam: 2 }).stop, 98.8);
});
t("plan: explicit price target and R label", () => {
  const p = L.computePlan({ entry: 50, stopRule: "price", stopParam: 49, targetRule: "price", targetParam: 53 });
  assert.strictEqual(p.rr, 3);
});
t("plan: errors are plain and specific", () => {
  assert.match(L.computePlan({ entry: 0, stopRule: "price", stopParam: 1 }).error, /above \$0/);
  assert.match(L.computePlan({ entry: 100, stopRule: "price", stopParam: 101, targetRule: "r" }).error, /at or above the entry/);
  assert.match(L.computePlan({ entry: 100, stopRule: "price", stopParam: 99.99, targetRule: "r" }).error, /tighter than 0.05%/);
  assert.match(L.computePlan({ entry: 100, stopRule: "or_mid", orHigh: 90, orLow: 95 }).error, /above the range low/);
  assert.match(L.computePlan({ entry: 100, stopRule: "or_mid" }).error, /needs the range/);
  assert.match(L.computePlan({ entry: 100, stopRule: "price", stopParam: 99, targetRule: "price", targetParam: 99 }).error, /at or below the entry/);
  assert.match(L.computePlan({ entry: 100, stopRule: "pct", stopParam: 150 }).error, /between 0 and 100/);
  assert.match(L.computePlan({ entry: 100, stopRule: "atr", stopParam: 1 }).error, /ATR value/);
  assert.match(L.computePlan({ entry: "abc", stopRule: "price" }).error, /above \$0/);
});
t("size: stop too wide for max loss gives 0 shares and a refusal", () => {
  const s = L.sizeTrade({ entry: 648, stop: 600, target: 700 }, { budget: 5000, max_loss_per_trade_usd: 40 });
  assert.strictEqual(s.qty, 0); assert.match(s.refusal, /max loss/);
});
t("size: cash limit binds on an expensive stock", () => {
  const s = L.sizeTrade({ entry: 1000, stop: 999, target: 1002 }, { budget: 5000, max_loss_per_trade_usd: 500 });
  assert.ok(s.qty <= 4); assert.ok(s.cost <= 4500);
});
t("size: reward:risk below minimum refuses", () => {
  const s = L.sizeTrade({ entry: 100, stop: 98, target: 101 }, { budget: 5000, min_reward_risk: 1.5 });
  assert.match(s.refusal, /Reward:risk 0.50/);
});
t("size: errors for bad input", () => {
  assert.ok(L.sizeTrade({ entry: 10, stop: 11, target: 12 }, {}).error);
  assert.ok(L.sizeTrade({ entry: 10, stop: 9, target: 9 }, {}).error);
  assert.ok(L.sizeTrade({ entry: 10, stop: 9, target: 12 }, { budget: 0 }).error);
  assert.ok(L.sizeTrade({ entry: "", stop: 9, target: 12 }, {}).error);
});
t("risk: PASS on a clean trade, BLOCK on daily loss and trade count", () => {
  const plan = { entry: 364.18, stop: 358.32, target: 370.04 };
  const s = L.sizeTrade(plan, { budget: 5000, max_loss_per_trade_usd: 50 });
  assert.strictEqual(L.riskCheck(plan, s, {}, { riskedToday: 0, tradesToday: 0 }).verdict, "PASS");
  assert.strictEqual(L.riskCheck(plan, s, {}, { riskedToday: 120, tradesToday: 0 }).verdict, "BLOCK");
  assert.strictEqual(L.riskCheck(plan, s, {}, { riskedToday: 0, tradesToday: 3 }).verdict, "BLOCK");
});
t("risk: entry window enforced only while market is open", () => {
  const plan = { entry: 100, stop: 98, target: 104 };
  const s = L.sizeTrade(plan, {});
  assert.strictEqual(L.riskCheck(plan, s, {}, { nowET: "09:40", marketOpen: true }).verdict, "BLOCK");
  assert.strictEqual(L.riskCheck(plan, s, {}, { nowET: "10:15", marketOpen: true }).verdict, "PASS");
  assert.strictEqual(L.riskCheck(plan, s, {}, { nowET: "15:45", marketOpen: true }).verdict, "BLOCK");
  assert.strictEqual(L.riskCheck(plan, s, {}, { nowET: "22:00", marketOpen: false }).verdict, "BLOCK");
});
t("risk: invalid sizing blocks with the reason", () => {
  const r = L.riskCheck({}, { error: "nope" }, {}, {});
  assert.strictEqual(r.verdict, "BLOCK"); assert.strictEqual(r.checks[0].detail, "nope");
});

/* market hours */
t("market: weekday open/closed/pre/after in NY time (EDT)", () => {
  assert.strictEqual(L.marketStatus(new Date("2026-10-29T14:00:00Z")).state, "open");   // 10:00 ET Thu
  assert.strictEqual(L.marketStatus(new Date("2026-10-29T12:00:00Z")).state, "pre");    // 08:00 ET
  assert.strictEqual(L.marketStatus(new Date("2026-10-29T20:30:00Z")).state, "after");  // 16:30 ET
  assert.strictEqual(L.marketStatus(new Date("2026-10-30T03:00:00Z")).state, "closed"); // 23:00 ET
  assert.strictEqual(L.marketStatus(new Date("2026-10-31T15:00:00Z")).state, "closed"); // Saturday
});
t("market: EST after daylight saving ends, and holidays", () => {
  assert.strictEqual(L.marketStatus(new Date("2026-11-02T14:30:00Z")).state, "open");   // 09:30 EST Mon
  assert.strictEqual(L.marketStatus(new Date("2026-11-02T14:29:00Z")).state, "pre");
  assert.strictEqual(L.marketStatus(new Date("2026-11-26T15:00:00Z")).state, "closed"); // Thanksgiving
});
t("market: early close day is open at 12:30 ET and after at 13:30 ET", () => {
  assert.strictEqual(L.marketStatus(new Date("2026-11-27T17:30:00Z")).state, "open");
  assert.strictEqual(L.marketStatus(new Date("2026-11-27T18:30:00Z")).state, "after");
});

/* cash-secured puts */
t("csp: KEY 19.5 put at 0.35", () => {
  const c = L.cspCalc({ price: 21.21, strike: 19.5, premium: 0.35, dte: 35, account: 5000, riskPct: 1 });
  assert.strictEqual(c.cashPerContract, 1950);
  assert.ok(near(c.creditPerContract, 35));
  assert.ok(near(c.breakeven, 19.15));
  assert.ok(near(c.returnPct, 0.35 / 19.15 * 100, 1e-9));
  assert.ok(near(c.loss20, 19.15 * 100 * 0.2, 1e-9));
  assert.strictEqual(c.fitsAccount, 2);
  assert.strictEqual(c.contractsByRisk, 0);      // 1% of 5000 = 50 < 383
  assert.strictEqual(c.contracts, 0);
  assert.ok(c.otmPct > 8 && c.otmPct < 9);
});
t("csp: contracts rise with account", () => {
  const c = L.cspCalc({ price: 21.21, strike: 19.5, premium: 0.35, dte: 35, account: 50000, riskPct: 2 });
  assert.strictEqual(c.contractsByRisk, 2); assert.strictEqual(c.contracts, 2);
});
t("csp: errors", () => {
  assert.ok(L.cspCalc({ price: 0, strike: 1, premium: 1, dte: 1 }).error);
  assert.ok(L.cspCalc({ price: 10, strike: 9, premium: 9, dte: 10 }).error);
  assert.ok(L.cspCalc({ price: 10, strike: 9, premium: 0.2, dte: 0 }).error);
});

/* scan filter */
const rows = [
  ["AAA", "Alpha Inc", 10, 25, 2000000, ["oversold"]],
  ["BBB", "Beta Corp", 50, 65, 9000000, ["breakout_20d", "bull_flag"]],
  ["ABC", "Gamma Ltd", 200, 55, 1500000, ["bull_flag"]]
];
t("filter: price cap, setup, query, sort", () => {
  assert.deepStrictEqual(L.filterScan(rows, { maxPrice: 60 }).map(r => r[0]), ["BBB", "AAA"]);       // dollar volume desc
  assert.deepStrictEqual(L.filterScan(rows, { setup: "bull_flag" }).map(r => r[0]), ["BBB", "ABC"]);
  assert.deepStrictEqual(L.filterScan(rows, { query: "a" }).map(r => r[0]).sort(), ["AAA", "ABC", "BBB"].sort()); // symbol prefix or name
  assert.deepStrictEqual(L.filterScan(rows, { query: "alp" }).map(r => r[0]), ["AAA"]);
  assert.deepStrictEqual(L.filterScan(rows, { sort: "price", dir: "asc" }).map(r => r[0]), ["AAA", "BBB", "ABC"]);
  assert.deepStrictEqual(L.filterScan(rows, { sort: "symbol", dir: "asc" }).map(r => r[0]), ["AAA", "ABC", "BBB"]);
  assert.deepStrictEqual(L.filterScan(rows, { sort: "rsi", dir: "desc" }).map(r => r[0]), ["BBB", "ABC", "AAA"]);
  assert.deepStrictEqual(L.filterScan(rows, { minVolume: 2000000 }).map(r => r[0]), ["BBB", "AAA"]);
  assert.deepStrictEqual(L.filterScan(rows, { exclude: ["BBB"] }).map(r => r[0]), ["ABC", "AAA"]);
  assert.strictEqual(L.filterScan(rows, { query: "zzz" }).length, 0);
});
t("filter: real scan file loads and filters", () => {
  const d = require("../data/scan.json");
  assert.strictEqual(d.hits.length, 707);
  const cheap = L.filterScan(d.hits, { maxPrice: 50 });
  assert.ok(cheap.length > 50 && cheap.every(r => r[2] <= 50));
  const names = d.hits.filter(r => r[1]).length;
  assert.ok(names > 650, "most rows should have names");
});

/* Parity with the real Python tools on random inputs */
t("parity: computePlan and sizeTrade match exit.py / size.py on 300 random cases", () => {
  const root = path.resolve(__dirname, "../../.claude/skills");
  const py = `
import importlib.util, json, random, sys
def load(n,p):
    s=importlib.util.spec_from_file_location(n,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
ex=load("ex","${root}/trader-exit/exit.py"); sz=load("sz","${root}/trader-budget/size.py")
random.seed(7); out=[]
for i in range(300):
    e=round(random.uniform(2,900),2); w=random.uniform(0.002,0.06)
    kind=random.choice(["pct","or_mid","price"])
    r=random.choice([1,1.5,2,3])
    try:
        if kind=="pct":
            pr=round(random.uniform(0.2,5),2); c=ex.compute(ex.D(e),"pct",ex.D(pr),"r",ex.D(r)); a=dict(entry=e,stopRule="pct",stopParam=pr,targetRule="r",targetParam=r)
        elif kind=="or_mid":
            hi=round(e*(1-random.uniform(0,0.01)),2); lo=round(hi*(1-w),2); c=ex.compute(ex.D(e),"or_mid",None,"r",ex.D(r),or_high=ex.D(hi),or_low=ex.D(lo)); a=dict(entry=e,stopRule="or_mid",orHigh=hi,orLow=lo,targetRule="r",targetParam=r)
        else:
            sp=round(e*(1-w),2); c=ex.compute(ex.D(e),"price",ex.D(sp),"r",ex.D(r)); a=dict(entry=e,stopRule="price",stopParam=sp,targetRule="r",targetParam=r)
    except Exception as ex_:
        out.append(dict(a=None,err=str(ex_))); continue
    plan=dict(symbol="TST",entry=float(c["entry"]),stop=float(c["stop"]),target=float(c["target"]))
    cfg=dict(budget=random.choice([2000,5000,25000]),max_loss_per_trade_usd=random.choice([25,50,200]),min_reward_risk=0)
    try:
        s=sz.size_trade(plan,cfg); sd=dict(qty=s["qty"],cost=s["cost"],loss=s["max_loss"],bound=s["bound_by"])
    except Exception as e2: sd=dict(err=str(e2))
    out.append(dict(a=a,stop=float(c["stop"]),target=float(c["target"]),rr=float(c["reward_risk"]),plan=plan,cfg=cfg,size=sd))
print(json.dumps(out))`;
  const cases = JSON.parse(execFileSync("python3", ["-c", py], { maxBuffer: 1 << 26 }).toString());
  let compared = 0, planErrs = 0;
  cases.forEach((c, i) => {
    if (!c.a) { const j = L.computePlan({ entry: 100, stopRule: "price", stopParam: 100 }); assert.ok(j.error); planErrs++; return; }
    const j = L.computePlan(c.a);
    assert.ok(!j.error, "case " + i + " js error " + j.error + " " + JSON.stringify(c.a));
    assert.ok(near(j.stop, c.stop, 1e-9), "stop mismatch case " + i + " " + j.stop + " vs " + c.stop);
    assert.ok(near(j.target, c.target, 1e-9), "target mismatch case " + i + " " + j.target + " vs " + c.target);
    assert.ok(near(j.rr, c.rr, 1e-9), "rr mismatch case " + i);
    if (c.size.err) return;
    const s = L.sizeTrade(c.plan, Object.assign({ cash_buffer_pct: 10, max_position_pct: 75, max_order_usd: 4000 }, c.cfg));
    assert.strictEqual(s.qty, c.size.qty, "qty mismatch case " + i + " js " + s.qty + " py " + c.size.qty + " " + JSON.stringify(c.plan) + JSON.stringify(c.cfg));
    assert.ok(near(s.cost, c.size.cost, 0.006), "cost mismatch case " + i);
    assert.ok(near(s.maxLoss, c.size.loss, 0.006), "loss mismatch case " + i);
    compared++;
  });
  assert.ok(compared > 150, "compared " + compared);
  console.log("     compared " + compared + " sized cases, " + planErrs + " python refusals");
});

console.log("\n" + passed + " passed, " + failed + " failed");
process.exit(failed ? 1 : 0);
