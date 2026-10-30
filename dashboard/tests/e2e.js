const puppeteer = require("puppeteer-core");
const http = require("http"), fs = require("fs"), path = require("path");
const ROOT = "/Users/malavshah/Desktop/DAY TRADER SKILL/dashboard";
const OUT = path.join(__dirname, "shots"); fs.mkdirSync(OUT, { recursive: true });
const MIME = { ".html": "text/html", ".json": "application/json", ".js": "text/javascript" };
const srv = http.createServer((q, r) => {
  let p = decodeURIComponent(q.url.split("?")[0]); if (p === "/") p = "/index.html";
  const f = path.join(ROOT, p);
  if (!f.startsWith(ROOT) || !fs.existsSync(f)) { r.writeHead(404); return r.end("nf"); }
  let body = fs.readFileSync(f);
  if (p === "/index.html") body = '<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0;font:14px system-ui;background:#fafafa}img{max-width:100%}[hidden]{display:none!important}</style></head><body>' + body + "</body></html>";
  r.writeHead(200, { "content-type": MIME[path.extname(f)] || "text/plain" }); r.end(body);
});

const MOCK = (mode) => `(() => {
  const mode = ${JSON.stringify(mode)};
  if (mode === "none") return;
  const store = new Map(); const listeners = [];
  const notify = () => listeners.forEach(l => l());
  const snapDoc = (id, data) => ({ id, exists: data !== undefined, data: () => data, metadata: {} });
  const doc = (p) => ({ id: p.split("/").pop(), path: p,
    get: async () => snapDoc(p.split("/").pop(), store.get(p)),
    set: async (d) => { store.set(p, JSON.parse(JSON.stringify(d))); notify(); },
    update: async (d) => { if (!store.has(p)) throw {code:"invalid_argument",message:"missing"}; store.set(p, Object.assign({}, store.get(p), d)); notify(); },
    delete: async () => { store.delete(p); notify(); },
    onSnapshot: (next) => { const f = () => next(snapDoc(p.split("/").pop(), store.get(p))); listeners.push(f); setTimeout(f, 0); return () => {}; } });
  const coll = (c, ord, lim) => ({
    path: c,
    orderBy: (f, d) => coll(c, [f, d], lim), limit: (n) => coll(c, ord, n),
    doc: (id) => doc(c + "/" + (id || Math.random().toString(36).slice(2, 10))),
    add: async (d) => { const r = doc(c + "/" + Math.random().toString(36).slice(2, 10)); await r.set(d); return r; },
    onSnapshot: (next) => { const f = () => {
        let docs = [...store.entries()].filter(([k]) => k.startsWith(c + "/") && k.split("/").length === c.split("/").length + 1).map(([k, v]) => snapDoc(k.split("/").pop(), v));
        if (ord) docs.sort((a, b) => String(b.data()[ord[0]]).localeCompare(String(a.data()[ord[0]])) * (ord[1] === "asc" ? -1 : 1));
        next({ docs, size: docs.length, empty: !docs.length, docChanges: () => [], metadata: {} }); };
      listeners.push(f); setTimeout(f, 0); return () => {}; } });
  window.__store = store;
  const sample = async (input, opts) => {
    window.__lastSample = input;
    if (mode === "samplefail") throw { code: "rate_limited", message: "x" };
    const full = "Mock answer. The stop sits below the range; watch earnings. Educational, not financial advice.";
    for (let i = 3; i <= full.length; i += 12) {
      if (opts.signal && opts.signal.aborted) throw { code: "cancelled", message: "c", text: full.slice(0, i) };
      opts.onText({ text: full.slice(0, i), delta: "" }); await new Promise(r => setTimeout(r, mode === "slow" ? 400 : 5));
      if (opts.signal && opts.signal.aborted) throw { code: "cancelled", message: "c", text: full.slice(0, i) };
    }
    opts.onText({ text: full, delta: "" }); return { text: full, truncated: false };
  };
  window.claude = { use: async (n) => n === "db" ? (mode === "nodb" ? null : { doc, collection: (c) => coll(c) }) : n === "sample" ? (mode === "nosample" ? null : sample) : null };
})();`;

let failures = 0;
function check(name, cond, extra) { if (cond) console.log("ok   " + name); else { failures++; console.log("FAIL " + name + (extra ? "  -> " + extra : "")); } }

