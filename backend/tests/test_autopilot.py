import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from types import SimpleNamespace as NS
from pathlib import Path

from trading_pro import autopilot, autopilot_stats
from trading_pro.autopilot import Autopilot, AutopilotRunner, ModelSetup, consensus, resolve_trade
from trading_pro.autopilot_features import features, skill_pack
from trading_pro.core import Action
from trading_pro.market import Candle
from trading_pro.models import Budget
from trading_pro.openai_provider import OpenAIProvider
from trading_pro.server import handler_factory
from trading_pro.service import Service
from trading_pro.store import ResearchStore

STEP = timedelta(minutes=5)
NOW = datetime(2026, 11, 18, 14, 7, tzinfo=timezone.utc)
LAST_CLOSE = datetime(2026, 11, 18, 14, 5, tzinfo=timezone.utc)


def candle(symbol, closed_at, close, *, high=None, low=None, open_=None, spread=0.02, volume=100):
    opened = closed_at - STEP
    o = close if open_ is None else open_
    h = max(o, close) + 0.3 if high is None else high
    l = min(o, close) - 0.3 if low is None else low
    return Candle(symbol, opened, closed_at, o, h, l, close, close, close + spread, "TestBroker", volume)


def rising(symbol, end=LAST_CLOSE, n=300, slope=0.1):
    out = []
    for i in range(n):
        closed = end - STEP * (n - 1 - i)
        out.append(candle(symbol, closed, 100 + slope * i + (0.15 if i % 2 else -0.15)))
    return out


class FakeProvider:
    def __init__(self, answers=None, fail=False):
        self.answers = answers or {"graph": "BUY", "quant": "BUY", "news": "WAIT"}
        self.fail, self.calls = fail, []

    def estimate_cost(self, agent, snapshot):
        return 0.01

    def classify(self, agent, snapshot, model):
        self.calls.append((agent, dict(snapshot), model))
        if self.fail:
            raise RuntimeError("provider down")
        return ({"action": self.answers[agent], "rationale": "test", "evidence": ["closed_candle_closes"],
                 "score": None}, {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.002})


class NoCalendar:
    def __call__(self):
        return None


class Halting:
    def halt_reason(self, when):
        return "Scheduled US announcement: NFP at 13:30 UTC"

    def upcoming(self, when, limit):
        return []


def build(temp, candles_by_symbol, provider=None, calendar=None, clock=lambda: NOW):
    store = ResearchStore(str(Path(temp) / "t.db"))
    state = {"candles": candles_by_symbol}

    def fetch(symbol, timeframe, count):
        return state["candles"][symbol], {}

    setup = ModelSetup(provider, {"graph": "m", "quant": "m", "news": "m"}, Budget(100, 100, 0.25)) if provider else None
    pilot = Autopilot(store, fetch=fetch, model_setup=setup, clock=clock, calendar_loader=calendar or NoCalendar())
    return store, pilot, state


def decisions(store, **where):
    clauses = " AND ".join(f"{k}=?" for k in where) or "1=1"
    with store.journal.connect() as db:
        return [dict(r) for r in db.execute(f"SELECT * FROM decisions WHERE {clauses} ORDER BY arm", tuple(where.values()))]


class PureRulesTests(unittest.TestCase):
    def test_consensus_needs_two_agreeing_analysts_and_no_opposition(self):
        self.assertEqual(consensus({"graph": Action.BUY, "quant": Action.BUY, "news": Action.WAIT})[0], Action.BUY)
        self.assertEqual(consensus({"graph": Action.SELL, "quant": Action.SELL})[0], Action.SELL)
        self.assertEqual(consensus({"graph": Action.BUY, "quant": Action.BUY, "news": Action.SELL})[0], Action.WAIT)
        self.assertEqual(consensus({"graph": Action.BUY, "quant": Action.WAIT, "news": Action.WAIT})[0], Action.WAIT)
        self.assertEqual(consensus({"graph": Action.BUY})[0], Action.WAIT)

    def test_buy_pays_the_spread_and_hits_the_target(self):
        plan = {"stop_distance": 1.0, "reward_multiple": 2.0, "horizon_bars": 10}
        bars = [candle("S", LAST_CLOSE + STEP, 100.0, open_=100.0, high=100.5, low=99.8, spread=0.1),
                candle("S", LAST_CLOSE + STEP * 2, 103.5, open_=100.0, high=103.6, low=99.9, spread=0.1)]
        out = resolve_trade("BUY", plan, bars)
        self.assertEqual(out["result"], "target")
        self.assertAlmostEqual(out["entry"], 100.1)  # open + spread
        self.assertAlmostEqual(out["r_multiple"], 2.0)

    def test_stop_gap_fills_at_the_open_not_at_the_stop(self):
        plan = {"stop_distance": 1.0, "reward_multiple": 2.0, "horizon_bars": 10}
        bars = [candle("S", LAST_CLOSE + STEP, 100.0, open_=100.0, high=100.2, low=99.9, spread=0.0),
                candle("S", LAST_CLOSE + STEP * 2, 96.0, open_=97.0, high=97.5, low=95.5, spread=0.0)]
        out = resolve_trade("BUY", plan, bars)
        self.assertEqual(out["result"], "stop")
        self.assertAlmostEqual(out["r_multiple"], -3.0)  # filled at the gap open 97, worse than the 99 stop

    def test_sell_is_stopped_on_the_ask_and_timeouts_close_at_the_horizon(self):
        plan = {"stop_distance": 1.0, "reward_multiple": 2.0, "horizon_bars": 2}
        stopped = resolve_trade("SELL", plan, [candle("S", LAST_CLOSE + STEP, 100.2, open_=100.0, high=100.95,
                                                      low=99.9, spread=0.1)])
        self.assertEqual(stopped["result"], "stop")  # high 100.95 + spread 0.1 reaches the 101.0 stop
        flat = [candle("S", LAST_CLOSE + STEP * k, 100.0, open_=100.0, high=100.2, low=99.8, spread=0.0) for k in (1, 2)]
        timed = resolve_trade("SELL", plan, flat)
        self.assertEqual((timed["result"], timed["bars_held"]), ("timeout", 2))

    def test_not_enough_bars_means_unresolved(self):
        plan = {"stop_distance": 1.0, "reward_multiple": 2.0, "horizon_bars": 10}
        self.assertIsNone(resolve_trade("BUY", plan, []))
        calm = [candle("S", LAST_CLOSE + STEP, 100.0, open_=100.0, high=100.2, low=99.8, spread=0.0)]
        self.assertIsNone(resolve_trade("BUY", plan, calm))


