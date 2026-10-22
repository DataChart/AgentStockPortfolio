# Analyst guidance

*Updated 2026-10-22 by the analyst, after day 6 of trading (the opening allocation was made on 2026-10-12). Runs for Oct 19 and Oct 20 did not execute; those days have valuation snapshots only.*

**Mandate:** maximize ROI % on a $10,000 paper portfolio. Aggressive is fine; reckless is not.

## Current playbook
- Concentrate: hold 3 to 6 high-conviction names. Size new buys at 15 to 35% of portfolio value; **no single name above 35%** at the time of a buy. Keep cash under 10% once fully invested. With about $6 in cash, every buy has to be funded by a same-day sell.
- Favor catalysts within weeks, such as earnings beats with raised guidance, regulatory approvals, product launches and sector momentum. Prefer names showing **relative strength on down days**: on Oct 22 that was LLY (+2.8%) and CRM (+3.5%) while the Nasdaq fell 2.6%.
- Rotate only for a clearly better setup. A swap costs about $2 plus 0.2% of the amount. When the regime turns against a theme, trim the most exposed name instead of waiting for the 12% stop.
- Exits:
  - Cut any holding that closes 12% below cost or whose thesis breaks.
  - Let winners run while momentum holds. Once a holding is up 15% or more, raise its mental stop to breakeven.
- Event risk:
  - Don't open new positions on the day before a binary report (earnings, CPI, FOMC) unless the setup is exceptional. FOMC decides Oct 28: no new opens on Oct 27.
  - Holding existing winners through their own earnings is fine. **A losing position that is a large weight is cut to half size or less before a binary report whose main risk is the market's top worry.** This now applies to MSFT (see instructions).
- **Act on confirmed closes after a report, never on after-hours prints.** Confirmed on Oct 22: META traded +5.9% after hours on Oct 21 and closed -7.0% the next day.
- **AI-capex regime: risk-off again.** META's report (record revenue, but its first cash outflow in over a decade, plus a non-voting share issue to fund AI spending) revived the debt- and equity-funded capex scare. Nasdaq -2.6%, Philadelphia semis about -6%, S&P 500 -1.2%, Dow flat. Oct 21's up day was not confirmed. Avoid AI-infrastructure and hyperscaler names until the Nasdaq makes two consecutive higher closes on news.
- **Semis remain off limits** until a leader clears its trigger: NVDA above 228.52, TSM above 445. Both fell sharply today and are further away.
- **Healthcare is the destination.** LLY made a new closing high (1,306.69) on Oct 22, rising on a risk-off day. It reports Oct 29.
- **Energy:** VLO and XLE together cap at about 40% of the portfolio (about 36% now). Brent about $113 and WTI about $100 (highest since May) on Middle East escalation; the 10-year slipped to about 4.95-5.0%. VLO posted a record quarter but sold off as the news was priced in. Hold, don't add.

## Watchlist
| Ticker | Why it's here | Trigger to act |
|---|---|---|
| LLY (held) | New closing high 1,306.69; relative strength on a risk-off day. Reports Oct 29. | Hold into the report. No further adds once it is about 30% of the book. |
| CRM (held) | +3.5% on Oct 22 (Agentforce, Braze deal); up about 6.8% vs cost. | Hold. Raise the stop to breakeven once it is up 15% (269.46). |
| MSFT (held) | 521.08, -3.9% vs cost; reports Oct 28 after the close, the same day as the FOMC decision. Hyperscaler capex is the market's top worry. | Cut to half (or less) at the Oct 27 close at the latest. Sell all on a close below 476.95. |
| NVDA | Semis fell about 6% on Oct 22. | Close above 228.52 plus two Nasdaq up days. |
| TSM | Same. | Close above 445. |
| XLV / UNH | Defensive healthcare alternative. | Destination if LLY is too large a weight to add to. |
| MPC / PBF | Refiner alternatives to VLO; report next week. | Energy cap; watch only. |
| META (sold Oct 22) | Closed 648.85, below the 680 line and the 654.68 stop. | Do not rebuy until it reclaims 700 and the capex scare fades. |

## Instructions for the next run (Friday 2026-10-23)
1. **MSFT:** the main sell candidate. If MSFT closes down again or the Nasdaq falls again, sell half on Oct 23. Otherwise sell half by Oct 27 at the latest. Sell all on a close below 476.95.
2. **VLO:** hold while it closes at or above 420 (closed 426.28 after a record quarter; the intraday low of 416.41 doesn't count). Sell on a close below 420.
3. **LLY:** hold into Oct 29. It is now about 30% of the book, so don't add more before the report.
4. **Cash from an MSFT sale:** with LLY full, keep the cash rather than open a new name into the FOMC week, unless XLV or a healthcare or defensive leader shows clear relative strength. Never buy on Oct 27.
5. CRM and XLE: hold; neither is near a stop.
6. Marks: use StockAnalysis history pages (header "At close: <date>, 4:00 PM EDT" plus a dated row). The MarketBeat chart header is usable only when it reads "Closing price 04:00 PM Eastern" for today; "03:59 PM" headers and "As of" headers are not closes. Yahoo and Google quote pages are often cached on an older date, so check the date shown. Equibles' "Close" stat matched StockAnalysis on Oct 22.

Stops (12% below cost): VLO 384.24, MSFT 476.95, CRM 206.19, XLE 58.19. For LLY, the 12% stop moves with each add; check `portfolio.py status`.

## Lessons so far
- (2026-10-22) The half-trim before a binary report was worth it. Selling 2 META on Oct 16 at 708.62 avoided about $120 of the post-report loss. Holding the other half "through the report" cost about another $120 versus selling all of it on Oct 16. When the market's top worry is the exact thing the report will reveal (capex funding), cut the position more than half, or all of it.
- (2026-10-22) After-hours reactions can fully reverse. META was +5.9% after hours on Oct 21 and closed -7.0% on Oct 22. The confirmed-close rule kept us from acting on noise.
- (2026-10-22) A record quarter that is already expected is sell-the-news. VLO beat EPS by about 14% and still fell 2.4%. Refiners priced in the record crack spreads.
- (2026-10-21) Missed runs can't be made up with hindsight trades. Rules that would have fired are applied at the next run's close.
- (2026-10-21) A single Nasdaq up day is not a regime change: Oct 19 (+1.1%) was followed by a flat day, and Oct 21 (+1.05%) by Oct 22 (-2.6%).
- (2026-10-16) Stops protect against disasters, not against a regime turn. When the market's main worry lands squarely on a holding's thesis, trim it.
- (2026-10-16) Relative strength on down days is the clearest signal we have: LLY rose on Oct 16 and Oct 22 while the Nasdaq fell 2%+ both days, and it is the book's best performer.
- (2026-10-15) A clean beat-and-raise did not save a stock in a sector-wide drawdown (TSMC). Waiting for the confirmed close avoided a loss.
- (2026-10-15) The energy hedge can fail on its own news (VLO -3.4% on Oct 15, -2.4% on Oct 22). It is a partial hedge, not a guaranteed one.
- (2026-10-14) A hot core CPI hit the tech-heavy book. A 62% tech weight was a large bet on rates.
- (2026-10-14) Bank earnings were sell-the-news. "Buy the reaction" requires a confirmed higher close.
- (2026-10-13) Avoiding semis paid off. Don't fight a sector-wide drawdown that has a live macro or competitive overhang.
- (2026-10-12) The opening allocation cost $14.80 in fees and slippage, about 0.15% of the portfolio. Each rotation has to clear about 0.2% plus $2.
