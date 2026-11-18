import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_pro.analytics import TradeResult, performance
from trading_pro.backtest import BacktestConfig, load_candles, run_baseline, chronological_evaluation
from trading_pro.market import Candle, closed_as_of, session_label, sessions_at
from trading_pro.news import active_halt, normalize_event
from trading_pro.orchestrator import analyze
from trading_pro.service import Service
from trading_pro.store import ResearchStore
from trading_pro.quality import assess


def bar(at, price=2000):
    return Candle("XAUUSD", at, at+timedelta(minutes=5), price, price+1, price-1,
                  price, price-.1, price+.1, "synthetic")


class ResearchTests(unittest.TestCase):
    def test_closed_candles_exclude_future_and_duplicates(self):
        t = datetime(2025, 1, 6, 8, tzinfo=timezone.utc)
        self.assertEqual(closed_as_of([bar(t), bar(t+timedelta(minutes=5))], t+timedelta(minutes=5)), [bar(t)])
        with self.assertRaises(ValueError):
            closed_as_of([bar(t), bar(t)], t+timedelta(minutes=5))

    def test_quality_gate_rejects_gap_stale_and_unclosed(self):
        t = datetime(2025, 1, 6, 8, tzinfo=timezone.utc)
        candles = [bar(t), bar(t+timedelta(minutes=10))]
        report = assess(candles, t+timedelta(minutes=15), expected_seconds=300, max_age_seconds=1)
        self.assertIn("Unexplained market gaps", report.reasons)
        report = assess([bar(t)], t+timedelta(minutes=15), expected_seconds=300, max_age_seconds=1)
        self.assertIn("Stale market data", report.reasons)
        report = assess([bar(t)], t+timedelta(minutes=2), expected_seconds=300, max_age_seconds=1)
        self.assertIn("Unclosed or future candle", report.reasons)

    def test_sessions_and_dst(self):
        self.assertIn("London", sessions_at(datetime(2025, 1, 6, 9, tzinfo=timezone.utc)))
        self.assertIn("London", sessions_at(datetime(2025, 7, 7, 7, tzinfo=timezone.utc)))
        self.assertEqual(session_label(datetime(2025, 1, 6, 15, tzinfo=timezone.utc)), "London/New York overlap")

    def test_unconfirmed_critical_halts_then_retraction(self):
        at = datetime(2025, 1, 6, 10, tzinfo=timezone.utc)
        event = normalize_event(source="official", url="https://example.org/event", headline="Release",
                                published_at=at, received_at=at+timedelta(seconds=2),
                                severity="critical", assets=("XAUUSD",), status="retracted",
                                verified_at=at+timedelta(minutes=5))
        self.assertTrue(active_halt([event], "XAUUSD", at+timedelta(minutes=2)))
        self.assertFalse(active_halt([event], "XAUUSD", at+timedelta(minutes=6)))

    def test_news_revisions_replay_as_of_receipt(self):
        at = datetime(2025, 1, 6, 10, tzinfo=timezone.utc)
        first = normalize_event(source="official", url="https://example.org/event", headline="Release",
                                published_at=at, received_at=at+timedelta(seconds=2),
                                severity="critical", assets=("XAUUSD",))
        later = normalize_event(source="official", url="https://example.org/event", headline="Release",
                                published_at=at, received_at=at+timedelta(minutes=5),
                                verified_at=at+timedelta(minutes=5), status="retracted",
                                severity="critical", assets=("XAUUSD",))
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchStore(str(Path(tmp)/"db.sqlite"))
            self.assertTrue(store.news(first))
            self.assertTrue(store.news(later))
            self.assertFalse(store.news(later))
            self.assertEqual(store.news_as_of(at+timedelta(minutes=1))[0]["status"], "unconfirmed")
            self.assertEqual(store.news_as_of(at+timedelta(minutes=6))[0]["status"], "retracted")

    def test_metrics_undefined_without_losses(self):
        summary = performance([TradeResult(10, 5, 1, "London", "baseline")], 10000)
        self.assertIsNone(summary["profit_factor"])
        self.assertTrue(summary["small_sample"])

    def test_offline_cycle_and_settings_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/"research.db")
            store = ResearchStore(path)
            cycle = analyze(store, symbol="XAUUSD", broker="synthetic", bid=2000, ask=2000.1,
                            closed_prices=[2000+i*.1 for i in range(30)])
            self.assertEqual(cycle["signal"].action.value, "WAIT")
            service = Service(path)
            self.assertEqual(len(service.read("/skills")), 27)
            self.assertEqual(len(service.read("/signals")), 1)
            current = service.settings()
            self.assertEqual(current["version"], 0)
            result = service.update_settings(current["settings"], 0, "test")
            self.assertEqual(result["version"], 1)
            with self.assertRaises(RuntimeError):
                service.update_settings(current["settings"], 0, "test")
            with self.assertRaises(ValueError):
                service.update_settings({**current["settings"], "mode": "real"}, 1, "test")
            self.assertTrue(store.killed())
            store.remember(cause="data", evidence="missing tick", recommendation="verify source", cycle_id=cycle["snapshot"].cycle_id)
            self.assertEqual(len(service.read("/memory")), 1)

    def test_backtest_next_bar_and_costs(self):
        t = datetime(2025, 1, 6, 8, tzinfo=timezone.utc)
        prices = [2000]*21+[2003]+[2004]*4+[1996]*6
        candles = [bar(t+timedelta(minutes=5*i), p) for i,p in enumerate(prices)]
        result = run_baseline(candles, BacktestConfig(stop_distance=2))
        self.assertGreaterEqual(result["metrics"]["trades"], 1)
        self.assertGreater(result["metrics"]["total_fees"], 0)
        self.assertGreaterEqual(result["trades"][0]["entered_at"], candles[22].opened_at.isoformat())

    def test_chronological_splits_do_not_overlap(self):
        t = datetime(2025, 1, 6, 8, tzinfo=timezone.utc)
        candles = [bar(t+timedelta(minutes=5*i), 2000+i*.01) for i in range(200)]
        result = chronological_evaluation(candles)
        self.assertLessEqual(result["train"]["end"], result["validation"]["start"])
        self.assertLessEqual(result["validation"]["end"], result["test"]["start"])


if __name__ == "__main__":
    unittest.main()
