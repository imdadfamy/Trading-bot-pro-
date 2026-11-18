import json
import unittest
from types import SimpleNamespace as NS

from trading_pro.mt5_dryrun import DRY_RUN_ALLOWED, dry_run
from trading_pro.mt5_status import ReadOnlyMT5

LOGIN, SERVER = 123456789, "Test-Demo"


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 1, 0, 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC = 0, 1
    SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2
    SYMBOL_TRADE_MODE_FULL = 4
    TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL, TRADE_RETCODE_REJECT = 10009, 10010, 10006

    def __init__(self, *, algo=True, retcode=0, visible=True, volume_min=0.01, stops=20, mode=0):
        self.algo, self.retcode, self.visible, self.volume_min, self.stops, self.mode = algo, retcode, visible, volume_min, stops, mode
        self.calls, self.checked = [], []

    def initialize(self, **kw): self.calls.append("initialize"); return True
    def shutdown(self): self.calls.append("shutdown")
    def last_error(self): return (0, "ok")
    def account_info(self): return NS(login=LOGIN, trade_mode=self.mode)
    def terminal_info(self): return NS(connected=True, trade_allowed=self.algo)
    def symbol_select(self, name, enable): self.calls.append("symbol_select"); return True

    def symbol_info(self, name):
        return NS(name=name, visible=self.visible, point=0.01, digits=2, volume_min=self.volume_min, volume_max=10.0,
                  volume_step=0.01, filling_mode=1, trade_mode=4, trade_stops_level=self.stops)

    def symbol_info_tick(self, name): return NS(time=0, bid=2000.0, ask=2000.18)

    def order_check(self, request):
        self.checked.append(request)
        return NS(retcode=self.retcode, comment="Done" if self.retcode == 0 else "refused", margin=20.5,
                  margin_free=9979.5, balance=10000.0)

    def order_send(self, request): raise AssertionError("order_send must be unreachable")
    positions_get = orders_get = order_send


def run(fake, **kw):
    return dry_run(fake, symbol="XAUUSD", expected_login=LOGIN, server=SERVER, password=None, **kw)


class DryRunTests(unittest.TestCase):
    def test_both_sides_are_checked_with_minimal_volume_and_valid_stops_and_nothing_is_sent(self):
        fake = FakeMT5()
        report = run(fake)
        self.assertEqual((report["orders_sent"], report["trading_algo_enabled"]), (0, True))
        self.assertEqual([c["side"] for c in report["checks"]], ["BUY", "SELL"])
        self.assertEqual(len(fake.checked), 2)
        buy, sell = fake.checked
        self.assertEqual((buy["volume"], buy["type_filling"]), (0.01, fake.ORDER_FILLING_FOK))
        self.assertLess(buy["sl"], buy["price"]); self.assertGreater(buy["tp"], buy["price"])
        self.assertGreater(sell["sl"], sell["price"]); self.assertLess(sell["tp"], sell["price"])
        self.assertGreaterEqual(buy["price"] - buy["sl"], 2 * (0.20 + 0.18) - 1e-9)  # twice (stop level + spread)
        self.assertTrue(all(c["accepted_by_broker"] and c["local_checks"] == "réussis" for c in report["checks"]))
        self.assertEqual(report["checks"][0]["broker_check"]["margin_required"], 20.5)
        self.assertEqual(fake.calls[-1], "shutdown")

    def test_algo_trading_off_is_reported_as_the_broker_answers_it(self):
        fake = FakeMT5(algo=False, retcode=10027)
        report = run(fake, sides=("BUY",))
        check = report["checks"][0]
        self.assertFalse(report["trading_algo_enabled"])
        self.assertFalse(check["accepted_by_broker"])
        self.assertEqual(check["broker_check"]["retcode"], 10027)
        self.assertIn("Trading algo", check["broker_check"]["meaning"])

    def test_local_contract_violations_stop_before_the_broker_is_asked(self):
        fake = FakeMT5()
        fake.symbol_info = lambda name: NS(name=name, visible=True, point=0.01, digits=2, volume_min=0.01, volume_max=10.0,
                                           volume_step=0.01, filling_mode=1, trade_mode=3, trade_stops_level=20)  # close-only
        report = run(fake, sides=("BUY",))
        self.assertIn("fully tradable", report["checks"][0]["local_checks"])
        self.assertEqual(fake.checked, [])
        self.assertFalse(report["checks"][0]["accepted_by_broker"])

    def test_synthetic_index_minimums_are_respected(self):
        fake = FakeMT5(volume_min=0.2, stops=1173)
        fake.symbol_info = lambda name: NS(name=name, visible=True, point=0.001, digits=3, volume_min=0.2, volume_max=190.0,
                                           volume_step=0.01, filling_mode=1, trade_mode=4, trade_stops_level=1173)
        fake.symbol_info_tick = lambda name: NS(time=0, bid=5800.0, ask=5800.08)
        report = dry_run(fake, symbol="Boom 500 Index", sides=("SELL",), expected_login=LOGIN, server=SERVER, password=None)
        order = fake.checked[0]
        self.assertEqual(order["volume"], 0.2)
        self.assertGreaterEqual(abs(order["price"] - order["sl"]), 1.173)  # broker minimum 1173 points
        self.assertTrue(report["checks"][0]["accepted_by_broker"])

    def test_wrapper_allows_order_check_only_and_refuses_account_changes(self):
        guarded = ReadOnlyMT5(FakeMT5(), DRY_RUN_ALLOWED)
        self.assertTrue(guarded.order_check({}))
        for name in ("order_send", "positions_get", "orders_get", "position_close_by"):
            with self.assertRaises(PermissionError):
                getattr(guarded, name)
        self.assertNotIn("order_check", ReadOnlyMT5(FakeMT5()).__dict__)  # default wrapper stays stricter
        with self.assertRaises(PermissionError):
            ReadOnlyMT5(FakeMT5()).order_check

    def test_real_account_hidden_symbol_and_unknown_symbol_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, "not DEMO"):
            run(FakeMT5(mode=2))
        with self.assertRaisesRegex(RuntimeError, "Market Watch"):
            run(FakeMT5(visible=False))
        fake = FakeMT5(visible=False)
        run(fake, select=True)
        self.assertIn("symbol_select", fake.calls)
        gone = FakeMT5()
        gone.symbol_info = lambda name: None
        with self.assertRaisesRegex(RuntimeError, "not found"):
            run(gone)

    def test_report_is_json_and_contains_no_secret(self):
        text = json.dumps(run(FakeMT5()), ensure_ascii=False)
        self.assertNotIn(str(LOGIN), text)


if __name__ == "__main__":
    unittest.main()
