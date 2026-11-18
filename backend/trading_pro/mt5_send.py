"""Supervised demo order: ONE minimal order on the MT5 DEMO account, launched by a person, never by the bot.

This is the only module whose terminal wrapper can reach ``order_send``. It is deliberately hard to trigger:

1. the operator types an exact confirmation phrase naming side and symbol;
2. no scheduled US announcement window may be active, and the calendar must cover today (strict mode);
3. the stop on new entries must have been lifted by the operator on purpose; it is RE-ARMED after every
   attempt that got past this check, so one release allows at most one attempt;
4. the account must be DEMO, the terminal's "Trading algo" switch must be on and no position may be open
   on the symbol;
5. the real risk engine (``check_risk``) must approve, then the broker's ``order_check`` must accept the exact
   request just before it is sent;
6. only the smallest allowed volume is ever sent, with a stop-loss and a target beyond the broker minimum.

Afterwards the order is reconciled with the account in read-only mode. Closing is a separate, equally explicit
command (``close_demo``). Nothing here is a strategy: it tests the plumbing with a forced, tiny order.
"""
from __future__ import annotations

from dataclasses import replace

from . import us_events
from .broker import MAGIC, MT5DemoBroker, execute_demo, reconcile_demo_ticket
from .core import Instrument, Limits, RiskState, utcnow, check_risk
from .mt5_dryrun import DRY_RUN_ALLOWED, build_signal
from .mt5_status import ReadOnlyMT5, connect_demo

SEND_ALLOWED = DRY_RUN_ALLOWED | {"order_send", "positions_get", "orders_get", "history_deals_get", "history_orders_get"}
RELEASE_PHRASE = "LEVER L'ARRET DES ENTREES"
SEND_PHRASE = "ENVOYER UN ORDRE DEMO {side} {symbol}"
CLOSE_PHRASE = "FERMER LA POSITION DEMO {symbol}"


class Refusal(RuntimeError):
    """A safeguard stopped the operation. When raised before any order_send, nothing was sent."""


def _positions(mt5, symbol):
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        raise Refusal("Positions could not be read: nothing is sent when the account state is unknown")
    return list(positions)


def _position_row(p) -> dict:
    return {"ticket": getattr(p, "ticket", None), "type": "BUY" if getattr(p, "type", 0) == 0 else "SELL",
            "volume": getattr(p, "volume", None), "price_open": getattr(p, "price_open", None),
            "stop_loss": getattr(p, "sl", None), "take_profit": getattr(p, "tp", None),
            "profit": getattr(p, "profit", None), "magic": getattr(p, "magic", None)}


def send_supervised(module, store, *, symbol: str, side: str, confirm: str, expected_login: int, server: str,
                    password: str | None, commission: float, slippage_ticks: float, terminal_path: str | None = None,
                    select: bool = False, max_spread: float | None = None, risk_fraction: float = 0.005,
                    stop_multiple: float = 3.0, calendar=None, now=None, timeout_ms: int = 20000) -> dict:
    if side not in ("BUY", "SELL"):
        raise Refusal("Side must be BUY or SELL")
    if confirm != SEND_PHRASE.format(side=side, symbol=symbol):
        raise Refusal(f"Confirmation phrase missing or wrong. Type exactly: {SEND_PHRASE.format(side=side, symbol=symbol)}")
    if min(commission, slippage_ticks) < 0 or not 0 < risk_fraction <= 0.02 or stop_multiple < 2:
        raise Refusal("Invalid commission, slippage, risk fraction (max 2%) or stop multiple (min 2)")
    now = now or utcnow()
    released = not store.killed()
    try:  # a release lifted on purpose is consumed by ANY attempt, accepted or refused
        try:
            halt = (calendar or us_events.load()).halt_reason(now, strict=True)
        except FileNotFoundError:
            halt = "US announcement calendar missing"
        if halt:
            raise Refusal(f"Caution window: {halt}")
        if not released:
            raise Refusal("The stop on new entries is active. Lift it on purpose with: kill-switch release")
        return _send(module, store, symbol=symbol, side=side, expected_login=expected_login, server=server,
                     password=password, commission=commission, slippage_ticks=slippage_ticks,
                     terminal_path=terminal_path, select=select, max_spread=max_spread, risk_fraction=risk_fraction,
                     stop_multiple=stop_multiple, now=now, timeout_ms=timeout_ms)
    finally:
        if released:
            store.set_killed()


