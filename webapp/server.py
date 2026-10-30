#!/usr/bin/env python3
"""Trader Desk web server. Standard library only, read-only.

Serves the dashboard and a small JSON API that fetches free public data
(Yahoo Finance charts, option chains and earnings dates) on the server, so the
page never has to ask Yahoo itself. It reuses the repo's own tools for the
scan (trader-scanner) and the news (trader-news). Nothing here can place an
order, and no broker keys are read or stored.

    DESK_PASSWORD=secret python3 webapp/server.py            # http://127.0.0.1:8000
    PORT=10000 DESK_PASSWORD=secret python3 webapp/server.py # cloud: binds 0.0.0.0

Environment:
    DESK_PASSWORD     required in the cloud (HTTP Basic, any user name)
    PORT              set by most hosts; when present the server binds 0.0.0.0
    SEC_USER_AGENT    "Your Name you@example.com", for SEC filings in the news
    DESK_DATA         where the scan and news are kept (default webapp/data)
    DESK_WATCH        extra tickers to always watch, comma separated
    DESK_NO_SCHEDULER set to 1 to turn the automatic daily scan off
"""

import base64
import datetime as dt
import gzip
import hashlib
import hmac
import http.cookiejar
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".claude" / "skills"
STATIC = Path(__file__).resolve().parent / "static"
SEED = ROOT / "dashboard" / "data"
DATA = Path(os.environ.get("DESK_DATA") or (Path(__file__).resolve().parent / "data"))
UA = "Mozilla/5.0"  # Yahoo rejects long browser-style agents that carry no cookies
SYM_RE = re.compile(r"^[A-Z0-9.\-^]{1,10}$")
INDEXES = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow"), ("^RUT", "Russell 2000"), ("^VIX", "VIX"), ("^VIX3M", "VIX3M")]
EXTRA_WATCH = ["SPY", "QQQ", "AMZN", "MSFT", "META", "NVDA", "TSLA", "KEY", "PFE", "BAC", "F", "T"]   # SPY and QQQ carry the market-wide headlines

_lock = threading.RLock()
_cache = {}


# ------------------------------------------------------------------ small helpers

_key_locks = {}


def cached(key, ttl, fn):
    """Return fn() for key, reusing a value younger than ttl seconds.

    Simultaneous callers for the same key share one fetch instead of each calling the data source."""
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        klock = _key_locks.setdefault(key, threading.Lock())
    with klock:
        with _lock:
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        value = fn()
        with _lock:
            _cache[key] = (time.time(), value)
            if len(_cache) > 3000:   # keep memory flat on a small host
                for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[:1000]:
                    _cache.pop(k, None)
                    _key_locks.pop(k, None)
        return value


