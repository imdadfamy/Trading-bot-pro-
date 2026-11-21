import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

from test_mt5_send import FakeMT5, LOGIN, SERVER, PASSWORD
from trading_pro import autopilot
from trading_pro.autopilot import Autopilot, AutopilotRunner
from trading_pro.autopilot_exec import Executor
from trading_pro.broker import MAGIC
from trading_pro.core import Limits, utcnow
from trading_pro.store import ResearchStore

PLAN = {"stop_distance": 3.0, "reward_multiple": 2.0, "horizon_bars": 48, "max_age_seconds": 4 * 3600}
RISK = {"fixed_lot": None, "commission_per_lot": 0.0, "slippage_ticks": 2.0}


class AutoMT5(FakeMT5):
    """The shared fake terminal, made realistic enough for the automatic path."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.day_deals, self.position_deals, self.tick_age = [], {}, 0.0

    def symbol_info_tick(self, name):
        return NS(time=int(datetime.now(timezone.utc).timestamp() - self.tick_age), bid=2000.0, ask=2000.0 + self.spread)

    def order_send(self, request):
        result = super().order_send(request)
        if result is not None and "position" not in request and self.positions and result.retcode == 10009:
            self.positions[-1].ticket = result.order  # the position id is the order ticket of a market order
        return result

    def history_deals_get(self, *args, position=None):
        if position is None:
            return list(self.day_deals)
        if position in self.position_deals:
            return list(self.position_deals[position])
        return super().history_deals_get(position=position)


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = ResearchStore(str(Path(self.folder.name) / "t.db"))
        self.store.release_killed(author="t", reason="test")

    def executor(self, fake):
        return Executor(fake, LOGIN, SERVER, PASSWORD)

    def send(self, fake, *, decision_id="d1", limits=None, risk=None, halt=None, side="BUY", ai_spend=0.0):
        return self.executor(fake).send(self.store, decision_id=decision_id, symbol="XAUUSD", side=side, arm="skills:director",
                                        plan=PLAN, limits=limits or Limits(), risk=risk or RISK, ai_spend=ai_spend,
                                        offset_hours=0.0, now=utcnow(), halt=halt, rationale="test")

    def kinds(self):
        return [e["kind"] for e in self.store.journal.events(80)]

    def order(self, decision_id="d1"):
        return next(o for o in self.store.orders() if o["decision_id"] == decision_id)


class SendTests(Base):
    def test_a_nominal_order_has_risk_sized_volume_protection_and_a_journaled_signal(self):
        fake = AutoMT5()
        report = self.send(fake)
        self.assertEqual(report["state"], "open")
        self.assertEqual(len(fake.sent), 1)
        request = fake.sent[0]
        self.assertEqual(request["magic"], MAGIC)
        self.assertEqual(request["volume"], 0.16)  # 0.5% of 10 000 over 302 ticks of risk, rounded down
        self.assertAlmostEqual(request["price"] - request["sl"], 3.0, places=2)
        self.assertAlmostEqual(request["tp"] - request["price"], 6.0, places=2)
        self.assertEqual(len(fake.checked), 2)  # preflight and the check just before sending
        row = self.order()
        self.assertEqual((row["state"], row["position_ticket"], row["max_age_seconds"]), ("open", 777, 4 * 3600))
        self.assertIn("autopilot.order_sent", self.kinds())
        self.assertIn("signal.created", self.kinds())  # every order is tied to a journaled signal
        self.assertTrue(self.store.journal.verify_audit())
        self.assertEqual(fake.calls[-1], "shutdown")

    def test_the_broker_minimum_distance_overrides_a_stop_that_is_too_tight(self):
        fake = AutoMT5(spread=0.29)
        self.executor(fake).send(self.store, decision_id="tight", symbol="XAUUSD", side="SELL", arm="a",
                                 plan={**PLAN, "stop_distance": 0.05}, limits=Limits(), risk=RISK, ai_spend=0,
                                 offset_hours=0.0, now=utcnow(), halt=None)
        request = fake.sent[0]
        self.assertGreaterEqual(request["sl"] - request["price"], 0.7)  # 1.5 x (stop level 0.20 + spread 0.29)

    def test_each_safeguard_refuses_before_order_send(self):
        self.store.set_killed()
        blocked = AutoMT5()
        stopped = self.send(blocked, decision_id="stopped")
        self.assertEqual((stopped["state"], stopped["code"], blocked.sent, blocked.calls), ("refused", "stopped", [], []))
        self.store.release_killed(author="t", reason="again")
        cases = [
            ("announcement", AutoMT5(), {"halt": "Scheduled US announcement: NFP"}),
            ("trading_algo_off", AutoMT5(algo=False), {}),
            ("position_open", AutoMT5(positions=[NS(ticket=9, type=0, volume=0.1, price_open=2000, sl=1990, tp=2010,
                                                    profit=0, magic=MAGIC, symbol="XAUUSD")]), {}),
            ("stale_quote", self.stale(), {}),
            ("risk", AutoMT5(spread=5.0), {}),  # spread above the limit
            ("risk", AutoMT5(), {"ai_spend": 1e6}),  # the risk engine's budget rule still applies
        ]
        for index, (code, fake, kwargs) in enumerate(cases):
            report = self.send(fake, decision_id=f"r{index}", **kwargs)
            self.assertEqual((report["state"], report["code"]), ("refused", code), code)
            self.assertEqual(fake.sent, [], code)
        refused = [e for e in self.store.journal.events(80) if e["kind"] == "autopilot.order_refused"]
        self.assertEqual(len(refused), len(cases) + 1)

    def test_a_zero_spread_limit_means_ten_percent_of_the_stop_whatever_the_price_scale(self):
        ok = AutoMT5(spread=0.29)  # 0.29 is under 10% of the 3.0 stop
        self.assertEqual(self.send(ok, decision_id="a1", limits=Limits(max_spread=0.0))["state"], "open")
        costly = AutoMT5(spread=0.45)
        report = self.send(costly, decision_id="a2", limits=Limits(max_spread=0.0))
        self.assertEqual((report["state"], report["code"]), ("refused", "risk"))
        self.assertIn("Spread too wide", report["message"])
        self.assertEqual(costly.sent, [])

    def stale(self):
        fake = AutoMT5()
        fake.tick_age = 120
        return fake

    def test_a_demo_check_failure_and_a_real_account_never_reach_the_market(self):
        real = AutoMT5(mode=2)
        report = self.send(real, decision_id="real")
        self.assertEqual(report["state"], "refused")
        self.assertEqual(real.sent, [])
        rejected = AutoMT5(check_code=10016)
        report = self.send(rejected, decision_id="rej")
        self.assertEqual((report["state"], report["code"]), ("refused", "broker"))
        self.assertEqual(rejected.sent, [])

    def test_daily_loss_and_aggregate_exposure_are_measured_from_the_account(self):
        fake = AutoMT5(equity=9700.0)  # balance = equity here; 3% were realised today
        today = int(datetime.now(timezone.utc).timestamp())
        fake.day_deals = [NS(type=1, time=today, profit=-300.0, commission=0.0, swap=0.0)]
        report = self.send(fake, decision_id="loss")
        self.assertEqual((report["state"], report["code"]), ("refused", "risk"))
        self.assertIn("Daily loss limit", report["message"])
        self.assertEqual(fake.sent, [])
        crowded = AutoMT5(positions=[NS(ticket=i, type=0, volume=0.1, price_open=2000, sl=1990, tp=2010, profit=0,
                                        magic=MAGIC, symbol=f"S{i}") for i in (1, 2)])
        crowded.symbol_info = lambda name: NS(name=name, visible=True, point=0.01, digits=2, volume_min=0.01, volume_max=10.0,
                                              volume_step=0.01, filling_mode=1, trade_mode=4, trade_stops_level=20,
                                              trade_tick_size=0.01, trade_tick_value=1.0)
        report = self.send(crowded, decision_id="crowd")
        self.assertEqual((report["state"], report["code"]), ("refused", "risk"))
        self.assertIn("Aggregate exposure", report["message"])

    def test_a_fixed_lot_replaces_the_computed_volume_but_never_the_risk_capacity(self):
        fake = AutoMT5()
        report = self.send(fake, decision_id="f1", risk={**RISK, "fixed_lot": 0.05})
        self.assertEqual(report["state"], "open")
        self.assertEqual(fake.sent[0]["volume"], 0.05)
        huge = AutoMT5()
        report = self.send(huge, decision_id="f2", risk={**RISK, "fixed_lot": 5.0})
        self.assertEqual((report["state"], report["code"]), ("refused", "fixed_lot"))
        self.assertEqual(huge.sent, [])

    def test_an_uncertain_outcome_arms_the_stop_raises_an_alert_and_is_never_resent(self):
        fake = AutoMT5(send_none=True)
        report = self.send(fake, decision_id="u1")
        self.assertEqual(report["state"], "uncertain")
        self.assertTrue(self.store.killed())
        self.assertEqual(self.store.recent("alerts")[0]["kind"], "order_uncertain")
        self.assertIn("autopilot.order_uncertain", self.kinds())
        again = self.send(fake, decision_id="u1")  # the stop is active now, and the intent is reserved anyway
        self.assertEqual(again["state"], "refused")
        self.assertEqual(len(fake.sent), 1)

    def test_a_position_without_protection_is_closed_and_stops_new_entries(self):
        fake = AutoMT5()
        original = fake.order_send

        def unprotected(request):
            result = original(request)
            if "position" not in request:
                fake.positions[-1].sl = 0.0
            return result
        fake.order_send = unprotected
        report = self.send(fake, decision_id="p1")
        self.assertEqual(report["state"], "closed_unprotected")
        self.assertTrue(self.store.killed())
        self.assertEqual(self.store.recent("alerts")[0]["kind"], "position_unprotected")
        self.assertEqual(len(fake.sent), 2)  # the order and the safety close
        self.assertIn("position", fake.sent[1])
        self.assertEqual(fake.positions, [])


class SynthMT5(AutoMT5):
    """Boom 500 as measured on the demo account: contract size 1, one dollar per lot per price unit, minimum lot 0.2."""

    def symbol_info(self, name):
        return NS(name=name, visible=True, point=0.001, digits=3, volume_min=0.2, volume_max=190.0, volume_step=0.01,
                  filling_mode=1, trade_mode=4, trade_stops_level=1173, trade_tick_size=0.001, trade_tick_value=0.001)

    def symbol_info_tick(self, name):
        return NS(time=int(datetime.now(timezone.utc).timestamp()), bid=5643.884, ask=5643.884 + self.spread)


class InstrumentScaleTests(Base):
    def boom(self, side, plan_stop=12.0, **kw):
        fake = SynthMT5(spread=0.528, **kw)
        report = self.executor(fake).send(self.store, decision_id=f"b-{side}", symbol="Boom 500 Index", side=side, arm="a",
                                          plan={**PLAN, "stop_distance": plan_stop}, limits=Limits(max_spread=0.0),
                                          risk=RISK, ai_spend=0, offset_hours=0.0, now=utcnow(), halt=None)
        return fake, report

    def test_the_same_risk_gives_a_large_lot_on_a_cheap_point_and_a_small_one_on_gold(self):
        gold = AutoMT5()
        self.send(gold, decision_id="g")
        boom, report = self.boom("BUY")
        self.assertEqual(report["state"], "open")
        self.assertEqual(gold.sent[0]["volume"], 0.16)
        self.assertAlmostEqual(boom.sent[0]["volume"], 4.16, places=2)  # 50 dollars over 12 price units at 1 dollar each
        self.assertGreater(boom.sent[0]["volume"], 0.2)  # far above the minimum lot: it is never the binding constraint

    def test_on_the_side_a_spike_runs_against_the_lot_is_smaller_to_cover_a_jumped_stop(self):
        favourable, _ = self.boom("BUY")   # a spike up helps a buy on Boom
        adverse, _ = self.boom("SELL")     # ...and hurts a sell
        self.assertLess(adverse.sent[0]["volume"], favourable.sent[0]["volume"])
        self.assertAlmostEqual(adverse.sent[0]["volume"], favourable.sent[0]["volume"] / 1.5, delta=0.05)

    def test_a_cheap_instrument_is_not_refused_for_its_minimum_lot_or_its_spread_once_the_stop_fits_the_cost(self):
        fake, report = self.boom("SELL", plan_stop=11.3)  # the spike stop of Boom 500: spread 0.528 is under 10% of it
        self.assertEqual(report["state"], "open")
        self.assertGreaterEqual(fake.sent[0]["volume"], 0.2)


class ReconcileTests(Base):
    def open_one(self, fake, decision_id="d1"):
        self.send(fake, decision_id=decision_id)
        return fake.positions[0]

    def test_a_closed_position_is_booked_with_its_net_result_and_reason(self):
        fake = AutoMT5()
        position = self.open_one(fake)
        fake.positions = []
        fake.position_deals[position.ticket] = [
            NS(ticket=1, entry=0, profit=0.0, commission=-1.0, swap=0.0, reason=3),
            NS(ticket=2, entry=1, profit=24.5, commission=-1.0, swap=-0.5, reason=5)]
        result = self.executor(fake).reconcile(self.store, now=utcnow())
        self.assertEqual(result["closed"], 1)
        row = self.order()
        self.assertEqual((row["state"], row["profit"], row["close_reason"]), ("closed", 22.0, "objectif"))
        self.assertIn("autopilot.order_closed", self.kinds())
        self.assertEqual(self.store.order_summary()["net_profit"], 22.0)
        self.assertEqual(self.executor(fake).reconcile(self.store, now=utcnow())["checked"], 0)

    def test_a_position_that_outlived_its_horizon_is_closed_at_market(self):
        fake = AutoMT5()
        self.open_one(fake)
        later = utcnow() + timedelta(hours=5)
        self.executor(fake).reconcile(self.store, now=later)
        self.assertEqual(len(fake.sent), 2)
        self.assertIn("position", fake.sent[1])
        fresh = AutoMT5()
        self.open_one(fresh, "d2")
        self.executor(fresh).reconcile(self.store, now=utcnow() + timedelta(hours=1))
        self.assertEqual(len(fresh.sent), 1)  # inside its horizon: left to its broker-side stop and target

    def test_an_order_that_disappears_without_a_deal_raises_an_alert_after_a_delay(self):
        fake = AutoMT5()
        self.open_one(fake)
        fake.positions = []
        fake.position_deals[777] = []
        self.executor(fake).reconcile(self.store, now=utcnow() + timedelta(minutes=2))
        self.assertEqual(self.order()["state"], "open")  # too early to conclude
        self.executor(fake).reconcile(self.store, now=utcnow() + timedelta(minutes=20))
        self.assertEqual(self.order()["state"], "vanished")
        self.assertEqual(self.store.recent("alerts")[0]["kind"], "order_vanished")

    def test_a_terminal_that_cannot_be_reached_leaves_the_orders_open_for_the_next_pass(self):
        fake = AutoMT5()
        self.open_one(fake)
        broken = AutoMT5()
        broken.initialize = lambda **kw: False
        result = self.executor(broken).reconcile(self.store, now=utcnow())
        self.assertIn("error", result)
        self.assertEqual(self.order()["state"], "open")


class FakeExecutor:
    def __init__(self, state="open"):
        self.sent, self.reconciled, self.state = [], 0, state

    def send(self, store, **kwargs):
        self.sent.append(kwargs)
        if self.state == "refused":
            return {"state": "refused", "code": "risk", "message": "x"}
        return {"state": self.state}

    def reconcile(self, store, **kwargs):
        self.reconciled += 1
        return {"checked": 0, "closed": 0}


STEP = timedelta(minutes=5)
NOW = datetime(2026, 11, 18, 14, 7, tzinfo=timezone.utc)
LAST_CLOSE = datetime(2026, 11, 18, 14, 5, tzinfo=timezone.utc)


def trending(symbol, n=300):
    from test_autopilot import candle
    return [candle(symbol, LAST_CLOSE - STEP * (n - 1 - i), 100 + 0.1 * i + (0.15 if i % 2 else -0.15)) for i in range(n)]


class WiringTests(unittest.TestCase):
    def make(self, temp, executor, provider=None):
        from test_autopilot import FakeProvider, ModelSetup, NoCalendar
        from trading_pro.models import Budget
        store = ResearchStore(str(Path(temp) / "t.db"))
        bars = {"XAUUSD": trending("XAUUSD")}
        setup = ModelSetup(provider, {"graph": "m", "quant": "m", "news": "m"}, Budget(100, 100, 0.25)) if provider else None
        pilot = Autopilot(store, fetch=lambda s, tf, n: (bars[s], {"server_offset_hours": 0.0}), model_setup=setup,
                          clock=lambda: NOW, calendar_loader=NoCalendar(), executor=executor,
                          limits_provider=Limits, risk_provider=lambda: RISK)
        autopilot.set_config(store, {"symbols": ["XAUUSD"], "execution_arms": ["det:graph"]}, author="t")
        return store, pilot

    def test_demo_auto_needs_the_bridge_and_an_arm_lifts_the_stop_and_leaving_it_arms_the_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            self.assertTrue(store.killed())
            with self.assertRaises(PermissionError):
                autopilot.set_mode(store, "demo_auto", author="op")  # no bridge in this process
            autopilot.set_config(store, {"execution_arms": []}, author="t")
            with self.assertRaises(PermissionError):
                autopilot.set_mode(store, "demo_auto", author="op", execution_available=True)  # no arm chosen
            autopilot.set_config(store, {"execution_arms": ["skills:director"]}, author="t")
            autopilot.set_mode(store, "demo_auto", author="op", execution_available=True)
            self.assertFalse(store.killed())
            self.assertIn("risk.kill_switch_released", [e["kind"] for e in store.journal.events(10)])
            autopilot.set_mode(store, "observe", author="op")
            self.assertTrue(store.killed())  # back to observation: no new entry, positions keep their stops
            for bad in ({"execution_arms": ["nope"]}, {"execution_arms": "skills:director"}):
                with self.assertRaises(ValueError):
                    autopilot.set_config(store, bad, author="t")

    def test_the_pilot_sends_only_in_demo_auto_and_only_the_chosen_arm(self):
        with tempfile.TemporaryDirectory() as temp:
            executor = FakeExecutor()
            store, pilot = self.make(temp, executor)
            autopilot.set_mode(store, "observe", author="op")
            pilot.run_symbol("XAUUSD")
            self.assertEqual(executor.sent, [])  # observation never sends
        with tempfile.TemporaryDirectory() as other:
            store2, pilot2 = self.make(other, executor)
            autopilot.set_mode(store2, "demo_auto", author="op", execution_available=True)
            result = pilot2.run_symbol("XAUUSD")
            self.assertEqual(len(executor.sent), 1)
            sent = executor.sent[0]
            self.assertEqual((sent["symbol"], sent["side"], sent["arm"]), ("XAUUSD", "BUY", "det:graph"))
            self.assertEqual(sent["plan"]["max_age_seconds"], 48 * 300)
            self.assertEqual(sent["halt"], "US announcement calendar missing")  # gold uses the strict calendar
            self.assertEqual(result["orders"], {"det:graph": "open"})
            # while a real position is open on the instrument no further attempt is made
            store2.record_order(decision_id="live", symbol="XAUUSD", arm="det:graph", side="BUY", state="open", opened_at=NOW,
                                position_ticket=5)
            store2.state_set("autopilot_last_bar:XAUUSD", "2000-01-01T00:00:00+00:00")
            pilot2.run_symbol("XAUUSD")
            self.assertEqual(len(executor.sent), 1)

    def test_while_the_emergency_stop_is_active_nothing_is_attempted_nothing_is_logged_and_analysis_goes_on(self):
        with tempfile.TemporaryDirectory() as temp:
            executor = FakeExecutor()
            store, pilot = self.make(temp, executor)
            autopilot.set_mode(store, "demo_auto", author="op", execution_available=True)
            store.set_killed()  # the red button
            result = pilot.run_symbol("XAUUSD")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(executor.sent, [])
            self.assertEqual(result["orders"], {"all": "stopped"})
            self.assertEqual(store.orders(), [])  # no "refused" row per cycle
            self.assertEqual(autopilot.get_mode(store), "demo_auto")  # the mode is untouched: only a deliberate act resumes
            with store.journal.connect() as db:
                self.assertGreater(db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 0)
            autopilot.set_mode(store, "demo_auto", author="op", execution_available=True)  # "Reprendre les ordres"
            self.assertFalse(store.killed())

    def test_a_refused_order_does_not_stop_the_analysis_and_an_exception_is_contained(self):
        with tempfile.TemporaryDirectory() as temp:
            executor = FakeExecutor(state="refused")
            store, pilot = self.make(temp, executor)
            autopilot.set_mode(store, "demo_auto", author="op", execution_available=True)
            result = pilot.run_symbol("XAUUSD")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["orders"], {"det:graph": "refused:risk"})

            def boom(*a, **k):
                raise RuntimeError("terminal exploded")
            executor.send = boom
            pilot.fetch = lambda s, tf, n: (trending("XAUUSD", 300)[:-1] + [trending("XAUUSD", 300)[-1]], {})
            store.state_set("autopilot_last_bar:XAUUSD", "2000-01-01T00:00:00+00:00")
            again = pilot.run_symbol("XAUUSD")
            self.assertEqual(again["status"], "ok")
            self.assertTrue(again["orders"]["det:graph"].startswith("error:"))

    def test_open_orders_are_followed_even_after_the_mode_is_switched_off(self):
        with tempfile.TemporaryDirectory() as temp:
            executor = FakeExecutor()
            store, pilot = self.make(temp, executor)
            store.record_order(decision_id="x", symbol="XAUUSD", arm="det:graph", side="BUY", state="open", opened_at=NOW,
                               position_ticket=1)
            autopilot.set_mode(store, "off", author="op")
            AutopilotRunner(pilot).tick()
            self.assertEqual(executor.reconciled, 1)

    def test_the_command_line_pilot_has_no_executor_and_cannot_send(self):
        import inspect
        from trading_pro import cli
        source = inspect.getsource(cli.main)
        self.assertNotIn("mt5_executor", source)

    def test_status_reports_the_bridge_orders_and_the_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot = self.make(temp, FakeExecutor())
            status = autopilot.status(store, NOW)
            self.assertTrue(status["demo_auto_available"])
            self.assertTrue(status["kill_switch"])
            self.assertEqual(status["orders"]["closed"], 0)
            bare = Autopilot(ResearchStore(str(Path(temp) / "b.db")), fetch=lambda *a: ([], {}))
            self.assertFalse(autopilot.status(bare.store, NOW)["demo_auto_available"])

    def test_the_endpoint_accepts_demo_auto_only_with_a_bridge(self):
        from test_autopilot import HttpAndProviderTests
        from trading_pro.server import handler_factory
        from trading_pro.service import Service
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp) / "db.sqlite"))
            call = HttpAndProviderTests().call

            class Runner:
                autopilot = NS(executor=None)
                def start(self): pass
            cls = handler_factory(service, "k", Runner())
            phrase = json.dumps({"mode": "demo_auto", "confirm": autopilot.DEMO_AUTO_PHRASE}).encode()
            self.assertEqual(call(cls, "POST", "/autopilot/mode", phrase, key="k")[0], 409)  # no bridge
            Runner.autopilot = NS(executor=object())
            self.assertEqual(call(cls, "POST", "/autopilot/mode", b'{"mode":"demo_auto"}', key="k")[0], 409)  # no phrase
            wrong = json.dumps({"mode": "demo_auto", "confirm": "oui"}).encode()
            self.assertEqual(call(cls, "POST", "/autopilot/mode", wrong, key="k")[0], 409)
            self.assertTrue(service.store.killed())  # nothing was lifted by the refusals
            code, payload = call(cls, "POST", "/autopilot/mode", phrase, key="k")
            self.assertEqual((code, payload["mode"]), (200, "demo_auto"))
            self.assertFalse(service.store.killed())
            self.assertEqual(call(cls, "GET", "/autopilot/orders")[0], 200)
            call(cls, "POST", "/risk/kill-switch", b"{}", key="k")  # the emergency button blocks new entries at once
            self.assertTrue(service.store.killed())


if __name__ == "__main__":
    unittest.main()
