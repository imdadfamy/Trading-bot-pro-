import unittest
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace as NS

from trading_pro.broker import MT5DemoBroker
from trading_pro.core import Action, Signal, Snapshot, utcnow


class RecordingMT5:
    """Models the real Deriv demo XAUUSD contract: FOK only, stops at 20 points, lot step 0.01."""
    ACCOUNT_TRADE_MODE_DEMO = 0
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 1, 0, 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2
    SYMBOL_TRADE_MODE_FULL = 4
    TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL, TRADE_RETCODE_REJECT = 10009, 10010, 10006

    def __init__(self, **symbol):
        self.symbol = dict(visible=True, point=0.01, volume_min=0.01, volume_max=10.0, volume_step=0.01,
                           filling_mode=1, trade_mode=4, trade_stops_level=20)
        self.symbol.update(symbol)
        self.checked, self.sent = [], []

    def account_info(self):
        return NS(trade_mode=0, login=1)

    def terminal_info(self):
        return NS(connected=True, trade_allowed=True)

    def symbol_info(self, name):
        return NS(**self.symbol)

    def symbol_info_tick(self, name):
        return NS(ask=2000.18, bid=2000.0)

    def order_check(self, request):
        self.checked.append(request)
        return NS(retcode=0)

    def order_send(self, request):
        self.sent.append(request)
        return NS(retcode=10009, order=7, deal=8, volume=request["volume"])


def make(action=Action.BUY, stop=1999.0, take=2003.0):
    now = utcnow()
    quote = Snapshot("c", "XAUUSD", 2000.0, 2000.18, now)
    signal = Signal("sig", "c", "XAUUSD", action, now, now + timedelta(minutes=1), "s", "1", "t",
                    2000.18, stop, take, status="validated")
    return signal, quote


class FillModeAndContractTests(unittest.TestCase):
    def test_fok_only_symbol_gets_fok_never_ioc(self):
        mt5 = RecordingMT5(filling_mode=1)
        signal, quote = make()
        MT5DemoBroker(mt5).preflight(signal, 0.01, quote)
        self.assertEqual(mt5.checked[0]["type_filling"], mt5.ORDER_FILLING_FOK)

    def test_ioc_is_used_only_when_fok_is_not_offered(self):
        mt5 = RecordingMT5(filling_mode=2)
        signal, quote = make()
        MT5DemoBroker(mt5).preflight(signal, 0.01, quote)
        self.assertEqual(mt5.checked[0]["type_filling"], mt5.ORDER_FILLING_IOC)
        both = RecordingMT5(filling_mode=3)
        MT5DemoBroker(both).preflight(signal, 0.01, quote)
        self.assertEqual(both.checked[0]["type_filling"], both.ORDER_FILLING_FOK)  # all-or-nothing preferred

    def test_unknown_fill_mode_or_untradable_symbol_is_refused_before_order_check(self):
        signal, quote = make()
        for symbol, text in (({"filling_mode": 0}, "fill mode"), ({"trade_mode": 3}, "fully tradable")):
            mt5 = RecordingMT5(**symbol)
            with self.assertRaisesRegex(RuntimeError, text):
                MT5DemoBroker(mt5).preflight(signal, 0.01, quote)
            self.assertEqual(mt5.checked, [])

    def test_volume_step_and_stop_distance_follow_the_live_contract(self):
        signal, quote = make()
        broker = MT5DemoBroker(RecordingMT5())
        self.assertTrue(broker.preflight(signal, 0.37, quote))
        with self.assertRaisesRegex(RuntimeError, "volume step"):
            broker.preflight(signal, 0.015, quote)
        # Stops are measured from the closing price (bid 2000.00 for a long, ask 2000.18 for a short), minimum 0.20.
        accepted_edge, _ = make(stop=1999.80, take=2000.20)
        self.assertTrue(broker.preflight(accepted_edge, 0.01, quote))
        for kwargs in ({"stop": 1999.81}, {"take": 2000.19}, {"stop": 2000.0}):
            with self.assertRaisesRegex(RuntimeError, "minimum distance"):
                broker.preflight(make(**kwargs)[0], 0.01, quote)
        sell_ok, sell_quote = make(Action.SELL, stop=2000.38, take=1999.98)
        self.assertTrue(broker.preflight(sell_ok, 0.01, sell_quote))
        for kwargs in ({"stop": 2000.37}, {"take": 1999.99}):
            with self.assertRaisesRegex(RuntimeError, "minimum distance"):
                broker.preflight(make(Action.SELL, **{"stop": 2001.0, "take": 1997.0, **kwargs})[0], 0.01, sell_quote)
        sell, sell_quote = make(Action.SELL, stop=2001.0, take=1997.0)
        self.assertTrue(broker.preflight(sell, 0.01, sell_quote))
        with self.assertRaisesRegex(RuntimeError, "volume invalid"):
            broker.preflight(signal, 10.5, quote)

    def test_send_uses_the_checked_request_and_stays_disabled_by_default(self):
        signal, quote = make()
        mt5 = RecordingMT5()
        with self.assertRaisesRegex(RuntimeError, "disabled by default"):
            MT5DemoBroker(mt5).send(signal, 0.01, quote)
        self.assertEqual((mt5.checked, mt5.sent), ([], []))
        enabled = RecordingMT5()
        result = MT5DemoBroker(enabled, demo_execution_enabled=True).send(signal, 0.01, quote)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(enabled.sent[0], enabled.checked[0])  # the exact request the broker validated
        self.assertEqual(enabled.sent[0]["type_filling"], enabled.ORDER_FILLING_FOK)
        self.assertEqual(enabled.sent[0]["magic"], 26001118)


if __name__ == "__main__":
    unittest.main()