def http_json(url, timeout=15, opener=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    last = None
    for attempt in range(2):
        try:
            with (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = e
        time.sleep(0.4)
    raise RuntimeError("fetch failed: %s" % (last,))


def clean_symbols(text, limit=60):
    out = []
    for s in str(text or "").upper().split(","):
        s = s.strip()
        if s and SYM_RE.match(s) and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def eastern_now(now=None):
    """New York wall-clock time (handles daylight saving without tzdata)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    y = now.year

    def nth_sunday(month, n):
        d = dt.date(y, month, 1)
        d += dt.timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))
        return d
    start = dt.datetime.combine(nth_sunday(3, 2), dt.time(7), tzinfo=dt.timezone.utc)   # 2:00 EST = 07:00 UTC
    end = dt.datetime.combine(nth_sunday(11, 1), dt.time(6), tzinfo=dt.timezone.utc)    # 2:00 EDT = 06:00 UTC
    off = -4 if start <= now < end else -5
    return (now + dt.timedelta(hours=off)).replace(tzinfo=None)


# ------------------------------------------------------------------ quotes and market

def fetch_quote(sym):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1m&includePrePost=true" % urllib.parse.quote(sym)
    res = http_json(url)["chart"]["result"][0]
    meta = res.get("meta", {})
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    stamps = res.get("timestamp") or []
    price = t = None
    for i in range(len(closes) - 1, -1, -1):
        if closes[i] is not None and i < len(stamps):
            price, t = float(closes[i]), stamps[i]
            break
    if price is None:
        price = meta.get("regularMarketPrice")
        t = meta.get("regularMarketTime")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None:
        raise RuntimeError("no price")
    out = {"p": round(float(price), 4), "t": iso(t) if t else None}
    if prev:
        out["pc"] = round(float(prev), 4)
        out["pct"] = round((float(price) / float(prev) - 1) * 100, 2)
    return out


def parse_batch_quote(r):
    """One entry of Yahoo's batch quote reply -> {p, pc, pct, t, ses}. The latest of regular, pre and post wins."""
    cands = []
    for pk, tk, ses in (("regularMarketPrice", "regularMarketTime", "reg"), ("preMarketPrice", "preMarketTime", "pre"),
                        ("postMarketPrice", "postMarketTime", "post")):
        p, t = r.get(pk), r.get(tk)
        if p is not None and t:
            cands.append((t, float(p), ses))
    if not cands:
        if r.get("regularMarketPrice") is None:
            raise ValueError("no price")
        cands.append((0, float(r["regularMarketPrice"]), "reg"))
    t, p, ses = max(cands)
    out = {"p": round(p, 4), "t": iso(t) if t else None, "ses": ses}
    prev = r.get("regularMarketPreviousClose")
    if prev:
        out["pc"] = round(float(prev), 4)
        out["pct"] = round((p / float(prev) - 1) * 100, 2)
    return out


def raw_batch(symbols):
    """Yahoo's batch quote rows, unparsed (up to 60 symbols per call)."""
    url = "https://query2.finance.yahoo.com/v7/finance/quote?symbols=%s&crumb={crumb}" % urllib.parse.quote(",".join(symbols))
    return crumb_json(url)["quoteResponse"]["result"]


def et_date_and_when(ts):
    """Earnings timestamp -> (YYYY-MM-DD in New York, 'pre' | 'post' | '')."""
    if not ts:
        return None, ""
    local = eastern_now(dt.datetime.fromtimestamp(ts, dt.timezone.utc))
    minutes = local.hour * 60 + local.minute
    return local.strftime("%Y-%m-%d"), ("pre" if minutes < 9 * 60 + 30 else "post" if minutes >= 16 * 60 else "")


def fetch_quotes_batch(symbols):
    """Up to 60 symbols in ONE Yahoo call (the per-symbol chart route needs one call each)."""
    got = {}
    for r in raw_batch(symbols):
        try:
            got[r["symbol"]] = parse_batch_quote(r)
        except (ValueError, KeyError):
            pass
    return got


def get_quote(sym):
    try:
        return cached("q:" + sym, 15, lambda: fetch_quote(sym))
    except Exception as e:  # one bad symbol must not fail the batch
        return {"err": "no data for " + sym if "no price" in str(e) or "404" in str(e) else "quote unavailable"}


def get_quotes(symbols):
    symbols = clean_symbols(",".join(symbols) if isinstance(symbols, list) else symbols)
    out, need, now = {}, [], time.time()
    with _lock:
        for sym in symbols:
            hit = _cache.get("q:" + sym)
            if hit and now - hit[0] < 15:
                out[sym] = hit[1]
            else:
                need.append(sym)
    if need:
        try:
            got = fetch_quotes_batch(need)
            for sym in need:
                q = got.get(sym)
                if q:
                    with _lock:
                        _cache["q:" + sym] = (time.time(), q)
                    out[sym] = q
                else:
                    out[sym] = {"err": "no data for " + sym}
        except Exception:
            # batch route is down: fall back to one chart call per symbol
            with ThreadPoolExecutor(max_workers=8) as ex:
                for sym, q in zip(need, ex.map(get_quote, need)):
                    out[sym] = q
    return {"as_of": iso(time.time()), "quotes": {s: out[s] for s in symbols}}


def fetch_index(sym, name):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=6mo&interval=1d" % urllib.parse.quote(sym)
    res = http_json(url)["chart"]["result"][0]
    pairs = [(t, c) for t, c in zip(res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]) if c is not None]
    if len(pairs) < 21:
        raise RuntimeError("not enough history")
    closes = [c for _, c in pairs]

    def sma(n):
        return round(sum(closes[-n:]) / n, 2)
    return {"name": name, "last": round(closes[-1], 2), "prev": round(closes[-2], 2),
            "pct": round((closes[-1] / closes[-2] - 1) * 100, 2), "sma20": sma(20), "sma50": sma(min(50, len(closes))),
            "date": dt.datetime.fromtimestamp(pairs[-1][0], dt.timezone.utc).strftime("%Y-%m-%d")}


def get_market():
    def build():
        idx, errors = {}, []
        for sym, name in INDEXES:
            try:
                idx[sym] = fetch_index(sym, name)
            except Exception as e:
                errors.append("%s: %s" % (sym, e))
        if not idx:
            raise RuntimeError("market data unavailable")
        return {"as_of": max(v["date"] for v in idx.values()), "idx": idx, "errors": errors}
    try:
        return cached("market", 60, build)
    except Exception:
        return read_json(DATA / "market.json", {"as_of": "", "idx": {}, "errors": ["unavailable"]})


# ------------------------------------------------------------------ yahoo crumb (earnings, options)

_session = {"opener": None, "crumb": None, "at": 0}


def crumb_json(url_template):
    """url_template contains {crumb}; one session is reused for ~45 minutes."""
    with _lock:
        if not _session["crumb"] or time.time() - _session["at"] > 2700:
            cj = http.cookiejar.CookieJar()
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            op.addheaders = [("User-Agent", UA)]
            try:
                op.open("https://fc.yahoo.com", timeout=10)
            except Exception:
                pass  # the cookie is set even on the 404 reply
            with op.open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10) as r:
                crumb = r.read().decode().strip()
            if not crumb or len(crumb) > 40 or "<" in crumb:
                raise RuntimeError("could not get a data session")
            _session.update(opener=op, crumb=crumb, at=time.time())
        op, crumb = _session["opener"], _session["crumb"]
    return http_json(url_template.replace("{crumb}", urllib.parse.quote(crumb)), opener=op)


