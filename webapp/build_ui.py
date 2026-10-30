#!/usr/bin/env python3
"""Build webapp/static/index.html from dashboard/src/index.src.html.

The web app shares the dashboard's page and logic (dashboard/lib.js) and swaps three things:
  * data comes from the server's /api/* routes instead of published files,
  * the claude.ai-only parts (Ask Claude, shared database) are removed,
  * a live layer is added: server-fetched prices, a put chain, and a scan button.
Every edit asserts that its anchor exists exactly once, so a change to the dashboard source that
breaks an anchor fails the build instead of silently shipping a half-converted page.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "dashboard" / "src" / "index.src.html"
OUT = HERE / "static" / "index.html"

s = SRC.read_text()


def rep(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        sys.exit("build_ui: anchor found %d time(s), expected %d:\n  %s" % (n, count, old[:120]))
    s = s.replace(old, new)


def cut(start, end):
    """Remove text from `start` up to (not including) `end`."""
    global s
    a, b = s.find(start), s.find(end)
    if a < 0 or b < 0 or b < a or s.count(start) != 1:
        sys.exit("build_ui: cannot cut between %r and %r" % (start[:50], end[:50]))
    s = s[:a] + s[b:]


def drop_line(fragment):
    global s
    lines = s.split("\n")
    hits = [i for i, l in enumerate(lines) if fragment in l]
    if len(hits) != 1:
        sys.exit("build_ui: expected one line containing %r, found %d" % (fragment, len(hits)))
    del lines[hits[0]]
    s = "\n".join(lines)


# ---- library: served by the server instead of inlined
rep("<script>\n/*__LIB__*/\n</script>", '<script src="/lib.js"></script>')

# ---- remove Ask Claude and the shared database
rep('["journal", "Journal"], ["ask", "Ask Claude"], ["settings", "Settings"]];', '["journal", "Journal"], ["settings", "Settings"]];')
rep('drawer: null, ctxSym: null, chat: [], chatBusy: false, chatCtl: null, chatNote: "", sampleOK: null',
    'drawer: null, q: {}, qAt: 0, qErr: "", chain: null, chainErr: "", chainBusy: false, scanSt: null')
rep("var db = null, sample = null, unsubs = [], writeQ = Promise.resolve(), base = null, jcoll = null;", "var db = null, writeQ = Promise.resolve();")
cut("  var cfgTimer = null;", "  function todayStats() {")
rep("  function todayStats() {", """  function saveCfg() { lsSet("td.cfg", JSON.stringify(S.cfg)); }
  function jAdd(e) {
    e.created = new Date().toISOString();
    e.id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    S.journal.unshift(e); lsSet("td.journal", JSON.stringify(S.journal)); return Promise.resolve();
  }
  function jUpdate(id, patch) {
    S.journal = S.journal.map(function (x) { return x.id === id ? Object.assign({}, x, patch) : x; });
    lsSet("td.journal", JSON.stringify(S.journal)); return Promise.resolve();
  }
  function jDelete(id) {
    S.journal = S.journal.filter(function (x) { return x.id !== id; });
    lsSet("td.journal", JSON.stringify(S.journal)); return Promise.resolve();
  }
  function todayStats() {""")
cut("  /* ---------------- Ask Claude ---------------- */", "  /* ---------------- events ---------------- */")
rep("journal: vJournal, ask: vAsk, settings: vSettings }[S.tab];", "journal: vJournal, settings: vSettings }[S.tab];")
rep('    if (S.tab === "ask") updateChat();\n    if (S.tab === "news") updateNews();', '    if (S.tab === "news") updateNews();\n    if (S.tab === "options") renderChain();\n    ensureQuotes(false); paintLive();')
rep("""<button class="btn" data-act="askabout" data-v="' + esc(sym) + '">Ask Claude</button></div>';""", """</div><div id="d-live" class="row" style="margin-top:-4px"></div>';""")
rep("""<button class=\\"btn sm\\" data-act=\\"askplan\\">Ask Claude to review</button>""", "")
rep("""    h += '<div class="row" style="margin-top:10px"><button class="btn sm" data-act="askcsp">Ask Claude to critique this put</button></div>';\n""", "")
drop_line('a === "askabout"'); drop_line('a === "askplan"'); drop_line('a === "askcsp"')
drop_line('a === "quick"'); drop_line('a === "send"'); drop_line('a === "stop"'); drop_line('a === "clearchat"')
drop_line("function go2ask(")
drop_line('ev.target.id === "a-in"')
cut("  async function connect() {", "  loadLocal();")
rep("    connect();\n", "    startLive();\n")

rep("{ S.drawer = v; S.ctxSym = v; renderDrawer(); }", "{ S.drawer = v; renderDrawer(); }")

# ---- data comes from the server
rep('fetchJSON("data/scan.json"), fetchJSON("data/news.json"), fetchJSON("data/earnings.json"), fetchJSON("data/market.json")',
    'fetchJSON("/api/scan"), fetchJSON("/api/news"), fetchJSON("/api/earnings"), fetchJSON("/api/market")')
rep("Could not load the data files (", "Could not load the data (")

# ---- guards for a market feed that is down
rep('var sp = m["^GSPC"], vix = m["^VIX"], v3 = m["^VIX3M"], tone, why = [];', 'var sp = m["^GSPC"], vix = m["^VIX"], v3 = m["^VIX3M"], tone, why = [];\n    if (!sp || !vix || !v3) return null;')
rep('["^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX"].map(function (k) {', '["^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX"].filter(function (k) { return mk.idx[k]; }).map(function (k) {')
rep("Thursday, from watched names", "Latest session, watched names")

# ---- rows added by filtering, sorting or "show more" fetch their live prices straight away
rep("""$("#scan-more").innerHTML = rows.length > shown.length ? '<button class="btn sm" data-act="more">Show 50 more</button>' : "";""",
    """$("#scan-more").innerHTML = rows.length > shown.length ? '<button class="btn sm" data-act="more">Show 50 more</button>' : "";
    paintLive(); scheduleLive();""")

# ---- live columns
rep('th("price", "Price", "r") + th("rsi", "RSI", "r")', 'th("price", "Close", "r hide-s") + \'<th class="r">Live</th>\' + th("rsi", "RSI", "r")')
rep("""</td><td class="r num">' + r[2].toFixed(2) + '</td><td class="r num">' + r[3].toFixed(0) + '</td><td class="r num hide-s">' + fmtVol(r[4])""",
    """</td><td class="r num hide-s">' + r[2].toFixed(2) + '</td>' + lvCell(r[0]) + '<td class="r num">' + r[3].toFixed(0) + '</td><td class="r num hide-s">' + fmtVol(r[4])""")
