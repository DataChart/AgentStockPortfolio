#!/usr/bin/env python3
"""Fact checker: independently audits the portfolio so returns can't be inflated.

  factcheck.py verify [--require-reviewed]
      Replays the whole ledger from the starting cash and checks every number:
      hash chain, fee math, cash after each trade, daily trade limits, no
      overdrafts or overselling, snapshot valuations and data/portfolio.json.
      With --require-reviewed, also fails if anything is still pending review.

  factcheck.py clear-trade ID --verified-price P --verified-source URL [--notes TEXT]
      Marks a trade "Fact check cleared" after an independent price check.

  factcheck.py clear-snapshot DATE --verified-prices FILE [--notes TEXT]
      FILE maps ticker -> {price, source}; marks the day's valuation cleared.

  factcheck.py clear-benchmark DATE --verified-close C --verified-source URL [--notes TEXT]
      Marks the day's S&P 500 comparison close cleared.

  factcheck.py flag (ID | --snapshot DATE | --benchmark DATE) --reason TEXT
      Marks an already-published item as failing fact check.

Clearing only succeeds when `verify` passes, the verified price is within the
configured tolerance of the price the research agent used, and the verifying
source is a different URL from the one the research agent cited.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio as pf  # noqa: E402

TOL = 0.011  # money comparisons: a cent plus float noise
TX_FIELDS = ("exec_price", "gross", "commission", "slippage_cost", "cash_delta")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def close(a, b, tol=TOL) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def price_ok(claimed: float, verified: float, cfg: dict) -> tuple[bool, float]:
    diff_pct = abs(verified - claimed) / claimed * 100
    return diff_pct <= cfg["fact_check"]["price_tolerance_pct"], round(diff_pct, 3)


def audit(cfg: dict, ledger: dict, history: dict, portfolio: dict | None) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings). Pure function so tests can feed it tampered data."""
    errors: list[str] = []
    warnings: list[str] = []
    txs = ledger.get("transactions", [])
    snaps = history.get("snapshots", [])

    # 1. Ledger integrity: ids, ordering, hash chain.
    prev_hash = pf.GENESIS_HASH
    prev_date = ""
    for i, tx in enumerate(txs):
        tid = tx.get("id", f"#{i}")
        if tid != f"T{i + 1:04d}":
            errors.append(f"{tid}: expected id T{i + 1:04d} (entries removed or reordered?)")
        if tx.get("date", "") < prev_date:
            errors.append(f"{tid}: dated {tx.get('date')} before previous entry {prev_date}")
        prev_date = tx.get("date", prev_date)
        if tx.get("prev_hash") != prev_hash:
            errors.append(f"{tid}: hash chain broken (prev_hash mismatch); history was rewritten")
        if tx.get("hash") != pf.tx_hash(tx):
            errors.append(f"{tid}: content does not match its hash; the entry was edited after recording")
        prev_hash = tx.get("hash")
        if tx.get("action") not in ("BUY", "SELL"):
            errors.append(f"{tid}: unknown action {tx.get('action')}")
            continue
        try:
            pf.check_trading_day(tx["date"], cfg)
        except pf.TradeError as e:
            errors.append(f"{tid}: {e}")
        if not tx.get("price_source") or not tx.get("price_timestamp"):
            errors.append(f"{tid}: missing price source or timestamp")
    if errors:
        return errors, warnings

    # 2. Recompute every fill and the running cash balance.
    for i, tx in enumerate(txs):
        tid = tx["id"]
        try:
            f = pf.fill(tx["action"], tx["quote_price"], tx["shares"], cfg, tx["date"])
        except pf.TradeError as e:
            errors.append(f"{tid}: {e}")
            continue
        for k in TX_FIELDS:
            if not close(f[k], tx.get(k), tol=0.0001 if k == "exec_price" else TOL):
                errors.append(f"{tid}: {k} recorded {tx.get(k)} but fee model gives {f[k]}")
        try:
            before = pf.replay(txs[:i], cfg)
            after = pf.replay(txs[: i + 1], cfg)
        except pf.TradeError as e:
            errors.append(str(e))
            break
        if not close(after["cash"], tx.get("cash_after")):
            errors.append(f"{tid}: cash_after recorded {tx.get('cash_after')} but replay gives {after['cash']}")
        if tx["action"] == "SELL":
            want = pf.money(after["realized_pl"] - before["realized_pl"])
            if not close(want, tx.get("realized_pl")):
                errors.append(f"{tid}: realized_pl recorded {tx.get('realized_pl')} but replay gives {want}")
        fc = tx.get("fact_check", {})
        if fc.get("status") == "cleared":
            ok, _ = price_ok(tx["quote_price"], float(fc.get("verified_price", -1)), cfg)
            if not ok:
                errors.append(f"{tid}: marked cleared but verified price {fc.get('verified_price')} "
                              f"is outside tolerance of {tx['quote_price']}")
            if not fc.get("verified_source") or fc.get("verified_source") == tx["price_source"]:
                errors.append(f"{tid}: marked cleared without an independent verifying source")

    # 3. Snapshots: cash and holdings must match the ledger, and the arithmetic must add up.
    prev = None
    for s in snaps:
        d = s.get("date")
        if prev and d <= prev["date"]:
            errors.append(f"snapshot {d}: out of order or duplicate")
        try:
            state = pf.replay(txs, cfg, upto_date=d)
        except pf.TradeError as e:
            errors.append(f"snapshot {d}: {e}")
            continue
        if not close(state["cash"], s.get("cash")):
            errors.append(f"snapshot {d}: cash {s.get('cash')} but ledger gives {state['cash']}")
        prices = s.get("prices", {})
        if set(prices) != set(state["positions"]):
            errors.append(f"snapshot {d}: priced {sorted(prices)} but held {sorted(state['positions'])}")
        hv = 0.0
        for t, pos in state["positions"].items():
            p = prices.get(t)
            if not p:
                continue
            if not close(p.get("shares"), pos["shares"], tol=1e-6):
                errors.append(f"snapshot {d}: {t} shares {p.get('shares')} but ledger gives {pos['shares']}")
            if not p.get("source") or not p.get("timestamp"):
                errors.append(f"snapshot {d}: {t} price missing source or timestamp")
            hv += pos["shares"] * float(p["price"])
        hv = pf.money(hv)
        if not close(hv, s.get("holdings_value")):
            errors.append(f"snapshot {d}: holdings_value {s.get('holdings_value')} but prices x shares = {hv}")
        total = pf.money(state["cash"] + hv)
        if not close(total, s.get("total_value")):
            errors.append(f"snapshot {d}: total_value {s.get('total_value')} but cash + holdings = {total}")
        ret = round((total / cfg["starting_cash"] - 1) * 100, 2)
        if not close(ret, s.get("return_pct"), tol=0.011):
            errors.append(f"snapshot {d}: return_pct {s.get('return_pct')} but should be {ret}")
        fc = s.get("fact_check", {})
        if fc.get("status") == "cleared":
            for t, p in prices.items():
                v = fc.get("verified_prices", {}).get(t)
                if not v:
                    errors.append(f"snapshot {d}: cleared but {t} was never independently verified")
                    continue
                ok, _ = price_ok(float(p["price"]), float(v["price"]), cfg)
                if not ok:
                    errors.append(f"snapshot {d}: cleared but {t} verified at {v['price']} vs {p['price']}")
        if prev and prev.get("total_value"):
            move = (s.get("total_value", 0) / prev["total_value"] - 1) * 100
            if abs(move) > 25:
                warnings.append(f"snapshot {d}: portfolio moved {move:+.1f}% in one step; double-check prices")
        prev = s

    # 4. The published summary must equal what the ledger and snapshots produce.
    if portfolio is not None:
        want = pf.build_portfolio(cfg, txs, snaps)
        for k in ("cash", "holdings_value", "total_value", "return_pct", "realized_pl", "fees_paid", "trade_count"):
            if not close(want[k], portfolio.get(k)):
                errors.append(f"portfolio.json: {k} is {portfolio.get(k)} but replay gives {want[k]}")
        if [p["ticker"] for p in want["positions"]] != [p.get("ticker") for p in portfolio.get("positions", [])]:
            errors.append("portfolio.json: positions differ from replay")
    return errors, warnings


