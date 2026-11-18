"""Dry-run of an order against the MT5 demo account: the broker validates it, nothing is executed.

Only ``order_check`` is added to the read-only allowlist. ``order_send`` and every other trading function stay
unreachable (the wrapper raises), and the module never builds a request it could send: it asks the broker to
*check* a minimal order (smallest allowed volume, stops beyond the broker minimum) for each requested side.
If the terminal's "Trading algo" switch is off the broker answers code 10027; that answer is reported as is,
never worked around.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from .broker import MT5DemoBroker
from .core import Action, Signal, Snapshot, utcnow
from .mt5_status import ALLOWED, ReadOnlyMT5, connect_demo

DRY_RUN_ALLOWED = ALLOWED | {"order_check"}
RETCODES = {
    0: "Requête valide (accord du courtier)",
    10009: "Requête valide (accord du courtier)",
    10027: "Trading algo désactivé dans le terminal : le courtier ne valide rien tant qu'il est éteint",
    10014: "Volume invalide", 10015: "Prix invalide", 10016: "Stops invalides",
    10018: "Marché fermé", 10019: "Fonds insuffisants", 10030: "Mode d'exécution non pris en charge",
    10025: "Aucun changement", 10013: "Requête invalide", 10017: "Trading désactivé pour ce compte",
    10031: "Pas de connexion au serveur de trading", 10033: "Limite d'ordres atteinte",
    10034: "Limite de volume atteinte",
}


def _round(value: float, digits: int) -> float:
    return round(value, digits)


def build_signal(info, tick, side: str, now, multiple: float = 2.0) -> tuple[Signal, Snapshot, float]:
    """A minimal order: smallest volume, stops at ``multiple`` times the broker's real minimum distance."""
    point = float(info.point)
    spread = max(0.0, tick.ask - tick.bid)
    # ``multiple`` times the real minimum, which is the broker's stop level plus the current spread.
    distance = max(multiple * ((getattr(info, "trade_stops_level", 0) or 0) * point + spread), 10 * point)
    digits = int(getattr(info, "digits", 2))
    buy = side == "BUY"
    price = tick.ask if buy else tick.bid
    stop = _round(price - distance if buy else price + distance, digits)
    target = _round(price + 2 * distance if buy else price - 2 * distance, digits)
    cycle = f"dryrun-{uuid4().hex[:8]}"
    signal = Signal(f"dryrun-{uuid4().hex[:8]}", cycle, info.name, Action.BUY if buy else Action.SELL, now,
                    now + timedelta(seconds=60), "dry-run", "1", "order_check only", price, stop, target,
                    status="validated")
    quote = Snapshot(cycle, info.name, tick.bid, tick.ask, now)
    return signal, quote, float(info.volume_min)


def dry_run(module, *, symbol: str, sides=("BUY", "SELL"), expected_login: int, server: str,
            password: str | None, terminal_path: str | None = None, select: bool = False,
            timeout_ms: int = 20000, now=None) -> dict:
    mt5 = ReadOnlyMT5(module, DRY_RUN_ALLOWED)
    connect_demo(mt5, expected_login=expected_login, server=server, password=password,
                 terminal_path=terminal_path, timeout_ms=timeout_ms)
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Symbol {symbol} not found on this account")
        if not getattr(info, "visible", False):
            if not select:
                raise RuntimeError(f"Symbol {symbol} is not in Market Watch: rerun with --select to add it")
            mt5.symbol_select(symbol, True)
        terminal = mt5.terminal_info()
        broker = MT5DemoBroker(mt5, demo_execution_enabled=False)
        results = []
        for side in sides:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise RuntimeError("No tick available: the market may be closed")
            signal, quote, volume = build_signal(info, tick, side, now or utcnow())
            row = {"side": side, "volume": volume, "price": signal.entry, "stop_loss": signal.stop_loss,
                   "take_profit": signal.take_profit, "stops_distance": abs(signal.entry - signal.stop_loss)}
            try:
                request = broker._checked_request(signal, volume, quote, require_trading=False)
                row.update(local_checks="réussis", filling=request["type_filling"])
            except RuntimeError as exc:
                row.update(local_checks=f"échec : {exc}")
            check = broker.last_check
            if check is not None:
                code = getattr(check, "retcode", None)
                row["broker_check"] = {
                    "retcode": code, "meaning": RETCODES.get(code, "Code non répertorié : voir la documentation MQL5"),
                    "comment": getattr(check, "comment", ""), "margin_required": getattr(check, "margin", None),
                    "margin_free_after": getattr(check, "margin_free", None), "balance": getattr(check, "balance", None)}
                row["accepted_by_broker"] = code in (0, 10009)
            else:
                row["accepted_by_broker"] = False
            broker.last_check = None
            results.append(row)
        return {"symbol": symbol, "demo_verified": True, "orders_sent": 0, "trading_algo_enabled":
                getattr(terminal, "trade_allowed", None), "checks": results,
                "note": "Aucun ordre n'est envoyé : le courtier valide seulement la requête."}
    finally:
        mt5.shutdown()
