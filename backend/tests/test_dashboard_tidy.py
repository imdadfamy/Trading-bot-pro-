import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_autopilot import FakeProvider, build, candle, rising, LAST_CLOSE, NOW, STEP
from test_autopilot_exec import FakeExecutor
from trading_pro import autopilot, autopilot_stats
from trading_pro.service import Service
from trading_pro.store import ResearchStore

ROOT = Path(__file__).resolve().parents[2]


class LauncherSafetyTests(unittest.TestCase):
    def snapshot(self):
        skills = ROOT / "skills"
        return {p.relative_to(skills).as_posix(): p.read_bytes() for p in sorted(skills.rglob("*")) if p.is_file()}

    def test_regenerating_the_skills_never_undoes_the_enrichment(self):
        before = self.snapshot()
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_skills.py")], check=True, capture_output=True)
        self.assertEqual(self.snapshot(), before)
        catalog = json.loads((ROOT / "skills" / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(len(catalog), 36)
        self.assertIn("agents", next(e for e in catalog if e["id"] == "economic-calendar"))

    def test_the_launcher_neither_regenerates_skills_nor_loads_fake_data_by_default(self):
        text = (ROOT / "Start-Local.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn("generate_skills", text)
        self.assertIn("[switch]$WithExamples", text)
        self.assertIn("[switch]$Verify", text)
        self.assertNotIn("Démo MT5 non connectée", text)


class DashboardTests(unittest.TestCase):
    def test_candles_are_those_of_one_instrument_and_real_bars_win_over_examples(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            service = Service(str(Path(temp) / "t.db"))
            for c in rising("Boom 500 Index", n=30):
                store.candle(c)
            for c in rising("XAUUSD", n=20):
                store.candle(c)
            example = [candle("XAUUSD", LAST_CLOSE + STEP * (k + 1), 2000 + k) for k in range(5)]
            from dataclasses import replace
            for c in example:
                store.candle(replace(c, broker="SYNTHETIC-NOT-A-BROKER"))
            boom = service.read("/market/candles", {"symbol": ["Boom 500 Index"]})
            self.assertEqual((boom["symbol"], len(boom["candles"])), ("Boom 500 Index", 30))
            self.assertTrue(all(c["symbol"] == "Boom 500 Index" for c in boom["candles"]))
            self.assertIn("MetaTrader", boom["source"])
            gold = service.read("/market/candles", {"symbol": ["XAUUSD"]})
            self.assertEqual(len(gold["candles"]), 20)  # the fictitious example bars are left out
            self.assertTrue(all(c["broker"] != "SYNTHETIC-NOT-A-BROKER" for c in gold["candles"]))
            self.assertIn("Boom 500 Index", gold["symbols"])
            only_example = service.read("/market/candles", {"symbol": ["Crash 500 Index"]})
            self.assertEqual(only_example["candles"], [])

    def test_example_bars_are_shown_only_as_a_labelled_last_resort(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            from dataclasses import replace
            for c in rising("XAUUSD", n=5):
                store.candle(replace(c, broker="SYNTHETIC-NOT-A-BROKER"))
            view = Service(str(Path(temp) / "t.db")).read("/market/candles", {"symbol": ["XAUUSD"]})
            self.assertEqual(len(view["candles"]), 5)
            self.assertIn("fictif", view["source"])

    def test_the_dashboard_follows_the_pilot_not_hard_coded_words(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = FakeProvider()
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, provider)
            service = Service(str(Path(temp) / "t.db"))
            autopilot.set_config(store, {"symbols": ["XAUUSD"]}, author="t")
            idle = service.dashboard()
            self.assertEqual((idle["mode"], idle["broker"]), ("off", "disconnected"))
            autopilot.set_mode(store, "observe", author="t")
            autopilot.AutopilotRunner(pilot).tick()
            live = Service(str(Path(temp) / "t.db")).dashboard()
            self.assertEqual(live["mode"], "observe")
            self.assertEqual(live["symbol"], "XAUUSD")
            self.assertGreater(live["decisions_total"], 0)
            kinds = {e["kind"] for e in live["events"]}
            self.assertFalse(kinds & Service.NOISY_EVENTS)  # the journal card shows what matters, not every decision
            self.assertIn("autopilot.mode_changed", kinds)
            votes = live["latest_votes"]
            self.assertEqual(set(votes) - {"graph", "quant", "news", "director", "ai_director"}, set())
            self.assertEqual(votes["graph"]["action"], "BUY")
            self.assertEqual(votes["graph"]["symbol"], "XAUUSD")

    def test_a_failed_model_call_is_never_shown_as_the_latest_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, FakeProvider(fail=True))
            pilot.run_symbol("XAUUSD")
            self.assertEqual(Service(str(Path(temp) / "t.db")).latest_votes(), {})
            self.assertEqual(autopilot_stats.recent_analyses(store), [])

    def test_recent_analyses_list_the_waits_with_their_reasons_newest_first(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": NOW}
            store, pilot, state = build(temp, {"XAUUSD": rising("XAUUSD")}, FakeProvider(), clock=lambda: clock["now"])
            pilot.run_symbol("XAUUSD")
            clock["now"] = NOW + timedelta(minutes=31)
            state["candles"]["XAUUSD"] = rising("XAUUSD", end=LAST_CLOSE + STEP * 7)
            pilot.run_symbol("XAUUSD")
            rows = autopilot_stats.recent_analyses(store)
            self.assertTrue(rows)
            self.assertEqual({r["arm"] for r in rows} - {"skills:graph", "skills:quant", "skills:news", "ai:director"}, set())
            self.assertGreaterEqual(rows[0]["at"], rows[-1]["at"])
            self.assertIn("WAIT", {r["action"] for r in rows})
            self.assertTrue(all("rationale" in r for r in rows))
            self.assertEqual(Service(str(Path(temp) / "t.db")).read("/autopilot/analyses"), rows)

    def test_readiness_reports_the_real_execution_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp) / "t.db"))
            self.assertEqual(service.read("/readiness")["execution_mode"], "off")
            autopilot.set_mode(service.store, "observe", author="t")
            self.assertEqual(service.read("/readiness")["execution_mode"], "observe")


class AccountTests(unittest.TestCase):
    class Ex(FakeExecutor):
        def __init__(self):
            super().__init__()
            self.summaries = 0

        def account_summary(self):
            self.summaries += 1
            return {"balance": 9999.28, "equity": 10010.5, "currency": "USD", "login_masked": "*****123"}

    def test_the_account_is_refreshed_every_five_minutes_and_exposed_on_the_dashboard(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": NOW}
            from trading_pro.autopilot import Autopilot
            store = ResearchStore(str(Path(temp) / "t.db"))
            executor = self.Ex()
            pilot = Autopilot(store, fetch=lambda *a: ([], {}), clock=lambda: clock["now"], executor=executor)
            pilot.refresh_account()
            pilot.refresh_account()
            self.assertEqual(executor.summaries, 1)
            clock["now"] = NOW + timedelta(minutes=6)
            pilot.refresh_account()
            self.assertEqual(executor.summaries, 2)
            account = Service(str(Path(temp) / "t.db")).dashboard()["account"]
            self.assertEqual((account["balance"], account["equity"]), (9999.28, 10010.5))
            self.assertNotIn("password", json.dumps(account).lower())

    def test_an_unreachable_terminal_keeps_the_last_known_values(self):
        with tempfile.TemporaryDirectory() as temp:
            from trading_pro.autopilot import Autopilot
            store = ResearchStore(str(Path(temp) / "t.db"))
            executor = self.Ex()
            pilot = Autopilot(store, fetch=lambda *a: ([], {}), clock=lambda: NOW, executor=executor)
            pilot.refresh_account()
            executor.account_summary = lambda: (_ for _ in ()).throw(RuntimeError("terminal closed"))
            pilot._last_account = None
            pilot.refresh_account()  # must not raise
            self.assertEqual(Service(str(Path(temp) / "t.db")).dashboard()["account"]["balance"], 9999.28)


class OverviewTests(unittest.TestCase):
    def test_one_card_per_configured_instrument_with_family_price_votes_and_positions(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD"), "Boom 500 Index": rising("Boom 500 Index")}, FakeProvider())
            autopilot.set_config(store, {"symbols": ["XAUUSD", "Boom 500 Index", "Drift Switch Index 20", "Volatility 10 Index",
                                                     "Crash 500 Index"]}, author="t")
            pilot.run_symbol("XAUUSD")
            pilot.run_symbol("Boom 500 Index")
            store.record_order(decision_id="o1", symbol="XAUUSD", arm="skills:director", side="BUY", state="open", opened_at=NOW,
                               volume=0.16, entry=2000.0, stop_loss=1997.0, take_profit=2006.0, position_ticket=1)
            cards = {c["symbol"]: c for c in Service(str(Path(temp) / "t.db")).read("/market/overview")["instruments"]}
            self.assertEqual({k: v["family"] for k, v in cards.items()},
                             {"XAUUSD": "gold", "Boom 500 Index": "boom", "Drift Switch Index 20": "drift",
                              "Volatility 10 Index": "volatility", "Crash 500 Index": "crash"})
            gold = cards["XAUUSD"]
            self.assertEqual(gold["timeframe"], "M5")
            self.assertEqual(len(gold["closes"]), 60)
            self.assertAlmostEqual(gold["price"], gold["closes"][-1])
            self.assertGreater(gold["change_pct"], 0)  # a rising series
            self.assertEqual(gold["votes"]["graph"]["action"], "BUY")
            self.assertEqual(gold["real_positions"][0]["side"], "BUY")
            self.assertGreater(gold["shadow_open"], 0)
            self.assertEqual(gold["status"], "waiting")  # the status comes from the pilot's heartbeat, none here
            self.assertEqual(autopilot.timeframe_for(autopilot.get_config(store), "Drift Switch Index 20"), "M1")
            self.assertEqual(cards["Drift Switch Index 20"]["timeframe"], "M1")
            empty = cards["Crash 500 Index"]
            self.assertEqual((empty["closes"], empty["price"], empty["change_pct"], empty["votes"]), ([], None, None, {}))

    def test_the_interface_files_are_there_and_the_removed_app_is_not(self):
        web = ROOT / "web"
        for name in ("index.html", "preview.js", "preview.css", "labels.json"):
            self.assertTrue((web / "preview" / name).is_file(), name)
        for gone in ("app", "package.json", "tsconfig.json"):
            self.assertFalse((web / gone).exists(), gone)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("npm", ci)


if __name__ == "__main__":
    unittest.main()