def fetch_earnings(symbols):
    out = {}
    for i in range(0, len(symbols), 10):
        chunk = symbols[i:i + 10]
        url = "https://query2.finance.yahoo.com/v7/finance/quote?symbols=%s&crumb={crumb}" % urllib.parse.quote(",".join(chunk))
        for r in crumb_json(url)["quoteResponse"]["result"]:
            ts = r.get("earningsTimestamp")
            out[r["symbol"]] = {"earn": dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d") if ts else None,
                                "div": r.get("dividendYield") or r.get("trailingAnnualDividendYield")}
    return out


def get_earnings(extra=()):
    base = read_json(DATA / "earnings.json", {"as_of": "", "earnings": {}})
    want = [s for s in dict.fromkeys(list(watch_set()) + list(extra)) if s]
    known = base["earnings"]

    def refresh():
        missing = [s for s in want if s not in known or (known[s] or {}).get("_at", 0) < time.time() - 6 * 3600]
        if not missing:
            return base
        try:
            got = fetch_earnings(missing[:60])
        except Exception:
            return base
        for s, v in got.items():
            v["_at"] = time.time()
            known[s] = v
        base["as_of"] = eastern_now().strftime("%Y-%m-%d")
        write_json(DATA / "earnings.json", base)
        return base
    cached_val = cached("earnings:" + ",".join(sorted(extra)), 300, refresh)
    return {"as_of": cached_val["as_of"], "earnings": {k: {kk: vv for kk, vv in v.items() if kk != "_at"} for k, v in cached_val["earnings"].items()}}


