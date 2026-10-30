// End-to-end test of the web app: real Python server + headless Chrome.
// Needs puppeteer-core (npm i puppeteer-core) and Google Chrome. Yahoo calls are stubbed in the browser
// so the numbers are deterministic; the server's own routes (scan, news, earnings, auth) are real.
const puppeteer = require(process.env.PUPPETEER_PATH || "puppeteer-core");
const { spawn } = require("child_process");
const fs = require("fs"), os = require("os"), path = require("path");
const ROOT = path.resolve(__dirname, "..", "..");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const OUT = process.env.SHOTS || path.join(os.tmpdir(), "desk-shots"); fs.mkdirSync(OUT, { recursive: true });
const PORT = 18765, PW = "test-password-123", BASIC = "Basic " + Buffer.from("me:" + PW).toString("base64");
const data = fs.mkdtempSync(path.join(os.tmpdir(), "desk-data-"));

let failures = 0;
const check = (n, c, x) => { if (c) console.log("ok   " + n); else { failures++; console.log("FAIL " + n + (x ? "  -> " + x : "")); } };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const PRICE = { KEY: 20.55, ABC: 12.5, AAPL: 352.05 };
const price = (s) => PRICE[s] || Math.round((50 + (s.charCodeAt(0) % 40) + 0.37) * 100) / 100;

