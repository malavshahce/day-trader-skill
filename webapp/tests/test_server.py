import base64
import gzip
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


def chart(closes, stamps=None, prev=100.0, regular=None):
    stamps = stamps or list(range(1_700_000_000, 1_700_000_000 + 60 * len(closes), 60))
    return {"chart": {"result": [{"meta": {"chartPreviousClose": prev, "regularMarketPrice": regular},
                                  "timestamp": stamps, "indicators": {"quote": [{"close": closes}]}}]}}


class Helpers(unittest.TestCase):
    def test_clean_symbols(self):
        self.assertEqual(server.clean_symbols("aapl, MSFT,aapl,^VIX,BRK.B"), ["AAPL", "MSFT", "^VIX", "BRK.B"])
        self.assertEqual(server.clean_symbols("A;B,../etc,<script>,OK"), ["OK"])
        self.assertEqual(server.clean_symbols(""), [])
        self.assertEqual(len(server.clean_symbols(",".join("S%d" % i for i in range(200)), limit=60)), 60)
        self.assertEqual(server.clean_symbols("TOOLONGSYMBOLX"), [])

    def test_eastern_time_dst(self):
        utc = dt.timezone.utc
        self.assertEqual(server.eastern_now(dt.datetime(2026, 10, 30, 3, 0, tzinfo=utc)).hour, 23)   # EDT -4
        self.assertEqual(server.eastern_now(dt.datetime(2026, 11, 2, 14, 30, tzinfo=utc)).strftime("%H:%M"), "09:30")  # EST -5
        self.assertEqual(server.eastern_now(dt.datetime(2026, 3, 8, 6, 59, tzinfo=utc)).hour, 1)    # still EST
        self.assertEqual(server.eastern_now(dt.datetime(2026, 3, 8, 7, 0, tzinfo=utc)).hour, 3)     # EDT starts

    def test_expected_scan_date(self):
        f = server.expected_scan_date
        self.assertEqual(f(dt.datetime(2026, 10, 29, 16, 31)), "2026-10-29")   # Thu after the scan time
        self.assertEqual(f(dt.datetime(2026, 10, 29, 10, 0)), "2026-10-28")    # Thu morning -> Wed close
        self.assertEqual(f(dt.datetime(2026, 10, 31, 12, 0)), "2026-10-30")    # Saturday -> Friday
        self.assertEqual(f(dt.datetime(2026, 11, 2, 9, 0)), "2026-10-30")      # Monday morning -> Friday
        self.assertEqual(f(dt.datetime(2026, 11, 1, 18, 0)), "2026-10-30")     # Sunday

    def test_convert_watchlist_and_news(self):
        wl = {"as_of": "2026-10-29 close", "created_at": "x", "universe": 10, "scanned": 5, "filters": {},
              "hits": [{"symbol": "AAA", "price": 10, "volume": 100, "rsi": 20, "setups": ["oversold"]},
                       {"symbol": "BBB", "price": 50, "volume": 1000, "rsi": 60, "setups": ["bull_flag"]}]}
        out = server.convert_watchlist(wl, {"AAA": "Alpha", "BBB": "Beta"})
        self.assertEqual([h[0] for h in out["hits"]], ["BBB", "AAA"])   # dollar volume desc
        self.assertEqual(out["hits"][1][1], "Alpha")
        raw = {"checked": "c", "moves": [{"ticker": "AAA", "price": 1, "prev_close": 2, "pct": -50, "moving": True}],
               "items": [{"id": str(i), "time": "2026-10-29T0%d:00:00+00:00" % (i % 9), "ticker": "AAA", "title": "t%d" % i, "link": "u",
                          "kind": "headline", "source": "Y"} for i in range(20)] +
                        [{"id": "0", "time": "2026-10-29T05:00:00+00:00", "ticker": "AAA", "title": "dup", "link": "u", "kind": "headline", "source": "Y"}]}
        n = server.compact_news(raw)
        self.assertEqual(len(n["items"]), 6)             # capped per ticker
        self.assertEqual(n["moves"]["AAA"]["pct"], -50)
        self.assertEqual(len({i["h"] for i in n["items"]}), 6)


