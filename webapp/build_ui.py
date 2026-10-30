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
rep('["journal", "Journal"], ["ask", "Ask Claude"], ["guide", "Guide"], ["settings", "Settings"]];', '["journal", "Journal"], ["guide", "Guide"], ["settings", "Settings"]];')
rep('["scanner", "Scanner"], ["planner", "Planner"]', '["scanner", "Scanner"], ["movers", "Movers"], ["planner", "Planner"]')
rep("  var IS_WEB = false;", "  var IS_WEB = true;")
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
rep("journal: vJournal, ask: vAsk, guide: vGuide, settings: vSettings }[S.tab];", "journal: vJournal, guide: vGuide, movers: vMovers, settings: vSettings }[S.tab];")
rep('    if (S.tab === "ask") updateChat();\n    if (S.tab === "news") updateNews();', '    if (S.tab === "news") updateNews();\n    if (S.tab === "options") renderChain();\n    ensureQuotes(false); paintLive(); paintMoversCards();\n    if (S.tab === "movers") { updateMovers(); loadMovers(false); }\n    if (S.tab === "news") paintNewsAge();')
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
rep("</style>", ".clock { flex-wrap: wrap; justify-content: flex-end; }\n#clock { white-space: nowrap; }\ntd.wrapc, td.wrapc .pill { white-space: normal; }\n@media (max-width: 560px) { [data-lv] .small { display: block; } }\n</style>")
rep('<tr><td colspan="6" class="empty">', '<tr><td colspan="7" class="empty">')
rep('<th class="r">Price</th><th class="r">RSI</th><th>Setup</th>', '<th class="r hide-s">Close</th><th class="r">Live</th><th class="r">RSI</th><th class="hide-s">Setup</th>')
rep("""'</td><td class="r num">' + r[2].toFixed(2) + '</td><td class="r num">' + r[3].toFixed(0) + '</td><td>' + esc(""", """'</td><td class="r num hide-s">' + r[2].toFixed(2) + '</td>' + lvCell(r[0]) + '<td class="r num">' + r[3].toFixed(0) + '</td><td class="hide-s">' + esc(""")
rep("""(d === null ? "open" : L.money(d))""", """(d === null ? '<span data-unreal="1" data-sym="' + esc(j.sym) + '" data-entry="' + esc(j.entry) + '" data-qty="' + esc(j.qty) + '">open</span>' : L.money(d))""")
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

# ---- Today: after-hours / pre-market movers card
rep("""h += '<div class="grid g2"><section class="card"><div class="head"><h2>Big movers</h2>""", """h += '<section class="card" id="td-movers"></section>';
    h += '<div class="grid g2"><section class="card"><div class="head"><h2>Big movers</h2>""")
# Scanner: look up any stock
rep("""h += '<div style="margin-top:12px"><div class="scroll"><table id="scan-t">""", """h += '<div class="form" style="margin-top:12px"><label class="f wide">Check any stock: does it match, and if not, why?<span class="row"><input id="lk-sym" placeholder="AMZN" maxlength="8" autocomplete="off" style="max-width:160px"><button class="btn" data-act="lookup">Check</button></span></label></div><div id="lk-out"></div>';
    h += '<div style="margin-top:12px"><div class="scroll"><table id="scan-t">""")
# News: refresh controls
rep("""h += '<div class="form"><label class="f">Ticker<select id="n-t">""", """h += '<div class="row" style="margin-bottom:10px"><button class="btn sm" data-act="refreshnews" id="n-refresh">Refresh news</button><span class="muted small" id="n-age"></span></div>';
    h += '<div class="form"><label class="f">Ticker<select id="n-t">""")

# ---- new actions and input hooks
rep("""    if (a === "tab") go(v);
    else if (a === "reload") boot();""", """    if (a === "tab") go(v);
    else if (a === "reload") boot();
    else if (a === "refresh") { ensureQuotes(true); refreshMarket(); }
    else if (a === "uselive") { var lq = S.q[v]; if (lq && lq.p) { S.plan.entry = lq.p.toFixed(2); S.plan.example = false; S.plan.auto = true; render(); } }
    else if (a === "usecsp") { var cq = S.q[v]; if (cq && cq.p) { S.csp.price = cq.p.toFixed(2); S.csp.example = false; S.csp.auto = true; render(); } }
    else if (a === "loadchain") loadChain("");
    else if (a === "expiry") loadChain(v);
    else if (a === "pickput") pickPut(+t.getAttribute("data-k"));
    else if (a === "lookup") lookupStock();
    else if (a === "refreshnews") refreshNews();
    else if (a === "mvfilter") { MV.filter = v; updateMovers(); }
    else if (a === "runscan") runScan();""")