def audit_benchmark(cfg: dict, bench: dict, history: dict) -> tuple[list[str], list[str]]:
    """Checks the S&P 500 comparison series, so the benchmark can't be shaded to flatter the portfolio."""
    errors: list[str] = []
    warnings: list[str] = []
    prev = ""
    for c in bench.get("closes", []):
        d = c.get("date", "")
        if d <= prev:
            errors.append(f"benchmark {d}: dates must be unique and ascending")
        prev = d
        try:
            pf.check_trading_day(d, cfg)
        except (pf.TradeError, ValueError) as e:
            errors.append(f"benchmark {d}: {e}")
        if not (isinstance(c.get("close"), (int, float)) and c["close"] > 0):
            errors.append(f"benchmark {d}: close must be a positive number")
            continue
        if not str(c.get("source", "")).startswith(("http://", "https://")) or not c.get("timestamp"):
            errors.append(f"benchmark {d}: needs an http(s) source and a timestamp")
        fc = c.get("fact_check", {})
        if fc.get("status") == "cleared":
            v = fc.get("verified_close")
            if v is None or str(fc.get("verified_source", "")).strip() == str(c.get("source", "")).strip():
                errors.append(f"benchmark {d}: cleared without an independent close")
            elif not price_ok(float(c["close"]), float(v), cfg)[0]:
                errors.append(f"benchmark {d}: cleared but verified at {v} vs {c['close']}")
    if bench.get("closes"):
        have = {c["date"] for c in bench["closes"]}
        first = bench["closes"][0]["date"]
        missing = [s["date"] for s in history.get("snapshots", []) if s["date"] >= first and s["date"] not in have]
        if missing:
            warnings.append(f"benchmark: no S&P 500 close for {', '.join(missing)}")
    return errors, warnings


