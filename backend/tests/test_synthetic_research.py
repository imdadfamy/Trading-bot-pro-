import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from trading_pro.market import Candle
from trading_pro.service import Service
from trading_pro.synthetic_research import describe


def candles(count=102, symbol="Volatility 75 Index"):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = []
    for i in range(count):
        price = 100 + i * .05
        at = start + timedelta(minutes=i)
        result.append(Candle(symbol, at, at + timedelta(minutes=1), price,
                             price + .1, price - .1, price, price - .01,
                             price + .01, "demo-feed"))
    return result


class SyntheticResearchTests(unittest.TestCase):
    def test_report_is_descriptive_and_split(self):
        report = describe(candles(), family="volatility")
        self.assertEqual(report["action"], "WAIT")
        self.assertEqual(report["all"]["observations"], 101)
        self.assertEqual(report["earlier_80_pct"]["observations"] +
                         report["later_20_pct"]["observations"], 101)
        self.assertFalse(report["statistically_sufficient"])
        self.assertEqual(report["all"]["absolute_jump_count"], 0)
        self.assertGreater(report["all"]["jump_frequency_wilson_95"][1], 0)

    def test_rejects_mixed_symbol_and_bad_threshold(self):
        data = candles(3)
        with self.assertRaises(ValueError):
            describe(data[:2] + candles(3, "Boom 500")[2:], family="boom")
        with self.assertRaises(ValueError):
            describe(data, family="step", jump_threshold_pct=float("nan"))
        with self.assertRaises(ValueError):
            describe(data[:1], family="step")

    def test_counts_jumps_and_rejects_overlapping_or_mixed_candles(self):
        data = candles(10)
        spike = data[5]
        data[5] = Candle(spike.symbol, spike.opened_at, spike.closed_at, spike.open,
                         spike.close * 1.03, spike.low, spike.close * 1.02, spike.bid,
                         spike.ask, spike.broker)
        report = describe(data, family="jump", jump_threshold_pct=1.0)
        self.assertGreaterEqual(report["all"]["absolute_jump_count"], 1)
        self.assertEqual(report["action"], "WAIT")
        overlapping = candles(3)
        overlapping[1] = Candle(overlapping[1].symbol, overlapping[0].opened_at,
                                overlapping[0].closed_at + timedelta(seconds=30),
                                100, 100.2, 99.8, 100, 99.99, 100.01, "demo-feed")
        with self.assertRaises(ValueError):
            describe(overlapping, family="other")
        with self.assertRaises(ValueError):
            describe(data, family="not-a-family")

    def test_reports_are_stored_read_only_and_exposed_by_the_service(self):
        report = describe(candles(), family="volatility")
        with tempfile.TemporaryDirectory() as folder:
            service = Service(str(Path(folder) / "t.db"))
            self.assertEqual(service.read("/synthetic/reports"), [])
            identifier = service.store.synthetic_report(report)
            rows = service.read("/synthetic/reports")
            self.assertEqual(rows[0]["id"], identifier)
            self.assertEqual(rows[0]["report"]["action"], "WAIT")
            self.assertEqual(rows[0]["symbol"], "Volatility 75 Index")
            self.assertTrue(service.store.journal.verify_audit())
            with self.assertRaises(ValueError):
                service.store.synthetic_report({**report, "action": "BUY"})


if __name__ == "__main__":
    unittest.main()
