# Agent Stock Portfolio

A paper-trading stock portfolio run entirely by Claude agents and managed in this repo.
Three agents run once per US trading day after the close, then push one commit to `main`;
GitHub Pages republishes the dashboard from that commit.

| Agent | Job | Instructions |
|---|---|---|
| Analyst | Reviews past trades and results, rewrites the strategy that guides future picks | [`agents/analyst.md`](agents/analyst.md) |
| Research | Searches the web and makes at most **one buy and one sell per day** | [`agents/research.md`](agents/research.md) |
| Fact checker | Replays every number from the $10,000 start and re-verifies prices from an independent source before marking a trade **Fact check cleared** | [`agents/fact_checker.md`](agents/fact_checker.md) |

The daily routine follows [`agents/RUNBOOK.md`](agents/RUNBOOK.md).

## Rules
- Starting cash **$10,000**, US stocks and ETFs, no margin or shorts.
- At most one buy and one sell per trading day. The one exception was the opening allocation on 2026-10-12, when the research agent could make up to 8 buys to build the starting portfolio.
- Fills at the day's closing price with simulated costs: **$1.00 commission per trade plus 0.10% slippage** (buys fill above the quote, sells below). Change them in [`config/settings.json`](config/settings.json) by adding a new fee schedule entry with a future `effective_from` date.

## Data
| File | What it is |
|---|---|
| `data/ledger.json` | Append-only transaction log. Each entry has the quote, source URL and timestamp, fees, cash after, rationale, a hash chained to the previous entry, and its fact-check result. |
| `data/history.json` | One mark-to-market snapshot per trading day (prices with sources), used for the chart. |
| `data/portfolio.json` | Current holdings and returns, derived from the two files above. |
| `data/strategy.md` | The analyst's current guidance. |
| `data/journal/YYYY-MM-DD.md` | Each day's analyst review, research notes and fact-check report. |

## How returns are kept honest
- Trades only enter the ledger through `scripts/portfolio.py`, which enforces cash, holdings, daily limits and fees.
- `scripts/factcheck.py verify` replays the ledger from scratch and fails on any mismatch: an edited or deleted trade breaks the hash chain, and an inflated price, cash balance or total no longer adds up.
- Clearing a trade needs an independent price within 1% from a different source.
- CI runs the audit on every push and pull request; the Pages deploy only runs after it passes, so an unverified or inconsistent portfolio never reaches the dashboard.

## Commands
```
python3 scripts/portfolio.py status
python3 scripts/factcheck.py verify --require-reviewed
python3 -m unittest discover -s tests
bash scripts/build_site.sh && python3 -m http.server -d _site 8000   # preview the dashboard
```

Live dashboard: https://datachart.github.io/AgentStockPortfolio/

Paper trading only; nothing here is investment advice.
