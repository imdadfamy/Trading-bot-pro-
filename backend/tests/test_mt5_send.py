import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from trading_pro import us_events
from trading_pro.broker import MAGIC
from trading_pro.mt5_dryrun import DRY_RUN_ALLOWED
from trading_pro.mt5_send import (CLOSE_PHRASE, RELEASE_PHRASE, SEND_ALLOWED, SEND_PHRASE, Refusal, close_demo,
                                  send_supervised)
from trading_pro.mt5_status import ALLOWED, ReadOnlyMT5
from trading_pro.store import ResearchStore

LOGIN, SERVER, PASSWORD = 123456789, "Test-Demo", "s3cret-pass-word"
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
PHRASE = SEND_PHRASE.format(side="BUY", symbol="XAUUSD")


def calendar(extra=()):
    """Covers a year before and after the real today, so the tests never age out."""
    today = datetime.now(timezone.utc).date()
    bounds = ((today - timedelta(days=365)).isoformat(), (today + timedelta(days=365)).isoformat())
    events = [{"kind": k, "date": d, "time_et": "08:30"} for k in us_events.KINDS for d in bounds]
    return us_events.parse({"schema": 1, "retrieved_on": today.isoformat(), "events": events + list(extra)})


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 1, 0, 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC = 0, 1
    SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2
    SYMBOL_TRADE_MODE_FULL = 4
    TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL, TRADE_RETCODE_REJECT = 10009, 10010, 10006

    def __init__(self, *, algo=True, mode=0, check_code=0, send_code=10009, send_none=False, positions=None,
                 equity=10000.0, spread=0.29):
        self.algo, self.mode, self.check_code, self.send_code, self.send_none = algo, mode, check_code, send_code, send_none
        self.positions, self.equity, self.spread = positions or [], equity, spread
        self.calls, self.checked, self.sent = [], [], []

    def initialize(self, **kw): self.calls.append("initialize"); return True
    def shutdown(self): self.calls.append("shutdown")
    def last_error(self): return (0, "ok")
    def account_info(self): return NS(login=LOGIN, trade_mode=self.mode, equity=self.equity, balance=self.equity, trade_allowed=True)
    def terminal_info(self): return NS(connected=True, trade_allowed=self.algo)
    def symbol_select(self, name, enable): self.calls.append("symbol_select"); return True

    def symbol_info(self, name):
        return NS(name=name, visible=True, point=0.01, digits=2, volume_min=0.01, volume_max=10.0, volume_step=0.01,
                  filling_mode=1, trade_mode=4, trade_stops_level=20, trade_tick_size=0.01, trade_tick_value=1.0)

    def symbol_info_tick(self, name): return NS(time=0, bid=2000.0, ask=2000.0 + self.spread)
    def positions_get(self, symbol=None): return list(self.positions)

    def order_check(self, request):
        self.checked.append(request)
        return NS(retcode=self.check_code, comment="check", margin=4.6, margin_free=9990.0, balance=self.equity)

    def order_send(self, request):
        self.sent.append(request)
        if self.send_none:
            return None
        if self.send_code == 10009 and "position" in request:  # closing deal: the position disappears
            self.positions = [p for p in self.positions if p.ticket != request["position"]]
        elif self.send_code == 10009:
            self.positions.append(NS(ticket=555, type=0 if request["type"] == 0 else 1, volume=request["volume"],
                                     price_open=request["price"], sl=request["sl"], tp=request["tp"], profit=0.0,
                                     magic=request["magic"], symbol=request["symbol"]))
        return NS(retcode=self.send_code, order=777, deal=888, volume=request["volume"])

    def history_deals_get(self, position=None):  # by position, like the real terminal
        return ((NS(ticket=888, order=777, symbol="XAUUSD", magic=MAGIC),
                 NS(ticket=889, order=778, symbol="XAUUSD", magic=MAGIC))  # 778 = closing order, must be ignored
                if self.send_code == 10009 else ())
    def orders_get(self, ticket=None): return ()
    def history_orders_get(self, ticket=None): return (NS(ticket=777, symbol="XAUUSD", magic=MAGIC),)


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = ResearchStore(str(Path(self.folder.name) / "t.db"))

    def release(self):
        self.store.release_killed(author="tester", reason="unit test")
        self.assertFalse(self.store.killed())

    def send(self, fake, **kw):
        options = dict(symbol="XAUUSD", side="BUY", confirm=PHRASE, expected_login=LOGIN, server=SERVER,
                       password=PASSWORD, commission=0.0, slippage_ticks=2.0, calendar=calendar())
        options.update(kw)
        return send_supervised(fake, self.store, **options)

    def kinds(self):
        return [e["kind"] for e in self.store.journal.events(50)]