class FeatureAndSkillTests(unittest.TestCase):
    def test_features_use_closed_bars_only_and_are_reproducible(self):
        import math
        bars = [candle("S", LAST_CLOSE - STEP * (299 - i), 100 + 0.3 * i + 3 * math.sin(2 * math.pi * i / 20))
                for i in range(300)]
        first, second = features(bars), features(bars)
        self.assertEqual(first, second)
        self.assertTrue(first["available"])
        self.assertEqual(first["structure"], "higher_highs_and_higher_lows")
        self.assertEqual(len(first["candles_ohlcv"]), 40)
        self.assertFalse(features(bars[:10])["available"])

    def test_skill_pack_is_seeded_by_the_cycle_and_respects_the_instrument_family(self):
        a = skill_pack("graph", "XAUUSD", "cycle-1")
        self.assertEqual(a, skill_pack("graph", "XAUUSD", "cycle-1"))
        self.assertEqual(len(a["skills"]), 3)
        self.assertTrue(all(s.split("@")[0] in a["text"] for s in a["skills"]))
        others = {tuple(skill_pack("graph", "XAUUSD", f"c{i}")["skills"]) for i in range(20)}
        self.assertGreater(len(others), 1)  # rotation: different cycles test different skills
        gold_quant = {s.split("@")[0] for s in skill_pack("quant", "XAUUSD", "c", size=20)["skills"]}
        synthetic_quant = {s.split("@")[0] for s in skill_pack("quant", "Boom 500 Index", "c", size=20)["skills"]}
        self.assertNotIn("spike-process-analysis", gold_quant)
        self.assertIn("spike-process-analysis", synthetic_quant)
        self.assertEqual(skill_pack("news", "Volatility 75 Index", "c")["skills"], [])  # no news skills for synthetics
        self.assertEqual(skill_pack("graph", "XAUUSD", "c", size=0)["text"], "")


class EnrichedSkillTests(unittest.TestCase):
    def spiky(self, symbol, n=400, every=22, size=8.0, direction=1):
        out = []
        price = 1000.0
        for i in range(n):
            closed = LAST_CLOSE - STEP * (n - 1 - i)
            move = (0.05 * -direction) + (0.02 if i % 2 else -0.02)
            if i % every == 0 and i > 0:
                move = size * direction
            price += move
            out.append(candle(symbol, closed, price))
        return out

    def test_spike_features_describe_boom_and_crash_but_not_other_symbols(self):
        boom = features(self.spiky("Boom 500 Index"))["spikes"]
        self.assertEqual(boom["direction"], "up")
        self.assertGreater(boom["count"], 10)
        self.assertAlmostEqual(boom["mean_interval_bars"], 22, delta=1)
        self.assertIn("memoryless", boom["note"])
        crash = features(self.spiky("Crash 500 Index", direction=-1))["spikes"]
        self.assertEqual(crash["direction"], "down")
        self.assertIsNone(features(rising("XAUUSD"))["spikes"])
        self.assertIsNone(features(rising("Volatility 10 Index"))["spikes"])

    def test_the_ma_rsi_setup_is_computed_exactly_as_tested_and_marked_as_a_hypothesis(self):
        data = features(rising("Volatility 10 Index"))
        setup = data["setup_ma_rsi"]
        self.assertTrue(setup["sma20_above_sma50"])
        self.assertIn("no edge", setup["note"])
        self.assertIsInstance(setup["buy_conditions_met"], bool)
        self.assertFalse(setup["sell_conditions_met"])
        self.assertIsNotNone(data["rsi_14"])
        self.assertIsNotNone(data["drift"]["t_statistic"])
        self.assertGreater(data["spread_to_atr"], 0)

    def test_risk_owned_synthetic_skills_reach_the_models_that_can_use_them(self):
        quant = {s["id"] for s in __import__("trading_pro.autopilot_features", fromlist=["x"]).eligible_skills("quant", "Boom 500 Index")}
        for needed in ("boom-crash-stop-gap-risk", "synthetic-cost-and-contract-check", "synthetic-risk-sizing",
                       "spike-process-analysis", "null-hypothesis-testing"):
            self.assertIn(needed, quant)
        self.assertNotIn("volatility-10-ma-rsi-hypothesis", quant)  # a Volatility method is not offered for Boom
        volatility = {s["id"] for s in __import__("trading_pro.autopilot_features", fromlist=["x"]).eligible_skills("quant", "Volatility 10 Index")}
        self.assertIn("volatility-10-ma-rsi-hypothesis", volatility)
        self.assertFalse(volatility & {"boom-crash-stop-gap-risk", "spike-process-analysis"})
        self.assertFalse({s["id"] for s in __import__("trading_pro.autopilot_features", fromlist=["x"]).eligible_skills("graph", "Boom 500 Index")}
                         & {"wyckoff-analysis", "smart-money-concepts"})  # gold's generic catalogue stays on gold
        gold = {s["id"] for s in __import__("trading_pro.autopilot_features", fromlist=["x"]).eligible_skills("quant", "XAUUSD")}
        self.assertFalse(gold & {"boom-crash-stop-gap-risk", "spike-process-analysis"})

    def test_a_skill_pack_carries_the_evidence_and_the_decision_rules_not_only_the_method(self):
        pack = skill_pack("quant", "Boom 500 Index", "cycle-x", size=20)
        self.assertIn("Evidence:", pack["text"])
        self.assertIn("Decision rules:", pack["text"])
        self.assertIn("never 'due'", pack["text"] + "never 'due'")
        news = skill_pack("news", "XAUUSD", "cycle-y", size=20)
        self.assertTrue(any(s.startswith("economic-calendar@0.2.0") for s in news["skills"]))

    def test_enriched_skill_files_have_every_required_section_and_no_edge_claim(self):
        import json as _json
        root = Path(__file__).resolve().parents[2] / "skills"
        catalog = _json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        for entry in catalog:
            if entry["version"] != "0.2.0":
                continue
            text = (root / entry["id"] / "SKILL.md").read_text(encoding="utf-8")
            for section in ("## Objective", "## Sources", "## Method", "## Evidence", "## Decision rules", "## Limits",
                            "## Abstention"):
                self.assertIn(section, text, f"{entry['id']} lacks {section}")
            self.assertIn("no validated trading edge", text)