rep("</style>", ".clock { flex-wrap: wrap; justify-content: flex-end; }\n#clock { white-space: nowrap; }\n@media (max-width: 560px) { [data-lv] .small { display: block; } }\n</style>")
rep('<tr><td colspan="6" class="empty">', '<tr><td colspan="7" class="empty">')
rep('<th class="r">Price</th><th class="r">RSI</th><th>Setup</th>', '<th class="r hide-s">Close</th><th class="r">Live</th><th class="r">RSI</th><th class="hide-s">Setup</th>')
rep("""'</td><td class="r num">' + r[2].toFixed(2) + '</td><td class="r num">' + r[3].toFixed(0) + '</td><td>' + esc(""", """'</td><td class="r num hide-s">' + r[2].toFixed(2) + '</td>' + lvCell(r[0]) + '<td class="r num">' + r[3].toFixed(0) + '</td><td class="hide-s">' + esc(""")
rep("""(d === null ? "open" : L.money(d))""", """(d === null ? '<span data-unreal="1" data-sym="' + esc(j.sym) + '" data-entry="' + esc(j.entry) + '" data-qty="' + esc(j.qty) + '">open</span>' : L.money(d))""")
rep("""h += '<p class="foot">Today you have logged '""", """h += '<div id="p-live" class="row" style="margin-top:10px"></div><p class="foot">Today you have logged '""")
rep("""    h += '<p class="foot">Sizing rule: risk = (strike""", """    h += '<div class="row" style="margin-top:12px"><button class="btn p" data-act="loadchain">Load live put chain</button><span id="c-live" class="row small"></span></div><div id="c-chain"></div>';
    h += '<p class="foot">Sizing rule: risk = (strike""")