(async () => {
  await new Promise(r => srv.listen(0, r)); const port = srv.address().port; const base = "http://127.0.0.1:" + port + "/";
  const browser = await puppeteer.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: "new", args: ["--no-sandbox"] });

  async function open(mode, vp, scheme) {
    const page = await browser.newPage();
    const errs = []; page.__errs = errs;
    page.on("pageerror", e => errs.push("pageerror: " + e.message));
    page.on("console", m => { if (m.type() === "error" && !/fonts\.g|ERR_|Failed to load resource/.test(m.text())) errs.push("console: " + m.text()); });
    page.on("requestfailed", r => { if (!/fonts\.g/.test(r.url())) errs.push("reqfail: " + r.url()); });
    await page.setViewport(vp || { width: 1280, height: 900 });
    await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme || "light" }]);
    await page.evaluateOnNewDocument(MOCK(mode));
    await page.goto(base, { waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("#view .card, #view .empty"), { timeout: 8000 });
    await new Promise(r => setTimeout(r, 150));
    return page;
  }
  const text = (p, sel) => p.$eval(sel, e => e.innerText);
  const click = async (p, sel) => { await p.click(sel); await new Promise(r => setTimeout(r, 60)); };
  const tab = async (p, v) => { await click(p, `[data-act=tab][data-v=${v}]`); };
  const type = async (p, sel, val) => { await p.$eval(sel, e => { e.focus(); if (e.select) e.select(); }); await p.keyboard.press("Backspace"); if (val) await p.type(sel, val); await new Promise(r => setTimeout(r, 60)); };

  /* ---------- 1. full db + sample mode ---------- */
  let p = await open("full");
  check("initial render has Today content", /Market read/.test(await text(p, "#view")));
  check("clock shows ET", /ET/.test(await text(p, "#clock")));
  check("asof shows scan date", /scan 2026-10-29/.test(await text(p, "#asof")));
  for (const [id] of [["today"], ["scanner"], ["planner"], ["options"], ["news"], ["journal"], ["ask"], ["settings"]]) {
    await tab(p, id);
    const t = await text(p, "#view");
    check("tab " + id + " renders without undefined/NaN", t.length > 40 && !/undefined|NaN|\[object|Infinity/.test(t), t.match(/.{0,30}(undefined|NaN|\[object|Infinity).{0,30}/) + "");
  }
  // scanner
  await tab(p, "scanner");
  check("scanner shows rows", (await p.$$("#scan-b tr.clk")).length === 50);
  await type(p, "#f-q", "tsla");
  const rowsTsla = await p.$$eval("#scan-b tr", t => t.map(x => x.innerText));
  check("scanner search narrows", rowsTsla.length < 10, rowsTsla.length + "");
  await type(p, "#f-q", "");
  await click(p, '[data-act=setup][data-v=oversold]');
  const nOver = (await p.$$("#scan-b tr.clk")).length; check("setup chip filters to oversold (<=50)", nOver > 0 && nOver <= 50, nOver + "");
  await click(p, '[data-act=setup][data-v=all]');
  await p.evaluate(() => { const c = document.getElementById("f-fit"); c.checked = true; c.dispatchEvent(new Event("input", { bubbles: true })); });
  await new Promise(r => setTimeout(r, 80));
  const prices = await p.$$eval("#scan-b tr.clk td:nth-child(2)", t => t.map(x => parseFloat(x.innerText)));
  check("fits-my-account caps price at $3,750", prices.length > 0 && prices.every(x => x <= 3750), Math.max(...prices) + "");
  await p.evaluate(() => { const c = document.getElementById("f-fit"); c.checked = false; c.dispatchEvent(new Event("input", { bubbles: true })); });
  await click(p, '[data-act=sort][data-v=price]');
  const p1 = await p.$$eval("#scan-b tr.clk td:nth-child(2)", t => t.map(x => parseFloat(x.innerText)));
  check("sort by price desc", p1.every((v, i) => i === 0 || p1[i - 1] >= v));
  await click(p, '[data-act=sort][data-v=price]');
  const p2 = await p.$$eval("#scan-b tr.clk td:nth-child(2)", t => t.map(x => parseFloat(x.innerText)));
  check("sort toggles to asc", p2.every((v, i) => i === 0 || p2[i - 1] <= v));
  await click(p, '[data-act=more]'); check("show 50 more", (await p.$$("#scan-b tr.clk")).length === 100);
  await type(p, "#f-q", "KEY");
  await click(p, "#scan-b tr.clk");
  check("drawer opens", !!(await p.$(".drawer")));
  check("drawer shows symbol + headlines section", /KEY/.test(await text(p, ".drawer")) && /Headlines/.test(await text(p, ".drawer")));
  await p.keyboard.press("Escape"); await new Promise(r => setTimeout(r, 50));
  check("Esc closes drawer", !(await p.$(".drawer")));
  // news-bearing name -> headline link safety
  await type(p, "#f-q", "AAPL"); await click(p, "#scan-b tr.clk");
  const links = await p.$$eval(".drawer a", a => a.map(x => [x.href, x.rel, x.target]));
  check("drawer headline links open safely", links.length > 0 && links.every(l => /^https?:/.test(l[0]) && /noopener/.test(l[1]) && l[2] === "_blank"), JSON.stringify(links.slice(0, 1)));
  await click(p, '[data-act=plan]');
  check("Plan this trade switches tab and prefills entry", (await text(p, ".tab[aria-selected=true]")) === "Planner" && /^\d+\.\d\d$/.test(await p.$eval("#p-entry", e => e.value)));
  // planner example numbers
  await p.reload({ waitUntil: "load" }); await p.waitForFunction(() => document.querySelector("#view .card"));
  await tab(p, "planner");
  let out = await text(p, "#p-out");
  check("planner example: stop 358.32, target 370.04, 8 shares", /358\.32/.test(out) && /370\.04/.test(out) && /\b8\b/.test(out), out.slice(0, 200));
  check("planner example verdict is PASS or BLOCK (market-hours dependent)", /PASS|BLOCK/.test(out));
  check("planner ticket text", /BUY 8 TSLA @ 364\.18 limit/.test(await text(p, "#p-ticket")));
  await type(p, "#p-entry", "0"); out = await text(p, "#p-out");
  check("planner entry 0 -> plain error", /above \$0/.test(out) && /BLOCK|Plan/.test(out) === true);
  await type(p, "#p-entry", "100");
  await p.select("#p-stopRule", "price"); await type(p, "#p-stopParam", "101");
  check("planner stop above entry -> error", /at or above the entry/.test(await text(p, "#p-out")));
  await type(p, "#p-stopParam", "98"); await type(p, "#p-targetParam", "2");
  out = await text(p, "#p-out"); check("planner price stop 98, 2R target 104", /98\.00/.test(out) && /104\.00/.test(out) && /2\.00 : 1/.test(out), out.slice(0, 160));
  await p.select("#p-stopRule", "atr"); await type(p, "#p-atr", "1"); await type(p, "#p-stopParam", "1.5");
  check("planner ATR stop 98.50", /98\.50/.test(await text(p, "#p-out")));
  await p.select("#p-stopRule", "pct"); await type(p, "#p-stopParam", "2");
  check("planner pct stop 98.00", /98\.00/.test(await text(p, "#p-out")));
  await p.select("#p-targetRule", "price"); await type(p, "#p-targetParam", "95");
  check("planner price target below entry -> error", /at or below the entry/.test(await text(p, "#p-out")));
  await p.select("#p-targetRule", "r"); await type(p, "#p-targetParam", "2");
  // log to journal
  await click(p, '[data-act=logplan]'); await new Promise(r => setTimeout(r, 150));
  const logged = await p.evaluate(() => [...window.__store.keys()].filter(k => k.startsWith("journal/")).length);
  check("log plan writes a journal doc to db", logged === 1, logged + "");
  await tab(p, "journal");
  check("journal shows logged trade", /TSLA/.test(await text(p, "#view")) && /1 \/ 3/.test(await text(p, "#view")));
  // add trade
  await type(p, "#j-sym", "abc"); await type(p, "#j-entry", "10"); await type(p, "#j-stop", "11"); await type(p, "#j-qty", "5");
  await click(p, '[data-act=jadd]'); check("journal rejects stop above entry", /under the entry/.test(await text(p, "#j-err")));
  await type(p, "#j-stop", "9"); await click(p, '[data-act=jadd]'); await new Promise(r => setTimeout(r, 150));
  check("journal adds ABC", /ABC/.test(await text(p, "#view")));
  await p.evaluate(() => { const i = document.querySelector("input[id^=x-]"); i.value = "12"; });
  await click(p, '[data-act=jclose]'); await new Promise(r => setTimeout(r, 150));
  const jt = await text(p, "#view"); check("journal close computes P&L +$10.00, 100% win, 2.00 R", /\$10\.00/.test(jt) && /100%/.test(jt) && /2\.00 avg R/.test(jt), jt.slice(0, 300));
  await click(p, '[data-act=jdel][aria-label*=ABC]'); await new Promise(r => setTimeout(r, 150));
  check("journal delete removes ABC", !/ABC/.test(await text(p, "#view")));
  // options
  await tab(p, "options");
  out = await text(p, "#c-out");
  check("csp example: cash $1,950, breakeven 19.15, 0 contracts", /\$1,950/.test(out) && /19\.15/.test(out) && /Suggested contracts\s*0/.test(out.replace(/\n/g, " ")), out.slice(0, 300));
  await type(p, "#c-account", "50000"); await type(p, "#c-riskPct", "2");
  check("csp bigger account -> 2 contracts", /Suggested contracts\s*2/.test((await text(p, "#c-out")).replace(/\n/g, " ")));
  await type(p, "#c-symbol", "PFE"); await type(p, "#c-expiry", "");
  await p.evaluate(() => { const e = document.getElementById("c-expiry"); e.value = "2026-12-04"; e.dispatchEvent(new Event("input", { bubbles: true })); });
  await new Promise(r => setTimeout(r, 80));
  check("csp earnings before expiry warns (PFE Nov 3)", /reports Nov 3.*before this expiry/.test(await text(p, "#c-out")), (await text(p, "#c-out")).slice(-200));
  await p.evaluate(() => { const e = document.getElementById("c-expiry"); e.value = "2026-10-01"; e.dispatchEvent(new Event("input", { bubbles: true })); });
  check("csp past expiry -> message", /after today/.test(await text(p, "#c-out")));
  await type(p, "#c-premium", "");
  check("csp empty premium -> message", /premium|expiry/.test(await text(p, "#c-out")));
  // news
  await tab(p, "news");
  const n0 = (await p.$$("#n-list .item")).length; check("news lists items", n0 > 10, n0 + "");
  await p.select("#n-t", "KEY"); const n1 = (await p.$$("#n-list .item")).length; check("news ticker filter narrows", n1 < n0 && n1 > 0, n0 + "->" + n1);
  await p.select("#n-t", "all"); await p.select("#n-g", "earnings"); const n2 = (await p.$$("#n-list .item")).length; check("news tag filter", n2 > 0 && n2 <= n0);
  // XSS: headline text is escaped
  const unsafe = await p.evaluate(() => [...document.querySelectorAll("#n-list a")].some(a => a.innerHTML.includes("<script")));
  check("news titles escaped", !unsafe);
  // settings
  await tab(p, "settings");
  await type(p, "#s-max_loss_per_trade_usd", "20");
  await new Promise(r => setTimeout(r, 900));
  check("settings saved to db after debounce", await p.evaluate(() => window.__store.get("settings/main") && window.__store.get("settings/main").max_loss_per_trade_usd === 20));
  await type(p, "#s-max_loss_per_trade_usd", "abc");
  check("settings invalid shows error", /valid number/.test(await text(p, "#s-err")) && await p.$eval("#s-max_loss_per_trade_usd", e => e.classList.contains("bad")));
  await type(p, "#s-max_loss_per_trade_usd", "20");
  await p.evaluate(() => { const e = document.getElementById("s-no_entries_after"); e.value = "14:00"; e.dispatchEvent(new Event("input", { bubbles: true })); });
  await tab(p, "planner");
  out = await text(p, "#p-out"); check("planner picks up the new max loss (20 -> fewer shares)", /Max loss/.test(out));
  await tab(p, "settings"); await click(p, '[data-act=sreset]');
  check("settings reset restores 50", (await p.$eval("#s-max_loss_per_trade_usd", e => e.value)) === "50");
  // ask
  await tab(p, "ask");
  await click(p, '[data-act=quick]'); await new Promise(r => setTimeout(r, 500));
  let chat = await text(p, "#chat"); check("ask streams an answer", /Mock answer/.test(chat), chat.slice(0, 120));
  const sent = await p.evaluate(() => JSON.stringify(window.__lastSample));
  check("ask sends rules + page data, no secrets", /PAGE DATA/.test(sent) && /USER LIMITS/.test(sent) && !/987malavshah|shahmalav/.test(sent));
  await p.type("#a-in", "What about my stop?"); await click(p, "#a-send"); await new Promise(r => setTimeout(r, 500));
  check("ask second turn", (await p.$$("#chat .bub.u")).length === 2);
  check("page errors none (full mode)", p.__errs.length === 0, p.__errs.join(" | "));
  // screenshots
  for (const t of ["today", "scanner", "planner", "options", "news", "journal", "ask", "settings"]) { await tab(p, t); await p.screenshot({ path: path.join(OUT, `desk-light-${t}.png`) }); }
  await p.close();

  /* ---------- 2. dark + mobile ---------- */
  p = await open("full", { width: 390, height: 844, isMobile: true, deviceScaleFactor: 2 }, "dark");
  for (const t of ["today", "scanner", "planner", "options", "news", "journal", "ask", "settings"]) {
    await tab(p, t);
    const ov = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
    check("mobile " + t + " no horizontal page scroll", ov.sw <= ov.iw + 1, JSON.stringify(ov));
    await p.screenshot({ path: path.join(OUT, `phone-dark-${t}.png`) });
  }
  await tab(p, "scanner"); await click(p, "#scan-b tr.clk");
  const dw = await p.evaluate(() => { const d = document.querySelector(".drawer"); return d ? d.getBoundingClientRect().width : -1; });
  check("mobile drawer fits width", dw > 300 && dw <= 390, dw + "");
  await p.screenshot({ path: path.join(OUT, "phone-dark-drawer.png") });
  check("mobile errors none", p.__errs.length === 0, p.__errs.join(" | "));
  await p.close();

  /* ---------- 3. no claude runtime at all (opened outside the viewer) ---------- */
  p = await open("none");
  await tab(p, "journal");
  await type(p, "#j-sym", "zzz"); await type(p, "#j-entry", "10"); await type(p, "#j-stop", "9"); await type(p, "#j-qty", "3");
  await click(p, '[data-act=jadd]'); await new Promise(r => setTimeout(r, 100));
  check("no-db: journal works via localStorage", /ZZZ/.test(await text(p, "#view")) && /this browser only/i.test(await text(p, "#view")));
  await p.reload({ waitUntil: "load" }); await p.waitForFunction(() => document.querySelector("#view .card")); await tab(p, "journal");
  check("no-db: journal survives reload", /ZZZ/.test(await text(p, "#view")));
  await tab(p, "ask"); check("no-runtime: ask tab explains unavailability and disables send", /not available/.test(await text(p, "#view")) && await p.$eval("#a-send", e => e.disabled));
  check("no-runtime errors none", p.__errs.length === 0, p.__errs.join(" | "));
  await p.close();

  /* ---------- 4. db present but sample declined / failing ---------- */
  p = await open("samplefail"); await tab(p, "ask"); await click(p, '[data-act=quick]'); await new Promise(r => setTimeout(r, 200));
  check("sample failure shows friendly message and no stuck 'Thinking'", /usage limit|Too many/.test(await text(p, "#chat-note")) && !/Thinking/.test(await text(p, "#chat")));
  check("send button re-enabled after failure", !(await p.$eval("#a-send", e => e.disabled)));
  await p.close();
  p = await open("slow"); await tab(p, "ask"); await click(p, '[data-act=quick]'); await new Promise(r => setTimeout(r, 300));
  check("stop button visible while streaming", !(await p.$eval("#a-stop", e => e.hidden)));
  await click(p, "#a-stop"); await new Promise(r => setTimeout(r, 600));
  check("stop cancels and restores Ask button", (await p.$eval("#a-stop", e => e.hidden)) && !(await p.$eval("#a-send", e => e.disabled)) && !/Thinking…$/.test(await text(p, "#chat")));
  await p.close();

  /* ---------- 5. data failure ---------- */
  const bad = await browser.newPage(); await bad.setRequestInterception(true);
  bad.on("request", r => /news\.json/.test(r.url()) ? r.respond({ status: 500, body: "x" }) : r.continue());
  await bad.goto(base, { waitUntil: "load" }); await bad.waitForFunction(() => document.querySelector("#view .card"));
  check("data failure shows retry card", /did not load/.test(await text(bad, "#view")) && !!(await bad.$("[data-act=reload]")));
  await bad.close();

  await browser.close(); srv.close();
  console.log("\n" + (failures ? failures + " FAILURES" : "ALL E2E CHECKS PASSED"));
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error("HARNESS ERROR", e); process.exit(2); });