def _send(module, store, *, symbol, side, expected_login, server, password, commission, slippage_ticks,
          terminal_path, select, max_spread, risk_fraction, stop_multiple, now, timeout_ms) -> dict:
    mt5 = ReadOnlyMT5(module, SEND_ALLOWED)
    account = connect_demo(mt5, expected_login=expected_login, server=server, password=password,
                           terminal_path=terminal_path, timeout_ms=timeout_ms)
    try:
        terminal = mt5.terminal_info()
        if not getattr(terminal, "trade_allowed", False):
            raise Refusal("'Trading algo' is off in the terminal. Switch it on yourself (toolbar button or Ctrl+E), "
                          "then run the command again; the stop on new entries will need to be lifted again")
        if not getattr(account, "trade_allowed", True):
            raise Refusal("The account does not allow trading")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise Refusal(f"Symbol {symbol} not found on this account")
        if not getattr(info, "visible", False):
            if not select:
                raise Refusal(f"Symbol {symbol} is not in Market Watch: rerun with --select")
            mt5.symbol_select(symbol, True)
        if _positions(mt5, symbol):
            raise Refusal(f"A position is already open on {symbol}: close it first")
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise Refusal("No tick available: the market may be closed")
        signal, quote, volume = build_signal(info, tick, side, now, multiple=stop_multiple)
        equity = float(getattr(account, "equity", None) or getattr(account, "balance", 0))
        state = RiskState(equity, equity, killed=False, broker_connected=True, demo_account=True)
        instrument = Instrument(float(info.trade_tick_size), float(info.trade_tick_value), float(info.volume_min),
                                float(info.volume_max), float(info.volume_step), commission, slippage_ticks)
        limits = Limits(risk_per_trade=risk_fraction) if max_spread is None else Limits(risk_per_trade=risk_fraction,
                                                                                         max_spread=max_spread)
        decision = check_risk(signal, quote, instrument, state, limits, now)
        if not decision.approved:
            raise Refusal(f"Risk engine refused: {decision.reason}")
        decision = replace(decision, volume=volume)  # only the smallest allowed volume is ever sent
        broker = MT5DemoBroker(mt5, demo_execution_enabled=True)
        report = {"symbol": symbol, "side": side, "volume": volume, "price": signal.entry, "stop_loss": signal.stop_loss,
                  "take_profit": signal.take_profit, "risk_engine": decision.reason, "signal_id": signal.signal_id}
        error = None
        result = None
        try:
            result = execute_demo(signal, decision, quote, broker, store.journal)
        except Exception as exc:  # the journal already holds the exact state; never retry automatically
            error = f"{type(exc).__name__}: {exc}"
        intent = store.journal.intent(signal.signal_id) or {}
        state_name = intent.get("state")
        report.update(intent_state=state_name, broker_result=result, error=error,
                      order_sent=state_name not in (None, "reserved", "preflight_rejected"))
        if report["order_sent"] and error is None and result and result.get("ticket"):
            try:
                report["reconciliation"] = reconcile_demo_ticket(signal, broker, store.journal,
                                                                 expected_account_login=int(account.login))
            except Exception as exc:
                report["reconciliation"] = f"à vérifier à la main : {exc}"
        if report["order_sent"] and error is not None:
            report["warning"] = "Outcome uncertain: check the terminal before anything else. Never resend."
        try:
            report["open_positions"] = [_position_row(p) for p in _positions(mt5, symbol)]
        except Refusal:
            report["open_positions"] = "illisible"
        report["kill_switch_rearmed"] = True
        report["next"] = f"Fermer avec : mt5-close-demo \"{symbol}\" --confirm \"{CLOSE_PHRASE.format(symbol=symbol)}\""
        return report
    finally:
        mt5.shutdown()


def close_demo(module, store, *, symbol: str, confirm: str, expected_login: int, server: str, password: str | None,
               terminal_path: str | None = None, timeout_ms: int = 20000) -> dict:
    """Close the open positions of THIS project (magic number) on ``symbol``. Works with the stop active."""
    if confirm != CLOSE_PHRASE.format(symbol=symbol):
        raise Refusal(f"Confirmation phrase missing or wrong. Type exactly: {CLOSE_PHRASE.format(symbol=symbol)}")
    mt5 = ReadOnlyMT5(module, SEND_ALLOWED)
    connect_demo(mt5, expected_login=expected_login, server=server, password=password,
                 terminal_path=terminal_path, timeout_ms=timeout_ms)
    try:
        terminal = mt5.terminal_info()
        if not getattr(terminal, "trade_allowed", False):
            raise Refusal("'Trading algo' is off in the terminal: switch it on yourself, or close the position by hand")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise Refusal(f"Symbol {symbol} not found on this account")
        mine = [p for p in _positions(mt5, symbol) if getattr(p, "magic", None) == MAGIC]
        if not mine:
            return {"symbol": symbol, "closed": [], "note": "Aucune position de ce projet à fermer.", "orders_sent": 0}
        supported = getattr(info, "filling_mode", 0) or 0
        filling = mt5.ORDER_FILLING_FOK if supported & getattr(mt5, "SYMBOL_FILLING_FOK", 1) else mt5.ORDER_FILLING_IOC
        closed = []
        for position in mine:
            long = getattr(position, "type", 0) == 0
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise Refusal("No tick available: the market may be closed")
            request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": position.volume,
                       "type": mt5.ORDER_TYPE_SELL if long else mt5.ORDER_TYPE_BUY, "position": position.ticket,
                       "price": tick.bid if long else tick.ask, "deviation": 10, "magic": MAGIC,
                       "comment": "close demo test", "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling}
            check = mt5.order_check(request)
            if check is None or check.retcode != 0:
                closed.append({"ticket": position.ticket, "status": "refused_by_broker_check",
                               "retcode": getattr(check, "retcode", None)})
                continue
            result = mt5.order_send(request)
            code = getattr(result, "retcode", None)
            store.journal.log("order.closed", str(position.ticket), {"symbol": symbol, "retcode": code})
            closed.append({"ticket": position.ticket, "status": "closed" if code == mt5.TRADE_RETCODE_DONE else "uncertain",
                           "retcode": code})
        return {"symbol": symbol, "closed": closed, "orders_sent": sum(1 for c in closed if c["status"] != "refused_by_broker_check")}
    finally:
        mt5.shutdown()