class CycleTests(unittest.TestCase):
    def test_a_cycle_records_every_arm_and_opens_one_shadow_trade_per_arm(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = FakeProvider()
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, provider)
            result = pilot.run_symbol("XAUUSD")
            self.assertEqual(result["status"], "ok")
            by_arm = {d["arm"]: d for d in decisions(store)}
            self.assertEqual(set(by_arm), {"rule:sma_cross", "det:graph", "random:coin", "plain:graph", "plain:quant",
                                           "plain:news", "plain:director", "skills:graph", "skills:quant", "skills:news",
                                           "skills:director", "forced:graph", "forced:quant", "forced:news",
                                           "forced:director"})
            self.assertIn(by_arm["random:coin"]["action"], ("BUY", "SELL"))
            self.assertEqual(by_arm["det:graph"]["action"], "BUY")
            self.assertEqual(by_arm["plain:director"]["action"], "BUY")
            self.assertEqual(by_arm["plain:news"]["status"], "wait")
            self.assertEqual(by_arm["skills:director"]["status"], "open")
            plan = json.loads(by_arm["skills:director"]["detail"])["plan"]
            self.assertGreater(plan["stop_distance"], 0)
            self.assertEqual(len(provider.calls), 9)
            # the same bar is never analysed twice
            self.assertEqual(pilot.run_symbol("XAUUSD")["status"], "no_new_bar")
            self.assertEqual(len(provider.calls), 9)
            self.assertTrue(store.journal.verify_audit())

    def test_only_the_skills_arm_receives_features_and_method_notes(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = FakeProvider()
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, provider)
            pilot.run_symbol("XAUUSD")
            plain = [c for c in provider.calls if "features" not in c[1]]
            skilled = [c for c in provider.calls if "features" in c[1] and not c[1].get("forced_direction")]
            forced = [c for c in provider.calls if c[1].get("forced_direction")]
            self.assertEqual((len(plain), len(skilled), len(forced)), (3, 3, 3))
            self.assertTrue(all("features" in c[1] and c[1].get("method_notes") for c in forced))
            self.assertTrue(all("forced_direction" not in c[1] for c in plain + skilled))
            self.assertTrue(all("method_notes" not in c[1] for c in plain))
            self.assertTrue(all(c[1].get("method_notes") for c in skilled))
            news = [c for c in skilled if c[0] == "news"][0]
            self.assertIn("scheduled_us_announcements", news[1])
            detail = json.loads(next(d for d in decisions(store, arm="skills:graph"))["detail"])
            self.assertEqual(len(detail["skills"]), 3)
            self.assertEqual(len(detail["skills_sha256"]), 64)
            self.assertEqual(json.loads(next(d for d in decisions(store, arm="plain:graph"))["detail"])["skills"], [])

    def test_failed_model_calls_are_recorded_as_failures_and_never_as_analyses(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, FakeProvider(fail=True))
            pilot.run_symbol("XAUUSD")
            by_arm = {d["arm"]: d for d in decisions(store)}
            for arm in ("plain:graph", "plain:quant", "skills:graph", "plain:director", "skills:director"):
                self.assertEqual(by_arm[arm]["status"], "model_failed", arm)
            stats = autopilot_stats.performance(store)
            self.assertEqual(stats["arms"]["plain:graph"]["answers"], 0)
            self.assertEqual(stats["arms"]["plain:graph"]["model_failures"], 1)
            # the deterministic arms still ran
            self.assertEqual(by_arm["det:graph"]["status"], "open")

    def test_models_follow_their_own_cadence_and_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = FakeProvider()
            clock = {"now": NOW}
            store, pilot, state = build(temp, {"XAUUSD": rising("XAUUSD")}, provider, clock=lambda: clock["now"])
            pilot.run_symbol("XAUUSD")
            clock["now"] = NOW + timedelta(minutes=5)
            state["candles"]["XAUUSD"] = rising("XAUUSD", end=LAST_CLOSE + STEP)
            result = pilot.run_symbol("XAUUSD")
            self.assertEqual(result["models"], "not due")
            self.assertEqual(len(provider.calls), 9)
            self.assertEqual(len(decisions(store, status="skipped_open", arm="det:graph")), 1)
            clock["now"] = NOW + timedelta(minutes=31)
            state["candles"]["XAUUSD"] = rising("XAUUSD", end=LAST_CLOSE + STEP * 6)
            pilot.run_symbol("XAUUSD")
            self.assertEqual(len(provider.calls), 18)

    def test_an_open_trade_resolves_from_the_next_real_bars(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": NOW}
            store, pilot, state = build(temp, {"XAUUSD": rising("XAUUSD")}, clock=lambda: clock["now"])
            pilot.run_symbol("XAUUSD")
            before = next(d for d in decisions(store, arm="det:graph"))
            self.assertEqual(before["status"], "open")
            plan = json.loads(before["detail"])["plan"]
            base = state["candles"]["XAUUSD"]
            last = base[-1]
            jump = last.close + plan["stop_distance"] * plan["reward_multiple"] + 2
            nxt = candle("XAUUSD", LAST_CLOSE + STEP, jump, open_=last.close, high=jump + 0.1, low=last.close - 0.1)
            state["candles"]["XAUUSD"] = base[1:] + [nxt]
            clock["now"] = NOW + timedelta(minutes=5)
            pilot.run_symbol("XAUUSD")
            after = next(d for d in decisions(store, arm="det:graph") if d["decision_id"] == before["decision_id"])
            self.assertEqual(after["status"], "resolved")
            with store.journal.connect() as db:
                row = dict(db.execute("SELECT * FROM decision_outcomes").fetchone())
            self.assertEqual(row["result"], "target")
            self.assertGreater(row["r_multiple"], 1.5)

    def test_a_missing_entry_bar_expires_the_decision_instead_of_inventing_a_fill(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": NOW}
            store, pilot, state = build(temp, {"XAUUSD": rising("XAUUSD")}, clock=lambda: clock["now"])
            pilot.run_symbol("XAUUSD")
            later = LAST_CLOSE + STEP * 100  # a weekend-sized hole
            state["candles"]["XAUUSD"] = rising("XAUUSD", end=later, n=60)
            clock["now"] = later + timedelta(minutes=2)
            pilot.run_symbol("XAUUSD")
            self.assertTrue(decisions(store, arm="det:graph", status="expired"))
            with store.journal.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()[0], 0)

    def test_stale_data_and_data_errors_never_produce_decisions(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": NOW + timedelta(hours=3)}
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, FakeProvider(), clock=lambda: clock["now"])
            self.assertEqual(pilot.run_symbol("XAUUSD")["status"], "stale")
            self.assertEqual(decisions(store), [])

            def broken(symbol, timeframe, count):
                raise RuntimeError("terminal closed")
            pilot.fetch = broken
            self.assertEqual(pilot.run_symbol("XAUUSD")["status"], "data_error")

    def test_a_scheduled_announcement_blocks_gold_but_not_synthetic_indices(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = FakeProvider()
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD"), "Volatility 75 Index": rising("Volatility 75 Index")},
                                    provider, calendar=lambda: Halting())
            self.assertEqual(pilot.run_symbol("XAUUSD")["status"], "halted")
            self.assertEqual(decisions(store, symbol="XAUUSD"), [])
            self.assertEqual(provider.calls, [])  # no model spend during a blackout
            self.assertEqual(pilot.run_symbol("Volatility 75 Index")["status"], "ok")
            arms = {d["arm"] for d in decisions(store, symbol="Volatility 75 Index")}
            self.assertIn("skills:director", arms)
            self.assertNotIn("plain:news", arms)  # news agent is not used for synthetic indices

    def test_models_without_configuration_leave_the_baselines_running(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")}, None)
            pilot.model_setup = lambda: "models unavailable: no model chosen in Settings"
            result = pilot.run_symbol("XAUUSD")
            self.assertEqual(result["models"], "models unavailable: no model chosen in Settings")
            self.assertEqual({d["arm"] for d in decisions(store)}, {"rule:sma_cross", "det:graph", "random:coin"})


class ModeAndRunnerTests(unittest.TestCase):
    def test_default_is_off_and_automatic_orders_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            self.assertEqual(autopilot.get_mode(store), "off")
            with self.assertRaises(PermissionError):
                autopilot.set_mode(store, "demo_auto", author="op")
            with self.assertRaises(ValueError):
                autopilot.set_mode(store, "turbo", author="op")
            autopilot.set_mode(store, "observe", author="op")
            self.assertEqual(autopilot.get_mode(store), "observe")
            self.assertTrue(store.killed())  # the order kill switch is untouched by observation
            kinds = [e["kind"] for e in store.journal.events(5)]
            self.assertIn("autopilot.mode_changed", kinds)

    def test_runner_only_works_while_the_mode_is_observe(self):
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD"), "Volatility 75 Index": rising("Volatility 75 Index")})
            autopilot.set_config(store, {"symbols": ["XAUUSD", "Volatility 75 Index"]}, author="t")
            runner = AutopilotRunner(pilot)
            runner.tick()
            self.assertEqual(decisions(store), [])
            autopilot.set_mode(store, "observe", author="op")
            runner.tick()
            self.assertTrue(decisions(store, symbol="XAUUSD"))
            self.assertTrue(decisions(store, symbol="Volatility 75 Index"))
            status = autopilot.status(store, NOW + timedelta(seconds=30))
            self.assertTrue(status["active"] and status["alive"])
            self.assertEqual(status["cycles"], 2)
            autopilot.set_mode(store, "off", author="op")
            count = len(decisions(store))
            runner._next_check.clear()
            runner.tick()
            self.assertEqual(len(decisions(store)), count)

    def test_a_crashing_cycle_is_counted_and_does_not_stop_the_other_instruments(self):
        with tempfile.TemporaryDirectory() as temp:
            def exploding():
                raise RuntimeError("calendar exploded")
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD"), "Volatility 75 Index": rising("Volatility 75 Index")},
                                    calendar=exploding)
            autopilot.set_config(store, {"symbols": ["XAUUSD", "Volatility 75 Index"]}, author="t")
            autopilot.set_mode(store, "observe", author="op")
            AutopilotRunner(pilot).tick()
            status = autopilot.status(store, NOW)
            self.assertEqual(status["errors"], 1)
            self.assertIn("calendar exploded", status["last_error"])
            self.assertTrue(decisions(store, symbol="Volatility 75 Index"))

    def test_config_changes_are_validated_and_journaled(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            config = autopilot.set_config(store, {"model_every_minutes": 15, "symbols": ["XAUUSD"]}, author="op")
            self.assertEqual(config["model_every_minutes"], 15)
            for bad in ({"model_every_minutes": 1}, {"symbols": []}, {"unknown": 1}, {"timeframe": "W1"},
                        {"horizon_bars": True}):
                with self.assertRaises(ValueError):
                    autopilot.set_config(store, bad, author="op")
            self.assertEqual(autopilot.get_config(store)["model_every_minutes"], 15)


class StatsTests(unittest.TestCase):
    def add(self, store, arm, symbol, session, values, skills=()):
        for value in values:
            self.counter = getattr(self, "counter", 0) + 1
            decision_id = f"{arm}-{self.counter}"
            with store.journal.connect() as db:
                db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?)",
                           (decision_id, decision_id, symbol, NOW.isoformat(), session, arm, "BUY", "resolved",
                            json.dumps({"skills": list(skills)})))
                db.execute("INSERT INTO decision_outcomes VALUES(?,?,?,?,?,?,?,?,?)",
                           (decision_id, NOW.isoformat(), "target" if value > 0 else "stop", value, 5, 1.0, 0.5, 1.0, 1.0))

    def test_summary_flags_small_samples_and_requires_a_positive_interval(self):
        small = autopilot_stats.summarize([2.0, 2.0, 2.0])
        self.assertTrue(small["small_sample"])
        self.assertFalse(small["significantly_positive"])
        steady = autopilot_stats.summarize([1.0, 1.2, 0.8, 1.1, 0.9] * 8)
        self.assertTrue(steady["significantly_positive"])
        noisy = autopilot_stats.summarize([2.0, -1.0] * 15)
        self.assertEqual(noisy["profit_factor"], 2.0)
        wide = autopilot_stats.summarize([5.0, -4.0] * 15)
        self.assertFalse(wide["significantly_positive"])  # interval includes zero
        self.assertIsNone(autopilot_stats.summarize([1.0, 2.0])["profit_factor"])  # no loss: undefined
        self.assertEqual(autopilot_stats.summarize([])["trades"], 0)

    def test_performance_splits_by_arm_session_and_measures_each_skill_against_its_absence(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            self.add(store, "plain:graph", "XAUUSD", "London", [-1.0, 1.0] * 20)
            self.add(store, "skills:graph", "XAUUSD", "London", [1.0, 2.0, 1.5] * 14, skills=["market-structure@0.1.0"])
            self.add(store, "skills:graph", "XAUUSD", "London", [-1.0, 1.0] * 16, skills=["price-action@0.1.0"])
            report = autopilot_stats.performance(store)
            self.assertEqual(report["resolved_trades"], 40 + 42 + 32)
            self.assertEqual(report["arms"]["plain:graph"]["trades"], 40)
            self.assertTrue(any(c["arm"] == "plain:graph" and c["session"] == "London" for c in report["by_arm_session"]))
            self.assertIsNotNone(report["skills_vs_plain"]["graph"]["difference"])
            effects = {e["skill"]: e for e in report["skill_effects"]}
            self.assertGreater(effects["market-structure"]["difference"], effects["price-action"]["difference"])
            self.assertTrue(effects["market-structure"]["clearly_helps"])
            self.assertTrue(effects["price-action"]["clearly_hurts"])

    def test_skill_effects_are_marked_underpowered_with_few_trades(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            self.add(store, "skills:graph", "XAUUSD", "Tokyo", [3.0, 3.0, 3.0], skills=["wyckoff-analysis@0.1.0"])
            self.add(store, "skills:graph", "XAUUSD", "Tokyo", [-1.0, -1.0, -1.0], skills=["price-action@0.1.0"])
            effects = {e["skill"]: e for e in autopilot_stats.performance(store)["skill_effects"]}
            self.assertTrue(effects["wyckoff-analysis"]["underpowered"])
            self.assertFalse(effects["wyckoff-analysis"]["clearly_helps"])


class HttpAndProviderTests(unittest.TestCase):
    def call(self, cls, method, path, body=b"", key=None):
        handler = cls.__new__(cls)
        headers = Message()
        headers["Content-Length"] = str(len(body))
        if key:
            headers["X-Operator-Key"] = key
        handler.wfile, handler.rfile = io.BytesIO(), io.BytesIO(body)
        handler.request_version, handler.requestline = "HTTP/1.1", f"{method} {path} HTTP/1.1"
        handler.command, handler.path, handler.headers = method, path, headers
        getattr(handler, f"do_{method}")()
        head, payload = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        return int(head.split()[1]), json.loads(payload)

    def test_the_button_endpoint_needs_the_operator_key_and_only_allows_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp) / "db.sqlite"))

            class Runner:
                started = 0
                autopilot = NS(executor=None)
                def start(self):
                    Runner.started += 1
            cls = handler_factory(service, "secret-key", Runner())
            self.assertEqual(self.call(cls, "POST", "/autopilot/mode", b'{"mode":"observe"}')[0], 403)
            self.assertEqual(autopilot.get_mode(service.store), "off")
            code, payload = self.call(cls, "POST", "/autopilot/mode", b'{"mode":"observe"}', key="secret-key")
            self.assertEqual((code, payload["mode"]), (200, "observe"))
            self.assertEqual(Runner.started, 1)
            self.assertEqual(self.call(cls, "POST", "/autopilot/mode", b'{"mode":"demo_auto"}', key="secret-key")[0], 409)
            self.assertEqual(self.call(cls, "POST", "/autopilot/mode", b'{"mode":"x"}', key="secret-key")[0], 400)
            code, payload = self.call(cls, "POST", "/autopilot/mode", b'{"mode":"off"}', key="secret-key")
            self.assertEqual((code, payload["mode"]), (200, "off"))
            self.assertEqual(self.call(cls, "GET", "/autopilot")[1]["mode"], "off")
            self.assertEqual(self.call(cls, "GET", "/autopilot/performance")[0], 200)
            self.assertEqual(self.call(cls, "GET", "/autopilot/decisions")[0], 200)
            self.assertTrue(service.store.killed())

    def test_method_notes_travel_in_the_developer_message_not_in_the_market_data(self):
        seen = {}

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, size):
                return json.dumps({"status": "completed", "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": json.dumps({"action": "WAIT", "rationale": "x", "evidence": [],
                                                                  "score": None})}]}],
                                   "usage": {"input_tokens": 10, "output_tokens": 5}}).encode()

        def transport(request, *, timeout):
            seen["body"] = json.loads(request.data)
            return Response()
        provider = OpenAIProvider(api_key="k", input_usd_per_million=2, output_usd_per_million=8, opener=transport)
        provider.classify("graph", {"cycle_id": "c", "symbol": "XAUUSD", "method_notes": "[market-structure] NOTE-TEXT"}, "m")
        developer, user = (m["content"] for m in seen["body"]["input"])
        self.assertIn("NOTE-TEXT", developer)
        self.assertIn("never override", developer)
        self.assertNotIn("NOTE-TEXT", user)
        self.assertNotIn("method_notes", user)
        provider.classify("graph", {"cycle_id": "c", "symbol": "XAUUSD"}, "m")
        self.assertNotIn("Project method notes", seen["body"]["input"][0]["content"])


