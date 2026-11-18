import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_pro.backtest import load_candles
from trading_pro.broker_hours import explained_gap, schedule_for
from trading_pro.market import Candle
from trading_pro.quality import assess

UTC = timezone.utc
STEP = timedelta(minutes=5)


def utc(*parts):
    return datetime(*parts, tzinfo=UTC)


def week(start, end, daily_break_utc_hour, friday_close_hour, skip=None):
    """M5 bars between two UTC instants following the observed schedule (break and weekend removed)."""
    bars, at = [], start
    while at < end:
        local_break = at.weekday() <= 3 and (at.hour, at.minute) >= (daily_break_utc_hour, 0) \
            and (at.hour, at.minute) < (daily_break_utc_hour + 1, 5)
        weekend = (at.weekday() == 4 and (at.hour, at.minute) >= (friday_close_hour, 50)) or at.weekday() == 5 \
            or (at.weekday() == 6 and (at.hour, at.minute) < (friday_close_hour + 1, 10))
        if not local_break and not weekend and not (skip and skip[0] <= at < skip[1]):
            price = 2000 + (at - start).total_seconds() / 3000
            bars.append(Candle("XAUUSD", at, at + STEP, price, price + 1, price - 1, price + .2, price + .2,
                               price + .35, "Deriv-Demo"))
        at += STEP
    return bars


class ExplainedGapTests(unittest.TestCase):
    def test_gaps_seen_on_the_real_server_are_explained_in_both_seasons(self):
        real = [  # (previous close, next open) in UTC, taken from the 5,000 exported bars
            (utc(2026, 10, 26, 21, 0), utc(2026, 10, 26, 22, 5)),     # summer daily break
            (utc(2026, 11, 3, 22, 0), utc(2026, 11, 3, 23, 5)),       # winter daily break
            (utc(2026, 10, 23, 20, 45), utc(2026, 10, 25, 22, 10)),   # summer weekend
            (utc(2026, 11, 6, 21, 45), utc(2026, 11, 8, 23, 10)),     # winter weekend
        ]
        for start, end in real:
            self.assertTrue(explained_gap(start, end), (start, end))

    def test_anything_else_stays_unexplained(self):
        cases = [
            (utc(2026, 11, 4, 14, 0), utc(2026, 11, 4, 16, 0)),        # midday outage
            (utc(2026, 11, 4, 22, 0), utc(2026, 11, 5, 14, 0)),        # break that lasts all night
            (utc(2026, 11, 3, 21, 0), utc(2026, 11, 3, 22, 5)),        # winter: break is an hour later
            (utc(2026, 11, 6, 21, 45), utc(2026, 11, 9, 23, 10)),      # weekend that lasts until Monday
            (utc(2026, 11, 6, 21, 45), utc(2026, 11, 8, 20, 0)),       # reopening hours too early
            (utc(2026, 11, 7, 12, 0), utc(2026, 11, 8, 23, 10)),       # starts on a Saturday
            (utc(2026, 12, 24, 22, 0), utc(2026, 12, 28, 23, 5)),      # holiday-sized gap
        ]
        for start, end in cases:
            self.assertFalse(explained_gap(start, end), (start, end))

    def test_schedule_only_applies_to_the_observed_symbol_and_broker(self):
        self.assertIs(schedule_for("XAUUSD", "Deriv-Demo"), explained_gap)
        self.assertIsNone(schedule_for("Boom 500 Index", "Deriv-Demo"))
        self.assertIsNone(schedule_for("XAUUSD", "Other-Broker"))


class QualityGateWithScheduleTests(unittest.TestCase):
    def test_a_full_winter_and_summer_week_pass_only_with_the_schedule(self):
        for start, end, hour, friday in ((utc(2026, 11, 8, 23, 10), utc(2026, 11, 13, 21, 50), 22, 21),
                                        (utc(2026, 7, 5, 22, 10), utc(2026, 7, 10, 20, 50), 21, 20)):
            bars = week(start, end, hour, friday)
            as_of = bars[-1].closed_at
            kwargs = dict(expected_seconds=300, max_age_seconds=1)
            self.assertIn("Unexplained market gaps", assess(bars, as_of, **kwargs).reasons)
            report = assess(bars, as_of, explained_gap=explained_gap, **kwargs)
            self.assertTrue(report.accepted, report.reasons)

    def test_an_unplanned_outage_is_still_refused(self):
        bars = week(utc(2026, 11, 8, 23, 10), utc(2026, 11, 13, 21, 50), 22, 21,
                    skip=(utc(2026, 11, 11, 14, 0), utc(2026, 11, 11, 16, 0)))
        report = assess(bars, bars[-1].closed_at, expected_seconds=300, max_age_seconds=1, explained_gap=explained_gap)
        self.assertFalse(report.accepted)
        self.assertEqual(report.reasons, ("Unexplained market gaps",))

    def test_the_exported_real_bars_pass_when_present(self):
        path = Path(__file__).resolve().parents[1] / "data" / "xauusd_m5.csv"  # local broker data, not in Git
        if not path.is_file():
            self.skipTest("local export not present")
        bars = load_candles(path)
        report = assess(bars, bars[-1].closed_at, expected_seconds=300, max_age_seconds=1,
                        explained_gap=schedule_for(bars[0].symbol, bars[0].broker))
        self.assertTrue(report.accepted, report.reasons)


if __name__ == "__main__":
    unittest.main()
