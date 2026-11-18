import json
import unittest
from types import SimpleNamespace as NS

from trading_pro.mt5_status import ReadOnlyMT5, credentials_from_env, inspect

LOGIN, SERVER, PASSWORD = 123456789, "Test-Demo", "s3cret-pass-word"


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2

    def __init__(self, *, logged_in=True, mode=0, init_ok=True, login_ok=True):
        self.logged_in, self.mode, self.init_ok, self.login_ok = logged_in, mode, init_ok, login_ok
        self.calls, self.login_args = [], None

    def _log(self, name):
        self.calls.append(name)

    def initialize(self, **kwargs):
        self._log("initialize")
        return self.init_ok

    def last_error(self):
        return (-6, "Authorization failed")

    def login(self, login, password=None, server=None, timeout=None):
        self._log("login")
        self.login_args = (login, password, server)
        self.logged_in = self.login_ok
        return self.login_ok

    def shutdown(self):
        self._log("shutdown")

    def account_info(self):
        self._log("account_info")
        return NS(login=LOGIN if self.logged_in else 5, trade_mode=self.mode, server=SERVER, currency="USD",
                  leverage=100, balance=10000.0, trade_allowed=True, trade_expert=True)

    def terminal_info(self):
        return NS(connected=True, trade_allowed=False, build=5000, ping_last=42000)

    def symbols_get(self):
        self._log("symbols_get")
        info = dict(description="", path="x", visible=True, digits=2, point=0.01, spread=25, spread_float=True,
                    trade_tick_size=0.01, trade_tick_value=1.0, trade_contract_size=100, volume_min=0.01,
                    volume_max=50, volume_step=0.01, trade_stops_level=10, trade_freeze_level=0, trade_mode=4,
                    filling_mode=3, currency_profit="USD")
        return [NS(name="XAUUSD", **info), NS(name="EURUSD", **info),
                NS(name="Volatility 75 Index", **{**info, "visible": False})]

    def symbol_info_tick(self, name):
        self._log("symbol_info_tick")
        return NS(time=1_700_000_000, bid=2000.0, ask=2000.25)

    def symbol_select(self, name, enable):
        self._log("symbol_select")
        return True

    def order_send(self, request):
        raise AssertionError("order_send must never be reachable")

    order_check = positions_get = orders_get = order_send


def run(fake, **kwargs):
    return inspect(fake, expected_login=LOGIN, server=SERVER, password=PASSWORD, **kwargs)


class Mt5StatusTests(unittest.TestCase):
    def test_trading_functions_are_blocked_by_the_wrapper(self):
        guarded = ReadOnlyMT5(FakeMT5())
        for name in ("order_send", "order_check", "positions_get", "orders_get", "history_deals_get"):
            with self.assertRaises(PermissionError):
                getattr(guarded, name)
        self.assertEqual(guarded.ACCOUNT_TRADE_MODE_DEMO, 0)  # constants stay readable
        self.assertTrue(guarded.initialize())

    def test_logged_in_terminal_needs_no_password_and_report_is_safe(self):
        fake = FakeMT5(logged_in=True)
        report = run(fake)
        self.assertNotIn("login", fake.calls)  # already on the right account: password not used
        self.assertEqual(fake.calls[-1], "shutdown")
        self.assertTrue(report["demo_verified"])
        self.assertEqual(report["orders_sent"], 0)
        self.assertEqual(report["account"]["login_masked"], "******789")
        self.assertEqual(report["account"]["type"], "DEMO")
        names = [s["name"] for s in report["symbols"]]
        self.assertEqual(names, ["Volatility 75 Index", "XAUUSD"])  # EURUSD not requested
        gold = next(s for s in report["symbols"] if s["name"] == "XAUUSD")
        self.assertEqual(gold["filling_modes"], ["FOK", "IOC"])
        self.assertEqual(gold["trading"], "complet")
        self.assertEqual(gold["last_tick"]["ask"], 2000.25)
        hidden = next(s for s in report["symbols"] if s["name"].startswith("Volatility"))
        self.assertIsNone(hidden["last_tick"])  # not in Market Watch: no tick, nothing selected
        self.assertNotIn("symbol_select", fake.calls)
        text = json.dumps(report)
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn(str(LOGIN), text)

    def test_login_is_used_only_when_needed_and_password_never_leaks(self):
        fake = FakeMT5(logged_in=False)
        report = run(fake)
        self.assertEqual(fake.login_args, (LOGIN, PASSWORD, SERVER))
        self.assertNotIn(PASSWORD, json.dumps(report))
        refused = FakeMT5(logged_in=False, login_ok=False)
        with self.assertRaises(RuntimeError) as caught:
            run(refused)
        self.assertNotIn(PASSWORD, str(caught.exception))
        self.assertEqual(refused.calls[-1], "shutdown")
        with self.assertRaises(RuntimeError):
            inspect(FakeMT5(logged_in=False), expected_login=LOGIN, server=SERVER, password=None)

    def test_real_account_is_refused_before_reading_anything(self):
        fake = FakeMT5(mode=2)
        with self.assertRaises(RuntimeError) as caught:
            run(fake)
        self.assertIn("not DEMO", str(caught.exception))
        self.assertNotIn("symbols_get", fake.calls)
        self.assertEqual(fake.calls[-1], "shutdown")

    def test_initialisation_failure_and_market_watch_selection_option(self):
        with self.assertRaises(RuntimeError):
            run(FakeMT5(init_ok=False))
        fake = FakeMT5()
        run(fake, select_symbols=True)
        self.assertIn("symbol_select", fake.calls)

    def test_credentials_from_env_validation(self):
        self.assertEqual(credentials_from_env({"TIP_MT5_DEMO_LOGIN": "42", "TIP_MT5_DEMO_SERVER": "S"}), (42, "S", None))
        for env in ({}, {"TIP_MT5_DEMO_LOGIN": "abc", "TIP_MT5_DEMO_SERVER": "S"}, {"TIP_MT5_DEMO_LOGIN": "42"}):
            with self.assertRaises(RuntimeError):
                credentials_from_env(env)


if __name__ == "__main__":
    unittest.main()
