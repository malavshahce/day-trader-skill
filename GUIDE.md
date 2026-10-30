# How Trader Desk works

Trader Desk finds stocks worth a look, helps you plan a trade, and checks the plan against your own rules.
**It never places an order.** You make every decision and place every order yourself, in a paper (practice)
account first. It is not financial advice. The same guide is inside the app, in the **Guide** tab.

## A daily routine

1. **Before the open (before 9:30 ET).**
   - **Today**: read the market read, the shortlist and the earnings flags.
   - **Movers** (web app): see who jumped or dropped overnight, especially after earnings.
   - **News**: read the headlines for those names.
2. **After 9:45 ET.** Pick one stock. On your broker's chart note the highest and lowest price of the first
   15 minutes (the opening range). In **Planner**, enter the symbol, choose a stop and a target.
3. **Read the result.** PASS means every one of your rules is met. BLOCK lists exactly what to change.
   If you still like it, place the order yourself with the stop and target attached, and log it in **Journal**.
4. **Before 3:55 PM ET.** Close anything still open. This is day trading: flat by the close.
5. **After the close.** In **Journal**, close each trade with its exit price to see profit or loss and how many R it made.

## Tab by tab

| Tab | What it does |
|---|---|
| Today | The market in one look, a shortlist of breakouts and flags that fit your account, earnings coming up, earnings reactions and big moves. |
| Scanner | Every chart from the last scan that matches a setup. Search, filter, sort, tap a row. **Check any stock** explains why a stock does or does not match. |
| Movers | The biggest moves right now among about 1,500 liquid stocks. Before the open and after the close the move is measured from the 4pm close, so earnings reactions show up here. |
| Planner | Turns a stock, a stop and a target into a share count, a loss and a gain, then checks your rules. |
| Options | Cash-secured put calculator. The web app loads the live put chain for every expiry from 0 DTE to long-dated. |
| News | Latest headlines and SEC filings for the watched stocks and the market (SPY, QQQ), newest first, with a Refresh button. |
| Journal | Your trades, profit and loss, win rate, and today's trade count and risk (the Planner uses these). |
| Guide | This guide. |
| Settings | Your account size and limits. Every check uses them. |

## Why a stock can be missing from the Scanner

The scanner reads **daily closes** from the regular session (9:30 to 4:00 ET) and tests five fixed rules:
20-day closing-high breakout, bull flag, reclaimed the 20-day average, oversold (RSI under 30) and oversold bounce.

- A stock that matches none of the rules is not listed. Type it into **Check any stock** to see which rule it missed and by how much.
- A company that **reported after the 4pm close** (Amazon and Intel on Oct 29, for example) has its reaction in
  after-hours trading. The daily scan cannot see that yet. Look in **Movers**, which measures the move since the close.
- Companies that reported **before the open** are in the scan, because their reaction is part of the regular session.

## Worked example: the Planner

Tesla, Oct 19 2026. The first 15 minutes traded between 354.47 and 362.18. At 10:15 the price closed above the
range at 364.18, so you plan to buy at 364.18.

- **Stop** = middle of the opening range = (362.18 + 354.47) / 2 = 358.325, rounded down to **358.32**.
- **Risk per share** = 364.18 − 358.32 = **5.86**. This is 1 R.
- **Target at 1 R** = 364.18 + 5.86 = **370.04**. At 2 R it would be 375.90.
- **Shares.** Your max loss per trade is $50, so 50 / 5.86 = 8.5, rounded down to **8 shares**. They cost $2,913.44.
  If stopped you lose 8 × 5.86 = **$46.88**.
- Four limits are checked: max loss, position cap, max order, cash. The smallest share count wins.
- The risk check then asks: is a stop set, is the loss within your limit, is the reward at least your minimum,
  are you under your daily loss and trade limits, and is it inside your entry window?

The result says it in plain words ("Buy 8 shares of TSLA at about $364.18 ... if it falls to $358.32, sell: you lose about $46.88")
and, when something fails, lists what to change.

## Options: expiry in plain words

A **cash-secured put** pays you a premium now. In return you agree to buy 100 shares at the strike if the stock closes
below it at expiry, so you keep strike × 100 in cash. Breakeven = strike − premium.

| Expiry | Meaning |
|---|---|
| 0 DTE | Expires today. Very fast, big gap risk. Only for the most liquid names (SPY, QQQ, mega-caps), small size. |
| 4 or 5 DTE | About a week out. |
| 7 DTE | The next weekly. |
| 14 DTE | Two weeks. |
| 21 to 45 DTE | The usual range for selling puts for income. Time decay works for you and you have time to react. |
| 60 to 180 DTE | Slower, less premium per day. |
| Long-dated (LEAPS) | A year or more. Your cash is tied up for a long time, so judge it by the annualized return. |

Skip any put whose expiry comes after earnings. Prefer strikes with open interest of 500 or more and a bid-ask gap under 10% of the mid.

## Words you will see

- **Stop**: the price where you sell to limit a loss. **Target**: the price where you sell to take a profit.
- **R**: your risk on one share (entry − stop). A 2 R target pays twice what you risk.
- **PASS / BLOCK**: PASS means every rule is met. BLOCK means at least one failed.
- **Opening range**: the high and low of the first 15 minutes after the 9:30 ET open.
- **RSI**: a 0 to 100 gauge of recent strength. Under 30 is called oversold, over 70 overbought.
- **ATR**: the typical size of a daily move. **DTE**: days to expiry. **IV**: how big a move the options market expects.
- **Open interest**: how many contracts exist. Low numbers are hard to trade. **Spread**: the gap between bid and ask.

## What it cannot do

- It cannot place orders and does not know your broker account.
- Prices come from Yahoo for free and can be up to 15 minutes late. Check your broker before acting.
- The scan reads daily closes with fixed rules. A match is a chart to look at, not a stock to buy.
- Most people who day trade lose money. Practice on paper first. Not financial advice.