class Quotes(unittest.TestCase):
    def setUp(self):
        self._orig, self._crumb = server.http_json, server.crumb_json
        server._cache.clear()

    def tearDown(self):
        server.http_json, server.crumb_json = self._orig, self._crumb

    def test_latest_bar_and_percent(self):
        server.http_json = lambda url, **k: chart([100.0, None, 101.5, None], prev=100.0)
        q = server.fetch_quote("AAPL")
        self.assertEqual(q["p"], 101.5); self.assertEqual(q["pc"], 100.0); self.assertEqual(q["pct"], 1.5)
        self.assertTrue(q["t"].endswith("Z"))

    def test_falls_back_to_regular_price_without_bars(self):
        server.http_json = lambda url, **k: chart([None, None], prev=10, regular=10.5)
        self.assertEqual(server.fetch_quote("X")["p"], 10.5)

    def test_no_price_raises_and_batch_survives(self):
        server.crumb_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("batch down"))   # force the per-symbol fallback
        def fake(url, **k):
            if "BAD" in url:
                raise RuntimeError("fetch failed: HTTP Error 404")
            return chart([50.0], prev=49.0)
        server.http_json = fake
        res = server.get_quotes("GOOD,BAD,ALSO")
        self.assertEqual(res["quotes"]["GOOD"]["p"], 50.0)
        self.assertIn("err", res["quotes"]["BAD"])
        self.assertEqual(res["quotes"]["ALSO"]["p"], 50.0)

    def test_quote_cache_avoids_refetch(self):
        calls = []
        server.http_json = lambda url, **k: (calls.append(url), chart([5.0], prev=5.0))[1]
        server.get_quote("C"); server.get_quote("C")
        self.assertEqual(len(calls), 1)

    def test_market_indexes(self):
        stamps = [1_700_000_000 + 86400 * i for i in range(60)]
        closes = [100.0 + i for i in range(60)]
        server.http_json = lambda url, **k: chart(closes, stamps=stamps)
        m = server.fetch_index("^GSPC", "S&P 500")
        self.assertEqual(m["last"], 159.0); self.assertEqual(m["prev"], 158.0)
        self.assertEqual(m["sma20"], round(sum(closes[-20:]) / 20, 2)); self.assertEqual(m["sma50"], round(sum(closes[-50:]) / 50, 2))

    def test_market_falls_back_to_saved_file_on_failure(self):
        d = tempfile.mkdtemp(); server.DATA = Path(d)
        (Path(d) / "market.json").write_text(json.dumps({"as_of": "2026-10-29", "idx": {"^VIX": {}}}))
        server.http_json = lambda url, **k: (_ for _ in ()).throw(RuntimeError("down"))
        self.assertEqual(server.get_market()["as_of"], "2026-10-29")


class BatchQuotes(unittest.TestCase):
    def setUp(self):
        self._orig, self._crumb = server.http_json, server.crumb_json
        server._cache.clear()

    def tearDown(self):
        server.http_json, server.crumb_json = self._orig, self._crumb

    @staticmethod
    def row(sym, reg=100.0, rt=1000, pre=None, pt=None, post=None, pot=None, prev=98.0):
        return {"symbol": sym, "regularMarketPrice": reg, "regularMarketTime": rt, "preMarketPrice": pre, "preMarketTime": pt,
                "postMarketPrice": post, "postMarketTime": pot, "regularMarketPreviousClose": prev}

    def test_latest_session_wins(self):
        self.assertEqual(server.parse_batch_quote(self.row("A"))["ses"], "reg")
        q = server.parse_batch_quote(self.row("A", post=101.0, pot=2000))
        self.assertEqual((q["p"], q["ses"]), (101.0, "post"))
        q = server.parse_batch_quote(self.row("A", pre=99.0, pt=900))      # pre-market older than the regular price: ignored
        self.assertEqual(q["ses"], "reg")
        q = server.parse_batch_quote(self.row("A", rt=500, pre=99.5, pt=900))
        self.assertEqual((q["p"], q["ses"]), (99.5, "pre"))
        self.assertEqual(server.parse_batch_quote(self.row("A", post=101.0, pot=2000))["pct"], round((101.0 / 98.0 - 1) * 100, 2))
        with self.assertRaises(ValueError):
            server.parse_batch_quote({"symbol": "X"})

    def test_sixty_symbols_use_one_call(self):
        calls = []
        syms = ["S%d" % i for i in range(60)]
        def fake(url):
            calls.append(url)
            return {"quoteResponse": {"result": [self.row(s) for s in syms if s != "S7"]}}
        server.crumb_json = fake
        server.http_json = lambda *a, **k: (_ for _ in ()).throw(AssertionError("chart route must not be used"))
        res = server.get_quotes(",".join(syms))
        self.assertEqual(len(calls), 1)
        self.assertEqual(res["quotes"]["S0"]["p"], 100.0)
        self.assertIn("err", res["quotes"]["S7"])
        self.assertEqual(len(res["quotes"]), 60)

    def test_cached_symbols_skip_the_network(self):
        calls = []
        server.crumb_json = lambda url: (calls.append(url), {"quoteResponse": {"result": [self.row("AAA"), self.row("BBB")]}})[1]
        server.get_quotes("AAA,BBB"); server.get_quotes("AAA,BBB")
        self.assertEqual(len(calls), 1)
        server.get_quotes("AAA,CCC")                       # only CCC is new, but one call is still enough
        self.assertEqual(len(calls), 2); self.assertIn("CCC", calls[1]); self.assertNotIn("AAA", calls[1].split("symbols=")[1].split("&")[0])

    def test_falls_back_to_chart_when_batch_route_fails(self):
        server.crumb_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429"))
        server.http_json = lambda url, **k: chart([10.0, 11.0], prev=10.0)
        res = server.get_quotes("AAA,BBB")
        self.assertEqual(res["quotes"]["AAA"]["p"], 11.0); self.assertEqual(res["quotes"]["BBB"]["pct"], 10.0)

    def test_cached_dedupes_simultaneous_requests(self):
        server._cache.clear(); calls = []
        def slow():
            calls.append(1); time.sleep(0.3); return "v"
        out = []
        ts = [threading.Thread(target=lambda: out.append(server.cached("dedupe-key", 30, slow))) for _ in range(10)]
        [x.start() for x in ts]; [x.join() for x in ts]
        self.assertEqual(len(calls), 1); self.assertEqual(out, ["v"] * 10)

    def test_cache_is_bounded(self):
        server._cache.clear()
        for i in range(3100):
            server.cached("k%d" % i, 60, lambda: 1)
        self.assertLess(len(server._cache), 3100)


