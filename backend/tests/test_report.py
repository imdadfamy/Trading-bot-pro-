import json
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import test_autopilot as base
from trading_pro import autopilot, weekly_report
from trading_pro.service import Service
from trading_pro.store import ResearchStore

NOW = datetime(2026, 11, 29, 12, 0, tzinfo=timezone.utc)


def add(store, symbol, arm, cycle, r, *, at=None, detail=None, direction=None):
    """One resolved shadow trade (and, if given, its fixed-horizon direction score)."""
    when = (at or NOW - timedelta(days=1)).isoformat()
    decision = str(uuid4())
    with store.journal.connect() as db:
        db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?)",
                   (decision, cycle, symbol, when, "Outside indicative sessions", arm, "BUY", "resolved", json.dumps(detail or {})))
        db.execute("INSERT INTO decision_outcomes VALUES(?,?,?,?,?,?,?,?,?)", (decision, when, "target" if r > 0 else "stop", r, 5, 1.0, 0.5, 1.0, 1.0))
        if direction is not None:
            db.execute("INSERT INTO direction_scores VALUES(?,?,?,?)", (decision, when, 6, direction))


def fill(store, symbol, arm, values, offset=0):
    for i, r in enumerate(values):
        add(store, symbol, arm, f"{symbol}-{offset + i}", r)


def noise(n, centre, seed):
    rnd = random.Random(seed)
    return [centre + rnd.uniform(-0.15, 0.15) for _ in range(n)]


