# Trader Desk web app

The dashboard as a real website. A small Python server (standard library only) fetches free public data
from Yahoo and SEC on the server, so prices refresh by themselves on your phone or laptop.

- **Live prices** for every stock on screen, refreshed every 15 to 60 seconds (Yahoo, delayed up to 15 minutes).
- **Live put chain** (bid, ask, open interest, IV) in the Options tab. Tap a strike to fill the calculator.
- **Automatic scan** after each close, plus a "Run scan now" button. News and earnings refresh by themselves.
- **Read-only.** It cannot place orders and never reads broker keys. Planner and journal are your own notes.
- Your journal and settings live in the browser you use (each person who logs in has their own).

## Run it on your computer

```bash
DESK_PASSWORD=pick-a-password python3 webapp/server.py
# open http://127.0.0.1:8000  (user name: anything, password: what you set)
```

## Put it online (Render, free tier)

1. Push this repo to GitHub (keep it private).
2. On render.com: New > Blueprint > pick the repo. `render.yaml` sets everything up.
3. When asked, enter `DESK_PASSWORD` (long, unique) and `SEC_USER_AGENT` ("Your Name you@example.com").
4. Open the URL Render gives you on your phone and sign in. Share the URL and password with whoever you trust.

The server refuses to start on a public port without `DESK_PASSWORD`.

## Things to know

- The free tier sleeps after about 15 minutes idle (first load then takes up to a minute) and forgets files on restart.
  The server rescans on wake when the saved scan is out of date. A scan takes a few minutes.
- Yahoo sometimes slows or blocks traffic from cloud hosts. If the price pill says "Prices unavailable" for long,
  that is the likely cause; the rest of the page keeps working with the last scan.
- Option quotes are empty when the market is closed. The page says so instead of showing fake premiums.
- Data is delayed and unofficial. Confirm every price in your broker before acting. Not financial advice.

## Files

```
webapp/server.py        the server and JSON API (/api/quotes, /api/market, /api/scan, /api/news, /api/earnings, /api/chain)
webapp/static/index.html  the page, built by build_ui.py from dashboard/src/index.src.html
webapp/build_ui.py      re-run after changing the dashboard source
webapp/tests/           python3 -m unittest discover -s webapp/tests ; node webapp/tests/e2e_web.js
render.yaml             Render blueprint
```