(async () => {
  const srv = spawn("python3", [path.join(ROOT, "webapp", "server.py")], {
    env: Object.assign({}, process.env, { PORT: String(PORT), HOST: "127.0.0.1", DESK_PASSWORD: PW, DESK_DATA: data, DESK_NO_SCHEDULER: "1" }), stdio: ["ignore", "pipe", "pipe"] });
  let log = ""; srv.stderr.on("data", d => log += d);
  for (let i = 0; i < 50; i++) { try { const r = await fetch(`http://127.0.0.1:${PORT}/healthz`); if (r.ok) break; } catch (e) { /* not up yet */ } await sleep(100); }
  const base = `http://127.0.0.1:${PORT}/`;
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new" });

  // stub state shared with the page interceptor
  const stub = { quotesFail: false, quoteCalls: [], chainLive: true, chainCalls: 0, scanRuns: 0, status: { running: false, step: "", error: null, finished: null }, scanAsOf: null };
  async function open(vp, scheme) {
    const p = await browser.newPage(); const errs = []; p.__errs = errs;
    p.on("pageerror", e => errs.push("pageerror: " + e.message));
    p.on("console", m => { if (m.type() === "error" && !/fonts\.g|Failed to load resource/.test(m.text())) errs.push("console: " + m.text()); });
    await p.setViewport(vp || { width: 1280, height: 900 });
    await p.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme || "light" }]);
    await p.setExtraHTTPHeaders({ Authorization: BASIC });
    await p.setRequestInterception(true);
    p.on("request", req => {
      const u = new URL(req.url());
      const json = (o, status = 200) => req.respond({ status, contentType: "application/json", body: JSON.stringify(o) });
      if (u.hostname.includes("googleapis") || u.hostname.includes("gstatic")) return req.abort();
      if (u.pathname === "/api/quotes") {
        const syms = (u.searchParams.get("symbols") || "").split(",").filter(Boolean); stub.quoteCalls.push(syms);
        if (stub.quotesFail) return json({ error: "x" }, 502);
        const q = {}; syms.forEach(s => { q[s] = s === "NOPE" ? { err: "no data for NOPE" } : { p: price(s), pc: price(s) - 1, pct: Math.round(1 / price(s) * 10000) / 100, t: new Date().toISOString() }; });
        return json({ as_of: new Date().toISOString(), quotes: q });
      }
      if (u.pathname === "/api/chain") {
        stub.chainCalls++;
        const live = stub.chainLive, row = (k, bid, ask, oi) => ({ k, bid: live ? bid : 0, ask: live ? ask : 0, mid: live && bid && ask ? +((bid + ask) / 2).toFixed(3) : null, spread: live && bid && ask ? +(((ask - bid) / ((bid + ask) / 2)) * 100).toFixed(1) : null, oi, vol: 3, iv: 31 });
        return json({ symbol: "KEY", price: 21.0, as_of: new Date().toISOString(), live_quotes: live, expiries: [
          { date: "2026-11-20", dte: 22, puts: [row(21, 0.4, 0.5, 900), row(20, 0.2, 0.3, 1400), row(19, 0.05, 0.15, 300)] },
          { date: "2026-12-18", dte: 50, puts: [row(20, 0.6, 0.7, 1200)] }] });
      }
      if (u.pathname === "/api/scan/run" && req.method() === "POST") { stub.scanRuns++; stub.status = { running: true, step: "scanning charts", error: null, finished: null }; setTimeout(() => { stub.status = { running: false, step: "done", error: null, finished: new Date().toISOString() }; stub.scanAsOf = "2026-10-30 close"; }, 1500); return json({ started: true }, 202); }
      if (u.pathname === "/api/status") return json({ scan: stub.status, now: new Date().toISOString(), sec_user_agent: true });
      if (u.pathname === "/api/scan" && stub.scanAsOf) { return fetch(`http://127.0.0.1:${PORT}/api/scan`, { headers: { Authorization: BASIC } }).then(r => r.json()).then(d => { d.as_of = stub.scanAsOf; json(d); }); }
      req.continue();
    });
    await p.goto(base, { waitUntil: "load" });
    await p.waitForFunction(() => document.querySelector("#view .card, #view .empty"), { timeout: 10000 });
    await sleep(300); return p;
  }
  const text = (p, sel) => p.$eval(sel, e => e.innerText);
  const click = async (p, sel) => { await p.click(sel); await sleep(80); };
  const tab = (p, v) => click(p, `[data-act=tab][data-v=${v}]`);
  const type = async (p, sel, val) => { await p.$eval(sel, e => { e.focus(); if (e.select) e.select(); }); await p.keyboard.press("Backspace"); if (val) await p.type(sel, val); await sleep(80); };

  /* ---- auth ---- */
  const noAuth = await fetch(base), badAuth = await fetch(base + "api/scan", { headers: { Authorization: "Basic " + Buffer.from("me:wrong").toString("base64") } });
  check("no credentials -> 401 with a sign-in challenge", noAuth.status === 401 && /Basic/.test(noAuth.headers.get("www-authenticate") || ""));
  check("wrong password -> 401", badAuth.status === 401);
  check("right password -> 200", (await fetch(base + "api/scan", { headers: { Authorization: BASIC } })).status === 200);

  /* ---- main flow ---- */
  let p = await open();
  check("page loads behind the password", /Market read/.test(await text(p, "#view")));
  check("live pill shows a price time", /Prices \d/.test(await text(p, "#lvpill")), await text(p, "#lvpill"));
  const todayLive = await p.$$eval("#view [data-lv]", e => e.map(x => x.innerText));
  check("Today shortlist shows live prices", todayLive.length >= 5 && todayLive.every(t => /^\d+\.\d\d/.test(t)), JSON.stringify(todayLive.slice(0, 3)));
  for (const id of ["today", "scanner", "planner", "options", "news", "journal", "settings"]) {
    await tab(p, id); const t = await text(p, "#view");
    check("tab " + id + " renders cleanly", t.length > 40 && !/undefined|NaN|\[object|Infinity/.test(t));
  }
  check("no Ask Claude tab in the web app", !(await p.$("[data-v=ask]")));

  // scanner live column
  await tab(p, "scanner"); await sleep(400);
  const lv = await p.$$eval("#scan-b [data-lv]", e => e.map(x => x.innerText));
  check("scanner rows show live prices", lv.length === 50 && lv.every(t => /^\d+\.\d\d/.test(t)), lv.length + " " + lv[0]);
  check("quote requests are chunked to 60 symbols or fewer", stub.quoteCalls.every(c => c.length <= 60) && stub.quoteCalls.some(c => c.length > 20), JSON.stringify(stub.quoteCalls.map(c => c.length)));
  await click(p, '[data-act=more]'); await sleep(1300);
  check("more rows also get live prices", (await p.$$eval("#scan-b [data-lv]", e => e.filter(x => /\d/.test(x.innerText)).length)) === 100);

  // planner auto price
  await tab(p, "planner");
  await type(p, "#p-symbol", "KEY"); await sleep(1100);
  check("planner fills entry from the live price", (await p.$eval("#p-entry", e => e.value)) === "20.55", await p.$eval("#p-entry", e => e.value));
  check("planner shows the live box", /Live\s+KEY/.test(await text(p, "#p-live")), JSON.stringify(await text(p, "#p-live")));
  await p.select("#p-stopRule", "pct"); await type(p, "#p-stopParam", "2");
  let out = await text(p, "#p-out");
  check("plan computes from the live entry (stop 20.13)", /20\.13/.test(out), out.slice(0, 160));
  await type(p, "#p-entry", "21"); await sleep(200);
  stub.quoteCalls.length = 0; await click(p, '[data-act=refresh]'); await sleep(500);
  check("typing an entry turns auto-price off", (await p.$eval("#p-entry", e => e.value)) === "21");
  await click(p, '[data-act=uselive]'); check("Use as entry sets the live price again", (await p.$eval("#p-entry", e => e.value)) === "20.55");
  await type(p, "#p-symbol", "NOPE"); await sleep(1100);
  check("unknown symbol shows 'No live price' and keeps working", /No live price for NOPE/.test(await text(p, "#p-live")));

  // options + chain
  await tab(p, "options");
  await type(p, "#c-symbol", "KEY"); await sleep(1100);
  check("options auto-fills the stock price", (await p.$eval("#c-price", e => e.value)) === "20.55", await p.$eval("#c-price", e => e.value));
  await click(p, '[data-act=loadchain]'); await sleep(400);
  check("chain table shows strikes, bid, ask, open interest", /21\.00/.test(await text(p, "#c-chain")) && /Open int/i.test(await text(p, "#c-chain")) && stub.chainCalls === 1, JSON.stringify((await text(p, "#c-chain")).slice(0, 160)) + " calls=" + stub.chainCalls);
  const tags = await text(p, "#c-chain"); check("thin and wide tags appear (300 OI, 100% spread)", /thin/.test(tags) && /wide/.test(tags));
  await click(p, '#c-chain tr.clk[data-k="20"]'); await sleep(200);
  check("picking a strike fills strike, premium and expiry",
    (await p.$eval("#c-strike", e => e.value)) === "20" && (await p.$eval("#c-premium", e => e.value)) === "0.25" && (await p.$eval("#c-expiry", e => e.value)) === "2026-11-20");
  out = await text(p, "#c-out"); check("put result uses the real mid (cash $2,000, breakeven 19.75)", /\$2,000/.test(out) && /19\.75/.test(out), out.slice(0, 200));
  await p.select("#c-exp", "1").catch(() => {});
  stub.chainLive = false; await type(p, "#c-symbol", "KEY"); await click(p, '[data-act=loadchain]'); await sleep(400);
  check("closed-market chain warns that premiums are not real", /no bid or ask right now/.test(await text(p, "#c-chain")));

  // journal live P&L
  await tab(p, "journal");
  await type(p, "#j-sym", "abc"); await type(p, "#j-entry", "10"); await type(p, "#j-stop", "9"); await type(p, "#j-qty", "4");
  await click(p, '[data-act=jadd]'); await sleep(900);
  check("open trade shows live unrealized P&L ($10.00 on 4 shares)", /\$10\.00 live/.test(await text(p, "#view")), (await text(p, "#view")).slice(-200));

  // quote outage and recovery
  stub.quotesFail = true; await click(p, '[data-act=refresh]'); await sleep(600);
  check("outage shows 'Prices unavailable' without breaking the page", /unavailable/.test(await text(p, "#lvpill")) && /Journal/.test(await text(p, "#view")));
  stub.quotesFail = false; await click(p, '[data-act=refresh]'); await sleep(600);
  check("pill recovers after the next refresh", /Prices \d/.test(await text(p, "#lvpill")));

  // scan button
  await tab(p, "today"); await click(p, '[data-act=runscan]'); await sleep(300);
  check("run scan shows progress and disables the button", /Scanning/.test(await text(p, "#scan-st")) && (await p.$eval("[data-act=runscan]", e => e.disabled)));
  await p.waitForFunction(() => /scan 2026-10-30/.test(document.getElementById("asof").innerText), { timeout: 15000 }).catch(() => {});
  check("finished scan reloads the new results", /scan 2026-10-30/.test(await text(p, "#asof")) && stub.scanRuns === 1, await text(p, "#asof"));
  check("no page errors", p.__errs.length === 0, p.__errs.join(" | "));
  for (const t of ["today", "scanner", "planner", "options"]) { await tab(p, t); await sleep(300); await p.screenshot({ path: path.join(OUT, `web-light-${t}.png`) }); }
  await p.close();

  /* ---- phone + dark ---- */
  stub.quotesFail = false; p = await open({ width: 390, height: 844, isMobile: true, deviceScaleFactor: 2 }, "dark");
  for (const t of ["today", "scanner", "planner", "options", "news", "journal", "settings"]) {
    await tab(p, t); await sleep(250);
    const o = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: innerWidth }));
    check("phone " + t + " has no sideways scroll", o.sw <= o.iw + 1, JSON.stringify(o));
    if (t === "today") { const r = await p.$eval("#view [data-lv]", e => e.getBoundingClientRect().right); check("phone Today shows the live price without scrolling", r > 0 && r <= 390, r + ""); }
    if (t === "scanner") { const r = await p.$eval("#scan-b [data-lv]", e => e.getBoundingClientRect().right); check("phone scanner shows the live price without scrolling", r > 0 && r <= 390, r + ""); }
    await p.screenshot({ path: path.join(OUT, `web-phone-${t}.png`) });
  }
  check("phone errors none", p.__errs.length === 0, p.__errs.join(" | "));
  await p.close();

  await browser.close(); srv.kill();
  check("server logged no tracebacks", !/Traceback/.test(log), log.slice(-300));
  console.log("\n" + (failures ? failures + " FAILURES" : "ALL WEB E2E CHECKS PASSED"));
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error("HARNESS ERROR", e); process.exit(2); });
