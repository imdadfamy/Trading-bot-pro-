import json
import tempfile
import unittest
from datetime import timedelta

from test_autopilot import LAST_CLOSE, NOW, STEP, build, candle, decisions, rising
from trading_pro import autopilot, autopilot_stats

SETTINGS = {"symbols": ["XAUUSD"], "execution_arms": ["det:graph"], "basket": {"symbols": ["XAUUSD"]}}


def start(temp):
    clock = {"now": NOW}
    store, pilot, state = build(temp, {"XAUUSD": rising("XAUUSD")}, clock=lambda: clock["now"])
    autopilot.set_config(store, SETTINGS, author="t")
    return store, pilot, state, clock


def next_bar(state, clock, move_in_stop_distances, plan):
    base = state["candles"]["XAUUSD"]
    last = base[-1]
    jump = last.close + plan["stop_distance"] * move_in_stop_distances
    bar = candle("XAUUSD", last.closed_at + STEP, jump, open_=last.close, high=jump + 0.05, low=last.close - 0.05)
    state["candles"]["XAUUSD"] = base[1:] + [bar]
    clock["now"] = clock["now"] + timedelta(minutes=5)


class BasketSimulationTests(unittest.TestCase):
    def test_nothing_is_recorded_for_an_instrument_or_an_arm_outside_the_basket_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": NOW}
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, clock=lambda: clock["now"])
            pilot.run_symbol("XAUUSD")  # default settings: basket on Volatility 10 only, execution arm skills:director
            self.assertEqual([d for d in decisions(store) if d["arm"].startswith("basket:")], [])
            autopilot.set_config(store, {"execution_arms": ["det:graph"], "basket": {"symbols": ["XAUUSD"], "simulate": False}}, author="t")
            clock["now"] += timedelta(minutes=5)
            pilot.run_symbol("XAUUSD")
            self.assertEqual([d for d in decisions(store) if d["arm"].startswith("basket:")], [])

    def test_a_basket_twin_shares_the_stop_and_has_the_money_target_as_its_objective(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = start(temp)
            pilot.run_symbol("XAUUSD")
            single = decisions(store, arm="det:graph")[0]
            twin = decisions(store, arm="basket:det:graph")[0]
            self.assertEqual((single["status"], twin["status"]), ("open", "open"))
            plan_single, detail = json.loads(single["detail"])["plan"], json.loads(twin["detail"])
            self.assertEqual(detail["plan"]["stop_distance"], plan_single["stop_distance"])  # the stop is not touched
            self.assertEqual(plan_single["reward_multiple"], 2.0)  # the single position is not touched either
            # no account read yet: 10 000 assumed, risk 0.5% = 50 USD, so a 50 USD basket target is 1 stop distance
            self.assertEqual(detail["basket"]["risk_money"], 50.0)
            self.assertTrue(detail["basket"]["equity_assumed"])
            self.assertEqual(detail["plan"]["reward_multiple"], 1.0)
            self.assertEqual(detail["twin_of"], single["decision_id"])

    def test_only_one_basket_at_a_time_per_instrument(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = start(temp)
            pilot.run_symbol("XAUUSD")
            plan = json.loads(decisions(store, arm="det:graph")[0]["detail"])["plan"]
            next_bar(state, clock, 0.1, plan)  # nothing reaches the target
            pilot.run_symbol("XAUUSD")
            statuses = [d["status"] for d in decisions(store, arm="basket:det:graph")]
            self.assertEqual(sorted(statuses), ["open", "skipped_open"])

    def test_the_basket_closes_at_its_target_while_the_single_position_is_still_running(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = start(temp)
            pilot.run_symbol("XAUUSD")
            plan = json.loads(decisions(store, arm="det:graph")[0]["detail"])["plan"]
            next_bar(state, clock, 1.3, plan)  # past the basket target (1 stop distance) but short of the 2 of the position
            pilot.run_symbol("XAUUSD")
            first = decisions(store, arm="basket:det:graph")[0]
            self.assertEqual(first["status"], "resolved")
            self.assertEqual(decisions(store, arm="det:graph")[0]["status"], "open")
            report = autopilot_stats.basket_performance(store)["arms"]["basket:det:graph"]
            self.assertEqual((report["trades"], report["ended_on"]["target"]), (1, 1))
            self.assertAlmostEqual(report["usd_mean"], 50.0, delta=6.0)  # about +50 USD once the spread is paid
            self.assertEqual(report["paired"]["n"], 0)  # the single position of that decision is not resolved yet

    def test_a_big_move_resolves_both_and_the_pair_shows_what_the_basket_gave_up(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = start(temp)
            pilot.run_symbol("XAUUSD")
            plan = json.loads(decisions(store, arm="det:graph")[0]["detail"])["plan"]
            next_bar(state, clock, 2.5, plan)
            pilot.run_symbol("XAUUSD")
            paired = autopilot_stats.basket_performance(store)["arms"]["basket:det:graph"]["paired"]
            self.assertEqual(paired["n"], 1)
            self.assertGreater(paired["mean_r_single"], 1.7)
            self.assertAlmostEqual(paired["mean_r_basket"], 1.0, delta=0.15)
            self.assertTrue(paired["underpowered"])  # one pair proves nothing

    def test_baskets_stay_out_of_the_real_arm_tables_and_the_decision_list(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, state, clock = start(temp)
            pilot.run_symbol("XAUUSD")
            plan = json.loads(decisions(store, arm="det:graph")[0]["detail"])["plan"]
            next_bar(state, clock, 2.5, plan)
            pilot.run_symbol("XAUUSD")
            performance = autopilot_stats.performance(store)
            self.assertFalse([arm for arm in performance["arms"] if arm.startswith("basket:")])
            self.assertIn("basket:det:graph", performance["basket"]["arms"])
            self.assertFalse([d for d in autopilot_stats.recent_decisions(store) if d["arm"].startswith("basket:")])

    def test_basket_settings_are_validated_and_merged(self):
        with tempfile.TemporaryDirectory() as temp:
            store, _, _ = build(temp, {"XAUUSD": rising("XAUUSD")})
            merged = autopilot.set_config(store, {"basket": {"positions": 10}}, author="t")["basket"]
            self.assertEqual((merged["positions"], merged["target_usd"], merged["symbols"]), (10, 50.0, ["Volatility 10 Index"]))
            for bad in ({"positions": 1}, {"positions": 51}, {"target_usd": 0}, {"simulate": "yes"}, {"symbols": "XAUUSD"},
                        {"unknown": 1}, {"positions": True}):
                with self.assertRaises(ValueError, msg=str(bad)):
                    autopilot.set_config(store, {"basket": bad}, author="t")
            self.assertEqual(autopilot.get_config(store)["basket"]["positions"], 10)


if __name__ == "__main__":
    unittest.main()