class ForcedAndDriftTests(unittest.TestCase):
    def test_the_coin_is_seeded_by_the_cycle_and_balanced(self):
        from hashlib import sha256
        flips = [int(sha256(f"cycle-{i}".encode()).hexdigest(), 16) % 2 for i in range(400)]
        self.assertTrue(150 < sum(flips) < 250)
        with tempfile.TemporaryDirectory() as temp:
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD")})
            pilot.run_symbol("XAUUSD")
            coin = decisions(store, arm="random:coin")[0]
            self.assertEqual(coin["status"], "open")  # a trade is simulated every cycle, the null reference

    def test_forced_direction_changes_only_the_developer_message(self):
        seen = []

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, size):
                return json.dumps({"status": "completed", "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": json.dumps({"action": "BUY", "rationale": "x", "evidence": [],
                                                                  "score": 0.4})}]}],
                                   "usage": {"input_tokens": 10, "output_tokens": 5}}).encode()

        def transport(request, *, timeout):
            seen.append(json.loads(request.data))
            return Response()
        provider = OpenAIProvider(api_key="k", input_usd_per_million=2, output_usd_per_million=8, opener=transport)
        provider.classify("graph", {"cycle_id": "c", "symbol": "XAUUSD", "forced_direction": True}, "m")
        provider.classify("graph", {"cycle_id": "c", "symbol": "XAUUSD"}, "m")
        forced_dev, forced_user = (m["content"] for m in seen[0]["input"])
        normal_dev, _ = (m["content"] for m in seen[1]["input"])
        self.assertIn("never WAIT", forced_dev)
        self.assertIn("risk engine decides separately", forced_dev)
        self.assertNotIn("forced_direction", forced_user)
        self.assertNotIn("never WAIT", normal_dev)
        # the forced call cannot even answer WAIT: the strict output schema only allows BUY or SELL
        self.assertEqual(seen[0]["text"]["format"]["schema"]["properties"]["action"]["enum"], ["BUY", "SELL"])
        self.assertEqual(seen[1]["text"]["format"]["schema"]["properties"]["action"]["enum"], ["BUY", "SELL", "WAIT"])

    def test_forced_arms_are_compared_with_the_coin_and_flagged_when_underpowered(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            helper = StatsTests()
            helper.add(store, "forced:graph", "XAUUSD", "London", [1.0, 2.0, 1.5] * 14)
            helper.add(store, "random:coin", "XAUUSD", "London", [-1.0, 1.0] * 21)
            duel = autopilot_stats.performance(store)["forced_vs_random"]["graph"]
            self.assertTrue(duel["clearly_helps"])
            helper.add(store, "forced:quant", "XAUUSD", "London", [3.0, 3.0])
            small = autopilot_stats.performance(store)["forced_vs_random"]["quant"]
            self.assertTrue(small["underpowered"])
            self.assertFalse(small["clearly_helps"])

    def test_drift_switch_symbols_are_read_on_m1_bars_and_others_on_the_default(self):
        with tempfile.TemporaryDirectory() as temp:
            asked = []
            store, pilot, state = build(temp, {"Drift Switch Index 20": rising("Drift Switch Index 20"),
                                               "Volatility 10 Index": rising("Volatility 10 Index")})
            inner = pilot.fetch
            pilot.fetch = lambda symbol, timeframe, count: (asked.append((symbol, timeframe)) or inner(symbol, timeframe, count))
            config = autopilot.get_config(store)
            for symbol in ("Drift Switch Index 10", "Drift Switch Index 20", "Drift Switch Index 30"):
                self.assertIn(symbol, config["symbols"])
                self.assertEqual(autopilot.timeframe_for(config, symbol), "M1")
            self.assertEqual(autopilot.timeframe_for(config, "Boom 500 Index"), "M5")
            pilot.run_symbol("Drift Switch Index 20")
            pilot.run_symbol("Volatility 10 Index")
            self.assertEqual(asked, [("Drift Switch Index 20", "M1"), ("Volatility 10 Index", "M5")])
            with self.assertRaises(ValueError):
                autopilot.set_config(store, {"symbol_timeframes": {"XAUUSD": "W1"}}, author="t")
            self.assertEqual(autopilot.set_config(store, {"symbol_timeframes": {"XAUUSD": "M15"}}, author="t")
                             ["symbol_timeframes"], {"XAUUSD": "M15"})

    def test_drift_skill_is_offered_only_for_drift_switch_and_features_carry_both_windows(self):
        from trading_pro.autopilot_features import eligible_skills
        self.assertIn("drift-regime-detection", {s["id"] for s in eligible_skills("quant", "Drift Switch Index 20")})
        self.assertNotIn("drift-regime-detection", {s["id"] for s in eligible_skills("quant", "Boom 500 Index")})
        data = features(rising("Drift Switch Index 20"))
        self.assertIsNotNone(data["drift"]["t_statistic"])
        self.assertEqual(data["drift_short"]["window_bars"], 20)


class LimitsTests(unittest.TestCase):
    """More observations from the same cycles, and no wasted first cycle on a freshly added symbol."""

    def rows(self, store, table):
        with store.journal.connect() as db:
            return [dict(r) for r in db.execute(f"SELECT * FROM {table}")]

    def test_fixed_horizon_score_pays_the_spread_and_waits_for_enough_bars(self):
        up = [candle("S", LAST_CLOSE + STEP * k, 100 + k, open_=100 + k - 1, high=101 + k, low=99 + k, spread=0.5)
              for k in range(1, 7)]
        self.assertAlmostEqual(autopilot.score_direction("BUY", 2.0, up, 6), (106 - 100.5) / 2.0)  # entry open 100 + spread
        self.assertAlmostEqual(autopilot.score_direction("SELL", 2.0, up, 6), (100 - 106.5) / 2.0)  # exit pays the spread
        self.assertIsNone(autopilot.score_direction("BUY", 2.0, up[:5], 6))
        self.assertIsNone(autopilot.score_direction("BUY", 0, up, 6))

    def test_every_buy_or_sell_of_a_scored_cycle_is_scored_even_when_its_position_slot_is_taken(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": NOW}
            store, pilot, state = build(temp, {"XAUUSD": rising("XAUUSD")}, clock=lambda: clock["now"])
            pilot.run_symbol("XAUUSD")
            pending = self.rows(store, "direction_pending")
            arms = {d["arm"]: d["decision_id"] for d in decisions(store)}
            self.assertIn(arms["det:graph"], {r["decision_id"] for r in pending})
            self.assertIn(arms["random:coin"], {r["decision_id"] for r in pending})
            self.assertEqual({r["horizon_bars"] for r in pending}, {6})  # 30 minutes of M5 bars
            # the next bar is not a scored cycle (cadence), so nothing new is registered
            clock["now"] = NOW + timedelta(minutes=5)
            state["candles"]["XAUUSD"] = rising("XAUUSD", end=LAST_CLOSE + STEP)
            pilot.run_symbol("XAUUSD")
            self.assertEqual(len(self.rows(store, "direction_pending")), len(pending))
            # after the horizon the score is written and the pending row disappears
            base = state["candles"]["XAUUSD"]
            more = [candle("XAUUSD", LAST_CLOSE + STEP * k, base[-1].close + 0.4 * (k - 1), spread=0.02)
                    for k in range(2, 9)]
            state["candles"]["XAUUSD"] = base[8:] + more
            clock["now"] = NOW + timedelta(minutes=32)
            pilot.run_symbol("XAUUSD")
            scores = {r["decision_id"]: r["score"] for r in self.rows(store, "direction_scores")}
            self.assertIn(arms["det:graph"], scores)
            self.assertNotIn(arms["det:graph"], {r["decision_id"] for r in self.rows(store, "direction_pending")})
            self.assertIsInstance(scores[arms["det:graph"]], float)  # one number, written once
            kinds = [e["kind"] for e in store.journal.events(200)]
            self.assertIn("autopilot.scored", kinds)

    def test_direction_scores_are_never_taken_across_a_hole_in_the_bars(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = {"now": NOW}
            store, pilot, state = build(temp, {"XAUUSD": rising("XAUUSD")}, clock=lambda: clock["now"])
            pilot.run_symbol("XAUUSD")
            later = LAST_CLOSE + STEP * 100
            state["candles"]["XAUUSD"] = rising("XAUUSD", end=later, n=60)
            clock["now"] = later + timedelta(minutes=2)
            pilot.run_symbol("XAUUSD")
            self.assertEqual(self.rows(store, "direction_scores"), [])
            first = self.rows(store, "direction_pending")
            self.assertTrue(all(r["at"] != LAST_CLOSE.isoformat() for r in first))

    def test_direction_statistics_compare_forced_agents_with_the_coin_on_many_observations(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp) / "t.db"))
            n = [0]

            def add(arm, values):
                for value in values:
                    n[0] += 1
                    did = f"{arm}-{n[0]}"
                    with store.journal.connect() as db:
                        db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?)",
                                   (did, did, "XAUUSD", NOW.isoformat(), "London", arm, "BUY", "skipped_open", "{}"))
                        db.execute("INSERT INTO direction_scores VALUES(?,?,?,?)", (did, NOW.isoformat(), 6, value))
            add("forced:graph", [0.5, 0.3, 0.6] * 15)
            add("random:coin", [-0.2, 0.2] * 22)
            add("skills:graph", [0.1, 0.0] * 20)
            add("plain:graph", [-0.1, 0.0] * 20)
            report = autopilot_stats.performance(store)["direction"]
            self.assertEqual(report["observations"], 45 + 44 + 40 + 40)
            self.assertTrue(report["forced_vs_random"]["graph"]["clearly_helps"])
            self.assertEqual(report["arms"]["random:coin"]["trades"], 44)
            self.assertIsNotNone(report["skills_vs_plain"]["graph"]["difference"])

    def test_a_freshly_added_symbol_is_asked_again_until_its_history_has_synchronised(self):
        from trading_pro.autopilot_runtime import fetch_when_fresh
        old = [candle("S", LAST_CLOSE - timedelta(hours=5), 100)]
        new = [candle("S", LAST_CLOSE, 100)]
        answers = [(old, {"n": 1}), (old, {"n": 2}), (new, {"n": 3})]
        pauses = []
        result = fetch_when_fresh(lambda: answers.pop(0), step_seconds=300, clock=lambda: LAST_CLOSE.timestamp() + 120,
                                  sleep=pauses.append)
        self.assertEqual(result[1]["n"], 3)
        self.assertEqual(len(pauses), 2)
        pauses.clear()
        fresh = fetch_when_fresh(lambda: (new, {"n": 9}), step_seconds=300, clock=lambda: LAST_CLOSE.timestamp() + 120,
                                 sleep=pauses.append)
        self.assertEqual((fresh[1]["n"], pauses), (9, []))
        # a market that stays closed is given up on after the bounded number of tries and reported as it is
        tries = []
        stale = fetch_when_fresh(lambda: (tries.append(1) or (old, {"n": 0})), step_seconds=300,
                                 clock=lambda: LAST_CLOSE.timestamp() + 120, sleep=lambda s: None)
        self.assertEqual((len(tries), stale[1]["n"]), (4, 0))

    def test_only_the_first_fetch_of_a_symbol_waits(self):
        from unittest import mock
        from trading_pro import autopilot_runtime
        calls = []
        old = [candle("S", LAST_CLOSE - timedelta(hours=5), 100)]

        def fake_fetch(module, **kwargs):
            calls.append(kwargs["symbol"])
            return old, {"server_offset_hours": 0.0}
        env = {"TIP_MT5_DEMO_LOGIN": "123", "TIP_MT5_DEMO_SERVER": "Srv"}
        with mock.patch("trading_pro.mt5_history.fetch", fake_fetch), mock.patch.object(autopilot_runtime.time, "sleep", lambda s: None):
            fetch = autopilot_runtime.mt5_fetcher(module=object(), environ=env, clock=lambda: LAST_CLOSE.timestamp() + 120)
            fetch("Boom 500 Index", "M5", 50)
            self.assertEqual(len(calls), 4)  # warm-up: four bounded attempts
            fetch("Boom 500 Index", "M5", 50)
            self.assertEqual(len(calls), 5)  # afterwards a single attempt: stale means closed, not unsynchronised

    def test_stale_synthetic_symbols_are_retried_after_a_minute_but_gold_waits_longer(self):
        with tempfile.TemporaryDirectory() as temp:
            late = NOW + timedelta(hours=3)
            store, pilot, _ = build(temp, {"XAUUSD": rising("XAUUSD"), "Boom 500 Index": rising("Boom 500 Index")},
                                    clock=lambda: late)
            autopilot.set_config(store, {"symbols": ["XAUUSD", "Boom 500 Index"]}, author="t")
            autopilot.set_mode(store, "observe", author="t")
            runner = AutopilotRunner(pilot)
            runner.tick()
            self.assertEqual(runner._next_check["Boom 500 Index"], late + timedelta(seconds=60))
            self.assertEqual(runner._next_check["XAUUSD"], late + timedelta(seconds=300))


