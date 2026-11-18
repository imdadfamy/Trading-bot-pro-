import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from trading_pro.backtest import BacktestConfig, run_baseline
from trading_pro.market import Candle

START = datetime(2026, 11, 2, tzinfo=timezone.utc)
SPREAD, SLIPPAGE = 0.4, 0.05


def wave(bid_built=True, count=240, amplitude=6.0):
    """Zig-zag series with many crossovers; bars on the bid price when ``bid_built`` else on the mid price."""
    bars, previous = [], 100.0
    for i in range(count):
        close = round(100 + amplitude * math.sin(i / 7), 4)
        high, low = max(previous, close) + 0.3, min(previous, close) - 0.3
        bid, ask = (close, close + SPREAD) if bid_built else (close - SPREAD / 2, close + SPREAD / 2)
        at = START + timedelta(minutes=5 * i)
        bars.append(Candle("TEST", at, at + timedelta(minutes=5), previous, high, low, close, bid, ask, "demo"))
        previous = close
    return bars


def config(basis):
    return BacktestConfig(stop_distance=1.5, slippage_price=SLIPPAGE, commission_per_lot_round_trip=0.0,
                          point_value_per_lot=1.0, price_basis=basis)


def first(ledger, side):
    return next(t for t in ledger if t["action"] == side)


class PriceBasisTests(unittest.TestCase):
    def test_bid_built_bars_pay_the_full_spread_on_a_buy_and_none_on_a_sell(self):
        bars = wave(bid_built=True)
        by_time = {c.opened_at.isoformat(): c for c in bars}
        ledger = run_baseline(bars, config("bid"))["trades"]
        buy, sell = first(ledger, "BUY"), first(ledger, "SELL")
        self.assertAlmostEqual(buy["entry"], by_time[buy["entered_at"]].open + SPREAD + SLIPPAGE, places=6)
        self.assertAlmostEqual(sell["entry"], by_time[sell["entered_at"]].open - SLIPPAGE, places=6)

    def test_mid_basis_keeps_half_a_spread_each_way(self):
        bars = wave(bid_built=False)
        by_time = {c.opened_at.isoformat(): c for c in bars}
        ledger = run_baseline(bars, config("mid"))["trades"]
        buy, sell = first(ledger, "BUY"), first(ledger, "SELL")
        self.assertAlmostEqual(buy["entry"], by_time[buy["entered_at"]].open + SPREAD / 2 + SLIPPAGE, places=6)
        self.assertAlmostEqual(sell["entry"], by_time[sell["entered_at"]].open - SPREAD / 2 - SLIPPAGE, places=6)

    def test_auto_detects_the_basis_from_the_bars(self):
        self.assertEqual(run_baseline(wave(True), config("auto"))["config"]["resolved_price_basis"], "bid")
        self.assertEqual(run_baseline(wave(False), config("auto"))["config"]["resolved_price_basis"], "mid")

    def test_bid_basis_is_never_cheaper_than_ignoring_the_spread_and_rejects_bad_values(self):
        bars = wave(True, amplitude=2.0)  # swings only slightly larger than the spread-adjusted stop
        costly = run_baseline(bars, config("bid"))["metrics"]["net_pnl"]
        flat = run_baseline([Candle(c.symbol, c.opened_at, c.closed_at, c.open, c.high, c.low, c.close, c.close,
                                    c.close, c.broker) for c in bars], config("bid"))["metrics"]["net_pnl"]
        self.assertLess(costly, flat)  # same prices, real spread: a winning series turns into a loss
        self.assertGreater(flat, 0)
        self.assertLess(costly, 0)
        with self.assertRaises(ValueError):
            run_baseline(bars, BacktestConfig(price_basis="ask"))


class SpikeGapFillTests(unittest.TestCase):
    """A stop hit by a spike fills after the jump, not at the stop price."""

    def bars(self, spike_low):
        bars, previous = [], 100.0
        for i in range(60):
            close = spike_low + 0.1 if i == 41 else 100.0
            low = spike_low if i == 41 else min(previous, close) - 0.1
            high = max(previous, close) + 0.1
            at = START + timedelta(minutes=5 * i)
            bars.append(Candle("TEST", at, at + timedelta(minutes=5), previous, high, low, close, close, close + 0.02, "demo"))
            previous = close
        return bars

    def trade(self, fill, spike_low=96.0):
        bars = self.bars(spike_low)
        fired = []

        def once(closes, _candles):
            if len(closes) == 40 and not fired:
                fired.append(1)
                return "BUY"
        cfg = BacktestConfig(stop_distance=0.5, slippage_price=0.0, commission_per_lot_round_trip=0.0,
                             point_value_per_lot=1.0, min_lot=0.01, stop_fill=fill)
        from trading_pro.backtest import run_rule
        return run_rule(bars, cfg, once, "test", warmup=30)["trades"][0]

    def test_spike_bar_fills_at_the_adverse_extreme_only_in_spike_gap_mode(self):
        level, gap = self.trade("level"), self.trade("spike_gap")
        self.assertAlmostEqual(level["exit"], level["entry"] - 0.5, places=6)  # stop price
        self.assertAlmostEqual(gap["exit"], 96.0, places=6)                    # the jump's extreme
        self.assertLess(gap["pnl"], level["pnl"])

    def test_an_ordinary_bar_is_not_treated_as_a_spike_and_options_are_validated(self):
        ordinary_level, ordinary_gap = self.trade("level", 99.4), self.trade("spike_gap", 99.4)
        self.assertAlmostEqual(ordinary_level["exit"], ordinary_gap["exit"], places=6)  # range 0.8 is below 5 x 0.2
        with self.assertRaises(ValueError):
            run_baseline(self.bars(96.0), BacktestConfig(stop_fill="worst"))
        with self.assertRaises(ValueError):
            run_baseline(self.bars(96.0), BacktestConfig(spike_range_factor=1.0))


class CommandOptionTests(unittest.TestCase):
    def run_cli(self, *argv):
        from trading_pro import cli
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["cli", *argv]), \
                mock.patch("trading_pro.local_env.load_local_env", return_value=()), \
                contextlib.redirect_stdout(out):
            cli.main()
        return json.loads(out.getvalue())

    def test_backtest_takes_the_contract_of_the_instrument(self):
        from trading_pro.deriv_history import write_csv
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "bars.csv"
            write_csv(wave(True), csv_path)
            report = self.run_cli("--database", str(Path(folder) / "t.db"), "backtest", str(csv_path),
                                  "--stop-from-range", "2", "--point-value", "0.01", "--max-lot", "15",
                                  "--lot-step", "0.001", "--commission", "0", "--slippage", "0")
            cfg = report["config"]
            self.assertEqual((cfg["point_value_per_lot"], cfg["max_lot"], cfg["lot_step"], cfg["commission_per_lot_round_trip"]),
                             (0.01, 15.0, 0.001, 0.0))
            self.assertAlmostEqual(cfg["stop_distance"], 2 * 0.6 + 2 * 0.3 * 0 + (cfg["stop_distance"] - 1.2), places=6)
            self.assertEqual(cfg["resolved_price_basis"], "bid")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.run_cli("--database", str(Path(folder) / "t.db"), "backtest", str(csv_path),
                             "--stop-distance", "1", "--stop-from-range", "2")


if __name__ == "__main__":
    unittest.main()
