# Daily run

The scheduled routine follows this file once per US trading day, after the 4:00 pm ET close.
Everything happens in this repo: the run ends with one commit pushed to `main`, and
the GitHub Pages dashboard redeploys from that push.

Run the three agents **in order**. The fact checker must be a fresh subagent that did
not take part in research, so it checks the work instead of remembering it.

## 0. Setup
- `git pull origin main`.
- `TODAY` is today's date in US Eastern time (`TZ=America/New_York date +%F`).
- If `TODAY` is a weekend or an NYSE holiday, stop: no commit.
- `python3 scripts/factcheck.py verify --require-reviewed` must pass before you start.
  If it fails, stop and leave a note in `data/journal/TODAY.md` explaining what is broken; do not trade on a broken ledger.

## 1. Analyst agent (`agents/analyst.md`)
Reviews every past trade and the portfolio's path, then rewrites `data/strategy.md`
and writes the "Analyst review" section of `data/journal/TODAY.md`.

## 2. Research agent (`agents/research.md`)
Reads `data/strategy.md`, searches the web, and decides on **at most one buy and at most
one sell** for `TODAY`, recorded with `scripts/portfolio.py buy|sell`. Doing nothing is
allowed. Then it records today's closing prices for every holding with
`scripts/portfolio.py mark`, and writes the "Research" section of the journal.

## 3. Fact-check agent (`agents/fact_checker.md`)
Launch as a separate subagent. It runs the audit, independently re-verifies every
price recorded today from a **different** source, and clears each item with
`scripts/factcheck.py clear-trade` / `clear-snapshot`. It writes the "Fact check"
section of the journal.

If any price can't be verified within tolerance, the trade is not published: run
`git checkout -- data/` to discard today's uncommitted changes, then redo step 2 with
corrected prices (or no trade). Never edit `data/ledger.json` or `data/history.json` by
hand, and never rewrite history that is already on `main`. If a mistake is found in an
already-published entry, use `scripts/factcheck.py flag` so it shows as failed on the
dashboard, and explain it in the journal.

## 4. Publish
- `python3 scripts/factcheck.py verify --require-reviewed` must print `OK`.
- `python3 -m unittest discover -s tests` must pass.
- Commit everything under `data/` with the message `Daily run TODAY: <one-line summary of trades>`
  and push to `main`. CI re-runs the audit; Pages deploys only if it passes.