class RefusalTests(Base):
    def test_wrong_or_missing_phrase_touches_nothing(self):
        self.release()
        fake = FakeMT5()
        for phrase in ("", "envoyer", SEND_PHRASE.format(side="SELL", symbol="XAUUSD"), PHRASE + " "):
            with self.assertRaises(Refusal):
                self.send(fake, confirm=phrase)
        self.assertEqual((fake.calls, fake.sent), ([], []))
        self.assertFalse(self.store.killed())  # refused before anything: the release is not consumed

    def test_stop_on_entries_blocks_everything_before_the_terminal_is_contacted(self):
        fake = FakeMT5()
        with self.assertRaisesRegex(Refusal, "stop on new entries is active"):
            self.send(fake)
        self.assertEqual((fake.calls, fake.sent), ([], []))

    def test_announcement_window_and_an_expired_calendar_block_and_consume_the_release(self):
        self.release()
        fake = FakeMT5()
        inside = calendar([{"kind": "NFP", "date": "2026-11-18", "time_et": "07:15"}])  # 12:15 UTC, window 11:45 to 13:15
        with self.assertRaisesRegex(Refusal, "Caution window.*NFP"):
            self.send(fake, calendar=inside, now=NOW)
        self.assertTrue(self.store.killed())  # any attempt re-arms the stop
        self.release()
        with self.assertRaisesRegex(Refusal, "missing or expired"):
            self.send(fake, now=datetime(2030, 1, 1, tzinfo=timezone.utc))
        self.assertEqual((fake.calls, fake.sent), ([], []))
        self.assertTrue(self.store.killed())

    def test_trading_algo_off_and_open_position_stop_before_any_order(self):
        for fake, text in ((FakeMT5(algo=False), "Trading algo"), (FakeMT5(positions=[NS(ticket=1)]), "already open")):
            self.release()
            with self.assertRaisesRegex(Refusal, text):
                self.send(fake)
            self.assertEqual((fake.checked, fake.sent), ([], []))
            self.assertTrue(self.store.killed())
            self.assertEqual(fake.calls[-1], "shutdown")

    def test_real_account_is_refused_and_the_stop_is_rearmed(self):
        self.release()
        fake = FakeMT5(mode=2)
        with self.assertRaisesRegex(RuntimeError, "not DEMO"):
            self.send(fake)
        self.assertEqual(fake.sent, [])
        self.assertTrue(self.store.killed())

    def test_risk_engine_veto_stops_before_the_broker_is_asked(self):
        self.release()
        fake = FakeMT5(spread=2.0)  # spread far above the engine's 0.5 default limit
        with self.assertRaisesRegex(Refusal, "Risk engine refused.*Spread"):
            self.send(fake)
        self.assertEqual((fake.checked, fake.sent), ([], []))

    def test_unreasonable_parameters_are_refused(self):
        self.release()
        for kw in ({"commission": -1}, {"risk_fraction": 0.5}, {"stop_multiple": 1.0}, {"side": "HOLD"}):
            with self.assertRaises(Refusal):
                self.send(FakeMT5(), **kw)


class NominalTests(Base):
    def test_one_minimal_order_with_protection_then_reconciliation_and_rearm(self):
        self.release()
        fake = FakeMT5()
        report = self.send(fake, risk_fraction=0.02)  # risk capacity far above the minimum volume
        self.assertEqual(len(fake.sent), 1)
        order = fake.sent[0]
        self.assertEqual((order["volume"], order["type_filling"], order["magic"]), (0.01, fake.ORDER_FILLING_FOK, MAGIC))
        self.assertAlmostEqual(order["price"] - order["sl"], 3 * (0.20 + 0.29), places=6)  # 3 x (level + spread)
        self.assertGreaterEqual(2000.0 - order["sl"], 0.20)  # and beyond the broker minimum from the closing price (bid)
        self.assertGreater(order["tp"], order["price"])
        self.assertEqual(fake.sent[0], fake.checked[-1])  # the exact request the broker validated
        self.assertTrue(report["order_sent"] and report["intent_state"] == "accepted")
        self.assertEqual(report["reconciliation"]["status"], "deals_observed")
        self.assertEqual(report["open_positions"][0]["ticket"], 555)
        self.assertTrue(self.store.killed() and report["kill_switch_rearmed"])
        kinds = self.kinds()
        self.assertTrue({"order.reserved", "order.result", "risk.kill_switch_released", "risk.kill_switch"} <= set(kinds))
        self.assertTrue(self.store.journal.verify_audit())
        self.assertNotIn(PASSWORD, json.dumps(report, default=str))
        self.assertIn("mt5-close-demo", report["next"])

    def test_a_second_attempt_needs_a_new_release(self):
        self.release()
        self.send(FakeMT5())
        with self.assertRaisesRegex(Refusal, "stop on new entries is active"):
            self.send(FakeMT5())

    def test_broker_rejection_is_recorded_not_retried(self):
        self.release()
        fake = FakeMT5(send_code=10006)
        report = self.send(fake)
        self.assertEqual((len(fake.sent), report["intent_state"], report["order_sent"]), (1, "rejected", True))
        self.assertTrue(self.store.killed())

    def test_failed_order_check_means_no_order_was_sent(self):
        self.release()
        fake = FakeMT5(check_code=10016)
        report = self.send(fake)
        self.assertEqual(fake.sent, [])
        self.assertEqual((report["intent_state"], report["order_sent"]), ("preflight_rejected", False))
        self.assertIn("order_check rejected", report["error"])

    def test_unknown_outcome_is_flagged_uncertain_with_a_warning(self):
        self.release()
        fake = FakeMT5(send_none=True)
        report = self.send(fake)
        self.assertEqual((report["intent_state"], report["order_sent"]), ("uncertain", True))
        self.assertIn("Never resend", report["warning"])
        self.assertTrue(self.store.killed())
        self.assertEqual(len(self.store.journal.pending_intents()), 1)  # appears in the manual review list


