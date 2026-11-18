import contextlib
import io
import json
import random
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from trading_pro import synthetic_rules as sr
from trading_pro.backtest import BacktestConfig
from trading_pro.market import Candle

START = datetime(2026, 11, 2, tzinfo=timezone.utc)


def series(returns, price=1000.0, spread=0.05):
    """Bid-built bars from a list of one-bar returns."""
    bars, close = [], price
    for i, r in enumerate(returns):
        previous, close = close, close * (1 + r)
        at = START + timedelta(minutes=5 * i)
        high, low = max(previous, close) * 1.0004, min(previous, close) * 0.9996
        bars.append(Candle("TEST", at, at + timedelta(minutes=5), previous, high, low, close, close, close + spread, "demo"))
    return bars


def calm(n, seed=1, sigma=0.0008):
    rng = random.Random(seed)
    return [rng.gauss(0, sigma) for _ in range(n)]


def config(bars):
    from statistics import median
    return BacktestConfig(stop_distance=2.5 * median(b.high - b.low for b in bars), slippage_price=0.0,
                          commission_per_lot_round_trip=0.0, point_value_per_lot=1.0, min_lot=0.01, max_lot=50)


class SignalTests(unittest.TestCase):
    def closes(self, last_return):
        base = [1000.0]
        for r in calm(150, seed=3):
            base.append(base[-1] * (1 + r))
        base.append(base[-1] * (1 + last_return))
        return base

    def test_fade_and_follow_are_mirror_images_on_a_spike_and_silent_otherwise(self):
        up, down, small = self.closes(0.02), self.closes(-0.02), self.closes(0.0005)
        fade, follow = sr.large_move_rule("fade"), sr.large_move_rule("follow")
        self.assertEqual((fade(up, []), fade(down, [])), ("SELL", "BUY"))
        self.assertEqual((follow(up, []), follow(down, [])), ("BUY", "SELL"))
        self.assertIsNone(fade(small, []))
        self.assertIsNone(fade([1000.0, 1001.0], []))  # no scale yet: no trade

    def test_drift_and_anticipation_rules_wait_for_calm_and_refuse_when_a_spike_is_recent(self):
        quiet = self.closes(0.0004)
        self.assertEqual(sr.drift_rider("SELL")(quiet, []), "SELL")
        recent = quiet[:-2] + [quiet[-2] * 1.03, quiet[-2] * 1.03 * 1.0004]  # spike two bars ago
        self.assertIsNone(sr.drift_rider("SELL")(recent, []))
        self.assertEqual(sr.spike_anticipation("BUY")(quiet, []), "BUY")
        self.assertIsNone(sr.spike_anticipation("BUY")(recent, []))
        self.assertIsNone(sr.drift_rider("SELL")([1000.0] * 5, []))  # unknown scale is treated as unsafe

    def test_zscore_rule_needs_a_two_sigma_move(self):
        fade = sr.zscore_rule("fade")
        self.assertEqual(fade(self.closes(0.02), []), "SELL")
        self.assertIsNone(fade(self.closes(0.0002), []))
        self.assertIsNone(fade([1000.0] * 10, []))

    def test_rules_by_family_include_the_reference_and_reject_unknown_families(self):
        bars = series(calm(200))
        for family, count in (("boom", 5), ("crash", 5), ("volatility", 3)):
            self.assertEqual(len(sr.rules_for(family, config(bars))), count)
        with self.assertRaises(ValueError):
            sr.rules_for("step", config(bars))


class EvaluationTests(unittest.TestCase):
    def test_structure_determinism_and_input_checks(self):
        bars = series(calm(500, seed=5))
        first = sr.evaluate(bars, "volatility", config(bars), null_runs=50, seed=7)
        again = sr.evaluate(bars, "volatility", config(bars), null_runs=50, seed=7)
        self.assertEqual(first, again)  # same seed, same answer
        self.assertEqual((first["rules_tested"], first["significance_threshold"]), (3, 0.05 / 3))
        self.assertIn("test", first["rules"][0]["periods"])
        for row in first["rules"]:
            if row["p_value"] is not None:
                self.assertTrue(0 < row["p_value"] <= 1)
        with self.assertRaises(ValueError):
            sr.evaluate(bars, "volatility", config(bars), null_runs=10)

    def test_pure_noise_does_not_produce_a_significant_rule(self):
        bars = series(calm(900, seed=11))
        report = sr.evaluate(bars, "volatility", config(bars), null_runs=60, seed=3)
        self.assertFalse(any(row["significant"] for row in report["rules"]))

    def test_a_planted_edge_is_detected(self):
        """Large shocks that keep going: the 'follow' rule must beat random entries clearly."""
        rng, returns = random.Random(21), []
        while len(returns) < 1500:
            returns.extend(rng.gauss(0, 0.0008) for _ in range(rng.randint(12, 25)))
            shock = rng.choice((-1, 1))
            returns.append(shock * 0.006)
            returns.extend(shock * 0.0025 for _ in range(4))  # strong continuation
        bars = series(returns[:1500])
        report = sr.evaluate(bars, "volatility", config(bars), null_runs=60, seed=2)
        follow = next(r for r in report["rules"] if r["rule"].startswith("avec"))
        fade = next(r for r in report["rules"] if r["rule"].startswith("contre"))
        self.assertGreater(follow["expectancy_r"], 0)
        self.assertLessEqual(follow["p_value"], 0.05 / 3)
        self.assertTrue(follow["significant"])
        self.assertLess(fade["expectancy_r"], 0)  # the mirror rule loses

    def test_rules_with_too_few_trades_get_no_p_value(self):
        bars = series(calm(120, seed=2))
        report = sr.evaluate(bars, "volatility", config(bars), null_runs=50, min_trades=500)
        self.assertTrue(all(r["p_value"] is None and not r["significant"] for r in report["rules"]))


class CommandTests(unittest.TestCase):
    def test_command_prints_a_report_and_applies_contract_options(self):
        from trading_pro import cli
        from trading_pro.deriv_history import write_csv
        bars = series(calm(400, seed=9))
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "bars.csv"
            write_csv(bars, csv_path)
            out = io.StringIO()
            argv = ["cli", "--database", str(Path(folder) / "t.db"), "evaluate-rules", str(csv_path), "--family",
                    "volatility", "--null-runs", "50", "--stop-from-range", "2.5", "--point-value", "1",
                    "--commission", "0", "--slippage", "0"]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch("trading_pro.local_env.load_local_env", return_value=()), \
                    contextlib.redirect_stdout(out):
                cli.main()
            report = json.loads(out.getvalue())
        self.assertEqual((report["family"], report["null_runs"]), ("volatility", 50))
        self.assertEqual(report["config"]["point_value_per_lot"], 1.0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            with mock.patch.object(sys, "argv", ["cli", "evaluate-rules", "x.csv", "--family", "step"]):
                cli.main()


if __name__ == "__main__":
    unittest.main()
