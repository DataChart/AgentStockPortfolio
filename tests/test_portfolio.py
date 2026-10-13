import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import factcheck as fc  # noqa: E402
import portfolio as pf  # noqa: E402

SRC = "https://example.com/quote"
SRC2 = "https://example.org/other-quote"
TS = "2026-10-13T20:00:00Z"
WHY = "Strong momentum after earnings beat; aggressive entry."


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._saved = (pf.LEDGER_PATH, pf.HISTORY_PATH, pf.PORTFOLIO_PATH)
        pf.LEDGER_PATH, pf.HISTORY_PATH, pf.PORTFOLIO_PATH = d / "l.json", d / "h.json", d / "p.json"
        self.cfg = pf.load_config()

    def tearDown(self):
        pf.LEDGER_PATH, pf.HISTORY_PATH, pf.PORTFOLIO_PATH = self._saved
        self.tmp.cleanup()

    def buy(self, ticker="NVDA", price=100.0, date="2026-10-13", **kw):
        if "shares" not in kw and "amount" not in kw:
            kw["shares"] = 10
        return pf.record_trade("BUY", ticker, price, SRC, TS, WHY, date, self.cfg, **kw)

    def sell(self, ticker="NVDA", price=110.0, date="2026-10-14", **kw):
        if "shares" not in kw and not kw.get("sell_all"):
            kw["shares"] = 10
        return pf.record_trade("SELL", ticker, price, SRC, TS, WHY, date, self.cfg, **kw)

    def audit(self):
        return fc.audit(self.cfg, pf.load_ledger(), pf.load_history(), pf.load_json(pf.PORTFOLIO_PATH, None))


class TradingTests(Base):
    def test_buy_applies_commission_and_slippage(self):
        tx = self.buy(price=100.0, shares=10)
        self.assertEqual(tx["exec_price"], 100.1)
        self.assertEqual(tx["gross"], 1001.0)
        self.assertEqual(tx["commission"], 1.0)
        self.assertEqual(tx["slippage_cost"], 1.0)
        self.assertEqual(tx["cash_after"], 10000 - 1002.0)

    def test_round_trip_realized_pl(self):
        self.buy(price=100.0, shares=10)
        tx = self.sell(price=110.0, shares=10)
        # 10 * 109.89 - 1 = 1097.90 received, 1002.00 paid
        self.assertEqual(tx["realized_pl"], 95.9)
        p = pf.rebuild(self.cfg)
        self.assertEqual(p["cash"], 10095.9)
        self.assertEqual(p["positions"], [])
        self.assertEqual(self.audit()[0], [])

    def test_amount_never_overspends(self):
        tx = self.buy(price=123.45, amount=10000)
        self.assertGreaterEqual(tx["cash_after"], 0)

    def test_overdraft_rejected(self):
        with self.assertRaises(pf.TradeError):
            self.buy(price=100.0, shares=200)

    def test_oversell_rejected(self):
        self.buy(shares=5)
        with self.assertRaises(pf.TradeError):
            self.sell(shares=6)

    def test_one_buy_and_one_sell_per_day(self):
        self.buy(ticker="AAA", shares=5)
        self.sell(ticker="AAA", shares=1, date="2026-10-13")
        with self.assertRaises(pf.TradeError):
            self.buy(ticker="BBB", shares=1)
        with self.assertRaises(pf.TradeError):
            self.sell(ticker="AAA", shares=1, date="2026-10-13")

    def test_weekend_rejected(self):
        with self.assertRaises(pf.TradeError):
            self.buy(date="2026-10-17")

    def test_ledger_is_append_only(self):
        self.buy(date="2026-10-14")
        with self.assertRaises(pf.TradeError):
            self.buy(ticker="X", date="2026-10-13")

    def test_mark_values_portfolio(self):
        self.buy(price=100.0, shares=10)
        snap = pf.mark({"nvda": {"price": 120.0, "source": SRC, "timestamp": TS}}, "2026-10-13", self.cfg)
        self.assertEqual(snap["total_value"], 8998.0 + 1200.0)
        self.assertEqual(snap["return_pct"], 1.98)
        self.assertEqual(self.audit()[0], [])

    def test_mark_requires_every_holding(self):
        self.buy()
        with self.assertRaises(pf.TradeError):
            pf.mark({}, "2026-10-13", self.cfg)


