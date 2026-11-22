import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

from test_autopilot_exec import NOW, PLAN, RISK, AutoMT5, Base, FakeExecutor, WiringTests
from test_mt5_send import LOGIN, PASSWORD, SERVER
from trading_pro import autopilot
from trading_pro.autopilot import Autopilot, AutopilotRunner
from trading_pro.autopilot_exec import Executor
from trading_pro.broker import MAGIC
from trading_pro.core import Limits, utcnow
from trading_pro.store import ResearchStore


class BasketMT5(AutoMT5):
    """A terminal where every fill is its own position (own ticket), and that can start failing after N fills."""

    def __init__(self, *, check_fails_after=None, send_none_after=None, **kw):
        super().__init__(**kw)
        self.next_ticket, self.fills = 7000, 0
        self.check_fails_after, self.send_none_after = check_fails_after, send_none_after

    def order_check(self, request):
        result = super().order_check(request)
        if "position" not in request and self.check_fails_after is not None and self.fills >= self.check_fails_after:
            return NS(retcode=10013, comment="invalid request", margin=0, margin_free=0, balance=self.equity)
        return result

    def order_send(self, request):
        if "position" in request:  # a closing deal: the position disappears
            self.sent.append(request)
            self.positions = [p for p in self.positions if p.ticket != request["position"]]
            return NS(retcode=10009, order=1, deal=2, volume=request["volume"])
        if self.send_none_after is not None and self.fills >= self.send_none_after:
            self.sent.append(request)
            return None
        self.fills += 1
        self.next_ticket += 1
        self.sent.append(request)
        self.positions.append(NS(ticket=self.next_ticket, type=request["type"], volume=request["volume"], price_open=request["price"],
                                 sl=request["sl"], tp=request["tp"], profit=0.0, swap=0.0, magic=request["magic"],
                                 symbol=request["symbol"], time=0, price_current=request["price"]))
        return NS(retcode=10009, order=self.next_ticket, deal=self.next_ticket + 1000, volume=request["volume"])

    def history_deals_get(self, *args, position=None):
        if position is None:
            return []
        return (NS(ticket=position + 1000, order=position, symbol="XAUUSD", magic=MAGIC, entry=0, profit=0.0),)

    def history_orders_get(self, ticket=None):
        return (NS(ticket=ticket, symbol="XAUUSD", magic=MAGIC),)


def basket_args(decision_id=None, **extra):
    return dict(decision_id=decision_id or str(uuid.uuid4()), symbol="XAUUSD", side="BUY", arm="det:graph", plan=PLAN,
                limits=Limits(), risk=RISK, ai_spend=0.0, offset_hours=0.0, now=utcnow(), halt=None, positions=4,
                target_usd=10.0, **extra)