def fetch_chain(sym, date=None):
    """Every expiry (0 DTE out to long-dated) plus the puts for one of them. Default: the one nearest 7 days."""
    base = "https://query2.finance.yahoo.com/v7/finance/options/%s?crumb={crumb}" % urllib.parse.quote(sym)
    head = crumb_json(base)["optionChain"]["result"]
    if not head:
        raise RuntimeError("no options for " + sym)
    head = head[0]
    price = head["quote"].get("regularMarketPrice")
    today = eastern_now().date()
    allx = []
    for ts in head.get("expirationDates", []):
        d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
        if (d - today).days >= 0:
            allx.append({"date": d.isoformat(), "dte": (d - today).days, "ts": ts})
    if not allx:
        raise RuntimeError("no open expiries for " + sym)
    pick = next((x for x in allx if x["date"] == date), None) or min(allx, key=lambda x: abs(x["dte"] - 7))
    puts = crumb_json(base + "&date=%d" % pick["ts"])["optionChain"]["result"][0]["options"][0].get("puts", [])
    rows = []
    for p in puts:
        k = p.get("strike")
        if not price or k is None or k < price * 0.5 or k > price * 1.05:
            continue
        bid, ask = p.get("bid") or 0, p.get("ask") or 0
        mid = round((bid + ask) / 2, 3) if bid and ask else None
        spread = round((ask - bid) / mid * 100, 1) if mid else None
        rows.append({"k": k, "bid": bid, "ask": ask, "mid": mid, "spread": spread, "oi": p.get("openInterest") or 0,
                     "vol": p.get("volume") or 0, "iv": round((p.get("impliedVolatility") or 0) * 100, 1)})
    return {"symbol": sym, "price": price, "as_of": iso(time.time()), "live_quotes": any(r["bid"] and r["ask"] for r in rows),
            "all": [{"date": x["date"], "dte": x["dte"]} for x in allx],
            "sel": {"date": pick["date"], "dte": pick["dte"], "puts": sorted(rows, key=lambda r: -r["k"])}}


def get_chain(sym, date=None):
    return cached("chain:%s:%s" % (sym, date or ""), 60, lambda: fetch_chain(sym, date))


# ------------------------------------------------------------------ movers (pre-market, after-hours, intraday)

liquid_state = {"running": False}


def build_liquid():
    """Which of the ~5,900 listed stocks trade enough to matter ($5+, 1M+ average shares). Runs about once a day."""
    with _lock:
        if liquid_state["running"]:
            return
        liquid_state["running"] = True
    try:
        uni = DATA / "trader" / "universe.txt"
        if not uni.exists():
            subprocess.run([sys.executable, str(SKILLS / "trader-scanner" / "scan.py"), "universe"], cwd=str(DATA), check=True, capture_output=True, timeout=180)
        syms = [l.split("|")[0] for l in uni.read_text().splitlines() if l.strip()]
        chunks = [syms[i:i + 60] for i in range(0, len(syms), 60)]

        def one(chunk):
            try:
                return raw_batch(chunk)
            except Exception:
                return []
        keep, names = [], {}
        with ThreadPoolExecutor(max_workers=4) as ex:
            for rows in ex.map(one, chunks):
                for r in rows:
                    if (r.get("regularMarketPrice") or 0) >= 5 and (r.get("averageDailyVolume3Month") or 0) >= 1_000_000:
                        keep.append(r["symbol"])
                        names[r["symbol"]] = r.get("shortName") or ""
        if len(keep) > 200:
            write_json(DATA / "liquid.json", {"at": iso(time.time()), "symbols": keep, "names": names})
    except Exception as e:
        sys.stderr.write("liquid build failed: %s\n" % e)
    finally:
        liquid_state["running"] = False


def mover_row(r, names):
    reg_t = r.get("regularMarketTime") or 0
    cands = [(r.get(tk), r.get(pk), ses) for pk, tk, ses in (("preMarketPrice", "preMarketTime", "pre"), ("postMarketPrice", "postMarketTime", "post"))
             if r.get(pk) is not None and (r.get(tk) or 0) > reg_t]
    reg = r.get("regularMarketPrice")
    if not reg:
        return None
    day = r.get("regularMarketChangePercent")
    if cands:
        t, p, ses = max(cands)
        move = (p / reg - 1) * 100            # reaction since the regular-session close
    else:
        p, ses, t = reg, "reg", reg_t
        move = day or 0.0
    e_date, e_when = et_date_and_when(r.get("earningsTimestamp"))
    return {"s": r["symbol"], "n": names.get(r["symbol"]) or r.get("shortName") or "", "close": round(reg, 2), "p": round(p, 2), "ses": ses,
            "move": round(move, 2), "day": round(day, 2) if day is not None else None, "e": e_date, "ew": e_when,
            "vol": r.get("regularMarketVolume") or 0, "t": iso(t) if t else None}