def pending_items(ledger: dict, history: dict, bench: dict | None = None) -> list[str]:
    out = [tx["id"] for tx in ledger.get("transactions", [])
           if tx.get("fact_check", {}).get("status") not in ("cleared", "flagged")]
    out += [f"snapshot {s['date']}" for s in history.get("snapshots", [])
            if s.get("fact_check", {}).get("status") not in ("cleared", "flagged")]
    out += [f"benchmark {c['date']}" for c in (bench or {}).get("closes", [])
            if c.get("fact_check", {}).get("status") not in ("cleared", "flagged")]
    return out


def load_all():
    return (pf.load_config(), pf.load_ledger(), pf.load_history(),
            pf.load_json(pf.PORTFOLIO_PATH, None))


def must_verify(cfg, ledger, history, portfolio) -> None:
    errors, _ = audit(cfg, ledger, history, portfolio)
    errors += audit_benchmark(cfg, pf.load_benchmark(), history)[0]
    if errors:
        raise pf.TradeError("verify failed, fix these first:\n  " + "\n  ".join(errors))


def cmd_verify(require_reviewed: bool) -> int:
    cfg, ledger, history, portfolio = load_all()
    bench = pf.load_benchmark()
    errors, warnings = audit(cfg, ledger, history, portfolio)
    b_errors, b_warnings = audit_benchmark(cfg, bench, history)
    errors += b_errors
    warnings += b_warnings
    pending = pending_items(ledger, history, bench)
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"FAIL  {e}")
    if require_reviewed and pending:
        for p in pending:
            print(f"FAIL  {p} has not been fact checked")
    n = len(ledger.get("transactions", []))
    m = len(history.get("snapshots", []))
    k = len(bench.get("closes", []))
    failed = bool(errors) or (require_reviewed and bool(pending))
    print(f"{'FAILED' if failed else 'OK'}: {n} trades, {m} snapshots, {k} S&P 500 closes audited; "
          f"{len(errors)} errors, {len(warnings)} warnings, {len(pending)} pending review")
    return 1 if failed else 0


def cmd_clear_trade(tid: str, verified_price: float, verified_source: str, notes: str) -> dict:
    cfg, ledger, history, portfolio = load_all()
    must_verify(cfg, ledger, history, portfolio)
    tx = next((t for t in ledger["transactions"] if t["id"] == tid), None)
    if tx is None:
        raise pf.TradeError(f"no transaction {tid}")
    if verified_source.strip() == tx["price_source"].strip():
        raise pf.TradeError("verifying source must differ from the research agent's source")
    ok, diff = price_ok(tx["quote_price"], verified_price, cfg)
    if not ok:
        raise pf.TradeError(f"{tid}: verified price {verified_price} differs {diff}% from {tx['quote_price']} "
                            f"(limit {cfg['fact_check']['price_tolerance_pct']}%); do not clear")
    tx["fact_check"] = {
        "status": "cleared",
        "checked_at": now_iso(),
        "verified_price": round(verified_price, 4),
        "verified_source": verified_source,
        "price_diff_pct": diff,
        "checks": ["hash chain", "fee math", "cash balance", "daily limits", "holdings", "independent price"],
        "notes": notes,
    }
    pf.save_json(pf.LEDGER_PATH, ledger)
    return tx["fact_check"]