class BasketExecutionTests(Base):
    def setUp(self):
        super().setUp()
        self.store.release_killed(author="t", reason="test")

    def open_basket(self, fake, **extra):
        return self.executor(fake).send_basket(self.store, **basket_args(**extra))

    def test_every_member_is_opened_with_its_own_stop_and_target_and_the_risk_is_one_positions(self):
        fake = BasketMT5()
        report = self.open_basket(fake)
        self.assertEqual((report["state"], report["members"]), ("open", 4))
        self.assertEqual(len(fake.positions), 4)
        self.assertEqual(len({p.ticket for p in fake.positions}), 4)
        self.assertTrue(all(p.sl > 0 and p.tp > 0 for p in fake.positions))  # same protection as a single order
        self.assertEqual(len({p.volume for p in fake.positions}), 1)  # identical members
        single = AutoMT5()
        self.send(single, decision_id="one")
        # four members together risk what one position risks (a little less: each volume is rounded down to the step)
        self.assertLessEqual(sum(p.volume for p in fake.positions), single.sent[0]["volume"] + 1e-9)
        self.assertGreaterEqual(sum(p.volume for p in fake.positions), single.sent[0]["volume"] - 4 * 0.01)
        rows = [r for r in self.store.open_orders() if r["basket_id"]]  # the single order sent above has none
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["basket_id"] for r in rows}, {report["basket_id"]})
        self.assertEqual(len({r["decision_id"] for r in rows}), 4)

    def test_a_basket_takes_one_slot_in_the_position_limit_not_one_per_member(self):
        fake = BasketMT5()
        self.open_basket(fake)
        self.store.record_order(decision_id="solo", symbol="XAUUSD", arm="det:graph", side="BUY", state="open", opened_at=NOW,
                                position_ticket=99)
        fake.positions.append(NS(ticket=99, magic=MAGIC, symbol="XAUUSD"))
        self.assertEqual(Executor._slots(fake.positions, self.store), 2)  # one basket + one single position

    def test_a_failing_member_cancels_the_basket_and_closes_what_was_opened(self):
        fake = BasketMT5(check_fails_after=2)
        report = self.open_basket(fake)
        self.assertEqual((report["state"], report["members"]), ("basket_cancelled", 2))
        self.assertEqual(fake.positions, [])  # the two opened members were closed at once
        self.assertFalse(self.store.killed())  # a refusal is not an emergency
        self.assertIn("basket_cancelled", [a["kind"] for a in self.store.recent("alerts")])
        self.assertIn("autopilot.basket_cancelled", [e["kind"] for e in self.store.journal.events(80)])

    def test_the_first_member_refused_is_a_plain_refusal(self):
        fake = BasketMT5()
        self.store.set_killed()
        report = self.open_basket(fake)
        self.assertEqual((report["state"], report["code"], report["members"]), ("refused", "stopped", 0))
        self.assertEqual((fake.sent, fake.positions), ([], []))

    def test_an_unknown_outcome_on_a_member_arms_the_emergency_stop_and_keeps_the_others(self):
        fake = BasketMT5(send_none_after=2)
        report = self.open_basket(fake)
        self.assertEqual((report["state"], report["members"]), ("basket_partial", 2))
        self.assertTrue(self.store.killed())
        self.assertEqual(len(fake.positions), 2)  # they keep their broker-side stop and target

    def test_the_same_decision_never_opens_two_baskets(self):
        fake = BasketMT5()
        decision = str(uuid.uuid4())
        self.assertEqual(self.open_basket(fake, decision_id=decision)["state"], "open")
        again = self.open_basket(fake, decision_id=decision)
        self.assertEqual((again["state"], again["code"]), ("refused", "duplicate"))
        self.assertEqual(len(fake.positions), 4)


class BasketWatchTests(Base):
    def make(self, profits, **extra):
        self.store.release_killed(author="t", reason="test")
        fake = BasketMT5()
        executor = self.executor(fake)
        report = executor.send_basket(self.store, **basket_args(**extra))
        for position, profit in zip(fake.positions, profits):
            position.profit = profit
        pilot = Autopilot(self.store, fetch=lambda *a: ([], {}), executor=executor, limits_provider=Limits,
                          risk_provider=lambda: RISK, clock=utcnow)
        return fake, executor, pilot, report

    def test_the_basket_closes_as_a_whole_when_its_total_reaches_the_target(self):
        fake, executor, pilot, report = self.make([1.0, 2.0, 3.0, 4.5])  # 10.5 >= 10
        closed = pilot.check_baskets(executor.positions_snapshot())
        self.assertEqual(closed, [report["basket_id"]])
        self.assertEqual(fake.positions, [])
        self.assertIn("autopilot.basket_target", [e["kind"] for e in self.store.journal.events(80)])

    def test_below_the_target_nothing_is_closed(self):
        fake, executor, pilot, _ = self.make([1.0, 2.0, 3.0, 3.9])  # 9.9
        self.assertEqual(pilot.check_baskets(executor.positions_snapshot()), [])
        self.assertEqual(len(fake.positions), 4)

    def test_money_already_booked_by_closed_members_counts_towards_the_target(self):
        fake, executor, pilot, report = self.make([2.0, 2.0, 2.0, 2.0])
        first = self.store.open_orders()[0]
        self.store.close_order(first["decision_id"], state="closed", profit=4.0, reason="stop", now=utcnow())
        fake.positions = [p for p in fake.positions if p.ticket != first["position_ticket"]]
        # 4.0 booked + 3 floating members of 2.0 = 10.0
        self.assertEqual(pilot.check_baskets(executor.positions_snapshot()), [report["basket_id"]])

    def test_an_opposite_signal_with_the_close_policy_closes_the_whole_basket(self):
        fake, executor, pilot, _ = self.make([1.0, 1.0, 1.0, 1.0])
        order = self.store.open_orders()[0]
        autopilot.set_config(self.store, {"symbols": ["XAUUSD"], "execution_arms": ["det:graph"], "opposite_signal_policy": "close"},
                             author="t")
        summary = {}
        rows = {"det:graph": {"action": "SELL", "decision_id": "x"}}
        pilot._opposite_signal("XAUUSD", order, rows, autopilot.get_config(self.store), summary, NOW)
        self.assertEqual(fake.positions, [])
        self.assertIn("closed", summary["conflict"])

    def test_the_status_lists_the_open_baskets_with_their_running_total(self):
        fake, executor, pilot, report = self.make([1.0, 1.0, 1.0, 1.0])
        self.store.state_set("autopilot_positions", json.dumps({"positions": executor.positions_snapshot()}))
        baskets = autopilot.status(self.store)["baskets"]
        self.assertEqual((len(baskets), baskets[0]["members"], baskets[0]["total"], baskets[0]["target_usd"]), (1, 4, 4.0, 10.0))