def get_movers():
    liquid = read_json(DATA / "liquid.json")
    fresh = False
    if liquid:
        try:
            fresh = time.time() - (DATA / "liquid.json").stat().st_mtime < 20 * 3600
        except OSError:
            pass
    if not fresh and not liquid_state["running"]:
        threading.Thread(target=build_liquid, daemon=True).start()
    if not liquid:
        return {"building": True, "rows": [], "as_of": iso(time.time())}
    names = liquid.get("names", {})

    def build():
        syms = liquid["symbols"]
        chunks = [syms[i:i + 60] for i in range(0, len(syms), 60)]

        def one(chunk):
            try:
                return raw_batch(chunk)
            except Exception:
                return []
        rows = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            for part in ex.map(one, chunks):
                for r in part:
                    m = mover_row(r, names)
                    if m and abs(m["move"]) >= 2.0:
                        rows.append(m)
        rows.sort(key=lambda x: -abs(x["move"]))
        return {"building": False, "as_of": iso(time.time()), "checked": len(syms), "rows": rows[:100]}
    return cached("movers", 240, build)


# ------------------------------------------------------------------ look up any stock

_scan_mod = []


def scanner_module():
    if not _scan_mod:
        spec = importlib.util.spec_from_file_location("trader_scan", str(SKILLS / "trader-scanner" / "scan.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _scan_mod.append(m)
    return _scan_mod[0]


def explain_setups(closes, nums, tags):
    last = closes[-1]
    notes = []
    gap = (nums["high20"] / last - 1) * 100
    notes.append(("breakout_20d", "breakout_20d" in tags,
                  "Closed above its 20-day closing high (%.2f)." % nums["high20"] if "breakout_20d" in tags else
                  "Closed at %.2f, %.1f%% below its 20-day closing high of %.2f. A breakout needs a close above it." % (last, gap, nums["high20"])))
    notes.append(("reclaim_ma20", "reclaim_ma20" in tags,
                  "Moved back above its 20-day average (%.2f) after closing below it." % nums["ma20"] if "reclaim_ma20" in tags else
                  "%s its 20-day average (%.2f), with no cross from below on the last close." % ("Above" if last > nums["ma20"] else "Below", nums["ma20"])))
    notes.append(("bull_flag", "bull_flag" in tags,
                  "Ran %.0f%% in the last 10 days and has traded in a tight %.1f%% range for 5 days." % (nums["run_pct"], nums["range5_pct"]) if "bull_flag" in tags else
                  "Ran %.0f%% over the last 10 days with a %.1f%% five-day range. A flag needs more than 10%% and under 5%%." % (nums["run_pct"], nums["range5_pct"])))
    r = nums["rsi"]
    notes.append(("oversold", "oversold" in tags, "RSI is %.0f, under 30." % r if "oversold" in tags else "RSI is %.0f. Oversold means under 30." % r))
    notes.append(("oversold_bounce", "oversold_bounce" in tags,
                  "RSI was under 30 yesterday and the stock closed up." if "oversold_bounce" in tags else "No bounce: RSI was not under 30 on the prior day."))
    return [{"k": k, "match": m, "why": w} for k, m, w in notes]


def lookup(sym):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=6mo&interval=1d" % urllib.parse.quote(sym)
    res = http_json(url)["chart"]["result"][0]
    meta = res.get("meta", {})
    pairs = [(t, c) for t, c in zip(res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]) if c is not None]
    now = eastern_now()
    if pairs and eastern_now(dt.datetime.fromtimestamp(pairs[-1][0], dt.timezone.utc)).date() == now.date() and now.time() < dt.time(16, 0):
        pairs = pairs[:-1]                                   # today's bar is still forming
    closes = [float(c) for _, c in pairs]
    if len(closes) < 30:
        raise RuntimeError("not enough history")
    tags, nums = scanner_module().find_setups(closes)
    out = {"symbol": sym, "name": meta.get("longName") or meta.get("shortName") or "", "close": round(closes[-1], 2), "rsi": round(nums["rsi"], 1),
           "high20": round(nums["high20"], 2), "ma20": round(nums["ma20"], 2), "setups": tags, "checks": explain_setups(closes, nums, tags),
           "as_of": dt.datetime.fromtimestamp(pairs[-1][0], dt.timezone.utc).strftime("%Y-%m-%d")}
    try:
        out["earn"] = (fetch_earnings([sym]).get(sym) or {}).get("earn")
    except Exception:
        out["earn"] = None
    return out


def get_lookup(sym):
    return cached("lookup:" + sym, 120, lambda: lookup(sym))


# ------------------------------------------------------------------ files, scan, news

def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")))
    os.replace(tmp, path)


def ensure_data():
    (DATA / "trader").mkdir(parents=True, exist_ok=True)
    for name in ("scan.json", "news.json", "earnings.json", "market.json"):
        if not (DATA / name).exists() and (SEED / name).exists():
            shutil.copy(SEED / name, DATA / name)


def watch_set():
    scan = read_json(DATA / "scan.json", {"hits": []})
    hits = sorted(scan.get("hits", []), key=lambda r: -r[2] * r[4])
    top = [r[0] for r in hits[:14]]
    cheap = [r[0] for r in hits if r[2] <= 60][:14]
    extra = clean_symbols(os.environ.get("DESK_WATCH", ""))
    return list(dict.fromkeys(top + cheap + EXTRA_WATCH + extra))


def convert_watchlist(wl, names):
    hits = sorted(wl["hits"], key=lambda x: -x["price"] * x["volume"])
    return {"as_of": wl["as_of"], "created_at": wl["created_at"], "universe": wl["universe"], "scanned": wl["scanned"],
            "filters": wl["filters"],
            "hits": [[x["symbol"], names.get(x["symbol"], ""), x["price"], x["rsi"], x["volume"], x["setups"]] for x in hits]}


scan_state = {"running": False, "started": None, "finished": None, "error": None, "step": "", "failed_at": 0}


def run_scan():
    """Run universe + daily scan with the repo's scanner, then publish scan.json."""
    with _lock:
        if scan_state["running"]:
            return False
        scan_state.update(running=True, started=iso(time.time()), error=None, step="starting")
    try:
        script = str(SKILLS / "trader-scanner" / "scan.py")
        uni = DATA / "trader" / "universe.txt"
        if not uni.exists() or time.time() - uni.stat().st_mtime > 20 * 3600:
            scan_state["step"] = "downloading symbol lists"
            subprocess.run([sys.executable, script, "universe"], cwd=str(DATA), check=True, capture_output=True, timeout=180)
        scan_state["step"] = "scanning charts"
        subprocess.run([sys.executable, script, "daily", "--show", "0"], cwd=str(DATA), check=True, capture_output=True, timeout=1200)
        wl = read_json(DATA / "trader" / "watchlist.json")
        if not wl or not wl.get("hits"):
            raise RuntimeError("the scan found nothing")
        names = {}
        for line in uni.read_text().splitlines():
            s, _, n = line.partition("|")
            names[s] = n
        write_json(DATA / "scan.json", convert_watchlist(wl, names))
        with _lock:
            _cache.pop("news-bg", None)
        scan_state.update(finished=iso(time.time()), step="done")
        return True
    except Exception as e:
        detail = getattr(e, "stderr", b"") or b""
        scan_state.update(error=("%s %s" % (e, detail.decode("utf-8", "ignore")[-200:])).strip()[:300], failed_at=time.time(), step="failed")
        return False
    finally:
        scan_state["running"] = False


def compact_news(raw):
    items, seen, per = [], set(), {}
    for it in sorted(raw.get("items", []), key=lambda x: x["time"], reverse=True):
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        if per.get(it["ticker"], 0) >= 6:
            continue
        per[it["ticker"]] = per.get(it["ticker"], 0) + 1
        items.append({"t": it["time"], "s": it["ticker"], "h": it["title"], "u": it["link"], "k": it["kind"], "src": it["source"],
                      "tags": it.get("tags", []), "touch": it.get("touches", [])})
    return {"checked": raw.get("checked"), "items": items,
            "moves": {m["ticker"]: {"p": m["price"], "pc": m["prev_close"], "pct": m["pct"], "mv": m["moving"]} for m in raw.get("moves", [])}}


def refresh_news():
    tickers = watch_set()
    cmd = [sys.executable, str(SKILLS / "trader-news" / "news.py"), "--tickers"] + tickers + ["--hours", "96", "--all", "--dry-run", "--json"]
    env = dict(os.environ)
    proc = subprocess.run(cmd, cwd=str(DATA), capture_output=True, timeout=300, env=env)
    raw = json.loads(proc.stdout.decode("utf-8"))
    out = compact_news(raw)
    write_json(DATA / "news.json", out)
    return out


def get_news(force=False):
    """Return the saved news at once; refresh it in the background when it is older than 5 minutes (or when asked, at most once a minute)."""
    news = read_json(DATA / "news.json", {"checked": None, "items": [], "moves": {}})
    age = 1e9
    try:
        age = time.time() - (DATA / "news.json").stat().st_mtime
    except OSError:
        pass
    stale = age > 300 or (force and age > 60)
    with _lock:
        busy = _cache.get("news-bg")
        news["refreshing"] = bool(busy) or stale
        if stale and not busy:
            _cache["news-bg"] = (time.time(), True)

            def work():
                try:
                    refresh_news()
                except Exception:
                    pass
                finally:
                    with _lock:
                        _cache.pop("news-bg", None)
            threading.Thread(target=work, daemon=True).start()
    return news


def expected_scan_date(now_et):
    d = now_et.date()
    if now_et.time() < dt.time(16, 30) or d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def scheduler():
    time.sleep(60)
    while True:
        try:
            scan = read_json(DATA / "scan.json", {"as_of": ""})
            have = str(scan.get("as_of", ""))[:10]
            need = expected_scan_date(eastern_now())
            if have < need and not scan_state["running"] and time.time() - scan_state["failed_at"] > 1800:
                run_scan()
        except Exception as e:
            print("scheduler:", e, file=sys.stderr)
        time.sleep(300)


# ------------------------------------------------------------------ http

STATIC_FILES = {"/": (STATIC / "index.html", "text/html; charset=utf-8"), "/index.html": (STATIC / "index.html", "text/html; charset=utf-8"),
                "/lib.js": (ROOT / "dashboard" / "lib.js", "text/javascript; charset=utf-8")}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
_fails = {}


class Handler(BaseHTTPRequestHandler):
    server_version = "TraderDesk"
    protocol_version = "HTTP/1.1"
    timeout = 20   # drop connections that stall instead of holding a thread forever

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body=b"", ctype="application/json", extra=None, static=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, separators=(",", ":")).encode()
        elif isinstance(body, str):
            body = body.encode()
        extra = dict(extra or {})
        if static:   # revalidate with an ETag: unchanged files cost a 304, not 70 KB
            etag = '"%s"' % hashlib.sha1(body).hexdigest()[:20]
            extra["ETag"] = etag
            if self.headers.get("If-None-Match") == etag:
                code, body = 304, b""
        if code != 304 and len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, 6)
            extra["Content-Encoding"] = "gzip"
        extra["Vary"] = "Accept-Encoding"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-cache" if static else "no-store")
        if self.headers.get("X-Forwarded-Proto") == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _client(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def _authed(self):
        pw = os.environ.get("DESK_PASSWORD")
        if not pw:
            return True
        ip, now = self._client(), time.time()
        if len(_fails) > 500:
            for k in [k for k, v in _fails.items() if not v or now - v[-1] > 300]:
                _fails.pop(k, None)
        recent = [t for t in _fails.get(ip, []) if now - t < 300]
        _fails[ip] = recent
        if len(recent) >= 10:
            self._send(429, {"error": "too many attempts, wait a few minutes"}, extra={"Retry-After": "300"})
            return False
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Basic "):
            try:
                given = base64.b64decode(hdr[6:]).decode("utf-8", "ignore").partition(":")[2]
            except Exception:
                given = ""
            if hmac.compare_digest(given.encode(), pw.encode()):
                return True
            recent.append(now)
            time.sleep(0.5)
        self._send(401, {"error": "sign in"}, extra={"WWW-Authenticate": 'Basic realm="Trader Desk", charset="UTF-8"'})
        return False

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path, qs = url.path, urllib.parse.parse_qs(url.query)
        if path == "/healthz":
            return self._send(200, {"ok": True})
        if not self._authed():
            return
        if path in STATIC_FILES:
            f, ctype = STATIC_FILES[path]
            try:
                return self._send(200, f.read_bytes(), ctype, static=True)
            except OSError:
                return self._send(404, {"error": "missing file"})
        try:
            if path == "/api/quotes":
                syms = clean_symbols((qs.get("symbols") or [""])[0])
                if not syms:
                    return self._send(400, {"error": "symbols required"})
                return self._send(200, get_quotes(syms))
            if path == "/api/market":
                return self._send(200, get_market())
            if path == "/api/scan":
                return self._send(200, read_json(DATA / "scan.json", {"hits": [], "as_of": ""}))
            if path == "/api/news":
                return self._send(200, get_news(force=(qs.get("refresh") or [""])[0] == "1"))
            if path == "/api/movers":
                return self._send(200, get_movers())
            if path == "/api/lookup":
                syms = clean_symbols((qs.get("symbol") or [""])[0], 1)
                if not syms:
                    return self._send(400, {"error": "symbol required"})
                try:
                    return self._send(200, get_lookup(syms[0]))
                except Exception:
                    return self._send(404, {"error": "no chart data for " + syms[0]})
            if path == "/api/earnings":
                return self._send(200, get_earnings(clean_symbols((qs.get("symbols") or [""])[0], 20)))
            if path == "/api/chain":
                syms = clean_symbols((qs.get("symbol") or [""])[0], 1)
                if not syms:
                    return self._send(400, {"error": "symbol required"})
                dq = (qs.get("date") or [""])[0]
                return self._send(200, get_chain(syms[0], dq if re.match(r"^\d{4}-\d{2}-\d{2}$", dq) else None))
            if path == "/api/status":
                return self._send(200, {"scan": {k: v for k, v in scan_state.items() if k != "failed_at"}, "now": iso(time.time()),
                                        "sec_user_agent": bool(os.environ.get("SEC_USER_AGENT"))})
        except Exception as e:
            sys.stderr.write("api error %s: %s\n" % (path, e))
            return self._send(502, {"error": "data source unavailable, try again shortly"})
        self._send(404, {"error": "not found"})

    do_HEAD = do_GET

    def do_POST(self):
        if not self._authed():
            return
        if urllib.parse.urlparse(self.path).path == "/api/scan/run":
            if scan_state["running"]:
                return self._send(409, {"error": "a scan is already running"})
            threading.Thread(target=run_scan, daemon=True).start()
            return self._send(202, {"started": True})
        self._send(404, {"error": "not found"})


def make_server(host, port):
    ensure_data()
    return ThreadingHTTPServer((host, port), Handler)


def main():
    cloud = bool(os.environ.get("PORT"))
    if cloud and not os.environ.get("DESK_PASSWORD") and not os.environ.get("DESK_ALLOW_OPEN"):
        sys.exit("Refusing to start on a public port without DESK_PASSWORD. Set one.")
    host = os.environ.get("HOST") or ("0.0.0.0" if cloud else "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    srv = make_server(host, port)
    if not os.environ.get("DESK_NO_SCHEDULER"):
        threading.Thread(target=scheduler, daemon=True).start()
    print("Trader Desk on http://%s:%d  (password %s)" % (host, port, "on" if os.environ.get("DESK_PASSWORD") else "OFF"), file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
