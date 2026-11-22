import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from test_autopilot import NOW, STEP, FakeProvider, build, candle, decisions, rising
import test_autopilot_exec as exec_tests  # a module import, so its test classes are not collected a second time
from trading_pro import autopilot, autopilot_stats
from trading_pro.service import Service


def jump(state, clock, plan, in_stop_distances):
    base = state["candles"]["XAUUSD"]
    last = base[-1]
    top = last.close + plan["stop_distance"] * in_stop_distances
    bar = candle("XAUUSD", last.closed_at + STEP, top, open_=last.close, high=top + 0.05, low=last.close - 0.05)
    state["candles"]["XAUUSD"] = base[1:] + [bar]
    clock["now"] = clock["now"] + timedelta(minutes=5)


class VariantTests(unittest.TestCase):
    def test_the_default_variants_are_skills_forced_and_plainforced(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = FakeProvider()
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, provider)
            autopilot.set_config(store, {"exit_study": {"enabled": False}}, author="t")
            pilot.run_symbol("XAUUSD")
            arms = {d["arm"] for d in decisions(store)}
            self.assertFalse([a for a in arms if a.startswith("plain:")])  # plain never traded in 191 consultations: off
            for variant in ("skills", "forced", "plainforced"):
                self.assertIn(f"{variant}:graph", arms)
                self.assertIn(f"{variant}:director", arms)
            self.assertIn("ai:director", arms)
            plainforced = [c for c in provider.calls if c[1].get("forced_direction") and "features" not in c[1]]
            forced = [c for c in provider.calls if c[1].get("forced_direction") and "features" in c[1]]
            self.assertEqual((len(plainforced), len(forced)), (3, 3))  # same rule, with and without the features and skills
            self.assertTrue(all("method_notes" not in c[1] for c in plainforced))
            detail = json.loads(decisions(store, arm="plainforced:graph")[0]["detail"])
            self.assertEqual((detail["variant"], detail["skills"]), ("plainforced", []))

    def test_the_variants_are_validated_and_the_ai_director_needs_the_skills_variant(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, FakeProvider())
            for bad in ([], ["nope"], ["forced", "forced"], "forced", ["plain", "skills", "forced", "plainforced", "x"]):
                with self.assertRaises(ValueError, msg=str(bad)):
                    autopilot.set_config(store, {"model_variants": bad}, author="t")
            autopilot.set_config(store, {"model_variants": ["forced", "plainforced"], "exit_study": {"enabled": False}}, author="t")
            pilot.run_symbol("XAUUSD")
            arms = {d["arm"] for d in decisions(store)}
            self.assertNotIn("ai:director", arms)  # it reads the skills analysts' reports: not consulted without them
            self.assertIn("plainforced:quant", arms)

    def test_what_the_skills_add_is_measured_as_forced_against_plainforced(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": NOW}
            store, pilot, state = build(temp, {"XAUUSD": rising("XAUUSD")}, FakeProvider(answers={"graph": "BUY", "quant": "BUY", "news": "BUY"}),
                                        clock=lambda: clock["now"])
            autopilot.set_config(store, {"exit_study": {"enabled": False}}, author="t")
            pilot.run_symbol("XAUUSD")
            plan = json.loads(decisions(store, arm="forced:graph")[0]["detail"])["plan"]
            jump(state, clock, plan, 3)
            pilot.run_symbol("XAUUSD")
            effect = autopilot_stats.performance(store)["skills_effect_forced"]["graph"]
            self.assertEqual((effect["n_with"], effect["n_without"]), (1, 1))
            self.assertTrue(effect["underpowered"])  # one pair proves nothing


class TradedInstrumentsTests(unittest.TestCase):
    def cycle(self, settings):
        with tempfile.TemporaryDirectory() as temp:
            executor = exec_tests.FakeExecutor()
            store, pilot = exec_tests.WiringTests().make(temp, executor)
            autopilot.set_config(store, settings, author="t")
            autopilot.set_mode(store, "demo_auto", author="op", execution_available=True)
            result = pilot.run_symbol("XAUUSD")
            return executor.sent, result, decisions(store)

    def test_an_instrument_can_be_analysed_without_receiving_real_orders(self):
        sent, result, rows = self.cycle({"traded_symbols": ["Volatility 10 Index"]})
        self.assertEqual(sent, [])
        self.assertEqual(result["orders"], {"all": "analysed only"})
        self.assertTrue([d for d in rows if d["arm"] == "det:graph" and d["status"] == "open"])  # the learning goes on
        sent, _, _ = self.cycle({"traded_symbols": ["XAUUSD"]})
        self.assertEqual(len(sent), 1)
        sent, _, _ = self.cycle({"traded_symbols": None})  # the default: every analysed instrument
        self.assertEqual(len(sent), 1)

    def test_the_list_is_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            store, _, _ = build(temp, {"XAUUSD": rising("XAUUSD")})
            for bad in ("XAUUSD", [1], ["x" * 61], [f"S{i}" for i in range(13)]):
                with self.assertRaises(ValueError, msg=str(bad)):
                    autopilot.set_config(store, {"traded_symbols": bad}, author="t")
            self.assertEqual(autopilot.set_config(store, {"traded_symbols": []}, author="t")["traded_symbols"], [])  # none at all


class ExitStudyTests(unittest.TestCase):
    SETTINGS = {"symbols": ["XAUUSD"], "exit_study": {"enabled": True, "arms": ["det:graph"], "horizons": [24, 48], "rewards": [1.0, 2.0]}}

    def start(self, temp):
        clock = {"now": NOW}
        store, pilot, state = build(temp, {"XAUUSD": rising("XAUUSD")}, clock=lambda: clock["now"])
        autopilot.set_config(store, self.SETTINGS, author="t")
        return store, pilot, state, clock

    def test_each_decision_is_followed_under_every_horizon_and_target_from_the_same_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = self.start(temp)
            pilot.run_symbol("XAUUSD")
            twins = [d for d in decisions(store) if d["arm"].startswith("exit:")]
            self.assertEqual(len(twins), 4)
            base = json.loads(decisions(store, arm="det:graph")[0]["detail"])["plan"]
            seen = set()
            for twin in twins:
                detail = json.loads(twin["detail"])
                self.assertEqual(twin["status"], "open")
                self.assertEqual(detail["plan"]["stop_distance"], base["stop_distance"])  # the stop is the same
                seen.add((detail["plan"]["horizon_bars"], detail["plan"]["reward_multiple"]))
            self.assertEqual(seen, {(24, 1.0), (24, 2.0), (48, 1.0), (48, 2.0)})
            self.assertEqual({d["cycle_id"] for d in twins}, {decisions(store, arm="det:graph")[0]["cycle_id"]})

    def test_disabled_or_for_other_arms_nothing_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = self.start(temp)
            autopilot.set_config(store, {"exit_study": {"enabled": False}}, author="t")
            pilot.run_symbol("XAUUSD")
            self.assertFalse([d for d in decisions(store) if d["arm"].startswith("exit:")])
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = self.start(temp)
            autopilot.set_config(store, {"exit_study": {"arms": ["forced:director"]}}, author="t")
            pilot.run_symbol("XAUUSD")
            self.assertFalse([d for d in decisions(store) if d["arm"].startswith("exit:")])

    def test_a_small_move_reaches_the_near_target_only_and_the_pairs_show_the_difference(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = self.start(temp)
            pilot.run_symbol("XAUUSD")
            plan = json.loads(decisions(store, arm="det:graph")[0]["detail"])["plan"]
            jump(state, clock, plan, 1.4)  # past 1 stop distance, short of 2
            pilot.run_symbol("XAUUSD")
            rows = [d for d in decisions(store) if d["arm"].startswith("exit:")]
            done = {d["arm"]: d["status"] for d in rows if d["cycle_id"] == rows[0]["cycle_id"]}
            self.assertEqual(done["exit:det:graph:h24:r1"], "resolved")
            self.assertEqual(done["exit:det:graph:h24:r2"], "open")
            stats = autopilot_stats.exit_performance(store)["arms"]["det:graph"]["variants"]
            near = next(v for v in stats if (v["horizon_bars"], v["reward_multiple"]) == (24, 1.0))
            self.assertEqual((near["trades"], near["ended_on"]["target"]), (1, 1))
            self.assertAlmostEqual(near["mean_r"], 1.0, delta=0.2)

    def test_the_report_pairs_every_variant_with_the_current_setting_and_stays_out_of_the_other_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = self.start(temp)
            pilot.run_symbol("XAUUSD")
            plan = json.loads(decisions(store, arm="det:graph")[0]["detail"])["plan"]
            jump(state, clock, plan, 3.0)  # every target is reached
            pilot.run_symbol("XAUUSD")
            report = autopilot_stats.exit_performance(store)
            self.assertEqual(report["baseline"], {"horizon_bars": 48, "reward_multiple": 2.0})
            variants = report["arms"]["det:graph"]["variants"]
            self.assertEqual(len(variants), 4)
            baseline = [v for v in variants if v["baseline"]]
            self.assertEqual([(v["horizon_bars"], v["reward_multiple"]) for v in baseline], [(48, 2.0)])
            near = next(v for v in variants if (v["horizon_bars"], v["reward_multiple"]) == (48, 1.0))
            self.assertEqual(near["paired_vs_baseline"]["n"], 1)
            self.assertTrue(near["paired_vs_baseline"]["underpowered"])  # one pair proves nothing
            performance = autopilot_stats.performance(store)
            self.assertFalse([a for a in performance["arms"] if a.startswith("exit:")])
            self.assertIn("exit_study", performance)
            self.assertFalse([d for d in autopilot_stats.recent_decisions(store) if d["arm"].startswith("exit:")])
            overview = Service(str(Path(temp) / "t.db")).overview()
            self.assertEqual(next(i for i in overview["instruments"] if i["symbol"] == "XAUUSD")["shadow_open"],
                             len([d for d in decisions(store) if d["status"] == "open" and not d["arm"].startswith(("exit:", "basket:"))]))

    def test_the_settings_are_validated_and_merged(self):
        with tempfile.TemporaryDirectory() as temp:
            store, _, _ = build(temp, {"XAUUSD": rising("XAUUSD")})
            merged = autopilot.set_config(store, {"exit_study": {"horizons": [12, 24, 36]}}, author="t")["exit_study"]
            self.assertEqual((merged["horizons"], merged["rewards"], merged["enabled"]), ([12, 24, 36], [1.0, 1.5, 2.0], True))
            for bad in ({"horizons": [3]}, {"horizons": [1.5]}, {"horizons": []}, {"horizons": list(range(10, 70, 10))},
                        {"rewards": [0.1]}, {"rewards": [True]}, {"arms": ["nope"]}, {"enabled": "yes"}, {"colour": 1}):
                with self.assertRaises(ValueError, msg=str(bad)):
                    autopilot.set_config(store, {"exit_study": bad}, author="t")


if __name__ == "__main__":
    unittest.main()