rep("""    if (id.indexOf("p-") === 0) { readPlan(); S.plan.example = false;""", """    if (id.indexOf("p-") === 0) { readPlan(); S.plan.example = false; if (id === "p-entry") S.plan.auto = false; if (id === "p-symbol") { S.plan.auto = true; scheduleLive(); }""")
rep("""    else if (id.indexOf("c-") === 0) { readCsp(); S.csp.example = false; updateCsp(); }""", """    else if (id === "c-exp") { if (ev.target.value) loadChain(ev.target.value); }
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
    return q.p.toFixed(2) + (q.ses === "post" ? ' <span class="muted small">AH</span>' : q.ses === "pre" ? ' <span class="muted small">PM</span>' : "") + (isFinite(q.pct) ? ' <span class="' + cls(q.pct) + ' small">' + fmtPct(q.pct) + "</span>" : "");
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

  /* ---------------- put chain: every expiry, from 0 DTE to long-dated ---------------- */
  var SHORT_BUCKETS = [["0 DTE", 0, 0], ["4-5 DTE", 4, 5], ["7 DTE", 6, 8], ["14 DTE", 12, 16]];
  async function loadChain(date) {
    var sym = String(S.csp.symbol || "").toUpperCase();
    if (!validSym(sym)) { S.chainErr = "Enter a symbol first."; renderChain(); return; }
    S.chainBusy = true; S.chainErr = ""; renderChain();
    try {
      var r = await fetch("/api/chain?symbol=" + encodeURIComponent(sym) + (date ? "&date=" + encodeURIComponent(date) : ""), { cache: "no-store" });
      if (!r.ok) throw new Error("http " + r.status);
      S.chain = { data: await r.json() };
      if (date) { S.csp.expiry = date; S.csp.example = false; }
      if (!(S.q[sym] && S.q[sym].p) && S.chain.data.price) S.csp.price = String(S.chain.data.price);
    } catch (e) { S.chain = null; S.chainErr = "Could not load options for " + sym + ". The symbol may have no options, or the data source is busy."; }
    S.chainBusy = false; if (S.tab === "options") render();
  }
  function dteChip(label, x, selDate) { return '<button class="chip" data-act="expiry" data-v="' + esc(x.date) + '" aria-pressed="' + (x.date === selDate) + '">' + esc(label) + "</button>"; }
  function renderChain() {
    var el = $("#c-chain"); if (!el) return;
    if (S.chainBusy) { el.innerHTML = '<p class="muted" style="margin-top:10px">Loading the put chain…</p>'; return; }
    if (S.chainErr) { el.innerHTML = '<div class="note bad" style="margin-top:10px">' + esc(S.chainErr) + "</div>"; return; }
    if (!S.chain) { el.innerHTML = ""; return; }
    var d = S.chain.data, all = d.all, sel = d.sel, used = {};
    var h = '<h3 style="margin-top:14px">Pick an expiry</h3><div class="row" style="margin-top:6px" id="c-short">';
    SHORT_BUCKETS.forEach(function (b) {
      var mid = (b[1] + b[2]) / 2, c = all.filter(function (x) { return x.dte >= b[1] && x.dte <= b[2]; }).sort(function (p, q) { return Math.abs(p.dte - mid) - Math.abs(q.dte - mid); })[0];
      if (c) { used[c.date] = 1; h += dteChip(b[0] + " · " + fmtDay(c.date), c, sel.date); }
      else h += '<button class="chip" disabled title="This stock has no expiry in that range">' + esc(b[0]) + ": none</button>";
    });
    h += "</div>";
    var std = all.filter(function (x) { return !used[x.date] && x.dte >= 15 && x.dte <= 60; }).slice(0, 6);
    if (std.length) h += '<p class="muted small" style="margin-top:10px">Standard (15 to 60 days)</p><div class="row" id="c-std">' + std.map(function (x) { return dteChip(x.dte + " DTE · " + fmtDay(x.date), x, sel.date); }).join("") + "</div>";
    var long = all.filter(function (x) { return x.dte > 60; });
    if (long.length) h += '<label class="f" style="margin-top:10px;max-width:340px">Long-dated expiries<select id="c-exp"><option value="">Choose…</option>' + long.map(function (x) { return '<option value="' + esc(x.date) + '"' + (x.date === sel.date ? " selected" : "") + ">" + esc(fmtDay(x.date)) + " " + x.date.slice(0, 4) + " · " + x.dte + " days" + (x.dte >= 330 ? " · LEAPS" : "") + "</option>"; }).join("") + "</select></label>";
    h += '<p style="margin-top:10px"><b>Showing ' + esc(fmtDay(sel.date)) + " " + sel.date.slice(0, 4) + " · " + (sel.dte === 0 ? "0 DTE (expires today)" : sel.dte + " DTE") + "</b></p>";
    if (sel.dte <= 7) h += '<div class="note" style="margin-top:8px">Short-dated: these move fast and can gap. Prefer only liquid names and small size.</div>';
    if (!d.live_quotes) h += '<div class="note" style="margin-top:10px">These contracts show no bid or ask right now, probably because the market is closed. Strikes and open interest are real, premiums are not. Load the chain again during market hours.</div>';
    h += '<div class="scroll" style="margin-top:10px"><table><thead><tr><th class="r">Strike</th><th class="r">Bid</th><th class="r">Ask</th><th class="r">Mid</th><th class="r hide-s">Spread</th><th class="r">Open int.</th><th class="r hide-s">IV</th><th></th></tr></thead><tbody>' + (sel.puts.length ? sel.puts.map(function (r) {
      var thin = r.oi < 500, wide = r.mid === null || r.spread > 10;
      return '<tr class="clk" tabindex="0" data-act="pickput" data-k="' + r.k + '"><td class="r num">' + r.k.toFixed(2) + '</td><td class="r num">' + r.bid.toFixed(2) + '</td><td class="r num">' + r.ask.toFixed(2) + '</td><td class="r num">' + (r.mid === null ? "–" : r.mid.toFixed(2)) + '</td><td class="r num hide-s">' + (r.spread === null ? "–" : r.spread.toFixed(0) + "%") + '</td><td class="r num">' + r.oi.toLocaleString() + '</td><td class="r num hide-s">' + r.iv.toFixed(0) + '%</td><td>' + (thin ? '<span class="tag">thin</span> ' : "") + (wide ? '<span class="tag">wide</span>' : "") + "</td></tr>";
    }).join("") : '<tr><td colspan="8" class="empty">No puts near the price for this expiry.</td></tr>') + '</tbody></table></div><p class="foot">Tap a strike to fill the calculator with its mid price. "Thin" means open interest under 500, "wide" means a bid-ask gap over 10% of the mid. The skill avoids both.</p>';
    el.innerHTML = h;
  }
  function pickPut(k) {
    if (!S.chain) return;
    var d = S.chain.data, r = d.sel.puts.filter(function (x) { return x.k === k; })[0];
    if (!r) return;
    S.csp.strike = String(r.k); S.csp.premium = r.mid === null ? "" : String(r.mid); S.csp.expiry = d.sel.date; S.csp.example = false;
    if (S.q[d.symbol] && S.q[d.symbol].p) S.csp.price = S.q[d.symbol].p.toFixed(2); else if (d.price) S.csp.price = String(d.price);
    render();
  }

  /* ---------------- movers: pre-market, after-hours and intraday moves, earnings reactions tagged ---------------- */
  var MV = { data: null, filter: "all", err: "", busy: false, at: 0 };
  async function loadMovers(force) {
    if (MV.busy || (!force && Date.now() - MV.at < 45000)) return;
    MV.busy = true;
    try {
      var r = await fetch("/api/movers", { cache: "no-store" });
      if (!r.ok) throw new Error("http " + r.status);
      MV.data = await r.json(); MV.err = ""; MV.at = Date.now();
      if (MV.data.building) setTimeout(function () { MV.at = 0; loadMovers(true); }, 8000);
    } catch (e) { MV.err = "Movers are unavailable right now."; }
    MV.busy = false;
    if (S.tab === "movers") updateMovers();
    paintMoversCards();
  }
  function earnTagFor(r) {
    if (!r.e) return "";
    var d = dayDiff(today(), r.e); if (d < -2 || d > 1) return "";
    var when = r.ew === "post" ? " · after close" : r.ew === "pre" ? " · before open" : "";
    return '<span class="pill ' + (d <= 0 ? "warn" : "") + '">Earnings ' + esc(fmtDay(r.e)) + esc(when) + "</span>";
  }
  function sesTag(ses) { return ses === "post" ? ' <span class="muted small">AH</span>' : ses === "pre" ? ' <span class="muted small">PM</span>' : ""; }
  function moverTr(r) {
    return '<tr class="clk" tabindex="0" data-act="open" data-v="' + esc(r.s) + '"><td class="wrapc"><span class="sym">' + esc(r.s) + "</span>" + earnTagFor(r) + '<span class="nm">' + esc(r.n) + '</span></td><td class="r num hide-s">' + r.close.toFixed(2) + '</td><td class="r num">' + r.p.toFixed(2) + sesTag(r.ses) + '</td><td class="r num ' + cls(r.move) + '">' + fmtPct(r.move) + '</td><td class="r num hide-s">' + fmtVol(r.vol) + "</td></tr>";
  }
  function moverRows() {
    var rows = (MV.data && MV.data.rows) || [];
    if (MV.filter === "earnings") rows = rows.filter(function (r) { return earnTagFor(r); });
    else if (MV.filter === "up") rows = rows.filter(function (r) { return r.move > 0; });
    else if (MV.filter === "down") rows = rows.filter(function (r) { return r.move < 0; });
    return rows;
  }
  function vMovers() {
    var h = '<section class="card"><div class="head"><h2>Movers</h2><span class="src" id="mv-src"></span></div>';
    h += '<p class="muted" style="margin-bottom:10px">The biggest moves right now among about 1,500 liquid stocks. Before the open and after the close, <b>Move</b> is the change since the 4pm close, which is where earnings reactions show up. During the day it is the change since yesterday.</p>';
    h += '<div class="row" id="mv-chips">' + [["all", "All"], ["earnings", "Earnings only"], ["up", "Up"], ["down", "Down"]].map(function (f) { return '<button class="chip" data-act="mvfilter" data-v="' + f[0] + '" aria-pressed="' + (MV.filter === f[0]) + '">' + f[1] + "</button>"; }).join("") + "</div>";
    h += '<div id="mv-body" style="margin-top:12px"></div></section>';
    return h;
  }
  function updateMovers() {
    var el = $("#mv-body"); if (!el) return;
    Array.prototype.forEach.call(document.querySelectorAll("#mv-chips .chip"), function (c) { c.setAttribute("aria-pressed", String(c.getAttribute("data-v") === MV.filter)); });
    var src = $("#mv-src");
    if (!MV.data) { el.innerHTML = MV.err ? '<div class="note bad">' + esc(MV.err) + "</div>" : '<p class="muted">Loading movers…</p>'; return; }
    if (src) src.textContent = "Updated " + ago(MV.data.as_of) + " · " + (MV.data.checked || 0).toLocaleString() + " stocks";
    if (MV.data.building) { el.innerHTML = '<div class="note info">Building the list of liquid stocks. This happens once a day and takes under a minute.</div>'; return; }
    var rows = moverRows();
    el.innerHTML = rows.length ? '<div class="scroll"><table><thead><tr><th>Stock</th><th class="r hide-s">Close</th><th class="r">Now</th><th class="r">Move</th><th class="r hide-s">Volume</th></tr></thead><tbody>' + rows.map(moverTr).join("") + '</tbody></table></div><p class="foot">Tap a row for details and to plan a trade. Pre-market and after-hours prices trade thinly and can jump. Data is delayed.</p>' : '<p class="empty">No stocks match this filter right now.</p>';
  }
  function paintMoversCards() {
    var el = $("#td-movers"); if (!el) return;
    if (!MV.data) { el.innerHTML = '<div class="head"><h2>After-hours and pre-market movers</h2></div><p class="muted">' + esc(MV.err || "Loading…") + "</p>"; loadMovers(false); return; }
    var rows = (MV.data.rows || []).slice().sort(function (a, b) { return (earnTagFor(b) ? 1 : 0) - (earnTagFor(a) ? 1 : 0) || Math.abs(b.move) - Math.abs(a.move); }).slice(0, 6);
    el.innerHTML = '<div class="head"><h2>Earnings reactions and big moves</h2><span class="src">Updated ' + esc(ago(MV.data.as_of)) + '</span></div>' + (MV.data.building ? '<p class="muted">Building the list of liquid stocks…</p>' : rows.length ? '<div class="scroll"><table><thead><tr><th>Stock</th><th class="r hide-s">Close</th><th class="r">Now</th><th class="r">Move</th><th class="r hide-s">Volume</th></tr></thead><tbody>' + rows.map(moverTr).join("") + '</tbody></table></div><p class="foot">These moved after the regular session or early today, so the daily scan cannot see them. <a href="#movers" data-act="tab" data-v="movers">See all movers</a></p>' : '<p class="muted">Nothing is moving more than 2% right now.</p>');
  }

  /* ---------------- look up any stock ---------------- */
  async function lookupStock() {
    var el = $("#lk-out"), sym = N("lk-sym").trim().toUpperCase().replace(/[^A-Z0-9.\-^]/g, "");
    if (!el) return;
    if (!validSym(sym)) { el.innerHTML = '<p class="err">Type a stock symbol, for example AMZN.</p>'; return; }
    el.innerHTML = '<p class="muted">Checking ' + esc(sym) + "…</p>";
    try {
      var r = await fetch("/api/lookup?symbol=" + encodeURIComponent(sym), { cache: "no-store" });
      if (r.status === 404) { el.innerHTML = '<div class="note">No chart data found for ' + esc(sym) + ". Check the symbol.</div>"; return; }
      if (!r.ok) throw new Error("http " + r.status);
      var d = await r.json(), n = d.setups.length;
      var h = '<div class="card flat" style="margin-top:12px"><div class="head"><div><h3 class="mono" style="display:inline">' + esc(d.symbol) + '</h3> <span class="muted">' + esc(d.name) + '</span></div><span class="pill ' + (n ? "good" : "") + '">' + (n ? "Matches " + n + " setup" + (n === 1 ? "" : "s") : "No setup today") + "</span></div>";
      h += "<p>Close <b>" + d.close.toFixed(2) + "</b> (" + esc(fmtDay(d.as_of)) + ") · RSI " + d.rsi.toFixed(0) + ' · Live <span data-lv="' + esc(d.symbol) + '"></span>' + (d.earn ? " · Earnings " + esc(fmtDay(d.earn)) : "") + "</p>";
      h += '<ul class="checks">' + d.checks.map(function (c) { return '<li><span class="' + (c.match ? "ok" : "no") + '">' + (c.match ? "✓" : "✕") + "</span><span><b>" + esc(setupName(c.k)) + ".</b> " + esc(c.why) + "</span></li>"; }).join("") + "</ul>";
      h += '<div class="row" style="margin-top:10px"><button class="btn p sm" data-act="plan" data-v="' + esc(d.symbol) + '">Plan this trade</button><button class="btn sm" data-act="open" data-v="' + esc(d.symbol) + '">Details</button></div>';
      h += '<p class="foot">The scan only reads regular-session closes. A move after the close, such as an earnings reaction, shows in the <a href="#movers" data-act="tab" data-v="movers">Movers</a> tab instead.</p></div>';
      el.innerHTML = h; ensureQuotes(false);
    } catch (e) { el.innerHTML = '<div class="note bad">Could not check ' + esc(sym) + " right now. Try again in a moment.</div>"; }
  }
  document.addEventListener("keydown", function (ev) { if (ev.key === "Enter" && ev.target && ev.target.id === "lk-sym") lookupStock(); });

  /* ---------------- news: newest first, refresh on demand ---------------- */
  function paintNewsAge() {
    var el = $("#n-age"); if (!el || !S.news) return;
    el.textContent = "Updated " + (S.news.checked ? ago(S.news.checked) : "just now") + (S.news.refreshing ? " · refreshing…" : "");
  }
  async function reloadNews() {
    try {
      var r = await fetch("/api/news", { cache: "no-store" }); if (!r.ok) return null;
      var d = await r.json(); if (!d || !d.items) return null;
      var changed = !S.news || d.checked !== S.news.checked;
      S.news = d;
      if (S.tab === "news" && changed && !isEditing()) updateNews();
      paintNewsAge(); return d;
    } catch (e) { return null; }
  }
  async function refreshNews() {
    var b = $("#n-refresh"); if (b) b.disabled = true;
    var before = S.news && S.news.checked;
    try { await fetch("/api/news?refresh=1", { cache: "no-store" }); } catch (e) { /* the polling below shows the old news */ }
    for (var i = 0; i < 12; i++) {
      await new Promise(function (res) { setTimeout(res, 4000); });
      var d = await reloadNews();
      if (d && d.checked !== before && !d.refreshing) break;
    }
    var b2 = $("#n-refresh"); if (b2) b2.disabled = false;
    paintNewsAge();
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
    setInterval(function () { if (!document.hidden) { if (S.tab === "movers" || S.tab === "today") loadMovers(false); if (S.tab === "news") reloadNews(); } }, 60000);
    loadMovers(false);
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
