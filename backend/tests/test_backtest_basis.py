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
