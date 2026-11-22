import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from test_autopilot import NOW, build, decisions, rising
from test_autopilot_exec import FakeExecutor, WiringTests
from test_basket_exec import BasketMT5, basket_args
from test_autopilot_exec import Base
from trading_pro import autopilot
from trading_pro.autopilot import basket_terms, single_terms
from trading_pro.core import Limits
from trading_pro.store import ResearchStore

GENERAL = Limits(risk_per_trade=0.02, max_open_risk=0.035, max_spread=0.0)


class SettingsTests(unittest.TestCase):
    def store(self, temp):
        return ResearchStore(str(Path(temp) / "t.db"))

    def test_the_basket_has_its_own_settings_and_instruments_their_own_risk_or_lot(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.store(temp)
            saved = autopilot.set_config(store, {
                "basket": {"risk_per_trade": 0.02, "max_open_risk": 0.05, "fixed_lot": 2.0, "max_spread": 1.5,
                           "per_symbol": {"XAUUSD": {"positions": 5, "target_usd": 80, "risk_per_trade": 0.01, "fixed_lot": None}}},
                "instrument_risk": {"XAUUSD": {"risk_per_trade": 0.01}, "Boom 500 Index": {"fixed_lot": 3}}}, author="t")
            self.assertEqual(saved["basket"]["risk_per_trade"], 0.02)
            self.assertEqual(saved["basket"]["positions"], 20)  # the rest of the block keeps its values
            self.assertEqual(saved["instrument_risk"]["Boom 500 Index"], {"fixed_lot": 3})
            back = autopilot.get_config(store)
            self.assertEqual(back["basket"]["per_symbol"]["XAUUSD"]["positions"], 5)

    def test_bad_values_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.store(temp)
            for bad in ({"basket": {"risk_per_trade": 0.5}}, {"basket": {"risk_per_trade": 0}}, {"basket": {"max_open_risk": 1}},
                        {"basket": {"fixed_lot": -1}}, {"basket": {"per_symbol": {"X": {"positions": 1}}}},
                        {"basket": {"per_symbol": {"X": {"colour": 1}}}}, {"basket": {"per_symbol": []}},
                        {"instrument_risk": {"X": {"risk_per_trade": 0.5}}}, {"instrument_risk": {"X": {"positions": 3}}},
                        {"instrument_risk": []}, {"instrument_risk": {"X": {"fixed_lot": True}}}):
                with self.assertRaises(ValueError, msg=str(bad)):
                    autopilot.set_config(store, bad, author="t")
            autopilot.set_config(store, {"basket": {"risk_per_trade": None, "fixed_lot": None}}, author="t")  # empty = follow general

    def test_a_configuration_saved_before_these_settings_gets_their_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.store(temp)
            store.state_set("autopilot_config", json.dumps({"basket": {"symbols": ["XAUUSD"], "positions": 7, "target_usd": 30.0,
                                                                        "simulate": True, "enabled": False}}))
            config = autopilot.get_config(store)
            self.assertEqual((config["basket"]["positions"], config["basket"]["risk_per_trade"], config["basket"]["per_symbol"]),
                             (7, None, {}))
            self.assertEqual(config["instrument_risk"], {})


class TermsTests(unittest.TestCase):
    def test_a_single_order_follows_the_general_risk_unless_its_instrument_has_its_own(self):
        config = {"instrument_risk": {"XAUUSD": {"risk_per_trade": 0.01}, "Boom 500 Index": {"fixed_lot": 3.0}}}
        limits, risk = single_terms(config, "XAUUSD", GENERAL, {"fixed_lot": None, "commission_per_lot": 0})
        self.assertEqual((limits.risk_per_trade, risk["fixed_lot"]), (0.01, None))
        limits, risk = single_terms(config, "Boom 500 Index", GENERAL, {"fixed_lot": None})
        self.assertEqual((limits.risk_per_trade, risk["fixed_lot"]), (0.02, 3.0))
        limits, risk = single_terms(config, "Crash 500 Index", GENERAL, {"fixed_lot": 1.0})
        self.assertEqual((limits.risk_per_trade, risk["fixed_lot"]), (0.02, 1.0))  # nothing set for it: the general settings

    def test_a_basket_takes_instrument_then_basket_then_general_settings(self):
        config = {"basket": {**autopilot.DEFAULT_CONFIG["basket"], "positions": 20, "target_usd": 50.0, "risk_per_trade": 0.03,
                             "max_open_risk": 0.12, "max_spread": 2.0,
                             "per_symbol": {"XAUUSD": {"positions": 6, "target_usd": 90.0, "fixed_lot": 0.4}}}}
        terms = basket_terms(config, "XAUUSD", GENERAL, {})
        self.assertEqual((terms["positions"], terms["target_usd"], terms["member_lot"]), (6, 90.0, 0.4))
        self.assertEqual((terms["limits"].risk_per_trade, terms["limits"].max_open_risk, terms["limits"].max_spread), (0.03, 0.12, 2.0))
        other = basket_terms(config, "Volatility 10 Index", GENERAL, {})
        self.assertEqual((other["positions"], other["target_usd"], other["member_lot"]), (20, 50.0, None))
        blank = basket_terms({"basket": autopilot.DEFAULT_CONFIG["basket"]}, "Volatility 10 Index", GENERAL, {})
        self.assertEqual((blank["limits"].risk_per_trade, blank["limits"].max_open_risk), (0.02, 0.035))  # empty = general


class RoutingTests(unittest.TestCase):
    def cycle(self, settings):
        with tempfile.TemporaryDirectory() as temp:
            executor = FakeExecutor()
            executor.send_basket = lambda store, **kw: (executor.sent.append(("basket", kw)) or {"state": "open", "members": 1})
            store, pilot = WiringTests().make(temp, executor)
            pilot.limits_provider = lambda: GENERAL
            autopilot.set_config(store, settings, author="t")
            autopilot.set_mode(store, "demo_auto", author="op", execution_available=True)
            pilot.run_symbol("XAUUSD")
            return executor.sent

    def test_the_single_order_gets_its_instrument_risk(self):
        sent = self.cycle({"instrument_risk": {"XAUUSD": {"risk_per_trade": 0.01, "fixed_lot": 0.7}}})
        self.assertEqual((sent[0]["limits"].risk_per_trade, sent[0]["risk"]["fixed_lot"]), (0.01, 0.7))

    def test_the_basket_gets_its_own_terms_apart_from_the_single_orders(self):
        sent = self.cycle({"instrument_risk": {"XAUUSD": {"risk_per_trade": 0.01}},
                           "basket": {"symbols": ["XAUUSD"], "enabled": True, "risk_per_trade": 0.04, "max_open_risk": 0.1,
                                      "per_symbol": {"XAUUSD": {"positions": 8, "target_usd": 70, "fixed_lot": 0.25}}}})
        kind, call = sent[0]
        self.assertEqual(kind, "basket")
        self.assertEqual((call["positions"], call["target_usd"], call["member_lot"]), (8, 70.0, 0.25))
        self.assertEqual((call["limits"].risk_per_trade, call["limits"].max_open_risk), (0.04, 0.1))  # not the instrument's 1%


class SimulationTests(unittest.TestCase):
    def test_the_simulated_basket_uses_the_basket_risk_and_the_instrument_target(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, clock=lambda: NOW)
            autopilot.set_config(store, {"symbols": ["XAUUSD"], "execution_arms": ["det:graph"],
                                         "basket": {"symbols": ["XAUUSD"], "risk_per_trade": 0.02,
                                                    "per_symbol": {"XAUUSD": {"target_usd": 40, "positions": 8}}}}, author="t")
            pilot.run_symbol("XAUUSD")
            detail = json.loads(decisions(store, arm="basket:det:graph")[0]["detail"])
            self.assertEqual((detail["basket"]["risk_money"], detail["basket"]["target_usd"], detail["basket"]["positions"]), (200.0, 40.0, 8))
            self.assertEqual(detail["basket"]["target_r"], 0.2)  # 40 USD of a 200 USD risk


class ExecutionTests(Base):
    def setUp(self):
        super().setUp()
        self.store.release_killed(author="t", reason="test")

    def test_an_explicit_lot_is_used_for_every_member_without_splitting(self):
        fake = BasketMT5()
        report = self.executor(fake).send_basket(self.store, **basket_args(positions=3, member_lot=0.05))
        self.assertEqual((report["state"], report["members"]), ("open", 3))
        self.assertEqual([p.volume for p in fake.positions], [0.05, 0.05, 0.05])

    def test_the_baskets_own_open_risk_cap_decides_what_it_may_risk(self):
        small = BasketMT5()
        report = self.executor(small).send_basket(self.store, **basket_args(positions=3, member_lot=0.5))  # 1% general cap
        self.assertEqual((report["state"], report["members"], small.positions), ("refused", 0, []))
        self.store.release_killed(author="t", reason="again")
        wide = BasketMT5()
        options = basket_args(positions=3, member_lot=0.5)
        options["limits"] = replace(options["limits"], max_open_risk=0.25)  # the basket's own, wider cap
        report = self.executor(wide).send_basket(self.store, **options)
        self.assertEqual((report["state"], report["members"]), ("open", 3))


if __name__ == "__main__":
    unittest.main()
