"""MT5 bridge. Never submits to an account unless its trade_mode is DEMO."""
from decimal import Decimal
from math import isfinite
from .core import Action, Signal, utcnow
from .journal import Journal


MAGIC = 26001118  # identifies the orders of this project in the broker's history


class DemoBroker:
    """Offline test broker. Does not create real market fills."""
    def preflight(self, signal, volume, quote):
        return True

    def send(self, signal, volume, quote):
        return {"status": "simulated", "ticket": f"SIM-{signal.signal_id}"}


class MT5DemoBroker:
    def __init__(self, mt5, *, demo_execution_enabled=False):
        self.mt5 = mt5
        self.demo_execution_enabled = demo_execution_enabled

    def _assert_demo(self, *, require_trading=True):
        account = self.mt5.account_info()
        if account is None or account.trade_mode != self.mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise RuntimeError("MT5 account must be confirmed DEMO")
        terminal = self.mt5.terminal_info()
        if terminal is None or not terminal.connected or (require_trading and not terminal.trade_allowed):
            raise RuntimeError("Terminal unavailable for trading")
        return account

    def _filling(self, info):
        """Pick a fill mode the symbol advertises: all-or-nothing (FOK) first, then IOC. Never guess."""
        supported = getattr(info, "filling_mode", 0) or 0
        if supported & getattr(self.mt5, "SYMBOL_FILLING_FOK", 1):
            return self.mt5.ORDER_FILLING_FOK
        if supported & getattr(self.mt5, "SYMBOL_FILLING_IOC", 2):
            return self.mt5.ORDER_FILLING_IOC
        raise RuntimeError("Symbol does not advertise a market fill mode (FOK or IOC)")

    def _request(self, signal, volume, quote, filling):
        mt5 = self.mt5
        price = quote.ask if signal.action == Action.BUY else quote.bid
        return {"action": mt5.TRADE_ACTION_DEAL, "symbol": signal.symbol,
                "volume": volume, "type": mt5.ORDER_TYPE_BUY if signal.action == Action.BUY else mt5.ORDER_TYPE_SELL,
                "price": price, "sl": signal.stop_loss, "tp": signal.take_profit,
                "deviation": 10, "magic": MAGIC, "comment": signal.signal_id[:28],  # MetaTrader refuses 30+ characters ("Invalid comment argument"); 28 verified
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling}

    last_check = None  # raw order_check answer of the latest validation, for diagnostics

    def _checked_request(self, signal, volume, quote, *, require_trading=True):
        """Validate against the live contract, then ask the broker to check the exact request."""
        self._assert_demo(require_trading=require_trading)
        info = self.mt5.symbol_info(signal.symbol)
        tick = self.mt5.symbol_info_tick(signal.symbol)
        if info is None or tick is None or not info.visible:
            raise RuntimeError("Symbol or tick unavailable")
        if getattr(info, "trade_mode", 4) != getattr(self.mt5, "SYMBOL_TRADE_MODE_FULL", 4):
            raise RuntimeError("Symbol is not fully tradable")
        if abs(tick.ask - quote.ask) > info.point * 10 or abs(tick.bid - quote.bid) > info.point * 10:
            raise RuntimeError("Broker quote moved; risk must be recalculated")
        if volume < info.volume_min or volume > info.volume_max:
            raise RuntimeError("Broker volume invalid")
        step = getattr(info, "volume_step", None)
        if step:
            steps = (Decimal(str(volume)) - Decimal(str(info.volume_min))) / Decimal(str(step))
            if steps != steps.to_integral_value():
                raise RuntimeError("Volume is not a multiple of the broker volume step")
        level = getattr(info, "trade_stops_level", 0) or 0
        minimum = Decimal(str(level)) * Decimal(str(info.point))
        # Stops are measured from the price at which the position would be CLOSED: the bid for a long, the ask
        # for a short. Measured from the entry price, the stop-loss would need the spread on top (verified with
        # order_check on the demo account).
        close_at = Decimal(str(tick.bid if signal.action == Action.BUY else tick.ask))
        sign = 1 if signal.action == Action.BUY else -1
        if signal.stop_loss is not None and sign * (close_at - Decimal(str(signal.stop_loss))) < minimum:
            raise RuntimeError("Stop closer than the broker minimum distance")
        if signal.take_profit is not None and sign * (Decimal(str(signal.take_profit)) - close_at) < minimum:
            raise RuntimeError("Target closer than the broker minimum distance")
        request = self._request(signal, volume, quote, self._filling(info))
        result = self.mt5.order_check(request)
        self.last_check = result
        if result is None or result.retcode != 0:
            if result is not None:
                why = f"retcode {result.retcode}: {getattr(result, 'comment', '')}"
            else:
                try:
                    why = f"no answer, last_error {self.mt5.last_error()}"
                except Exception:  # noqa: BLE001 - a diagnostic must never hide the refusal itself
                    why = "no answer"
            raise RuntimeError(f"MT5 order_check rejected ({why})")
        return request

    def preflight(self, signal, volume, quote):
        self._checked_request(signal, volume, quote)
        return True

    def send(self, signal, volume, quote):
        try:
            if not self.demo_execution_enabled:
                raise RuntimeError("MT5 demo execution is disabled by default")
            request = self._checked_request(signal, volume, quote)  # refresh account, tick and order_check just before send
        except Exception as exc:
            # order_send was never reached: the order is certainly NOT at the broker (a moved quote is not an unknown outcome)
            raise NotSent(str(exc)) from exc
        result = self.mt5.order_send(request)
        if result is None:
            raise RuntimeError("MT5 send outcome unknown; reconcile before retry")
        if result.retcode == self.mt5.TRADE_RETCODE_DONE:
            status = "accepted"
        elif result.retcode == self.mt5.TRADE_RETCODE_DONE_PARTIAL:
            status = "partial"
        elif result.retcode == self.mt5.TRADE_RETCODE_REJECT:
            status = "rejected"
        else:
            status = "uncertain"  # timeout, placed, requote, or unknown code: never retry
        return {"status": status, "ticket": result.order or None,
                "deal": getattr(result, "deal", None), "volume": getattr(result, "volume", None),
                "retcode": result.retcode}

    def inspect_ticket(self, signal: Signal, ticket: int, *, expected_account_login: int):
        """Read-only broker observation. Absence of a record never proves no fill."""
        account = self._assert_demo(require_trading=False)
        if (not isinstance(expected_account_login, int) or isinstance(expected_account_login, bool)
                or expected_account_login <= 0 or getattr(account, "login", None) != expected_account_login):
            raise RuntimeError("MT5 demo account identity mismatch")
        if not isinstance(ticket, int) or isinstance(ticket, bool) or ticket <= 0:
            raise ValueError("A confirmed MT5 order ticket is required")
        # history_deals_get(ticket=...) takes a DEAL ticket and answers "Invalid params" for an order ticket
        # (observed on the real terminal). A market order opens the position whose id equals the order ticket,
        # so the deals are read by position and then narrowed to the ones that belong to this very order
        # (the closing deal of the same position belongs to another order).
        position_deals = self.mt5.history_deals_get(position=ticket)
        orders = self.mt5.orders_get(ticket=ticket)
        history = self.mt5.history_orders_get(ticket=ticket)
        if any(records is None for records in (position_deals, orders, history)):
            raise RuntimeError("Incomplete MT5 history; intent remains unresolved")
        deals = tuple(deal for deal in position_deals if getattr(deal, "order", None) == ticket)
        for record in (*deals, *orders, *history):
            if record.symbol != signal.symbol or record.magic != MAGIC:
                raise RuntimeError("Broker record does not match expected symbol and magic")
        for record in (*orders, *history):
            if record.ticket != ticket:
                raise RuntimeError("Order ticket mismatch")
        if deals:
            return {"status": "deals_observed", "ticket": ticket,
                    "deal_tickets": [deal.ticket for deal in deals]}
        if orders or history:
            return {"status": "order_observed", "ticket": ticket, "deal_tickets": []}
        return {"status": "unresolved", "ticket": ticket, "deal_tickets": []}


