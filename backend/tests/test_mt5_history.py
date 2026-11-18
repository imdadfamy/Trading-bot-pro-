import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from trading_pro.backtest import load_candles
from trading_pro.deriv_history import write_csv
from trading_pro.mt5_history import fetch, server_offset_seconds
from trading_pro.mt5_status import ReadOnlyMT5

LOGIN, SERVER = 123456789, "Test-Demo"
NOW = 1_700_000_000 - (1_700_000_000 % 300) + 120  # two minutes into an M5 bar


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_H1 = 1, 5, 16385

    def __init__(self, *, offset_hours=2, visible=True, mode=0, tick_age=5, spread=18, rates=None, frozen=False):
        self.offset, self.visible, self.mode, self.tick_age, self.spread = offset_hours * 3600, visible, mode, tick_age, spread
        self.calls, self.requested, self._rates, self.frozen, self.polls = [], None, rates, frozen, 0

    def initialize(self, **kwargs): self.calls.append("initialize"); return True
    def shutdown(self): self.calls.append("shutdown")
    def last_error(self): return (0, "ok")
    def account_info(self): return NS(login=LOGIN, trade_mode=self.mode)
    def symbol_info(self, name): return NS(visible=self.visible, point=0.01)
    def symbol_select(self, name, enable): self.calls.append("symbol_select"); return True
    def symbol_info_tick(self, name):
        self.polls += 1
        return NS(time=NOW + self.offset - self.tick_age + (0 if self.frozen else self.polls), bid=1, ask=1)

    def copy_rates_from_pos(self, symbol, frame, start, count):
        self.requested = (symbol, frame, start, count)
        if self._rates is not None:
            return self._rates
        bars = []
        first_open = NOW - (NOW % 300) - 300 * (count - 1)  # the last bar (forming) opens at NOW - NOW % 300
        for i in range(count):
            price = 2000 + i * 0.1
            bars.append({"time": first_open + 300 * i + self.offset, "open": price, "high": price + 0.5,
                         "low": price - 0.5, "close": price + 0.1, "tick_volume": 100 + i, "spread": self.spread,
                         "real_volume": 0})
        return bars

    def order_send(self, request): raise AssertionError("no trading function may be reachable")


def run(fake, **kwargs):
    options = dict(symbol="XAUUSD", timeframe="M5", count=6, expected_login=LOGIN, server=SERVER, password=None,
                   now_epoch=NOW, sleep=lambda seconds: None)
    options.update(kwargs)
    return fetch(fake, **options)