rep("entry: r ? r[2].toFixed(2) : \"\", stopRule: \"pct\"", "entry: S.q[v] && S.q[v].p ? S.q[v].p.toFixed(2) : r ? r[2].toFixed(2) : \"\", auto: true, stopRule: \"pct\"")
rep('From the Oct 27 review · re-check before use', 'From the Oct 27 review')
rep("The premium in the calculator is an assumption. Use your broker\\'s quote.", "Load the live put chain in Options to see real bids and asks.")
rep('Premium and delta must come from a live chain.', 'Use the live chain above for bids, asks and open interest.')
rep("Example inputs. The premium is a placeholder, not a quote. Copy the real bid/mid from your broker.", "Example inputs. Tap Load live put chain, then pick a strike to fill in a real premium.")

# ---- header: price status + refresh
rep('<div class="clock"><span id="clock" class="muted"></span>', '<div class="clock"><span id="lvpill" class="pill"><i></i><span>Prices…</span></span><button class="btn sm" data-act="refresh" aria-label="Refresh prices">↻</button><span id="clock" class="muted"></span>')
rep("Data is free and delayed (Yahoo, SEC).", "Prices come from Yahoo through this server and can be delayed up to 15 minutes.")

# ---- scan button on the Last scan card
rep("""h += '<div class="row" style="margin-top:10px">' + Object.keys(L.SETUPS)""", """h += '<div class="row" style="margin-top:10px"><button class="btn sm" data-act="runscan">Run scan now</button><span id="scan-st" class="muted small"></span></div><div class="row" style="margin-top:10px">' + Object.keys(L.SETUPS)""")

# ---- new actions and input hooks
rep("""    if (a === "tab") go(v);
    else if (a === "reload") boot();""", """    if (a === "tab") go(v);
    else if (a === "reload") boot();
    else if (a === "refresh") { ensureQuotes(true); refreshMarket(); }
    else if (a === "uselive") { var lq = S.q[v]; if (lq && lq.p) { S.plan.entry = lq.p.toFixed(2); S.plan.example = false; S.plan.auto = true; render(); } }
    else if (a === "usecsp") { var cq = S.q[v]; if (cq && cq.p) { S.csp.price = cq.p.toFixed(2); S.csp.example = false; S.csp.auto = true; render(); } }
    else if (a === "loadchain") loadChain();
    else if (a === "pickput") pickPut(+t.getAttribute("data-k"));
    else if (a === "runscan") runScan();""")
rep("""    if (id.indexOf("p-") === 0) { readPlan(); S.plan.example = false;""", """    if (id.indexOf("p-") === 0) { readPlan(); S.plan.example = false; if (id === "p-entry") S.plan.auto = false; if (id === "p-symbol") { S.plan.auto = true; scheduleLive(); }""")
rep("""    else if (id.indexOf("c-") === 0) { readCsp(); S.csp.example = false; updateCsp(); }""", """    else if (id === "c-exp") { if (S.chain) { S.chain.exp = +ev.target.value; renderChain(); } }
    else if (id.indexOf("c-") === 0) { readCsp(); S.csp.example = false; if (id === "c-price") S.csp.auto = false; if (id === "c-symbol") { S.csp.auto = true; S.chain = null; scheduleLive(); } updateCsp(); }""")