class NotSent(RuntimeError):
    """The final validation before ``order_send`` failed: nothing reached the broker, so there is nothing to reconcile."""


def execute_demo(signal: Signal, decision, quote, broker, journal: Journal):
    if signal.action == Action.WAIT or not decision.approved or signal.status != "validated":
        raise ValueError("Only approved validated non-WAIT signals may be sent")
    if (not isinstance(decision.volume, (int, float)) or isinstance(decision.volume, bool)
            or not isfinite(decision.volume) or decision.volume <= 0):
        raise ValueError("Approved volume must be positive and finite")
    if (signal.expires_at.tzinfo is None or quote.observed_at.tzinfo is None
            or signal.cycle_id != quote.cycle_id or signal.symbol != quote.symbol
            or utcnow() >= signal.expires_at or not -1 <= (utcnow()-quote.observed_at).total_seconds() <= 5):
        raise ValueError("Expired or mismatched execution snapshot")
    if not journal.reserve(signal.signal_id, {"cycle_id": signal.cycle_id, "volume": decision.volume}):
        raise RuntimeError("Intent already exists: reconcile broker before any retry")
    journal.log("order.reserved", signal.signal_id, {"volume": decision.volume})
    try:
        if broker.preflight(signal, decision.volume, quote) is not True:
            raise RuntimeError("Broker preflight did not approve")
    except Exception as exc:
        journal.transition_intent(signal.signal_id, {"reserved"}, "preflight_rejected", detail=str(exc))
        journal.log("order.preflight_rejected", signal.signal_id, {"error": str(exc)})
        raise
    journal.transition_intent(signal.signal_id, {"reserved"}, "sending")
    try:
        result = broker.send(signal, decision.volume, quote)
        if result["status"] not in {"accepted", "partial", "rejected", "uncertain", "simulated"}:
            raise RuntimeError("Unrecognized broker response")
        state = result["status"]
        journal.transition_intent(signal.signal_id, {"sending"}, state,
                                  ticket=result.get("ticket"), detail=str(result))
        journal.log("order.result", signal.signal_id, result)
        return result
    except NotSent as exc:
        journal.transition_intent(signal.signal_id, {"sending"}, "preflight_rejected", detail=str(exc))
        journal.log("order.preflight_rejected", signal.signal_id, {"error": str(exc), "phase": "before_send"})
        raise
    except Exception as exc:
        if journal.intent(signal.signal_id)["state"] == "sending":
            journal.transition_intent(signal.signal_id, {"sending"}, "uncertain", detail=str(exc))
        journal.log("order.uncertain", signal.signal_id, {"error": str(exc)})
        raise


def reconcile_demo_ticket(signal: Signal, broker: MT5DemoBroker, journal: Journal, *, expected_account_login: int):
    """Confirm a known ticket only. Unknown outcomes require operator investigation."""
    intent = journal.intent(signal.signal_id)
    if intent is None or intent["state"] not in {"uncertain", "accepted", "partial", "order_observed"}:
        raise RuntimeError("No reconcilable intent")
    if not intent["broker_ticket"]:
        raise RuntimeError("Unknown MT5 ticket: inspect the account manually; do not resend")
    result = broker.inspect_ticket(signal, int(intent["broker_ticket"]),
                                   expected_account_login=expected_account_login)
    if result["status"] in {"unresolved", intent["state"]}:
        return result
    journal.transition_intent(signal.signal_id, {intent["state"]}, result["status"],
                              ticket=result["ticket"], detail=str(result))
    journal.log("order.reconciled", signal.signal_id, result)
    return result