class Options(unittest.TestCase):
    def test_chain_parsing_and_filters(self):
        today = server.eastern_now().date()
        e1 = int(dt.datetime.combine(today + dt.timedelta(days=30), dt.time(12), tzinfo=dt.timezone.utc).timestamp())
        e2 = int(dt.datetime.combine(today + dt.timedelta(days=200), dt.time(12), tzinfo=dt.timezone.utc).timestamp())

        def fake(url):
            if "date=" in url:
                return {"optionChain": {"result": [{"options": [{"puts": [
                    {"strike": 19.5, "bid": 0.3, "ask": 0.4, "openInterest": 800, "volume": 5, "impliedVolatility": 0.35},
                    {"strike": 5.0, "bid": 0, "ask": 0, "openInterest": 1},       # too far out of the money: dropped
                    {"strike": 21.0, "bid": 0, "ask": 0, "openInterest": 10}]}]}]}}
            return {"optionChain": {"result": [{"quote": {"regularMarketPrice": 21.21}, "expirationDates": [e1, e2]}]}}
        orig = server.crumb_json; server.crumb_json = fake
        try:
            c = server.fetch_chain("KEY", 14, 60)
        finally:
            server.crumb_json = orig
        self.assertEqual(len(c["expiries"]), 1)                    # 200 days out is excluded
        rows = c["expiries"][0]["puts"]
        self.assertEqual([r["k"] for r in rows], [21.0, 19.5])     # sorted high to low, 5.0 dropped
        r = rows[1]
        self.assertEqual(r["mid"], 0.35); self.assertEqual(r["spread"], round(0.1 / 0.35 * 100, 1)); self.assertEqual(r["iv"], 35.0)
        self.assertIsNone(rows[0]["mid"])
        self.assertTrue(c["live_quotes"])

    def test_no_live_quotes_flag(self):
        today = server.eastern_now().date()
        e1 = int(dt.datetime.combine(today + dt.timedelta(days=30), dt.time(12), tzinfo=dt.timezone.utc).timestamp())

        def fake(url):
            if "date=" in url:
                return {"optionChain": {"result": [{"options": [{"puts": [{"strike": 20.0, "bid": 0, "ask": 0}]}]}]}}
            return {"optionChain": {"result": [{"quote": {"regularMarketPrice": 21.0}, "expirationDates": [e1]}]}}
        orig = server.crumb_json; server.crumb_json = fake
        try:
            self.assertFalse(server.fetch_chain("KEY", 14, 60)["live_quotes"])
        finally:
            server.crumb_json = orig


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        server.DATA = Path(cls.tmp)
        server.ensure_data()
        os.environ["DESK_PASSWORD"] = "s3cret-pw"
        cls.srv = server.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        server.http_json = lambda url, **k: chart([20.0, 21.0], prev=20.0)
        cls._crumb = server.crumb_json
        server.crumb_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no batch in tests"))

    @classmethod
    def tearDownClass(cls):
        server.crumb_json = cls._crumb
        cls.srv.shutdown()
        os.environ.pop("DESK_PASSWORD", None)

    def req(self, path, pw="s3cret-pw", method="GET", user="me"):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method)
        if pw is not None:
            r.add_header("Authorization", "Basic " + base64.b64encode(("%s:%s" % (user, pw)).encode()).decode())
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_requires_password(self):
        self.assertEqual(self.req("/api/scan", pw=None)[0], 401)
        self.assertEqual(self.req("/api/scan", pw="wrong")[0], 401)
        self.assertEqual(self.req("/", pw="wrong")[0], 401)
        self.assertEqual(self.req("/api/scan")[0], 200)
        self.assertEqual(self.req("/api/scan", user="anyone")[0], 200)

    def test_healthz_is_open_and_not_leaky(self):
        s, body, _ = self.req("/healthz", pw=None)
        self.assertEqual(s, 200); self.assertEqual(json.loads(body), {"ok": True})

    def test_static_whitelist_and_traversal(self):
        for bad in ("/server.py", "/../server.py", "/%2e%2e/server.py", "/static/../server.py", "/data/scan.json", "/.env"):
            self.assertEqual(self.req(bad)[0], 404, bad)
        s, body, h = self.req("/lib.js")
        self.assertEqual(s, 200); self.assertIn(b"TraderLib", body); self.assertIn("javascript", h["Content-Type"])

    def test_gzip_and_etag(self):
        def get(path, headers):
            r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path))
            r.add_header("Authorization", "Basic " + base64.b64encode(b"me:s3cret-pw").decode())
            for k, v in headers.items():
                r.add_header(k, v)
            try:
                with urllib.request.urlopen(r, timeout=10) as resp:
                    return resp.status, resp.read(), resp.headers
            except urllib.error.HTTPError as e:
                return e.code, e.read(), e.headers
        plain = get("/api/scan", {})[1]
        s, zipped, h = get("/api/scan", {"Accept-Encoding": "gzip"})
        self.assertEqual(h["Content-Encoding"], "gzip"); self.assertLess(len(zipped), len(plain) / 2)
        self.assertEqual(gzip.decompress(zipped), plain)
        self.assertNotIn("Content-Encoding", get("/api/scan", {})[2])
        s, body, h = get("/lib.js", {"Accept-Encoding": "gzip"})
        etag = h["ETag"]; self.assertTrue(etag); self.assertEqual(h["Cache-Control"], "no-cache")
        s2, body2, h2 = get("/lib.js", {"If-None-Match": etag, "Accept-Encoding": "gzip"})
        self.assertEqual(s2, 304); self.assertEqual(body2, b"")
        self.assertNotEqual(get("/lib.js", {"If-None-Match": '"stale"'})[0], 304)
        self.assertEqual(get("/api/scan", {})[2]["Cache-Control"], "no-store")

    def test_security_headers(self):
        _, _, h = self.req("/api/scan")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertIn("connect-src 'self'", h["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertEqual(h["Cache-Control"], "no-store")

    def test_quotes_endpoint(self):
        server._cache.clear()
        s, body, _ = self.req("/api/quotes?symbols=AAPL,msft")
        d = json.loads(body)
        self.assertEqual(s, 200); self.assertEqual(sorted(d["quotes"]), ["AAPL", "MSFT"]); self.assertEqual(d["quotes"]["AAPL"]["p"], 21.0)
        self.assertEqual(self.req("/api/quotes")[0], 400)
        self.assertEqual(self.req("/api/quotes?symbols=%3Cscript%3E")[0], 400)

    def test_scan_news_earnings_market_seed_data(self):
        d = json.loads(self.req("/api/scan")[1]); self.assertEqual(len(d["hits"]), 707)
        n = json.loads(self.req("/api/news")[1]); self.assertIn("items", n)
        self.assertIn("earnings", json.loads(self.req("/api/earnings")[1]))
        self.assertIn("idx", json.loads(self.req("/api/market")[1]))

    def test_upstream_failure_is_a_clean_502(self):
        orig = server.crumb_json
        server.crumb_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        server._cache.clear()
        try:
            s, body, _ = self.req("/api/chain?symbol=KEY")
            self.assertEqual(s, 502); self.assertNotIn(b"boom", body)
        finally:
            server.crumb_json = orig

    def test_read_only_no_order_endpoints(self):
        for m in ("PUT", "DELETE", "PATCH"):
            s = self.req("/api/orders", method=m)[0]
            self.assertIn(s, (404, 501))
        self.assertEqual(self.req("/api/orders", method="POST")[0], 404)
        self.assertEqual(self.req("/api/place_order")[0], 404)

    def test_scan_run_conflict(self):
        server.scan_state["running"] = True
        try:
            self.assertEqual(self.req("/api/scan/run", method="POST")[0], 409)
        finally:
            server.scan_state["running"] = False

    def test_lockout_after_repeated_failures(self):
        server._fails.clear()
        codes = [self.req("/api/scan", pw="nope")[0] for _ in range(12)]
        self.assertIn(429, codes)
        server._fails.clear()


class Startup(unittest.TestCase):
    def test_refuses_public_port_without_password(self):
        import subprocess
        env = {k: v for k, v in os.environ.items() if k not in ("DESK_PASSWORD", "DESK_ALLOW_OPEN")}
        env["PORT"] = "0"
        p = subprocess.run([sys.executable, str(Path(server.__file__))], env=env, capture_output=True, timeout=20)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn(b"DESK_PASSWORD", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
