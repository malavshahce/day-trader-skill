/* Trader Desk logic. Pure functions, no DOM. Mirrors trader-exit (compute),
   trader-budget (size_trade) and trader-risk (checks). Prices are handled in
   integer cents so 358.32 never becomes 358.3199999. */
(function (root) {
  "use strict";

  var DEFAULTS = {
    budget: 5000, cash_buffer_pct: 10, max_position_pct: 75, max_order_usd: 4000,
    min_order_usd: 5, max_loss_per_trade_usd: 50, max_daily_loss_usd: 150,
    max_trades_per_day: 3, min_reward_risk: 1.0,
    no_entries_before: "09:45", no_entries_after: "15:30", flat_by: "15:55"
  };

  var MIN_RISK_PCT = 0.05;

  function num(x) {
    if (x === null || x === undefined || x === "") return NaN;
    var n = typeof x === "number" ? x : parseFloat(String(x).replace(/[$,\s]/g, ""));
    return isFinite(n) ? n : NaN;
  }
  function toCents(x) { return Math.round(num(x) * 100 + 1e-9); }
  function floorCents(x) { return Math.floor(num(x) * 100 + 1e-9); }
  function fromCents(c) { return c / 100; }
  function money(x, d) {
    if (!isFinite(x)) return "–";
    var neg = x < 0, v = Math.abs(x);
    var s = v.toLocaleString("en-US", { minimumFractionDigits: d === undefined ? 2 : d, maximumFractionDigits: d === undefined ? 2 : d });
    return (neg ? "-$" : "$") + s;
  }
  function hhmmToMin(t) {
    var m = /^(\d{1,2}):(\d{2})$/.exec(String(t || "").trim());
    if (!m) return NaN;
    var h = +m[1], mi = +m[2];
    if (h > 23 || mi > 59) return NaN;
    return h * 60 + mi;
  }

  /* ---------- exit plan: stop + target in exact cents ---------- */
  function computePlan(o) {
    var e = toCents(o.entry);
    if (!(e > 0)) return { error: "Enter an entry price above $0." };
    var raw, label;
    var rule = o.stopRule || "or_mid";
    if (rule === "or_mid" || rule === "or_low") {
      var oh = toCents(o.orHigh), ol = toCents(o.orLow);
      if (!(oh > 0) || !(ol > 0)) return { error: "An opening-range stop needs the range high and low." };
      if (oh <= ol) return { error: "The range high must be above the range low." };
      raw = rule === "or_mid" ? (oh + ol) / 2 : ol;
      label = rule === "or_mid" ? "opening-range midpoint" : "opening-range low";
    } else if (rule === "price") {
      var sp = num(o.stopParam);
      if (!isFinite(sp)) return { error: "Enter your stop price." };
      raw = sp * 100; label = "your price";
    } else if (rule === "pct") {
      var p = num(o.stopParam);
      if (!isFinite(p) || p <= 0 || p >= 100) return { error: "Enter a stop percent between 0 and 100." };
      raw = e * (1 - p / 100); label = p + "% under the entry";
    } else if (rule === "atr") {
      var a = num(o.atr), k = num(o.stopParam);
      if (!isFinite(a) || a <= 0) return { error: "An ATR stop needs the ATR value." };
      if (!isFinite(k) || k <= 0) return { error: "Enter an ATR multiple above 0." };
      raw = e - k * a * 100; label = k + " x ATR under the entry";
    } else return { error: "Unknown stop rule." };
    var stop = Math.floor(raw + 1e-6);
    if (stop >= e) return { error: "The stop " + money(fromCents(stop)) + " is at or above the entry " + money(fromCents(e)) + ". A long's stop goes under the entry." };
    if (stop <= 0) return { error: "The stop works out to " + money(fromCents(stop)) + ". Pick a stop above $0." };
    var risk = e - stop;
    if (risk < e * MIN_RISK_PCT / 100) return { error: "The stop is " + money(fromCents(risk)) + " under the entry, tighter than 0.05% of the price. Normal wiggle would stop you out. Widen it." };
    var target, tLabel;
    if (o.targetRule === "price") {
      var tp = num(o.targetParam);
      if (!isFinite(tp)) return { error: "Enter your target price." };
      target = toCents(tp); tLabel = "your price";
    } else {
      var r = num(o.targetParam === undefined || o.targetParam === "" ? 2 : o.targetParam);
      if (!isFinite(r) || r <= 0) return { error: "Enter a target in R above 0." };
      target = Math.round(e + r * risk); tLabel = r + "R";
    }
    if (target <= e) return { error: "The target " + money(fromCents(target)) + " is at or below the entry " + money(fromCents(e)) + "." };
    var rr = Math.round((target - e) / risk * 100) / 100;
    return {
      entry: fromCents(e), stop: fromCents(stop), target: fromCents(target),
      risk: fromCents(risk), reward: fromCents(target - e), rr: rr,
      stopLabel: label, targetLabel: tLabel
    };
  }

  /* ---------- sizing: four limits, smallest wins ---------- */
  function sharesFor(usd, perShare) {
    var u = Math.round(num(usd) * 100), p = Math.round(num(perShare) * 100);
    if (!(p > 0) || !(u > 0)) return 0;
    return Math.floor(u / p);
  }
  function sizeTrade(plan, cfg, opts) {
    var c = Object.assign({}, DEFAULTS, cfg || {});
    opts = opts || {};
    var ref = num(plan.entry), stop = num(plan.stop), target = num(plan.target);
    if (!(ref > 0) || !(stop > 0) || !(target > 0)) return { error: "The plan needs an entry, a stop and a target." };
    if (stop >= ref) return { error: "The stop is not below the entry." };
    if (target <= ref) return { error: "The target is not above the entry." };
    var budget = num(c.budget);
    if (!(budget > 0)) return { error: "Set an account budget above $0 in Settings." };
    var buf = num(c.cash_buffer_pct) || 0;
    if (buf < 0 || buf >= 100) return { error: "Cash buffer must be between 0 and 100 percent." };
    var riskC = toCents(ref) - toCents(stop), rewardC = toCents(target) - toCents(ref);
    var risk = riskC / 100;
    var available = Math.max(budget - Math.round(budget * buf) / 100, 0);
    var limits = [];
    var ml = num(c.max_loss_per_trade_usd);
    if (ml > 0) limits.push({ name: "Max loss", usd: ml, shares: sharesFor(ml, risk), how: money(ml) + " ÷ " + money(risk) + " risk a share" });
    var cp = num(c.max_position_pct);
    if (cp > 0) { var cap = Math.round(budget * cp) / 100; limits.push({ name: "Position cap", usd: cap, shares: sharesFor(cap, ref), how: cp + "% of " + money(budget, 0) + " = " + money(cap, 0) + " ÷ " + money(ref) }); }
    var mo = num(c.max_order_usd);
    if (mo > 0) limits.push({ name: "Max order", usd: mo, shares: sharesFor(mo, ref), how: money(mo, 0) + " ÷ " + money(ref) });
    limits.push({ name: "Cash", usd: available, shares: sharesFor(available, ref), how: money(available) + " after the " + buf + "% buffer ÷ " + money(ref) });
    var qty = Math.max(0, Math.min.apply(null, limits.map(function (l) { return l.shares; })));
    var bound = limits.filter(function (l) { return l.shares === qty; })[0].name;
    limits.forEach(function (l) { l.binds = l.name === bound; });
    var cost = Math.round(qty * ref * 100) / 100;
    var maxLoss = Math.round(qty * riskC) / 100;
    var reward = Math.round(qty * rewardC) / 100;
    var refusal = null;
    var minRR = num(c.min_reward_risk);
    if (qty === 0) {
      refusal = bound === "Max loss"
        ? "One share risks " + money(risk) + ", more than your " + money(ml) + " max loss per trade. Skip it or plan a closer stop."
        : "One share costs " + money(ref) + ", more than your " + bound.toLowerCase() + " limit.";
    } else if (minRR > 0 && rewardC < minRR * riskC - 1e-9) {
      refusal = "Reward:risk " + (rewardC / riskC).toFixed(2) + " is under your minimum " + minRR + ".";
    } else if (cost < num(c.min_order_usd)) {
      refusal = qty + " share(s) cost " + money(cost) + ", under your " + money(num(c.min_order_usd)) + " minimum order.";
    }
    return {
      qty: qty, cost: cost, maxLoss: maxLoss, maxReward: reward, risk: risk, limits: limits,
      boundBy: bound, refusal: refusal, rr: Math.round(rewardC / riskC * 100) / 100,
      pctOfBudget: Math.round(cost / budget * 1000) / 10
    };
  }

  /* ---------- risk check: PASS / BLOCK with reasons ---------- */
  function riskCheck(plan, sizing, cfg, state) {
    var c = Object.assign({}, DEFAULTS, cfg || {});
    state = state || {};
    var checks = [];
    function add(name, ok, detail) { checks.push({ name: name, ok: !!ok, detail: detail }); }
    if (!sizing || sizing.error) {
      add("Plan valid", false, sizing && sizing.error ? sizing.error : "No sizing available.");
      return { verdict: "BLOCK", checks: checks };
    }
    add("Stop is set", true, "Stop " + money(plan.stop));
    add("Size is at least 1 share", sizing.qty > 0, sizing.qty > 0 ? sizing.qty + " share(s)" : (sizing.refusal || "0 shares"));
    var ml = num(c.max_loss_per_trade_usd);
    if (ml > 0) add("Loss at stop within max per trade", sizing.maxLoss <= ml + 1e-9, money(sizing.maxLoss) + " vs " + money(ml));
    var minRR = num(c.min_reward_risk);
    if (minRR > 0) add("Reward:risk meets minimum", sizing.rr >= minRR - 1e-9, sizing.rr.toFixed(2) + " vs " + minRR);
    var riskedToday = num(state.riskedToday) || 0;
    var dl = num(c.max_daily_loss_usd);
    if (dl > 0) add("Daily loss limit", riskedToday + sizing.maxLoss <= dl + 1e-9, money(riskedToday) + " already risked + " + money(sizing.maxLoss) + " vs " + money(dl));
    var tradesToday = num(state.tradesToday) || 0;
    var mt = num(c.max_trades_per_day);
    if (mt > 0) add("Trades per day", tradesToday + 1 <= mt, "Trade " + (tradesToday + 1) + " of " + mt);
    if (state.nowET) {
      var now = hhmmToMin(state.nowET), a = hhmmToMin(c.no_entries_before), b = hhmmToMin(c.no_entries_after);
      if (isFinite(now) && isFinite(a) && isFinite(b)) {
        var open = !!state.marketOpen;
        add("Market open", open, open ? "Open" : "Closed now. Plan only, nothing to enter.");
        if (open) add("Inside entry window", now >= a && now <= b, state.nowET + " ET, window " + c.no_entries_before + "–" + c.no_entries_after);
      }
    }
    var ok = checks.every(function (x) { return x.ok; });
    return { verdict: ok ? "PASS" : "BLOCK", checks: checks };
  }

  /* ---------- New York time + NYSE hours ---------- */
  var HOLIDAYS = {
    "2026-01-01": 1, "2026-01-19": 1, "2026-02-16": 1, "2026-04-03": 1, "2026-05-25": 1, "2026-06-19": 1,
    "2026-07-03": 1, "2026-09-07": 1, "2026-11-26": 1, "2026-12-25": 1,
    "2027-01-01": 1, "2027-01-18": 1, "2027-02-15": 1, "2027-03-26": 1, "2027-05-31": 1, "2027-06-18": 1,
    "2027-07-05": 1, "2027-09-06": 1, "2027-11-25": 1, "2027-12-24": 1
  };
  var EARLY = { "2026-11-27": 1, "2026-12-24": 1, "2027-11-26": 1 };
  function nyParts(date) {
    var f = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour12: false, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", weekday: "short" });
    var o = {};
    f.formatToParts(date).forEach(function (p) { o[p.type] = p.value; });
    var h = o.hour === "24" ? "00" : o.hour;
    return { date: o.year + "-" + o.month + "-" + o.day, time: h + ":" + o.minute, weekday: o.weekday };
  }
  function marketStatus(date) {
    var p = nyParts(date);
    var wk = p.weekday !== "Sat" && p.weekday !== "Sun";
    var tradingDay = wk && !HOLIDAYS[p.date];
    var m = hhmmToMin(p.time), close = EARLY[p.date] ? 13 * 60 : 16 * 60;
    var state = "closed";
    if (tradingDay) {
      if (m >= 4 * 60 && m < 9 * 60 + 30) state = "pre";
      else if (m >= 9 * 60 + 30 && m < close) state = "open";
      else if (m >= close && m < 20 * 60) state = "after";
    }
    return { date: p.date, time: p.time, weekday: p.weekday, tradingDay: tradingDay, state: state, open: state === "open" };
  }

  /* ---------- cash-secured put math ---------- */
  function cspCalc(o) {
    var px = num(o.price), k = num(o.strike), prem = num(o.premium), dte = num(o.dte);
    var acct = num(o.account), riskPct = num(o.riskPct);
    if (!(px > 0)) return { error: "Enter the stock price." };
    if (!(k > 0)) return { error: "Enter the strike." };
    if (!(prem > 0)) return { error: "Enter the premium you would receive per share." };
    if (!(dte > 0)) return { error: "Enter days to expiry." };
    if (prem >= k) return { error: "The premium cannot be as large as the strike." };
    var cash = k * 100;
    var credit = prem * 100;
    var breakeven = k - prem;
    var retPct = prem / (k - prem) * 100;           // return on cash actually tied up (strike less premium)
    var ann = retPct * 365 / dte;
    var otm = (px - k) / px * 100;
    var out = {
      cashPerContract: cash, creditPerContract: credit, breakeven: breakeven,
      returnPct: retPct, annualizedPct: ann, otmPct: otm,
      worstCase: (k - prem) * 100,                  // stock to zero
      loss20: (k - prem) * 100 * 0.20               // options-strategist sizing rule: 20% adverse move
    };
    if (acct > 0) {
      out.fitsAccount = Math.floor(acct / cash);
      out.pctOfAccount = cash / acct * 100;
      if (riskPct > 0) {
        var rd = acct * riskPct / 100;
        out.riskBudget = rd;
        out.contractsByRisk = Math.floor(rd / out.loss20);
      }
    }
    out.contracts = Math.min(out.fitsAccount === undefined ? Infinity : out.fitsAccount,
                             out.contractsByRisk === undefined ? Infinity : out.contractsByRisk);
    if (!isFinite(out.contracts)) out.contracts = 0;
    return out;
  }

  /* ---------- scan filtering ---------- */
  var SETUPS = {
    breakout_20d: "20-day breakout", bull_flag: "Bull flag", reclaim_ma20: "Reclaimed 20-day",
    oversold: "Oversold", oversold_bounce: "Oversold bounce"
  };
  function filterScan(rows, f) {
    f = f || {};
    var q = String(f.query || "").trim().toUpperCase();
    var maxP = num(f.maxPrice), minP = num(f.minPrice), minV = num(f.minVolume);
    var out = rows.filter(function (r) {
      var sym = r[0], name = r[1] || "", price = r[2], rsi = r[3], vol = r[4], su = r[5] || [];
      if (q && sym.indexOf(q) !== 0 && name.toUpperCase().indexOf(q) === -1) return false;
      if (isFinite(maxP) && price > maxP) return false;
      if (isFinite(minP) && price < minP) return false;
      if (isFinite(minV) && vol < minV) return false;
      if (f.setup && f.setup !== "all" && su.indexOf(f.setup) === -1) return false;
      if (f.exclude && f.exclude.length && f.exclude.indexOf(sym) !== -1) return false;
      return true;
    });
    var key = f.sort || "dollar";
    var dir = f.dir === "asc" ? 1 : -1;   // 1 = ascending
    out.sort(function (a, b) {
      if (key === "symbol") return a[0] < b[0] ? -dir : a[0] > b[0] ? dir : 0;
      var va, vb;
      if (key === "price") { va = a[2]; vb = b[2]; }
      else if (key === "rsi") { va = a[3]; vb = b[3]; }
      else if (key === "volume") { va = a[4]; vb = b[4]; }
      else { va = a[2] * a[4]; vb = b[2] * b[4]; }
      return (va - vb) * dir;
    });
    return out;
  }

  var api = {
    DEFAULTS: DEFAULTS, SETUPS: SETUPS, num: num, money: money, toCents: toCents,
    computePlan: computePlan, sizeTrade: sizeTrade, riskCheck: riskCheck,
    marketStatus: marketStatus, nyParts: nyParts, cspCalc: cspCalc, filterScan: filterScan,
    hhmmToMin: hhmmToMin, sharesFor: sharesFor
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TraderLib = api;
})(typeof window !== "undefined" ? window : this);
