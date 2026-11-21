"""Automatic orders on the MT5 DEMO account, sent by the pilot when the operator switched on "demo_auto".

This is the only automatic path to ``order_send``. Every order must pass, in this order:

1. the mode is ``demo_auto`` and the stop on new entries is lifted (the emergency stop blocks new entries at once);
2. no scheduled US announcement window for gold (strict calendar) and the account is DEMO;
3. the terminal's "Trading algo" switch is on (the operator's own switch: never touched by the bot);
4. a live tick, recent and with a spread within the limit; no open position of the project on the symbol;
5. the real risk engine (``check_risk``) approves with the real equity, the real daily loss and the real open risk,
   then the broker's ``order_check`` accepts the exact request;
6. stop-loss and target are set at the broker, and their presence is verified after the fill: a position
   without protection is closed at once, the stop on new entries is armed and an alert is raised.

An uncertain outcome (no answer after sending) arms the stop on new entries and is never resent. Positions
live on their broker-side stop and target; one that outlives the strategy's horizon is closed at market,
exactly as its simulated twin is. Nothing here changes a strategy: it executes the choice of the arms named in
the pilot's ``execution_arms`` setting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN

from .autopilot_features import has_family_word
from .broker import MAGIC, MT5DemoBroker, execute_demo, reconcile_demo_ticket
from .core import Action, Instrument, Limits, RiskState, Signal, Snapshot, check_risk
from .mt5_send import SEND_ALLOWED
from .mt5_status import ReadOnlyMT5, connect_demo

DEAL_OUT = (1, 2, 3)  # DEAL_ENTRY_OUT, INOUT, OUT_BY
REASONS = {0: "terminal", 1: "mobile", 2: "web", 3: "programme", 4: "stop", 5: "objectif", 6: "appel de marge"}
MAX_TICK_AGE_SECONDS = 15.0


class Refused(RuntimeError):
    """A safeguard stopped the order before ``order_send``. ``code`` is a short machine-readable reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Executor:
    module: object
    login: int
    server: str
    password: str | None = None
    terminal_path: str | None = None
    timeout_ms: int = 20000

    # ------------------------------------------------------------------ helpers
    def _connect(self):
        mt5 = ReadOnlyMT5(self.module, SEND_ALLOWED)
        account = connect_demo(mt5, expected_login=self.login, server=self.server, password=self.password,
                               terminal_path=self.terminal_path, timeout_ms=self.timeout_ms)
        return mt5, account

    @staticmethod
    def _ours(mt5):
        positions = mt5.positions_get()
        if positions is None:
            raise Refused("account_unreadable", "Positions could not be read: nothing is sent when the account state is unknown")
        return [p for p in positions if getattr(p, "magic", None) == MAGIC]

    @staticmethod
    def _open_risk(mt5, positions, equity, max_open_risk) -> float:
        total = 0.0
        for p in positions:
            info = mt5.symbol_info(p.symbol)
            sl = getattr(p, "sl", 0) or 0
            if info is None or sl <= 0:  # unknown or unprotected: count it as using all the capacity
                return equity * max_open_risk
            total += abs(p.price_open - sl) / info.trade_tick_size * info.trade_tick_value * p.volume
        return total

    @staticmethod
    def _daily_start_equity(mt5, account, now, offset_seconds) -> float:
        """Equity at the start of the UTC day = balance minus what was realised since then."""
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(start - timedelta(hours=14), now + timedelta(hours=14))
        if deals is None:
            raise Refused("account_unreadable", "Deal history could not be read: the daily loss cannot be measured")
        realised = 0.0
        for d in deals:
            if getattr(d, "type", None) in (0, 1) and getattr(d, "time", 0) - offset_seconds >= start.timestamp():
                realised += (getattr(d, "profit", 0) or 0) + (getattr(d, "commission", 0) or 0) + \
                            (getattr(d, "swap", 0) or 0) + (getattr(d, "fee", 0) or 0)
        return float(account.balance) - realised

    def account_summary(self) -> dict:
        """Capital and equity of the demo account, for the dashboard (read only)."""
        mt5, account = self._connect()
        try:
            return {"balance": round(float(account.balance), 2), "equity": round(float(account.equity), 2),
                    "currency": getattr(account, "currency", "USD"), "login_masked": "*" * 5 + str(account.login)[-3:]}
        finally:
            mt5.shutdown()

    # ------------------------------------------------------------------ sending
    def send(self, store, *, decision_id: str, symbol: str, side: str, arm: str, plan: dict, limits: Limits, risk: dict,
             ai_spend: float, offset_hours: float, now: datetime, halt: str | None, rationale: str = "") -> dict:
        """One attempt for one decision. Returns a report; never raises for a refusal."""
        try:
            return self._send(store, decision_id=decision_id, symbol=symbol, side=side, arm=arm, plan=plan,
                              limits=limits, risk=risk, ai_spend=ai_spend, offset_hours=offset_hours, now=now,
                              halt=halt, rationale=rationale)
        except Refused as refusal:
            store.record_order(decision_id=decision_id, symbol=symbol, arm=arm, side=side, state="refused",
                               detail={"code": refusal.code, "message": str(refusal)}, opened_at=now, keep_existing=True)
            store.journal.log("autopilot.order_refused", decision_id,
                              {"symbol": symbol, "arm": arm, "code": refusal.code, "message": str(refusal)[:200]})
            return {"state": "refused", "code": refusal.code, "message": str(refusal)}

    def _send(self, store, *, decision_id, symbol, side, arm, plan, limits, risk, ai_spend, offset_hours, now, halt,
              rationale) -> dict:
        if store.killed():
            raise Refused("stopped", "The stop on new entries is active")
        if store.journal.intent(decision_id) is not None:  # idempotence: one decision, one attempt, ever
            raise Refused("duplicate", "This decision already has an order intent: never resent")
        if halt:
            raise Refused("announcement", f"Caution window: {halt}")
        try:
            mt5, account = self._connect()
        except RuntimeError as exc:
            raise Refused("terminal", f"MetaTrader unavailable: {exc}") from exc
        try:
            terminal = mt5.terminal_info()
            if not getattr(terminal, "trade_allowed", False):
                raise Refused("trading_algo_off", "'Trading algo' is off in MetaTrader: switch it on yourself (Ctrl+E)")
            if not getattr(account, "trade_allowed", True):
                raise Refused("account", "The account does not allow trading")
            info = mt5.symbol_info(symbol)
            if info is None:
                raise Refused("symbol", f"Symbol {symbol} not found on this account")
            if not getattr(info, "visible", False):
                mt5.symbol_select(symbol, True)
            mine = self._ours(mt5)
            if any(p.symbol == symbol for p in mine):
                raise Refused("position_open", f"A position of the project is already open on {symbol}")
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise Refused("no_tick", "No tick available: the market may be closed")
            offset = offset_hours * 3600
            tick_age = now.timestamp() - (getattr(tick, "time", 0) - offset)
            if not -2 <= tick_age <= MAX_TICK_AGE_SECONDS:
                raise Refused("stale_quote", f"The latest tick is {tick_age:.0f} s old: no order on a stale quote")
            equity = float(getattr(account, "equity", None) or getattr(account, "balance", 0))
            daily_start = self._daily_start_equity(mt5, account, now, offset)
            open_risk = self._open_risk(mt5, mine, equity, limits.max_open_risk)

            buy = side == "BUY"
            point = float(info.point)
            spread = max(0.0, tick.ask - tick.bid)
            minimum = (getattr(info, "trade_stops_level", 0) or 0) * point + spread
            distance = max(plan["stop_distance"], 1.5 * minimum, 10 * point)  # never below the broker's real minimum
            digits = int(getattr(info, "digits", 2))
            price = tick.ask if buy else tick.bid
            stop = round(price - distance if buy else price + distance, digits)
            target = round(price + plan["reward_multiple"] * distance if buy else price - plan["reward_multiple"] * distance, digits)
            cycle = f"auto-{decision_id[:12]}"
            signal = Signal(decision_id, cycle, symbol, Action.BUY if buy else Action.SELL, now, now + timedelta(seconds=60),
                            arm, "0.2.0", rationale[:500] or f"decision of arm {arm}", price, stop, target,
                            status="validated", horizon=f"{plan['horizon_bars']} bars",
                            invalidation="New critical event, stale quote or changed market snapshot")
            quote = Snapshot(cycle, symbol, tick.bid, tick.ask, now)
            # On the side a spike runs against (a sell on Boom, a buy on Crash, either side on Jump/DEX) the stop can be
            # jumped: size as if half a stop more could be lost, so the planned risk is not understated.
            adverse = ((has_family_word(symbol, ("boom",)) and not buy) or (has_family_word(symbol, ("crash",)) and buy)
                       or has_family_word(symbol, ("jump", "dex")))
            slippage_ticks = float(risk.get("slippage_ticks", 0.0))
            if adverse:
                slippage_ticks = max(slippage_ticks, 0.5 * distance / float(info.trade_tick_size))
            instrument = Instrument(float(info.trade_tick_size), float(info.trade_tick_value), float(info.volume_min),
                                    float(info.volume_max), float(info.volume_step),
                                    float(risk.get("commission_per_lot", 0.0)), slippage_ticks)
            fixed = risk.get("fixed_lot")
            # Spreads live on very different price scales: 0 means automatic, a spread of at most 10% of the stop.
            ceiling = limits.max_spread if limits.max_spread > 0 else 0.10 * distance
            effective = replace(limits, max_spread=ceiling)
            if fixed:
                effective = replace(effective, risk_per_trade=limits.max_open_risk)
            state = RiskState(equity, daily_start, open_risk, len(mine), ai_spend, killed=False, broker_connected=True,
                              demo_account=True)
            decision = check_risk(signal, quote, instrument, state, effective, now)
            if not decision.approved:
                raise Refused("risk", f"Risk engine refused: {decision.reason}")
            volume = decision.volume
            if fixed:
                step = Decimal(str(info.volume_step))
                volume = float((Decimal(str(fixed)) / step).to_integral_value(rounding=ROUND_DOWN) * step)
                per_lot = ((abs(price - stop) / instrument.tick_size + instrument.expected_slippage_ticks) * instrument.tick_value
                           + instrument.commission_per_lot_round_trip)
                if volume < instrument.volume_min or volume > instrument.volume_max:
                    raise Refused("fixed_lot", f"Fixed lot {fixed} is outside the broker's limits")
                if volume * per_lot > equity * limits.max_open_risk - open_risk:
                    raise Refused("fixed_lot", "Fixed lot risks more than the aggregate risk capacity")
            decision = replace(decision, volume=volume)

            store.snapshot(quote)  # every order is tied to a journaled snapshot and signal
            store.signal(signal)
            broker = MT5DemoBroker(mt5, demo_execution_enabled=True)
            error = result = None
            try:
                result = execute_demo(signal, decision, quote, broker, store.journal)
            except Exception as exc:  # the journal holds the exact state; never resend
                error = f"{type(exc).__name__}: {exc}"
            intent = store.journal.intent(decision_id) or {}
            sent = intent.get("state") not in (None, "reserved", "preflight_rejected")
            report = {"symbol": symbol, "side": side, "volume": volume, "price": price, "stop_loss": stop,
                      "take_profit": target, "arm": arm, "intent_state": intent.get("state"), "error": error}
            if not sent:
                raise Refused("broker", f"Order not sent: {error or 'preflight failed'}")
            if error is not None or not result or not result.get("ticket") or result.get("status") not in ("accepted", "partial"):
                state_name = "uncertain" if error is not None or (result or {}).get("status") == "uncertain" else "rejected"
                store.record_order(decision_id=decision_id, symbol=symbol, arm=arm, side=side, volume=volume,
                                   state=state_name, entry=price, stop_loss=stop, take_profit=target, opened_at=now,
                                   detail={"error": error, "result": result})
                if state_name == "uncertain":  # never resend, never continue blindly
                    store.set_killed()
                    store.add_alert("order_uncertain", f"Résultat incertain sur {symbol} ({arm}) : vérifier MetaTrader. "
                                    "Arrêt des nouvelles entrées activé.")
                    store.journal.log("autopilot.order_uncertain", decision_id, {"symbol": symbol, "arm": arm, "error": error})
                return {**report, "state": state_name}
            ticket = int(result["ticket"])
            try:
                report["reconciliation"] = reconcile_demo_ticket(signal, broker, store.journal,
                                                                 expected_account_login=int(account.login))
            except Exception as exc:  # read-only check only: the position exists either way
                report["reconciliation"] = f"à vérifier à la main : {exc}"
            store.record_order(decision_id=decision_id, symbol=symbol, arm=arm, side=side, volume=volume,
                               ticket=ticket, position_ticket=ticket, state="open", entry=price, stop_loss=stop,
                               take_profit=target, opened_at=now, max_age_seconds=int(plan["max_age_seconds"]),
                               detail={"reconciliation": str(report["reconciliation"])[:200]})
            store.journal.log("autopilot.order_sent", decision_id,
                              {"symbol": symbol, "arm": arm, "side": side, "volume": volume, "ticket": ticket})
            protected = self._verify_protection(mt5, store, symbol=symbol, ticket=ticket, decision_id=decision_id)
            return {**report, "state": "open" if protected else "closed_unprotected", "ticket": ticket}
        finally:
            mt5.shutdown()

    # ------------------------------------------------------------------ protection and closing
    def _verify_protection(self, mt5, store, *, symbol, ticket, decision_id) -> bool:
        for p in self._ours(mt5):
            if getattr(p, "ticket", None) == ticket:
                if (getattr(p, "sl", 0) or 0) > 0 and (getattr(p, "tp", 0) or 0) > 0:
                    return True
                self._close(mt5, p)
                store.close_order(decision_id, state="closed_unprotected", profit=None, reason="sans protection",
                                  now=datetime.now(timezone.utc))
                store.set_killed()
                store.add_alert("position_unprotected", f"Position {ticket} sur {symbol} sans stop ou objectif : "
                                "fermée, arrêt des nouvelles entrées activé.")
                store.journal.log("autopilot.position_unprotected", decision_id, {"symbol": symbol, "ticket": ticket})
                return False
        return True  # not visible yet: the next reconciliation checks it again

    def _close(self, mt5, position) -> dict:
        info = mt5.symbol_info(position.symbol)
        tick = mt5.symbol_info_tick(position.symbol)
        if info is None or tick is None:
            return {"status": "no_quote"}
        long = getattr(position, "type", 0) == 0
        supported = getattr(info, "filling_mode", 0) or 0
        filling = mt5.ORDER_FILLING_FOK if supported & getattr(mt5, "SYMBOL_FILLING_FOK", 1) else mt5.ORDER_FILLING_IOC
        request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": position.symbol, "volume": position.volume,
                   "type": mt5.ORDER_TYPE_SELL if long else mt5.ORDER_TYPE_BUY, "position": position.ticket,
                   "price": tick.bid if long else tick.ask, "deviation": 20, "magic": MAGIC,
                   "comment": "pilot close", "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling}
        check = mt5.order_check(request)
        if check is None or check.retcode != 0:
            return {"status": "refused_by_broker_check"}
        result = mt5.order_send(request)
        return {"status": "sent", "retcode": getattr(result, "retcode", None)}

    def reconcile(self, store, *, now: datetime, offset_hours: float = 0.0) -> dict:
        """Follow the open orders: close what outlived its horizon or lost its protection, book what is closed."""
        rows = store.open_orders()
        if not rows:
            return {"checked": 0, "closed": 0}
        try:
            mt5, _ = self._connect()
        except RuntimeError as exc:
            return {"checked": len(rows), "closed": 0, "error": str(exc)[:200]}
        closed = 0
        try:
            positions = {getattr(p, "ticket", None): p for p in self._ours(mt5)}
            for row in rows:
                position = positions.get(row["position_ticket"])
                if position is not None:
                    opened = datetime.fromisoformat(row["opened_at"])
                    if not ((getattr(position, "sl", 0) or 0) > 0 and (getattr(position, "tp", 0) or 0) > 0):
                        self._close(mt5, position)
                        store.close_order(row["decision_id"], state="closed_unprotected", profit=None,
                                          reason="sans protection", now=now)
                        store.set_killed()
                        store.add_alert("position_unprotected", f"Position {row['position_ticket']} sans protection : fermée, "
                                        "arrêt des nouvelles entrées activé.")
                        store.journal.log("autopilot.position_unprotected", row["decision_id"],
                                          {"symbol": row["symbol"], "ticket": row["position_ticket"]})
                    elif row["max_age_seconds"] and (now - opened).total_seconds() > row["max_age_seconds"]:
                        self._close(mt5, position)  # the strategy's horizon, like its simulated twin
                    continue
                deals = mt5.history_deals_get(position=row["position_ticket"])
                if deals is None:
                    continue
                outs = [d for d in deals if getattr(d, "entry", None) in DEAL_OUT]
                if not outs:
                    if (now - datetime.fromisoformat(row["opened_at"])).total_seconds() > 600:
                        store.close_order(row["decision_id"], state="vanished", profit=None, reason="introuvable", now=now)
                        store.add_alert("order_vanished", f"Ordre {row['position_ticket']} introuvable chez le courtier.")
                    continue
                profit = sum((getattr(d, "profit", 0) or 0) + (getattr(d, "commission", 0) or 0) + (getattr(d, "swap", 0) or 0)
                             + (getattr(d, "fee", 0) or 0) for d in deals)
                reason = REASONS.get(getattr(outs[-1], "reason", None), "autre")
                store.close_order(row["decision_id"], state="closed", profit=round(profit, 2), reason=reason, now=now)
                store.journal.log("autopilot.order_closed", row["decision_id"],
                                  {"symbol": row["symbol"], "arm": row["arm"], "profit": round(profit, 2), "reason": reason})
                closed += 1
        finally:
            mt5.shutdown()
        return {"checked": len(rows), "closed": closed}