class BasketRoutingTests(unittest.TestCase):
    def run_cycle(self, basket):
        with tempfile.TemporaryDirectory() as temp:
            executor = FakeExecutor()
            executor.send_basket = lambda store, **kwargs: (executor.sent.append(("basket", kwargs)) or {"state": "open", "members": 20})
            store, pilot = WiringTests().make(temp, executor)
            autopilot.set_config(store, {"basket": basket}, author="t")
            autopilot.set_mode(store, "demo_auto", author="op", execution_available=True)
            result = pilot.run_symbol("XAUUSD")
            return executor.sent, result

    def test_a_basket_replaces_the_single_order_only_where_it_is_enabled(self):
        sent, result = self.run_cycle({"symbols": ["XAUUSD"], "enabled": True, "positions": 20, "target_usd": 50})
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "basket")
        self.assertEqual((sent[0][1]["positions"], sent[0][1]["target_usd"]), (20, 50.0))
        self.assertEqual(result["orders"], {"det:graph": "open"})
        sent, _ = self.run_cycle({"symbols": ["XAUUSD"], "enabled": False})  # off by default: the single order, as before
        self.assertEqual(len(sent), 1)
        self.assertNotIn("positions", sent[0])
        sent, _ = self.run_cycle({"symbols": ["Volatility 10 Index"], "enabled": True})  # another instrument: untouched
        self.assertNotIn("positions", sent[0])

    def test_the_basket_switch_is_off_by_default(self):
        self.assertFalse(autopilot.DEFAULT_CONFIG["basket"]["enabled"])


class MigrationTests(unittest.TestCase):
    def test_an_older_database_gains_the_basket_column_and_keeps_its_orders(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "old.db")
            db = sqlite3.connect(path)
            db.executescript("""CREATE TABLE auto_orders (
              decision_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, arm TEXT NOT NULL, side TEXT NOT NULL,
              volume REAL, ticket INTEGER, position_ticket INTEGER, entry REAL, stop_loss REAL, take_profit REAL,
              opened_at TEXT NOT NULL, max_age_seconds INTEGER, state TEXT NOT NULL, closed_at TEXT,
              profit REAL, close_reason TEXT, detail TEXT NOT NULL DEFAULT '{}');
              INSERT INTO auto_orders(decision_id,symbol,arm,side,opened_at,state) VALUES('old','XAUUSD','a','BUY','2026-01-01T00:00:00+00:00','closed');""")
            db.commit()
            db.close()
            store = ResearchStore(path)
            self.assertEqual(store.orders()[0]["decision_id"], "old")
            self.assertIsNone(store.orders()[0]["basket_id"])
            ResearchStore(path)  # opening it again is harmless


if __name__ == "__main__":
    unittest.main()