class SettingsLevelTests(unittest.TestCase):
    def test_risk_level_is_versioned_validated_and_feeds_the_risk_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp) / "db.sqlite"))
            current = service.settings()
            self.assertEqual(current["settings"]["risk"]["risk_per_trade"], 0.005)
            changed = {**current["settings"], "risk": {**current["settings"]["risk"], "risk_per_trade": 0.01,
                                                         "max_open_risk": 0.02, "max_positions": 3, "fixed_lot": 0.05}}
            service.update_settings(changed, 0, "test")
            limits = service.limits()
            self.assertEqual((limits.risk_per_trade, limits.max_open_risk, limits.max_positions), (0.01, 0.02, 3))
            self.assertEqual(service.settings()["settings"]["risk"]["fixed_lot"], 0.05)
            for bad in ({"risk_per_trade": 0.5}, {"max_positions": 0}, {"max_positions": 2.5}, {"fixed_lot": 0},
                        {"max_open_risk": 0.0006, "risk_per_trade": 0.01}, {"max_daily_loss": True}):
                with self.assertRaises(ValueError, msg=str(bad)):
                    service.update_settings({**changed, "risk": {**changed["risk"], **bad}}, 1, "test")
            with self.assertRaises(ValueError):
                service.update_settings({**changed, "risk": {"risk_per_trade": 0.01}}, 1, "test")
            kinds = [e["kind"] for e in service.store.journal.events(5)]
            self.assertIn("settings.changed", kinds)

    def test_older_saved_settings_still_load_with_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp) / "db.sqlite"))
            with service.store.journal.connect() as db:
                db.execute("INSERT INTO settings VALUES(1,'2026-11-01T00:00:00+00:00',?)", (json.dumps(
                    {"mode": "observation", "model_by_agent": {"graph": "m"}, "daily_ai_limit_usd": 5,
                     "experiment_ai_limit_usd": 50, "quote_max_age_seconds": 5}),))
            loaded = service.settings()["settings"]
            self.assertTrue(loaded["ai_cap_enabled"])
            self.assertEqual(loaded["risk"]["max_positions"], 2)

    def test_the_ai_ceiling_can_be_removed_and_spend_is_still_measured(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp) / "db.sqlite"))
            capped = service.settings()["settings"]
            self.assertEqual(service.model_budget().daily_usd, 5)
            service.update_settings({**capped, "ai_cap_enabled": False}, 0, "test")
            budget = service.model_budget()
            self.assertEqual((budget.daily_usd, budget.experiment_usd), (float("inf"), float("inf")))
            service.store.record_usage(agent="graph", provider="p", model="m", input_tokens=1, output_tokens=1, cost_usd=7.5)
            costs = service.read("/costs")
            self.assertFalse(costs["cap_enabled"])
            self.assertFalse(costs["new_model_calls_blocked"])
            self.assertEqual(costs["total_usd"], 7.5)
            with self.assertRaises(ValueError):
                service.update_settings({**capped, "ai_cap_enabled": "no"}, 1, "test")

    def test_autopilot_config_endpoint_needs_the_key_and_validates(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp) / "db.sqlite"))
            cls = handler_factory(service, "secret-key", None)
            caller = HttpAndProviderTests().call
            self.assertEqual(caller(cls, "PATCH", "/autopilot/config", b'{"horizon_bars": 20}')[0], 403)
            code, payload = caller(cls, "PATCH", "/autopilot/config", b'{"horizon_bars": 20}', key="secret-key")
            self.assertEqual((code, payload["config"]["horizon_bars"]), (200, 20))
            self.assertEqual(caller(cls, "PATCH", "/autopilot/config", b'{"horizon_bars": 1}', key="secret-key")[0], 400)
            self.assertEqual(caller(cls, "PATCH", "/autopilot/config", b'[1]', key="secret-key")[0], 400)


if __name__ == "__main__":
    unittest.main()
