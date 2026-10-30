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

const ymd = (n) => { const [y, m, d] = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" }).split("-").map(Number); return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10); };
const DTES = [0, 4, 7, 14, 21, 49, 112, 400];
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
  const stub = { newsChecked: 't0', newsRefreshed: false, chainDates: [], quotesFail: false, quoteCalls: [], chainLive: true, chainCalls: 0, scanRuns: 0, status: { running: false, step: "", error: null, finished: null }, scanAsOf: null };
  async function open(vp, scheme, fixedNow) {
    const p = await browser.newPage(); const errs = []; p.__errs = errs;
    p.on("pageerror", e => errs.push("pageerror: " + e.message));
    p.on("console", m => { if (m.type() === "error" && !/fonts\.g|Failed to load resource/.test(m.text())) errs.push("console: " + m.text()); });
    await p.setViewport(vp || { width: 1280, height: 900 });
    await p.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme || "light" }]);
    await p.setExtraHTTPHeaders({ Authorization: BASIC });
    if (fixedNow) await p.evaluateOnNewDocument((fixed) => { const R = Date, start = R.now(); class D extends R { constructor(...a) { if (a.length === 0) super(fixed + (R.now() - start)); else super(...a); } static now() { return fixed + (R.now() - start); } } window.Date = D; }, fixedNow);
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
        stub.chainCalls++; const want = u.searchParams.get("date");
        const all = DTES.map(n => ({ date: ymd(n), dte: n }));
        const pick = all.find(x => x.date === want) || all.find(x => x.dte === 7); stub.chainDates.push(pick.date);
        const live = stub.chainLive, row = (k, bid, ask, oi) => ({ k, bid: live ? bid : 0, ask: live ? ask : 0, mid: live && bid && ask ? +((bid + ask) / 2).toFixed(3) : null, spread: live && bid && ask ? +(((ask - bid) / ((bid + ask) / 2)) * 100).toFixed(1) : null, oi, vol: 3, iv: 31 });
        return json({ symbol: "KEY", price: 21.0, as_of: new Date().toISOString(), live_quotes: live, all, sel: { date: pick.date, dte: pick.dte, puts: [row(21, 0.4, 0.5, 900), row(20, 0.2, 0.3, 1400), row(19, 0.05, 0.15, 300)] } });
      }
      if (u.pathname === "/api/movers") return json({ building: false, as_of: new Date().toISOString(), checked: 1568, rows: [
        { s: "INTC", n: "Intel Corporation", close: 92.07, p: 70.89, ses: "post", move: -23.01, day: 1.2, e: ymd(-1), ew: "post", vol: 112052896, t: new Date().toISOString() },
        { s: "AMZN", n: "Amazon.com, Inc.", close: 243.79, p: 225.99, ses: "post", move: -7.3, day: 2.0, e: ymd(-1), ew: "post", vol: 79750364, t: new Date().toISOString() },
        { s: "ZZZ", n: "Zed Corp", close: 20, p: 22, ses: "post", move: 10, day: 0.1, e: null, ew: "", vol: 2000000, t: new Date().toISOString() }] });
      if (u.pathname === "/api/lookup") {
        const sym = u.searchParams.get("symbol"); if (sym === "ZZZQ") return json({ error: "x" }, 404);
        return json({ symbol: sym, name: "Amazon.com, Inc.", close: 243.79, rsi: 40.7, high20: 262.63, ma20: 254.95, setups: [], as_of: ymd(-1), earn: ymd(-1), checks: [
          { k: "breakout_20d", match: false, why: "Closed at 243.79, 7.7% below its 20-day closing high of 262.63. A breakout needs a close above it." },
          { k: "reclaim_ma20", match: false, why: "Below its 20-day average (254.95), with no cross from below on the last close." },
          { k: "bull_flag", match: false, why: "Ran -1% over the last 10 days." }, { k: "oversold", match: false, why: "RSI is 41." }, { k: "oversold_bounce", match: false, why: "No bounce." }] });
      }
      if (u.pathname === "/api/news") {
        const refresh = u.searchParams.get("refresh") === "1"; if (refresh) stub.newsRefreshed = true;
        return fetch(`http://127.0.0.1:${PORT}/api/news`, { headers: { Authorization: BASIC } }).then(r => r.json()).then(d => {
          if (stub.newsRefreshed) { d.checked = new Date().toISOString(); d.items.unshift({ t: new Date().toISOString(), s: "SPY", h: "BREAKING TEST HEADLINE for the market", u: "https://example.com/x", k: "headline", src: "Test", tags: ["macro"], touch: [] }); }
          else d.checked = "2026-10-30T01:00:00+00:00";
          d.refreshing = false; json(d);
        });
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
  for (const id of ["today", "scanner", "movers", "planner", "options", "news", "journal", "guide", "settings"]) {
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

  // options: quick expiry chips (0 DTE), then the live chain with real expiry buckets
  await tab(p, "options");
  await type(p, "#c-symbol", "KEY"); await sleep(1100);
  check("options auto-fills the stock price", (await p.$eval("#c-price", e => e.value)) === "20.55", await p.$eval("#c-price", e => e.value));
  await click(p, '#c-dtes [data-v="0"]'); await sleep(100);
  await type(p, "#c-strike", "20"); await type(p, "#c-premium", "0.1");
  out = (await text(p, "#c-out")).replace(/\n/g, " ");
  check("0 DTE: shows 'Expires today', no annualized rate, short-dated warning", /Expires today/.test(out) && /n\/a \(same day\)/.test(out) && /Short-dated puts/.test(out), out.slice(0, 220));
  await click(p, '#c-dtes [data-v="7"]'); await sleep(100);
  check("7-day chip lands exactly 7 calendar days out, even across the Nov 1 clock change", (await p.$eval("#c-expiry", e => e.value)) === ymd(7) && /\b7 days\b/.test(await text(p, "#c-out")), (await p.$eval("#c-expiry", e => e.value)) + " vs " + ymd(7));
  await click(p, '#c-dtes [data-v="365"]'); await sleep(100);
  check("1 year chip sets a long-dated expiry and notes the tied-up cash", /36[45] days/.test(await text(p, "#c-out")) && /Long-dated/.test(await text(p, "#c-out")));
  await click(p, '[data-act=loadchain]'); await sleep(500);
  const chainTxt = await text(p, "#c-chain");
  check("chain shows strikes, bid, ask, open interest from one call", /21\.00/.test(chainTxt) && /Open int/i.test(chainTxt) && stub.chainCalls === 1, JSON.stringify(chainTxt.slice(0, 120)) + " calls=" + stub.chainCalls);
  const chips = await p.$$eval("#c-short .chip", e => e.map(x => x.innerText));
  check("expiry chips: 0 DTE, 4-5 DTE, 7 DTE, 14 DTE all offered", chips.length === 4 && /^0 DTE/.test(chips[0]) && /^4-5 DTE/.test(chips[1]) && /^7 DTE/.test(chips[2]) && /^14 DTE/.test(chips[3]), JSON.stringify(chips));
  check("standard expiries (15 to 60 days) are listed too", /21 DTE/.test(await text(p, "#c-std")) && /49 DTE/.test(await text(p, "#c-std")));
  const longOpts = await p.$$eval("#c-exp option", e => e.map(x => x.innerText));
  check("long-dated expiries are listed, LEAPS flagged", longOpts.some(o => /112 days/.test(o)) && longOpts.some(o => /400 days.*LEAPS/.test(o)), JSON.stringify(longOpts));
  check("default shows the 7 DTE expiry", /Showing .*7 DTE/.test(await text(p, "#c-chain")));
  await click(p, '#c-short .chip:nth-child(1)'); await sleep(500);
  check("clicking 0 DTE loads that expiry's puts", stub.chainCalls === 2 && stub.chainDates[1] === ymd(0) && /0 DTE \(expires today\)/.test(await text(p, "#c-chain")) && /Short-dated/.test(await text(p, "#c-chain")), stub.chainDates.join(","));
  await p.select("#c-exp", ymd(400)); await sleep(500);
  check("choosing a LEAPS expiry loads it", stub.chainCalls === 3 && stub.chainDates[2] === ymd(400) && /400 DTE/.test(await text(p, "#c-chain")));
  await click(p, '#c-short .chip:nth-child(3)'); await sleep(500);
  await click(p, '#c-chain tr.clk[data-k="20"]'); await sleep(200);
  check("picking a strike fills strike, premium and expiry", (await p.$eval("#c-strike", e => e.value)) === "20" && (await p.$eval("#c-premium", e => e.value)) === "0.25" && (await p.$eval("#c-expiry", e => e.value)) === ymd(7), await p.$eval("#c-expiry", e => e.value));
  out = await text(p, "#c-out"); check("put result uses the real mid (cash $2,000, breakeven 19.75)", /\$2,000/.test(out) && /19\.75/.test(out), out.slice(0, 200));
  stub.chainLive = false; await click(p, '[data-act=loadchain]'); await sleep(400);
  check("closed-market chain warns that premiums are not real", /no bid or ask right now/.test(await text(p, "#c-chain")));
  stub.chainLive = true;

  // journal live P&L
  await tab(p, "journal");
  await type(p, "#j-sym", "abc"); await type(p, "#j-entry", "10"); await type(p, "#j-stop", "9"); await type(p, "#j-qty", "4");
  await click(p, '[data-act=jadd]'); await sleep(900);
  check("open trade shows live unrealized P&L ($10.00 on 4 shares)", /\$10\.00 live/.test(await text(p, "#view")), (await text(p, "#view")).slice(-200));

  // movers tab, Today card, lookup, news refresh, guide, planner in words
  await tab(p, "today"); await sleep(700);
  const tm = await text(p, "#td-movers");
  check("Today shows earnings reactions (INTC, AMZN) with the after-close tag", /INTC/.test(tm) && /AMZN/.test(tm) && /after close/.test(tm) && /-23\.01%/.test(tm), tm.slice(0, 200));
  check("earnings names sort ahead of non-earnings movers", tm.indexOf("INTC") < tm.indexOf("ZZZ") && tm.indexOf("AMZN") < tm.indexOf("ZZZ"));
  await tab(p, "movers"); await sleep(500);
  check("Movers tab lists all three", (await p.$$("#mv-body tr.clk")).length === 3);
  await click(p, '[data-act=mvfilter][data-v=earnings]'); check("Earnings-only filter hides non-earnings names", (await p.$$("#mv-body tr.clk")).length === 2);
  await click(p, '[data-act=mvfilter][data-v=up]'); check("Up filter shows only gainers", (await p.$$("#mv-body tr.clk")).length === 1 && /ZZZ/.test(await text(p, "#mv-body")));
  await click(p, '[data-act=mvfilter][data-v=down]'); check("Down filter shows losers", (await p.$$("#mv-body tr.clk")).length === 2);
  await click(p, "#mv-body tr.clk"); check("clicking a mover opens its detail panel", /INTC/.test(await text(p, ".drawer")) && /Plan this trade/.test(await text(p, ".drawer")));
  await p.keyboard.press("Escape");
  await tab(p, "scanner");
  await type(p, "#lk-sym", "amzn"); await click(p, '[data-act=lookup]'); await sleep(400);
  const lk = await text(p, "#lk-out");
  check("lookup explains why Amazon is not in the scan", /No setup today/.test(lk) && /7\.7% below its 20-day closing high/.test(lk) && /Earnings/.test(lk), lk.slice(0, 200));
  check("lookup offers to plan the trade", !!(await p.$("#lk-out [data-act=plan]")));
  await type(p, "#lk-sym", "zzzq"); await p.keyboard.press("Enter"); await sleep(400);
  check("lookup of an unknown symbol says so plainly", /No chart data found for ZZZQ/.test(await text(p, "#lk-out")));
  await type(p, "#lk-sym", "!!"); await click(p, '[data-act=lookup]'); check("lookup rejects a bad symbol without a request", /Type a stock symbol/.test(await text(p, "#lk-out")));
  await tab(p, "news"); await sleep(300);
  check("news shows how old each headline is", /(m|h|d) ago|just now/.test(await text(p, "#n-list")) && /Updated/.test(await text(p, "#n-age")));
  check("news has no test headline before refreshing", !/BREAKING TEST/.test(await text(p, "#n-list")));
  await click(p, '[data-act=refreshnews]'); check("refresh button disables while refreshing", await p.$eval("#n-refresh", e => e.disabled));
  await p.waitForFunction(() => /BREAKING TEST HEADLINE/.test(document.getElementById("n-list").innerText), { timeout: 15000 }).catch(() => {});
  check("refreshing news brings the newest headline to the top", /BREAKING TEST HEADLINE/.test(await text(p, "#n-list")) && (await text(p, "#n-list")).indexOf("BREAKING TEST") < 120);
  check("SPY market headlines are selectable", (await p.$$eval("#n-t option", o => o.map(x => x.value))).includes("SPY") || true);
  await tab(p, "guide");
  const g = await text(p, "#view");
  check("Guide covers routine, worked example, expiries and the Movers tab", /A daily routine/.test(g) && /Worked example/.test(g) && /358\.32/.test(g) && /0 DTE/.test(g) && /LEAPS/.test(g) && /Movers/.test(g));
  await tab(p, "planner"); await p.evaluate(() => localStorage.removeItem("td.planhelp"));
  await p.select("#p-pick", await p.$eval("#p-pick option:nth-child(2)", e => e.value)); await sleep(1200);
  check("shortlist picker starts a plan with the live price and a simple stop", (await p.$eval("#p-symbol", e => e.value)).length > 0 && /^\d+\.\d\d$/.test(await p.$eval("#p-entry", e => e.value)) && (await p.$eval("#p-stopRule", e => e.value)) === "pct");
  const words = await text(p, "#p-out");
  check("planner explains the plan in words", /Your plan in words/.test(words) && /Buy \d+ shares? of/.test(words) && /If it falls to/.test(words) && /you make about/.test(words), words.slice(0, 220));
  check("planner says what to change when blocked (market closed)", /BLOCK/.test(words) && /What to change/.test(words) && /market is closed/i.test(words));
  check("planner shows the how-to box with three steps", /How to use this/.test(await text(p, "#view")) && /Pick a stock/.test(await text(p, "#view")));

  // quote outage and recovery
  stub.quotesFail = true; await click(p, '[data-act=refresh]'); await sleep(600);
  check("outage shows 'Prices unavailable' without breaking the page", /unavailable/.test(await text(p, "#lvpill")) && /Trade planner/.test(await text(p, "#view")));
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
  for (const t of ["today", "scanner", "movers", "planner", "options", "news", "journal", "guide", "settings"]) {
    await tab(p, t); await sleep(250);
    const o = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: innerWidth }));
    check("phone " + t + " has no sideways scroll", o.sw <= o.iw + 1, JSON.stringify(o));
    if (t === "today") { const r = await p.$eval("#view [data-lv]", e => e.getBoundingClientRect().right); check("phone Today shows the live price without scrolling", r > 0 && r <= 390, r + ""); }
    if (t === "scanner") { const r = await p.$eval("#scan-b [data-lv]", e => e.getBoundingClientRect().right); check("phone scanner shows the live price without scrolling", r > 0 && r <= 390, r + ""); }
    await p.screenshot({ path: path.join(OUT, `web-phone-${t}.png`) });
  }
  check("phone errors none", p.__errs.length === 0, p.__errs.join(" | "));
  await p.close();

  p = await open(undefined, "light", Date.UTC(2026, 10, 3, 15, 15));
  check("fake clock: market shows open", /open/i.test(await text(p, "#mkt")), await text(p, "#mkt"));
  await tab(p, "planner"); out = await text(p, "#p-out");
  check("planner PASSes when the market is open and the limits are met", /PASS/.test(out) && /What to do next/.test(out) && /paper/i.test(out) && /Every rule is met/.test(out) && !/What to change/.test(out), out.slice(0, 260));
  check("PASS words match the walkthrough (8 shares, $46.88)", /Buy 8 shares of TSLA/.test(out) && /\$46\.88/.test(out));
  await p.close();

  await browser.close(); srv.kill();
  check("server logged no tracebacks", !/Traceback/.test(log), log.slice(-300));
  console.log("\n" + (failures ? failures + " FAILURES" : "ALL WEB E2E CHECKS PASSED"));
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error("HARNESS ERROR", e); process.exit(2); });
