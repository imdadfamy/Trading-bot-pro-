import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from trading_pro.agents import graph_agent, news_agent, quant_agent, risk_agent
from trading_pro.broker import DemoBroker, MT5DemoBroker, execute_demo, reconcile_demo_ticket
from trading_pro.core import Action, Director, Instrument, Limits, Report, RiskState, Signal, Snapshot, check_risk, utcnow
from trading_pro.journal import Journal


class SafetyTests(unittest.TestCase):
    def setUp(self):
        now = utcnow()
        self.quote = Snapshot("cycle", "XAUUSD", 2000, 2000.1, now)
        self.signal = Signal("id", "cycle", "XAUUSD", Action.BUY, now, now+timedelta(minutes=1),
                             "baseline", "1", "test", 2000.1, 1999.1, 2002, status="validated")
        self.instrument = Instrument(.01, 1, .01, 10, .01, 7, 2)
        self.state = RiskState(10000, 10000, killed=False, broker_connected=True, demo_account=True)

    def check(self, signal=None, quote=None, state=None, instrument=None):
        return check_risk(signal or self.signal, quote or self.quote,
                          instrument or self.instrument, state or self.state, Limits())

    def test_wait_and_real_account_blocked(self):
        self.assertFalse(self.check(signal=replace(self.signal, action=Action.WAIT)).approved)
        self.assertFalse(self.check(state=replace(self.state, demo_account=False)).approved)
        self.assertFalse(self.check(state=replace(self.state, killed=True)).approved)

    def test_stale_event_spread_budget_loss_exposure(self):
        self.assertFalse(self.check(quote=replace(self.quote, observed_at=utcnow()-timedelta(seconds=10))).approved)
        self.assertFalse(self.check(quote=replace(self.quote, critical_event=True)).approved)
        self.assertFalse(self.check(quote=replace(self.quote, ask=2001)).approved)
        self.assertFalse(self.check(state=replace(self.state, ai_spend=50)).approved)
        self.assertFalse(self.check(state=replace(self.state, equity=9700)).approved)
        self.assertFalse(self.check(state=replace(self.state, open_positions=2)).approved)

    def test_minimum_lot_and_invalid_stop(self):
        self.assertFalse(self.check(instrument=Instrument(.01, 1000, .01, 10, .01, 7, 2)).approved)
        self.assertFalse(self.check(instrument=Instrument(.01, 1, .01, 10, .01)).approved)
        self.assertFalse(self.check(signal=replace(self.signal, stop_loss=2001)).approved)

    def test_size_rounds_down(self):
        decision = self.check()
        self.assertTrue(decision.approved)
        self.assertLessEqual(decision.volume, .5)

    def test_director_abstains_without_independent_agreement(self):
        reports = [graph_agent([2000+i for i in range(20)]), news_agent(self.quote),
                   quant_agent([2000]*30), risk_agent()]
        self.assertEqual(Director().decide(self.quote, reports).action, Action.WAIT)

    def test_idempotent_durable_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(str(Path(tmp)/"db.sqlite"))
            decision = self.check()
            result = execute_demo(self.signal, decision, self.quote, DemoBroker(), journal)
            self.assertEqual(result["status"], "simulated")
            with self.assertRaises(RuntimeError):
                execute_demo(self.signal, decision, self.quote, DemoBroker(), Journal(journal.path))

    def test_unknown_send_is_never_retried(self):
        class TimedOut(DemoBroker):
            def send(self, signal, volume, quote):
                raise TimeoutError("outcome unknown")
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(str(Path(tmp)/"db.sqlite"))
            with self.assertRaises(TimeoutError):
                execute_demo(self.signal, self.check(), self.quote, TimedOut(), journal)
            self.assertEqual(journal.intent("id")["state"], "uncertain")
            with self.assertRaises(RuntimeError):
                execute_demo(self.signal, self.check(), self.quote, DemoBroker(), journal)

    def test_preflight_failure_does_not_claim_unknown_send(self):
        class Rejected(DemoBroker):
            def preflight(self, signal, volume, quote):
                return False
            def send(self, *args):
                self.fail("send must not run")
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(str(Path(tmp)/"db.sqlite"))
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                execute_demo(self.signal, self.check(), self.quote, Rejected(), journal)
            self.assertEqual(journal.intent("id")["state"], "preflight_rejected")
            with self.assertRaises(RuntimeError):
                execute_demo(self.signal, self.check(), self.quote, DemoBroker(), journal)

    def test_reconciliation_requires_known_ticket_and_demo_account(self):
        class ReadOnlyMT5:
            ACCOUNT_TRADE_MODE_DEMO = 0
            def __init__(self):
                self.mode = 0
                self.trade_allowed = True
                self.deals = ()
                self.orders = ()
                self.history = ()
            def account_info(self):
                return type("Account", (), {"trade_mode": self.mode, "login": 111})()
            def terminal_info(self):
                return type("Terminal", (), {"connected": True, "trade_allowed": self.trade_allowed})()
            def history_deals_get(self, *, ticket):
                return self.deals
            def orders_get(self, *, ticket):
                return self.orders
            def history_orders_get(self, *, ticket):
                return self.history
        mt5 = ReadOnlyMT5()
        broker = MT5DemoBroker(mt5)
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(str(Path(tmp)/"db.sqlite"))
            journal.reserve("id", {"volume": .1})
            journal.transition_intent("id", {"reserved"}, "sending")
            journal.transition_intent("id", {"sending"}, "uncertain")
            with self.assertRaisesRegex(RuntimeError, "Unknown MT5 ticket"):
                reconcile_demo_ticket(self.signal, broker, journal, expected_account_login=111)
            self.assertEqual(len(journal.pending_intents()), 1)
            journal.reserve("known", {"volume": .1})
            journal.transition_intent("known", {"reserved"}, "sending")
            journal.transition_intent("known", {"sending"}, "accepted", ticket=123)
            known = replace(self.signal, signal_id="known")
            self.assertEqual(reconcile_demo_ticket(known, broker, journal, expected_account_login=111)["status"], "unresolved")
            self.assertEqual(journal.intent("known")["state"], "accepted")
            mt5.deals = (type("Deal", (), {"ticket": 456, "order": 123, "symbol": "XAUUSD", "magic": 26001118})(),)
            mt5.mode = 2
            with self.assertRaisesRegex(RuntimeError, "DEMO"):
                reconcile_demo_ticket(known, broker, journal, expected_account_login=111)
            mt5.mode = 0
            mt5.trade_allowed = False  # read-only reconciliation must remain available
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                reconcile_demo_ticket(known, broker, journal, expected_account_login=222)
            self.assertEqual(reconcile_demo_ticket(known, broker, journal, expected_account_login=111)["status"], "deals_observed")
            self.assertEqual(journal.intent("known")["state"], "deals_observed")
            with self.assertRaises(ValueError):
                journal.transition_intent("known", {"deals_observed"}, "sending")

    def test_mt5_partial_is_not_reported_as_complete(self):
        class PartialMT5:
            ACCOUNT_TRADE_MODE_DEMO = 0
            TRADE_ACTION_DEAL = ORDER_TYPE_BUY = ORDER_TYPE_SELL = 1
            ORDER_TIME_GTC = ORDER_FILLING_IOC = 1
            ORDER_FILLING_FOK = 0
            TRADE_RETCODE_DONE = 10009
            TRADE_RETCODE_DONE_PARTIAL = 10010
            TRADE_RETCODE_REJECT = 10006
            def account_info(self):
                return type("Account", (), {"trade_mode": 0})()
            def terminal_info(self):
                return type("Terminal", (), {"connected": True, "trade_allowed": True})()
            def symbol_info(self, symbol):
                return type("Info", (), {"visible": True, "point": .01, "volume_min": .01, "volume_max": 10,
                                         "volume_step": .01, "filling_mode": 1, "trade_mode": 4,
                                         "trade_stops_level": 0})()
            def symbol_info_tick(self, symbol):
                return type("Tick", (), {"ask": 2000.1, "bid": 2000})()
            def order_check(self, request):
                return type("Check", (), {"retcode": 0})()
            def order_send(self, request):
                return type("Result", (), {"retcode": 10010, "order": 123, "deal": 456, "volume": .05})()
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(str(Path(tmp)/"db.sqlite"))
            result = execute_demo(self.signal, self.check(), self.quote,
                                  MT5DemoBroker(PartialMT5(), demo_execution_enabled=True), journal)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(journal.intent("id")["state"], "partial")
            self.assertEqual(journal.intent("id")["broker_ticket"], "123")
        with self.assertRaisesRegex(RuntimeError, "disabled by default"):
            MT5DemoBroker(PartialMT5()).send(self.signal, .1, self.quote)

    def test_execution_snapshot_rechecked_before_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(str(Path(tmp)/"db.sqlite"))
            with self.assertRaisesRegex(ValueError, "Expired"):
                execute_demo(self.signal, self.check(),
                             replace(self.quote, observed_at=utcnow()-timedelta(seconds=10)),
                             DemoBroker(), journal)
            self.assertIsNone(journal.intent("id"))

    def test_mt5_live_mode_veto_even_if_other_flags_are_valid(self):
        class LiveMT5:
            ACCOUNT_TRADE_MODE_DEMO = 0
            def account_info(self):
                return type("Account", (), {"trade_mode": 2})()
        with self.assertRaisesRegex(RuntimeError, "DEMO"):
            MT5DemoBroker(LiveMT5()).preflight(self.signal, .1, self.quote)

    def test_audit_chain_detects_local_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(str(Path(tmp)/"db.sqlite"))
            journal.log("test", "one", {"status": "original"})
            journal.log("test", "two", {"status": "original"})
            self.assertTrue(journal.verify_audit())
            with journal.connect() as db:
                db.execute("UPDATE audit SET payload='{}' WHERE seq=1")
            self.assertFalse(journal.verify_audit())


if __name__ == "__main__":
    unittest.main()