class Mt5HistoryTests(unittest.TestCase):
    def test_closed_bars_only_with_utc_times_and_real_spread(self):
        fake = FakeMT5(offset_hours=2)
        candles, meta = run(fake)
        self.assertEqual(fake.requested, ("XAUUSD", 5, 0, 7))  # one extra position for the forming bar
        self.assertEqual(len(candles), 6)
        self.assertTrue(all(c.closed_at.timestamp() <= NOW for c in candles))
        self.assertEqual(meta["server_offset_hours"], 2.0)
        last = candles[-1]
        self.assertEqual(last.closed_at.timestamp(), NOW - NOW % 300)  # last closed bar ends at the bar boundary
        self.assertAlmostEqual(last.ask - last.bid, 0.18)  # 18 points x 0.01
        self.assertEqual(last.bid, last.close)
        self.assertEqual(last.broker, SERVER)
        self.assertEqual((meta["median_spread"], meta["zero_spread_bars"], meta["orders_sent"]), (0.18, 0, 0))
        self.assertEqual(fake.calls[-1], "shutdown")

    def test_server_clock_is_measured_from_a_fresh_tick_or_given_explicitly(self):
        mt5 = ReadOnlyMT5(FakeMT5(offset_hours=3))
        self.assertEqual(server_offset_seconds(mt5, "XAUUSD", now_epoch=NOW, explicit_hours=None, wait_seconds=5,
                                               sleep=lambda s: None), 3 * 3600)
        stale = ReadOnlyMT5(FakeMT5(offset_hours=3, tick_age=1800))
        with self.assertRaisesRegex(RuntimeError, "No live tick"):
            server_offset_seconds(stale, "XAUUSD", now_epoch=NOW, explicit_hours=None)  # no wait: immediate refusal
        frozen_hour = ReadOnlyMT5(FakeMT5(offset_hours=0, tick_age=3600, frozen=True))  # looks like a -1 h offset
        ticking = iter(range(1000, 2000))
        with self.assertRaisesRegex(RuntimeError, "No live tick"):
            server_offset_seconds(frozen_hour, "XAUUSD", now_epoch=NOW, explicit_hours=None, wait_seconds=5,
                                  sleep=lambda s: None, clock=lambda: next(ticking))
        self.assertEqual(server_offset_seconds(stale, "XAUUSD", now_epoch=NOW, explicit_hours=-5), -5 * 3600)
        with self.assertRaises(ValueError):
            server_offset_seconds(stale, "XAUUSD", now_epoch=NOW, explicit_hours=20)
        candles, meta = run(FakeMT5(offset_hours=3, tick_age=1800), utc_offset_hours=3)  # weekend-style run
        self.assertEqual(meta["server_offset_hours"], 3.0)

    def test_a_symbol_just_added_to_market_watch_gets_a_few_seconds_to_receive_a_tick(self):
        class WarmingUp(FakeMT5):
            def symbol_info_tick(self, name):
                self.polls += 1
                if self.polls < 3:  # frozen old tick on the first polls, then the live feed starts
                    return NS(time=NOW - 7200, bid=1, ask=1)
                return NS(time=NOW + self.polls, bid=1, ask=1)
        slept, fake = [], WarmingUp(offset_hours=0)
        clock = iter(range(1000, 1100))
        offset = server_offset_seconds(ReadOnlyMT5(fake), "Boom 500 Index", now_epoch=NOW,
                                       explicit_hours=None, wait_seconds=8, sleep=slept.append, clock=lambda: next(clock))
        self.assertEqual((offset, fake.polls >= 4, len(slept) >= 3), (0, True, True))
        with self.assertRaisesRegex(RuntimeError, "No live tick"):  # never fresh: gives up after the wait
            tick_clock = iter(range(1000, 1100))
            server_offset_seconds(ReadOnlyMT5(FakeMT5(tick_age=7200, frozen=True)), "X", now_epoch=NOW, explicit_hours=None,
                                  wait_seconds=3, sleep=lambda s: None, clock=lambda: next(tick_clock))

    def test_symbol_must_be_in_market_watch_unless_select_is_requested(self):
        with self.assertRaisesRegex(RuntimeError, "Market Watch"):
            run(FakeMT5(visible=False))
        fake = FakeMT5(visible=False)
        run(fake, select=True)
        self.assertIn("symbol_select", fake.calls)

    def test_real_account_unknown_timeframe_and_bad_counts_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, "not DEMO"):
            run(FakeMT5(mode=2))
        for kwargs in ({"timeframe": "M7"}, {"count": 1}, {"count": 60000}):
            with self.assertRaises(ValueError):
                run(FakeMT5(), **kwargs)

    def test_bad_series_are_refused_and_csv_round_trips(self):
        duplicate = [{"time": NOW - 900 + 0, "open": 1, "high": 2, "low": 0.5, "close": 1, "tick_volume": 1, "spread": 0}] * 3
        with self.assertRaisesRegex(RuntimeError, "chronological|Duplicate"):
            run(FakeMT5(offset_hours=0, rates=duplicate))
        with self.assertRaisesRegex(RuntimeError, "No bars"):
            run(FakeMT5(rates=[]))
        candles, _ = run(FakeMT5())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gold.csv"
            write_csv(candles, path)
            loaded = load_candles(path)
        self.assertEqual([c.ask for c in loaded], [c.ask for c in candles])
        self.assertEqual({c.broker for c in loaded}, {SERVER})


if __name__ == "__main__":
    unittest.main()