class CloseTests(Base):
    def position(self, ticket=555, magic=MAGIC, kind=0):
        return NS(ticket=ticket, type=kind, volume=0.01, price_open=2000.3, sl=1998, tp=2004, profit=-0.1, magic=magic)

    def close(self, fake, **kw):
        options = dict(symbol="XAUUSD", confirm=CLOSE_PHRASE.format(symbol="XAUUSD"), expected_login=LOGIN,
                       server=SERVER, password=None)
        options.update(kw)
        return close_demo(fake, self.store, **options)

    def test_needs_the_phrase_and_trading_algo(self):
        fake = FakeMT5(positions=[self.position()])
        with self.assertRaises(Refusal):
            self.close(fake, confirm="fermer")
        with self.assertRaisesRegex(Refusal, "Trading algo"):
            self.close(FakeMT5(algo=False, positions=[self.position()]))
        self.assertEqual(fake.sent, [])

    def test_closes_only_this_projects_positions_and_works_while_the_stop_is_active(self):
        self.assertTrue(self.store.killed())
        fake = FakeMT5(positions=[self.position(555), self.position(556, magic=42), self.position(557, kind=1)])
        report = self.close(fake)
        self.assertEqual([c["ticket"] for c in report["closed"]], [555, 557])
        long, short = fake.sent
        self.assertEqual((long["position"], long["type"], long["price"]), (555, fake.ORDER_TYPE_SELL, 2000.0))
        self.assertEqual((short["position"], short["type"], short["price"]), (557, fake.ORDER_TYPE_BUY, 2000.29))
        self.assertTrue(all(r["magic"] == MAGIC and r["type_filling"] == fake.ORDER_FILLING_FOK for r in fake.sent))
        self.assertEqual(self.kinds().count("order.closed"), 2)
        self.assertTrue(self.store.killed())  # closing never lifts the stop

    def test_nothing_to_close_and_broker_refusal(self):
        self.assertEqual(self.close(FakeMT5())["orders_sent"], 0)
        refused = FakeMT5(positions=[self.position()], check_code=10018)
        report = self.close(refused)
        self.assertEqual((report["closed"][0]["status"], refused.sent, report["orders_sent"]), ("refused_by_broker_check", [], 0))


class CommandAndWrapperTests(Base):
    def run_cli(self, *argv):
        from trading_pro import cli
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["cli", "--database", str(Path(self.folder.name) / "c.db"), *argv]), \
                mock.patch("trading_pro.local_env.load_local_env", return_value=()), \
                contextlib.redirect_stdout(out):
            cli.main()
        return json.loads(out.getvalue())

    def test_kill_switch_command_release_needs_phrase_and_reason_and_is_audited(self):
        self.assertTrue(self.run_cli("kill-switch", "status")["kill_switch_active"])
        for argv in (("kill-switch", "release"), ("kill-switch", "release", "--confirm", "oui", "--reason", "x"),
                     ("kill-switch", "release", "--confirm", RELEASE_PHRASE)):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.run_cli(*argv)
        self.assertTrue(self.run_cli("kill-switch", "status")["kill_switch_active"])
        released = self.run_cli("kill-switch", "release", "--confirm", RELEASE_PHRASE, "--reason", "essai supervisé")
        self.assertFalse(released["kill_switch_active"])
        self.assertTrue(self.run_cli("kill-switch", "activate")["kill_switch_active"])
        events = [e["kind"] for e in ResearchStore(str(Path(self.folder.name) / "c.db")).journal.events(20)]
        self.assertIn("risk.kill_switch_released", events)

    def test_send_command_without_the_exact_phrase_never_reaches_the_terminal(self):
        with mock.patch.dict("os.environ", {"TIP_MT5_DEMO_LOGIN": "1", "TIP_MT5_DEMO_SERVER": "S"}, clear=True), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli("mt5-send-demo", "XAUUSD", "--side", "BUY", "--confirm", "oui", "--commission", "0",
                         "--slippage-ticks", "0")

    def test_only_the_supervised_module_can_reach_order_send(self):
        for allowed in (ALLOWED, DRY_RUN_ALLOWED):
            self.assertNotIn("order_send", allowed)
            with self.assertRaises(PermissionError):
                ReadOnlyMT5(FakeMT5(), allowed).order_send
        self.assertIn("order_send", SEND_ALLOWED)
        self.assertNotIn("position_close_by", SEND_ALLOWED)  # nothing else that changes the account


if __name__ == "__main__":
    unittest.main()