class ReportTests(unittest.TestCase):
    def build(self, temp):
        store = ResearchStore(str(Path(temp) / "t.db"))
        # A: a method clearly beats the coin, pair by pair
        fill(store, "Boom 500 Index", "random:coin", noise(40, -0.2, 1))
        fill(store, "Boom 500 Index", "forced:quant", noise(40, 0.5, 2))
        # B: everything is noise
        fill(store, "Crash 500 Index", "random:coin", noise(40, -0.1, 3))
        fill(store, "Crash 500 Index", "forced:quant", noise(40, -0.1, 4))
        # C: too few consultations
        fill(store, "XAUUSD", "random:coin", noise(5, -0.1, 5))
        fill(store, "XAUUSD", "forced:quant", noise(5, 0.4, 6))
        # the skills help the graph analyst on Boom
        fill(store, "Boom 500 Index", "forced:graph", noise(40, 0.4, 7))
        fill(store, "Boom 500 Index", "plainforced:graph", noise(40, 0.0, 8))
        return store

    def test_an_instrument_is_kept_only_when_a_method_clearly_beats_the_coin(self):
        with tempfile.TemporaryDirectory() as temp:
            report = weekly_report.build_report(self.build(temp), days=7, now=NOW)
            verdicts = report["verdicts"]["instruments"]
            self.assertEqual(verdicts["Boom 500 Index"]["verdict"], "retenu")
            self.assertEqual(verdicts["Boom 500 Index"]["method"], "forced:quant")
            self.assertEqual(verdicts["Crash 500 Index"]["verdict"], "aucun avantage démontré")
            self.assertEqual(verdicts["XAUUSD"]["verdict"], "trop peu de données")  # 5 pairs prove nothing, even a big gap

    def test_the_skills_verdict_compares_forced_with_and_without_them(self):
        with tempfile.TemporaryDirectory() as temp:
            report = weekly_report.build_report(self.build(temp), days=7, now=NOW)
            self.assertIn("aident", report["verdicts"]["skills"]["graph"])
            self.assertEqual(report["skills"]["graph"]["overall_shadow"]["n"], 40)
            self.assertIn("elles aident pour graph", report["verdicts"]["summary"][1])

    def test_the_exit_rule_changes_only_for_a_clearly_better_variant(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            for variant, centre in (((48, 2.0), 0.0), ((24, 1.0), 0.5), ((96, 2.0), 0.0)):
                rnd = random.Random(int(variant[0] * 10 + variant[1]))
                for i in range(40):
                    detail = {"variant": "exit", "twin_arm": "forced:director", "exit": {"horizon_bars": variant[0], "reward_multiple": variant[1]}}
                    add(store, "Volatility 10 Index", f"exit:forced:director:h{variant[0]}:r{variant[1]:g}", f"v-{i}",
                        centre + rnd.uniform(-0.2, 0.2), detail=detail)
            report = weekly_report.build_report(store, days=7, now=NOW)
            choice = report["verdicts"]["exit"]["forced:director"]
            self.assertEqual((choice["verdict"], choice["horizon_bars"], choice["reward_multiple"]), ("changer", 24, 1.0))
            self.assertIn("passer à 24 bougies", report["verdicts"]["summary"][2])

    def test_only_the_period_asked_for_is_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            for i in range(35):
                add(store, "Boom 500 Index", "random:coin", f"in-{i}", -0.2)
                add(store, "Boom 500 Index", "forced:quant", f"in-{i}", 0.4)
                add(store, "Boom 500 Index", "forced:quant", f"old-{i}", -5.0, at=NOW - timedelta(days=20))
            report = weekly_report.build_report(store, days=7, now=NOW)
            self.assertEqual(report["instruments"]["Boom 500 Index"]["methods"]["forced:quant"]["shadow"]["trades"], 35)
            wide = weekly_report.build_report(store, days=30, now=NOW)
            self.assertEqual(wide["instruments"]["Boom 500 Index"]["methods"]["forced:quant"]["shadow"]["trades"], 70)

    def test_health_costs_and_real_orders_are_summarised(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            start = NOW - timedelta(days=2)
            with store.journal.connect() as db:
                for minutes in (0, 5, 10, 90, 95):  # a 80-minute hole between the third and the fourth
                    db.execute("INSERT INTO audit(at,kind,correlation_id,payload) VALUES(?,?,?,?)",
                               ((start + timedelta(minutes=minutes)).isoformat(), "autopilot.cycle", "c", json.dumps({"symbol": "XAUUSD"})))
                db.execute("INSERT INTO audit(at,kind,correlation_id,payload) VALUES(?,?,?,?)",
                           (start.isoformat(), "autopilot.data_error", "x", json.dumps({"message": "MT5 login refused (code -6)"})))
                db.execute("INSERT INTO model_usage(at,agent,provider,model,input_tokens,output_tokens,cost_usd) VALUES(?,?,?,?,?,?,?)",
                           (start.isoformat(), "graph", "p", "m", 10, 5, 0.5))
            store.record_order(decision_id="a", symbol="XAUUSD", arm="x", side="BUY", state="closed", opened_at=start, volume=1)
            store.close_order("a", state="closed", profit=12.5, reason="objectif", now=start)
            for i in range(3):
                store.record_order(decision_id=f"b{i}", symbol="Volatility 10 Index", arm="x", side="BUY", state="closed", opened_at=start,
                                   volume=1, basket_id="BASKET01")
                store.close_order(f"b{i}", state="closed", profit=-70.0, reason="stop", now=start)
            report = weekly_report.build_report(store, days=7, now=NOW)
            health, costs, real = report["health"], report["costs"], report["real"]
            self.assertEqual((health["cycles"], len(health["interruptions"]), health["interruptions"][0]["minutes"]), (5, 1, 80))
            self.assertEqual(health["errors"], {"MT5 login refused (code -6)": 1})
            self.assertEqual((costs["total_usd"], costs["calls"]), (0.5, 1))
            self.assertEqual((real["single_net"], real["baskets_net"], real["baskets_lost"]), (12.5, -210.0, 1))

    def test_the_markdown_and_the_service_route_carry_the_same_report(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.build(temp)
            text = weekly_report.build_report(store, days=7, now=NOW)["markdown"]
            for heading in ("# Rapport de collecte", "## Conclusions", "## Verdict par instrument", "## Résultats par instrument",
                            "## Les compétences aident-elles", "## Étude des sorties", "## Santé du pilote", "## Coût de l'IA"):
                self.assertIn(heading, text)
            self.assertIn("| Boom 500 Index | retenu |", text)
            service = Service(str(Path(temp) / "t.db"))
            payload = service.read("/autopilot/report", {"days": ["30"]})
            self.assertEqual(payload["period"]["days"], 30)
            self.assertIn("markdown", payload)
            self.assertEqual(service.read("/autopilot/report", {"days": ["x"]})["period"]["days"], 7)  # a bad value falls back


class DailyFileTests(unittest.TestCase):
    def runner(self, temp, report_dir, clock):
        store, pilot, _ = base.build(temp, {"XAUUSD": base.rising("XAUUSD")}, clock=lambda: clock["now"])
        return store, autopilot.AutopilotRunner(pilot, report_dir=report_dir)

    def test_the_report_is_written_once_a_day_and_never_stops_the_pilot(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "reports"
            clock = {"now": datetime(2026, 11, 29, 0, 2, tzinfo=timezone.utc)}
            store, runner = self.runner(temp, folder, clock)
            runner.tick()
            self.assertFalse(folder.exists())  # too close to midnight: the day is not complete
            clock["now"] = datetime(2026, 11, 29, 0, 10, tzinfo=timezone.utc)
            runner.tick()
            self.assertTrue((folder / "rapport-2026-11-29.md").exists())
            self.assertIn("# Rapport de collecte", (folder / "dernier-rapport.md").read_text(encoding="utf-8"))
            (folder / "dernier-rapport.md").write_text("changed", encoding="utf-8")
            runner.tick()  # same day: not written again
            self.assertEqual((folder / "dernier-rapport.md").read_text(encoding="utf-8"), "changed")
            clock["now"] = datetime(2026, 11, 30, 3, 0, tzinfo=timezone.utc)
            runner.tick()
            self.assertTrue((folder / "rapport-2026-11-30.md").exists())
            self.assertEqual([e["kind"] for e in store.journal.events(50)].count("autopilot.report_written"), 2)

    def test_no_folder_means_no_file_and_a_failure_is_only_journaled(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": datetime(2026, 11, 29, 5, 0, tzinfo=timezone.utc)}
            store, runner = self.runner(temp, None, clock)
            runner.tick()
            self.assertFalse(store.state_get("autopilot_report_day"))
        with tempfile.TemporaryDirectory() as temp:
            blocker = Path(temp) / "reports"
            blocker.write_text("a file where the folder should be", encoding="utf-8")
            clock = {"now": datetime(2026, 11, 29, 5, 0, tzinfo=timezone.utc)}
            store, runner = self.runner(temp, blocker, clock)
            runner.tick()  # must not raise
            self.assertIn("autopilot.error", [e["kind"] for e in store.journal.events(20)])


if __name__ == "__main__":
    unittest.main()
