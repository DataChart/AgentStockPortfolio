# CLAUDE.md

Paper-trading portfolio run by agents. Read `README.md` for the layout and `agents/RUNBOOK.md` for the daily run.

- Never hand-edit `data/ledger.json`, `data/history.json` or `data/portfolio.json`; use `scripts/portfolio.py` and `scripts/factcheck.py`.
- The ledger is append-only. Entries already on `main` are never rewritten; use `factcheck.py flag` to mark a bad one.
- Before any commit: `python3 scripts/factcheck.py verify --require-reviewed` and `python3 -m unittest discover -s tests` must both pass.
- Python 3 standard library only; the dashboard in `site/` is plain HTML/CSS/JS with no build step.