LIVE = r'''
  /* ---------------- live prices: the server fetches Yahoo, this page only reads /api ---------------- */
  var symTimer = null, scanPoll = null;
  function lvCell(sym) { return '<td class="r num"><span data-lv="' + esc(sym) + '"></span></td>'; }
  function validSym(x) { return /^[A-Z0-9.\-^]{1,10}$/.test(x); }
  function ttl() { var st = L.marketStatus(new Date()).state; return st === "open" ? 20000 : st === "closed" ? 300000 : 60000; }
  function neededSymbols() {
    var out = [];
    function add(x) { x = String(x || "").toUpperCase(); if (validSym(x) && out.indexOf(x) === -1) out.push(x); }
    if (S.drawer) add(S.drawer);
    if (S.tab === "planner") add(S.plan.symbol);
    if (S.tab === "options") add(S.csp.symbol);
    Array.prototype.forEach.call(document.querySelectorAll("[data-lv],[data-unreal]"), function (el) { add(el.getAttribute("data-lv") || el.getAttribute("data-sym")); });
    return out.slice(0, 180);
  }
  async function fetchQuotes(syms) {
    for (var i = 0; i < syms.length; i += 60) {
      try {
        var r = await fetch("/api/quotes?symbols=" + encodeURIComponent(syms.slice(i, i + 60).join(",")), { cache: "no-store" });
        if (r.status === 401) { S.qErr = "Signed out. Reload the page and sign in."; break; }
        if (!r.ok) throw new Error("http " + r.status);
        var d = await r.json(), now = Date.now();
        Object.keys(d.quotes).forEach(function (k) { var q = d.quotes[k]; q._at = now; S.q[k] = q; });
        S.qAt = now; S.qErr = "";
      } catch (e) { S.qErr = "Prices unavailable right now."; break; }
    }
    paintLive();
  }
  function ensureQuotes(force) {
    if (!S.scan) return Promise.resolve();
    var t = ttl(), now = Date.now();
    var need = neededSymbols().filter(function (x) { var q = S.q[x]; return force || !q || now - q._at > t; });
    if (need.length) return fetchQuotes(need);
    paintLive(); return Promise.resolve();
  }
  function scheduleLive() { clearTimeout(symTimer); symTimer = setTimeout(function () { ensureQuotes(false); }, 500); }
  function lvHtml(q) {
    if (!q || q.err) return '<span class="muted">–</span>';
    return q.p.toFixed(2) + (isFinite(q.pct) ? ' <span class="' + cls(q.pct) + ' small">' + fmtPct(q.pct) + "</span>" : "");
  }
  function quoteTime(q) {
    if (!q || !q.t) return "";
    return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date(q.t)) + " ET";
  }
  function liveBox(sym, q, act, label) {
    if (!validSym(sym)) return "";
    if (!q) return '<span class="muted small">Looking up ' + esc(sym) + "…</span>";
    if (q.err) return '<span class="muted small">No live price for ' + esc(sym) + ".</span>";
    return '<span class="pill acc">Live <b class="mono">' + esc(sym) + "</b> " + lvHtml(q) + '</span><span class="muted small">' + esc(quoteTime(q)) + '</span><button class="btn sm" data-act="' + act + '" data-v="' + esc(sym) + '">' + esc(label) + "</button>";
  }
  function paintLive() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-lv]"), function (el) { el.innerHTML = lvHtml(S.q[el.getAttribute("data-lv")]); });
    Array.prototype.forEach.call(document.querySelectorAll("[data-unreal]"), function (el) {
      var q = S.q[el.getAttribute("data-sym")];
      if (!q || q.err) { el.textContent = "open"; el.className = ""; return; }
      var d = (q.p - L.num(el.getAttribute("data-entry"))) * L.num(el.getAttribute("data-qty"));
      el.className = cls(d); el.textContent = L.money(d) + " live";
    });
    var sp = String(S.plan.symbol || "").toUpperCase(), pq = S.q[sp], pl = $("#p-live");
    if (pl) pl.innerHTML = liveBox(sp, pq, "uselive", "Use as entry");
    if (S.tab === "planner" && S.plan.auto && pq && !pq.err) {
      var v = pq.p.toFixed(2);
      if (S.plan.entry !== v) { S.plan.entry = v; var pe = $("#p-entry"); if (pe && document.activeElement !== pe) pe.value = v; updatePlanner(); }
    }
    var cs = String(S.csp.symbol || "").toUpperCase(), cq = S.q[cs], cl = $("#c-live");
    if (cl) cl.innerHTML = liveBox(cs, cq, "usecsp", "Use live price");
    if (S.tab === "options" && S.csp.auto && cq && !cq.err) {
      var cv = cq.p.toFixed(2);
      if (S.csp.price !== cv) { S.csp.price = cv; var ce = $("#c-price"); if (ce && document.activeElement !== ce) ce.value = cv; updateCsp(); }
    }
    var dl = $("#d-live"); if (dl && S.drawer) dl.innerHTML = liveBox(S.drawer, S.q[S.drawer], "plan", "Plan from live price");
    var pill = $("#lvpill");
    if (pill) {
      pill.className = "pill " + (S.qErr ? "bad" : S.qAt ? "acc" : "");
      pill.lastChild.textContent = S.qErr ? S.qErr : S.qAt ? "Prices " + new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date(S.qAt)) : "Prices…";
    }
  }
  async function refreshMarket() {
    try {
      var r = await fetch("/api/market", { cache: "no-store" }); if (!r.ok) return;
      var d = await r.json(); if (!d.idx || !d.idx["^GSPC"]) return;
      S.market = d; if (S.tab === "today" && !isEditing() && !S.drawer) render();
    } catch (e) { /* keep the last market read */ }
  }

  /* ---------------- put chain ---------------- */
  async function loadChain() {
    var sym = String(S.csp.symbol || "").toUpperCase();
    if (!validSym(sym)) { S.chainErr = "Enter a symbol first."; renderChain(); return; }
    S.chainBusy = true; S.chainErr = ""; renderChain();
    try {
      var r = await fetch("/api/chain?symbol=" + encodeURIComponent(sym), { cache: "no-store" });
      if (!r.ok) throw new Error("http " + r.status);
      var d = await r.json(); S.chain = { data: d, exp: 0 };
      if (d.price && S.csp.auto !== false) { S.csp.price = String(d.price); }
    } catch (e) { S.chain = null; S.chainErr = "Could not load options for " + sym + ". The symbol may have no options, or the data source is busy."; }
    S.chainBusy = false; if (S.tab === "options") render();
  }
  function renderChain() {
    var el = $("#c-chain"); if (!el) return;
    if (S.chainBusy) { el.innerHTML = '<p class="muted" style="margin-top:10px">Loading the put chain…</p>'; return; }
    if (S.chainErr) { el.innerHTML = '<div class="note bad" style="margin-top:10px">' + esc(S.chainErr) + "</div>"; return; }
    if (!S.chain) { el.innerHTML = ""; return; }
    var d = S.chain.data;
    if (!d.expiries.length) { el.innerHTML = '<div class="note" style="margin-top:10px">No expiries 14 to 60 days out for ' + esc(d.symbol) + ".</div>"; return; }
    var e = d.expiries[Math.min(S.chain.exp, d.expiries.length - 1)];
    var h = '<label class="f" style="margin-top:12px;max-width:260px">Expiry<select id="c-exp">' + d.expiries.map(function (x, i) { return '<option value="' + i + '"' + (i === S.chain.exp ? " selected" : "") + ">" + esc(fmtDay(x.date)) + " · " + x.dte + " days</option>"; }).join("") + "</select></label>";
    if (!d.live_quotes) h += '<div class="note" style="margin-top:10px">These contracts show no bid or ask right now, probably because the market is closed. Strikes and open interest are real, premiums are not. Load the chain again during market hours.</div>';
    h += '<div class="scroll" style="margin-top:10px"><table><thead><tr><th class="r">Strike</th><th class="r">Bid</th><th class="r">Ask</th><th class="r">Mid</th><th class="r hide-s">Spread</th><th class="r">Open int.</th><th class="r hide-s">IV</th><th></th></tr></thead><tbody>' + e.puts.map(function (r) {
      var thin = r.oi < 500, wide = r.mid === null || r.spread > 10;
      return '<tr class="clk" tabindex="0" data-act="pickput" data-k="' + r.k + '"><td class="r num">' + r.k.toFixed(2) + '</td><td class="r num">' + r.bid.toFixed(2) + '</td><td class="r num">' + r.ask.toFixed(2) + '</td><td class="r num">' + (r.mid === null ? "–" : r.mid.toFixed(2)) + '</td><td class="r num hide-s">' + (r.spread === null ? "–" : r.spread.toFixed(0) + "%") + '</td><td class="r num">' + r.oi.toLocaleString() + '</td><td class="r num hide-s">' + r.iv.toFixed(0) + '%</td><td>' + (thin ? '<span class="tag">thin</span> ' : "") + (wide ? '<span class="tag">wide</span>' : "") + "</td></tr>";
    }).join("") + '</tbody></table></div><p class="foot">Tap a strike to fill the calculator with its mid price. "Thin" means open interest under 500, "wide" means a bid-ask gap over 10% of the mid. The skill avoids both.</p>';
    el.innerHTML = h;
  }
  function pickPut(k) {
    if (!S.chain) return;
    var d = S.chain.data, e = d.expiries[Math.min(S.chain.exp, d.expiries.length - 1)], r = e.puts.filter(function (x) { return x.k === k; })[0];
    if (!r) return;
    S.csp.strike = String(r.k); S.csp.premium = r.mid === null ? "" : String(r.mid); S.csp.expiry = e.date; S.csp.example = false;
    if (S.q[d.symbol] && S.q[d.symbol].p) S.csp.price = S.q[d.symbol].p.toFixed(2); else if (d.price) S.csp.price = String(d.price);
    render();
  }

  /* ---------------- scan status ---------------- */
  async function loadStatus() {
    try { var r = await fetch("/api/status", { cache: "no-store" }); if (r.ok) S.scanSt = (await r.json()).scan; } catch (e) { /* keep the last status */ }
    paintScan();
  }
  function paintScan() {
    var el = $("#scan-st"), s = S.scanSt, b = $("[data-act=runscan]");
    if (el) el.textContent = !s ? "" : s.running ? "Scanning: " + (s.step || "working") + ". This takes a few minutes." : s.error ? "Last run failed: " + s.error : s.finished ? "Last run finished " + fmtET(s.finished) : "";
    if (b) b.disabled = !!(s && s.running);
  }
  async function runScan() {
    try { var r = await fetch("/api/scan/run", { method: "POST" }); if (!r.ok && r.status !== 409) throw new Error("http " + r.status); }
    catch (e) { S.scanSt = { running: false, error: "could not start the scan" }; paintScan(); return; }
    S.scanSt = { running: true, step: "starting" }; paintScan(); pollScan();
  }
  function pollScan() {
    clearTimeout(scanPoll);
    scanPoll = setTimeout(async function () {
      var before = S.scanSt && S.scanSt.finished;
      await loadStatus();
      if (S.scanSt && S.scanSt.running) pollScan(); else if (S.scanSt && !S.scanSt.error) reloadScan();
    }, 5000);
  }
  async function reloadScan() {
    try {
      var r = await fetch("/api/scan", { cache: "no-store" }); if (!r.ok) return;
      var d = await r.json();
      if (d.hits && d.hits.length && (!S.scan || d.as_of !== S.scan.as_of)) { S.scan = d; S.scan._map = null; $("#asof").textContent = "scan " + d.as_of; if (!isEditing()) render(); }
    } catch (e) { /* keep the current scan */ }
  }
  function startLive() {
    loadStatus().then(function () { if (S.scanSt && S.scanSt.running) pollScan(); });
    ensureQuotes(true);
    setInterval(function () { if (!document.hidden) ensureQuotes(false); }, 15000);
    setInterval(function () { if (!document.hidden) { refreshMarket(); reloadScan(); } }, 60000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) ensureQuotes(false); });
  }

'''
rep("  /* ---------------- boot ---------------- */", LIVE + "  /* ---------------- boot ---------------- */")

# ---- wrap as a full page
head = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}[hidden]{display:none!important}img{max-width:100%}</style>\n')
s = head + s + "\n</body></html>\n"
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(s)
print("built", OUT, len(s), "bytes")