def cmd_clear_snapshot(date: str, verified: dict, notes: str) -> dict:
    cfg, ledger, history, portfolio = load_all()
    must_verify(cfg, ledger, history, portfolio)
    snap = next((s for s in history["snapshots"] if s["date"] == date), None)
    if snap is None:
        raise pf.TradeError(f"no snapshot for {date}")
    verified = {k.upper(): v for k, v in verified.items()}
    out = {}
    for t, p in snap["prices"].items():
        v = verified.get(t)
        if not v or not v.get("source"):
            raise pf.TradeError(f"{t}: need an independently verified price and source")
        if v["source"].strip() == p["source"].strip():
            raise pf.TradeError(f"{t}: verifying source must differ from {p['source']}")
        ok, diff = price_ok(float(p["price"]), float(v["price"]), cfg)
        if not ok:
            raise pf.TradeError(f"{t}: verified {v['price']} differs {diff}% from {p['price']}; do not clear")
        out[t] = {"price": round(float(v["price"]), 4), "source": v["source"], "diff_pct": diff}
    snap["fact_check"] = {"status": "cleared", "checked_at": now_iso(), "verified_prices": out, "notes": notes}
    pf.save_json(pf.HISTORY_PATH, history)
    return snap["fact_check"]


def cmd_clear_benchmark(date: str, verified_close: float, verified_source: str, notes: str) -> dict:
    cfg, ledger, history, portfolio = load_all()
    must_verify(cfg, ledger, history, portfolio)
    bench = pf.load_benchmark()
    c = next((x for x in bench["closes"] if x["date"] == date), None)
    if c is None:
        raise pf.TradeError(f"no S&P 500 close recorded for {date}")
    if verified_source.strip() == c["source"].strip():
        raise pf.TradeError("verifying source must differ from the research agent's source")
    ok, diff = price_ok(c["close"], verified_close, cfg)
    if not ok:
        raise pf.TradeError(f"benchmark {date}: verified {verified_close} differs {diff}% from {c['close']}; do not clear")
    c["fact_check"] = {"status": "cleared", "checked_at": now_iso(), "verified_close": round(verified_close, 2),
                       "verified_source": verified_source, "diff_pct": diff, "notes": notes}
    pf.save_json(pf.BENCHMARK_PATH, bench)
    return c["fact_check"]


def cmd_flag(tid: str | None, date: str | None, reason: str, bench_date: str | None = None) -> dict:
    ledger, history = pf.load_ledger(), pf.load_history()
    fc = {"status": "flagged", "checked_at": now_iso(), "reason": reason}
    if tid:
        item = next((t for t in ledger["transactions"] if t["id"] == tid), None)
        path, data = pf.LEDGER_PATH, ledger
    elif bench_date:
        data = pf.load_benchmark()
        item = next((c for c in data["closes"] if c["date"] == bench_date), None)
        path = pf.BENCHMARK_PATH
    else:
        item = next((s for s in history["snapshots"] if s["date"] == date), None)
        path, data = pf.HISTORY_PATH, history
    if item is None:
        raise pf.TradeError("item not found")
    item["fact_check"] = fc
    pf.save_json(path, data)
    return fc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--require-reviewed", action="store_true")
    c = sub.add_parser("clear-trade")
    c.add_argument("id")
    c.add_argument("--verified-price", type=float, required=True)
    c.add_argument("--verified-source", required=True)
    c.add_argument("--notes", default="")
    s = sub.add_parser("clear-snapshot")
    s.add_argument("date")
    s.add_argument("--verified-prices", required=True)
    s.add_argument("--notes", default="")
    b = sub.add_parser("clear-benchmark")
    b.add_argument("date")
    b.add_argument("--verified-close", type=float, required=True)
    b.add_argument("--verified-source", required=True)
    b.add_argument("--notes", default="")
    f = sub.add_parser("flag")
    f.add_argument("id", nargs="?")
    f.add_argument("--snapshot")
    f.add_argument("--benchmark")
    f.add_argument("--reason", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "verify":
            return cmd_verify(args.require_reviewed)
        if args.cmd == "clear-trade":
            r = cmd_clear_trade(args.id, args.verified_price, args.verified_source, args.notes)
        elif args.cmd == "clear-snapshot":
            r = cmd_clear_snapshot(args.date, pf.load_json(Path(args.verified_prices), {}), args.notes)
        elif args.cmd == "clear-benchmark":
            r = cmd_clear_benchmark(args.date, args.verified_close, args.verified_source, args.notes)
        else:
            if sum(map(bool, (args.id, args.snapshot, args.benchmark))) != 1:
                raise pf.TradeError("give exactly one of ID, --snapshot DATE or --benchmark DATE")
            r = cmd_flag(args.id, args.snapshot, args.reason, args.benchmark)
        print(json.dumps(r, indent=2))
    except pf.TradeError as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
