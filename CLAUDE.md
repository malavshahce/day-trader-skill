# Day Trader workspace

Intraday trading co-pilot built on the `trader-*` skills (source: github.com/Jakeschincariol/day-trader-skill, installed in `.claude/skills/`). All output lands in `trader/` (git-ignored).

## Flow (one trade)
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker; alerts run while a trade is open; analyst/pelosi on demand.
Never skip `/trader-risk` before `/trader-broker`.

## Hard rules
- Paper trading only (`"paper": true` in `trader/config.json`). Do not flip it without the user saying so explicitly in that message.
- Never place, modify or cancel an order without the user typing an explicit yes for that exact ticket. Broker tools must stay on "Needs approval".
- Long side only, no options/margin/shorting unless the config enables them.
- Never put API keys in chat, files or git; use environment variables (ALPACA_API_KEY, ALPACA_SECRET_KEY).
- Times are New York time. Flat by 15:55 ET.
- Simulation output (Time Machine) is a reality check, not a prediction. Not financial advice.

## Setup status
- `trader/config.json`: starter limits ($5,000 budget, $50 max loss/trade, $150 daily, 3 trades/day). Edit to match the real account.
- `sec_user_agent` in config (or `SEC_USER_AGENT` env) must be "Name email" for news filings and the analyst.
- Alpaca paper MCP server: not connected yet (see `.claude/skills/trader-broker/SKILL.md`).

## Web app and dashboard
- `webapp/` is a read-only website with live prices (server fetches Yahoo). Run: `DESK_PASSWORD=... python3 webapp/server.py`. Deploy notes in `webapp/README.md`, blueprint in `render.yaml`.
- `dashboard/` is the page published on claude.ai (private artifact). Its source is `dashboard/src/index.src.html`; `webapp/build_ui.py` derives the web app page from it.
- Tests: `node dashboard/tests/test_lib.js`, `python3 -m unittest discover -s webapp/tests`, `node webapp/tests/e2e_web.js` (needs puppeteer-core and Chrome).
- The web app must never gain order endpoints or read broker keys.