class FactCheckTests(Base):
    def setUp(self):
        super().setUp()
        self.buy(price=100.0, shares=10)
        pf.mark({"NVDA": {"price": 105.0, "source": SRC, "timestamp": TS}}, "2026-10-13", self.cfg)

    def tampered(self, fn):
        ledger, history = pf.load_ledger(), pf.load_history()
        portfolio = pf.load_json(pf.PORTFOLIO_PATH, None)
        fn(ledger, history, portfolio)
        return fc.audit(self.cfg, ledger, history, portfolio)[0]

    def test_clean_state_passes(self):
        self.assertEqual(self.audit()[0], [])

    def test_inflated_snapshot_value_caught(self):
        errs = self.tampered(lambda l, h, p: h["snapshots"][0].update(total_value=20000))
        self.assertTrue(any("total_value" in e for e in errs))

    def test_inflated_price_with_consistent_math_caught_by_portfolio_summary(self):
        def bump(l, h, p):
            s = h["snapshots"][0]
            s["prices"]["NVDA"]["price"] = 500.0
            s["holdings_value"] = 5000.0
            s["total_value"] = 13998.0
        errs = self.tampered(bump)
        self.assertTrue(any("return_pct" in e or "portfolio.json" in e for e in errs))

    def test_edited_trade_caught_by_hash(self):
        errs = self.tampered(lambda l, h, p: l["transactions"][0].update(quote_price=50.0))
        self.assertTrue(any("hash" in e for e in errs))

    def test_deleted_trade_caught(self):
        self.sell(shares=5, date="2026-10-14")
        errs = self.tampered(lambda l, h, p: l["transactions"].pop(0))
        self.assertTrue(errs)

    def test_cash_edit_caught(self):
        errs = self.tampered(lambda l, h, p: p.update(cash=50000))
        self.assertTrue(any("cash" in e for e in errs))

    def test_clear_requires_independent_source_and_close_price(self):
        with self.assertRaises(pf.TradeError):
            fc.cmd_clear_trade("T0001", 100.0, SRC, "")
        with self.assertRaises(pf.TradeError):
            fc.cmd_clear_trade("T0001", 103.0, SRC2, "")
        r = fc.cmd_clear_trade("T0001", 100.4, SRC2, "matches close")
        self.assertEqual(r["status"], "cleared")
        self.assertEqual(self.audit()[0], [])

    def test_forged_clear_caught(self):
        fc.cmd_clear_trade("T0001", 100.4, SRC2, "")
        errs = self.tampered(lambda l, h, p: l["transactions"][0]["fact_check"].update(verified_price=150))
        self.assertTrue(any("cleared" in e for e in errs))

    def test_clear_snapshot(self):
        with self.assertRaises(pf.TradeError):
            fc.cmd_clear_snapshot("2026-10-13", {"NVDA": {"price": 120, "source": SRC2}}, "")
        r = fc.cmd_clear_snapshot("2026-10-13", {"NVDA": {"price": 105.2, "source": SRC2}}, "")
        self.assertEqual(r["status"], "cleared")
        self.assertEqual(fc.pending_items(pf.load_ledger(), pf.load_history()), ["T0001"])


class RandomizedReplayTests(Base):
    def test_many_random_trades_always_audit_clean(self):
        import datetime as dt
        import random
        rng = random.Random(7)
        px = {"AAA": 12.3456, "BBB": 87.91, "CCC": 431.07}
        held = set()
        d = dt.date(2026, 7, 1)
        for _ in range(120):
            d += dt.timedelta(days=1)
            if d.weekday() >= 5:
                continue
            for t in px:
                px[t] = round(px[t] * (1 + rng.gauss(0, 0.04)), 6)
            ds = d.isoformat()
            if held and rng.random() < 0.4:
                t = rng.choice(sorted(held))
                pf.record_trade("SELL", t, px[t], SRC, TS, WHY, ds, self.cfg, sell_all=True)
                held.discard(t)
            cash = pf.replay(pf.load_ledger()["transactions"], self.cfg)["cash"]
            if cash > 50 and rng.random() < 0.5:
                t = rng.choice(sorted(px))
                pf.record_trade("BUY", t, px[t], SRC, TS, WHY, ds, self.cfg, amount=cash * rng.uniform(0.2, 1))
                held.add(t)
            st = pf.replay(pf.load_ledger()["transactions"], self.cfg)
            pf.mark({t: {"price": px[t], "source": SRC, "timestamp": TS} for t in st["positions"]}, ds, self.cfg)
        errors, _ = self.audit()
        self.assertEqual(errors, [])
        self.assertGreater(len(pf.load_ledger()["transactions"]), 20)


class RepoDataTests(unittest.TestCase):
    def test_committed_data_passes_audit(self):
        cfg = pf.load_config()
        errors, _ = fc.audit(cfg, pf.load_ledger(), pf.load_history(), pf.load_json(pf.PORTFOLIO_PATH, None))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
