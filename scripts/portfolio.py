#!/usr/bin/env python3
"""Paper-trading portfolio engine.

The ledger (data/ledger.json) is the single source of truth. Every other file
(data/portfolio.json, data/history.json values) is derived from it and can be
re-derived by replaying the ledger, which is exactly what the fact checker does.

Usage:
  portfolio.py buy  TICKER (--shares N | --amount USD) --price P --source URL --timestamp ISO --rationale TEXT [--date D]
  portfolio.py sell TICKER (--shares N | --all)        --price P --source URL --timestamp ISO --rationale TEXT [--date D]
  portfolio.py mark --prices prices.json [--date D]    # end-of-day mark-to-market snapshot
  portfolio.py rebuild                                 # regenerate data/portfolio.json
  portfolio.py status
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "settings.json"
LEDGER_PATH = ROOT / "data" / "ledger.json"
HISTORY_PATH = ROOT / "data" / "history.json"
PORTFOLIO_PATH = ROOT / "data" / "portfolio.json"

GENESIS_HASH = "0" * 64
EPS = 0.005  # half a cent


class TradeError(Exception):
    pass


# ---------------------------------------------------------------- io helpers

def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def load_config() -> dict:
    return load_json(CONFIG_PATH, None)


def load_ledger() -> dict:
    return load_json(LEDGER_PATH, {"transactions": []})


def load_history() -> dict:
    return load_json(HISTORY_PATH, {"snapshots": []})


def money(x: float) -> float:
    return round(x + 0.0, 2)


def round_shares(x: float, cfg: dict) -> float:
    return round(x, cfg["shares"]["decimals"])


# ---------------------------------------------------------------- fees

def fees_for(date: str, cfg: dict) -> dict:
    """The fee schedule entry in force on `date`."""
    active = [f for f in cfg["fees"]["schedule"] if f["effective_from"] <= date]
    if not active:
        raise TradeError(f"no fee schedule in force on {date}")
    return max(active, key=lambda f: f["effective_from"])


def fill(action: str, quote_price: float, shares: float, cfg: dict, date: str) -> dict:
    """Simulated fill: price after slippage, commission, and the cash change."""
    fees = fees_for(date, cfg)
    slip = fees["slippage_pct"] / 100.0
    commission = money(fees["commission_per_trade"])
    if action == "BUY":
        exec_price = round(quote_price * (1 + slip), 4)
        gross = money(shares * exec_price)
        cash_delta = money(-(gross + commission))
    elif action == "SELL":
        exec_price = round(quote_price * (1 - slip), 4)
        gross = money(shares * exec_price)
        cash_delta = money(gross - commission)
    else:
        raise TradeError(f"unknown action {action}")
    slippage_cost = money(abs(exec_price - quote_price) * shares)
    return {
        "exec_price": exec_price,
        "gross": gross,
        "commission": commission,
        "slippage_cost": slippage_cost,
        "total_fees": money(commission + slippage_cost),
        "cash_delta": cash_delta,
    }


# ---------------------------------------------------------------- hashing

HASHED_FIELDS = (
    "id", "date", "action", "ticker", "shares", "quote_price", "price_source",
    "price_timestamp", "exec_price", "gross", "commission", "slippage_cost",
    "cash_delta", "cash_after", "rationale", "prev_hash",
)


def tx_hash(tx: dict) -> str:
    body = {k: tx.get(k) for k in HASHED_FIELDS}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------- replay

def replay(transactions: list[dict], cfg: dict, upto_date: str | None = None) -> dict:
    """Rebuild cash and positions from the ledger. Raises TradeError on any
    rule violation so the same code guards new trades and audits old ones."""
    cash = money(cfg["starting_cash"])
    positions: dict[str, dict] = {}
    realized = 0.0
    fees_paid = 0.0
    per_day: dict[tuple[str, str], int] = {}
    limits = cfg["limits"]
    for tx in transactions:
        if upto_date and tx["date"] > upto_date:
            break
        key = (tx["date"], tx["action"])
        per_day[key] = per_day.get(key, 0) + 1
        cap = limits["max_buys_per_day"] if tx["action"] == "BUY" else limits["max_sells_per_day"]
        if per_day[key] > cap:
            raise TradeError(f"{tx['id']}: more than {cap} {tx['action']} on {tx['date']}")
        f = fill(tx["action"], tx["quote_price"], tx["shares"], cfg, tx["date"])
        pos = positions.setdefault(tx["ticker"], {"shares": 0.0, "cost_basis": 0.0})
        if tx["action"] == "BUY":
            if cash + f["cash_delta"] < -EPS:
                raise TradeError(f"{tx['id']}: buy needs ${-f['cash_delta']:.2f} but only ${cash:.2f} cash")
            pos["shares"] = round_shares(pos["shares"] + tx["shares"], cfg)
            pos["cost_basis"] = money(pos["cost_basis"] - f["cash_delta"])
        else:
            if tx["shares"] > pos["shares"] + 1e-9:
                raise TradeError(f"{tx['id']}: sells {tx['shares']} {tx['ticker']} but holds {pos['shares']}")
            portion = tx["shares"] / pos["shares"]
            basis_out = money(pos["cost_basis"] * portion)
            realized = money(realized + f["cash_delta"] - basis_out)
            pos["shares"] = round_shares(pos["shares"] - tx["shares"], cfg)
            pos["cost_basis"] = money(pos["cost_basis"] - basis_out)
        if pos["shares"] <= 0:
            positions.pop(tx["ticker"])
        cash = money(cash + f["cash_delta"])
        fees_paid = money(fees_paid + f["total_fees"])
    return {"cash": cash, "positions": positions, "realized_pl": realized, "fees_paid": fees_paid}


# ---------------------------------------------------------------- trading

def parse_date(s: str | None) -> str:
    d = dt.date.fromisoformat(s) if s else dt.date.today()
    return d.isoformat()


def check_trading_day(date: str, cfg: dict) -> None:
    day = dt.date.fromisoformat(date).strftime("%a")
    if day not in cfg["limits"]["trading_days"]:
        raise TradeError(f"{date} is a {day}; trades only on {cfg['limits']['trading_days']}")


def record_trade(action: str, ticker: str, quote_price: float, source: str, timestamp: str,
                 rationale: str, date: str, cfg: dict, shares: float | None = None,
                 amount: float | None = None, sell_all: bool = False) -> dict:
    ledger = load_ledger()
    txs = ledger["transactions"]
    ticker = ticker.upper().strip()
    quote_price = round(quote_price, 4)  # what gets stored is what the fees are computed from
    if quote_price <= 0:
        raise TradeError("price must be positive")
    if not source or not timestamp:
        raise TradeError("price source and timestamp are required so the fact checker can re-verify")
    if not rationale or len(rationale.strip()) < 20:
        raise TradeError("give a real rationale (at least 20 characters)")
    if txs and date < txs[-1]["date"]:
        raise TradeError(f"ledger is append-only; {date} is before last entry {txs[-1]['date']}")
    check_trading_day(date, cfg)
    state = replay(txs, cfg)

    if action == "BUY":
        if amount is not None:
            # Spend `amount` dollars including commission.
            fees = fees_for(date, cfg)
            exec_price = round(quote_price * (1 + fees["slippage_pct"] / 100.0), 4)
            budget = amount - fees["commission_per_trade"]
            shares = budget / exec_price
            if not cfg["shares"]["allow_fractional"]:
                shares = float(int(shares))
            # Truncate (never round up) so we never overspend.
            factor = 10 ** cfg["shares"]["decimals"]
            shares = int(shares * factor) / factor
    else:
        held = state["positions"].get(ticker, {}).get("shares", 0.0)
        if sell_all:
            shares = held
    if shares is None or shares <= 0:
        raise TradeError("share count must be positive")
    shares = round_shares(shares, cfg)

    f = fill(action, quote_price, shares, cfg, date)
    tx = {
        "id": f"T{len(txs) + 1:04d}",
        "date": date,
        "action": action,
        "ticker": ticker,
        "shares": shares,
        "quote_price": quote_price,
        "price_source": source,
        "price_timestamp": timestamp,
        **{k: f[k] for k in ("exec_price", "gross", "commission", "slippage_cost", "cash_delta")},
        "cash_after": money(state["cash"] + f["cash_delta"]),
        "rationale": rationale.strip(),
        "prev_hash": txs[-1]["hash"] if txs else GENESIS_HASH,
    }
    # Validate against the rules by replaying with the new trade appended.
    after = replay(txs + [tx], cfg)
    if action == "SELL":
        before_basis = state["positions"][ticker]["cost_basis"]
        after_basis = after["positions"].get(ticker, {}).get("cost_basis", 0.0)
        tx["realized_pl"] = money(f["cash_delta"] - (before_basis - after_basis))
    tx["hash"] = tx_hash(tx)
    tx["fact_check"] = {"status": "pending"}
    txs.append(tx)
    save_json(LEDGER_PATH, ledger)
    rebuild(cfg)
    return tx


# ---------------------------------------------------------------- marking

def mark(prices: dict, date: str, cfg: dict) -> dict:
    """Record an end-of-day snapshot. `prices` maps ticker -> {price, source, timestamp}.
    Every held ticker needs a price; replaces an existing snapshot for the same date."""
    txs = load_ledger()["transactions"]
    state = replay(txs, cfg, upto_date=date)
    prices = {k.upper(): v for k, v in prices.items()}
    missing = [t for t in state["positions"] if t not in prices]
    if missing:
        raise TradeError(f"missing prices for held tickers: {missing}")
    used = {}
    holdings_value = 0.0
    for t, pos in state["positions"].items():
        p = prices[t]
        if not p.get("source") or not p.get("timestamp") or float(p["price"]) <= 0:
            raise TradeError(f"price for {t} needs a positive price, source and timestamp")
        price = round(float(p["price"]), 4)
        used[t] = {"price": price, "source": p["source"], "timestamp": p["timestamp"], "shares": pos["shares"]}
        holdings_value += pos["shares"] * price
    holdings_value = money(holdings_value)
    total = money(state["cash"] + holdings_value)
    snap = {
        "date": date,
        "cash": state["cash"],
        "holdings_value": holdings_value,
        "total_value": total,
        "return_pct": round((total / cfg["starting_cash"] - 1) * 100, 2),
        "prices": used,
        "fact_check": {"status": "pending"},
    }
    history = load_history()
    snaps = [s for s in history["snapshots"] if s["date"] != date]
    snaps.append(snap)
    snaps.sort(key=lambda s: s["date"])
    history["snapshots"] = snaps
    save_json(HISTORY_PATH, history)
    rebuild(cfg)
    return snap


# ---------------------------------------------------------------- derived state

def build_portfolio(cfg: dict, txs: list[dict], snaps: list[dict]) -> dict:
    state = replay(txs, cfg)
    last = snaps[-1] if snaps else None
    positions = []
    holdings_value = 0.0
    for t, pos in sorted(state["positions"].items()):
        price_info = (last or {}).get("prices", {}).get(t)
        last_price = price_info["price"] if price_info else None
        value = money(pos["shares"] * last_price) if last_price is not None else pos["cost_basis"]
        holdings_value += value
        positions.append({
            "ticker": t,
            "shares": pos["shares"],
            "cost_basis": pos["cost_basis"],
            "avg_cost": round(pos["cost_basis"] / pos["shares"], 4),
            "last_price": last_price,
            "market_value": value,
            "unrealized_pl": money(value - pos["cost_basis"]),
            "unrealized_pl_pct": round((value / pos["cost_basis"] - 1) * 100, 2) if pos["cost_basis"] else 0.0,
        })
    total = money(state["cash"] + holdings_value)
    return {
        "as_of": last["date"] if last else None,
        "starting_cash": money(cfg["starting_cash"]),
        "cash": state["cash"],
        "holdings_value": money(holdings_value),
        "total_value": total,
        "return_pct": round((total / cfg["starting_cash"] - 1) * 100, 2),
        "realized_pl": state["realized_pl"],
        "fees_paid": state["fees_paid"],
        "trade_count": len(txs),
        "positions": positions,
    }


def rebuild(cfg: dict) -> dict:
    p = build_portfolio(cfg, load_ledger()["transactions"], load_history()["snapshots"])
    save_json(PORTFOLIO_PATH, p)
    return p


# ---------------------------------------------------------------- cli

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("buy", "sell"):
        p = sub.add_parser(name)
        p.add_argument("ticker")
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--shares", type=float)
        if name == "buy":
            g.add_argument("--amount", type=float, help="dollars to spend, commission included")
        else:
            g.add_argument("--all", action="store_true", dest="sell_all")
        p.add_argument("--price", type=float, required=True, help="quoted price before slippage")
        p.add_argument("--source", required=True, help="URL the price came from")
        p.add_argument("--timestamp", required=True, help="when the quote was observed (ISO 8601)")
        p.add_argument("--rationale", required=True)
        p.add_argument("--date")
    m = sub.add_parser("mark")
    m.add_argument("--prices", required=True, help="JSON file: {TICKER: {price, source, timestamp}}")
    m.add_argument("--date")
    sub.add_parser("rebuild")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    cfg = load_config()
    try:
        if args.cmd in ("buy", "sell"):
            tx = record_trade(
                args.cmd.upper(), args.ticker, args.price, args.source, args.timestamp, args.rationale,
                parse_date(args.date), cfg, shares=args.shares,
                amount=getattr(args, "amount", None), sell_all=getattr(args, "sell_all", False))
            print(json.dumps(tx, indent=2))
        elif args.cmd == "mark":
            snap = mark(load_json(Path(args.prices), {}), parse_date(args.date), cfg)
            print(json.dumps(snap, indent=2))
        elif args.cmd == "rebuild":
            print(json.dumps(rebuild(cfg), indent=2))
        else:
            p = rebuild(cfg)
            print(f"Value ${p['total_value']:,.2f} ({p['return_pct']:+.2f}%)  cash ${p['cash']:,.2f}  "
                  f"fees ${p['fees_paid']:,.2f}  trades {p['trade_count']}  as of {p['as_of']}")
            for pos in p["positions"]:
                print(f"  {pos['ticker']:6} {pos['shares']:>10} sh  ${pos['market_value']:>10,.2f}  "
                      f"{pos['unrealized_pl_pct']:+.2f}%")
    except TradeError as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
