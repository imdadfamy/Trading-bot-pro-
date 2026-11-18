"""Read-only inspection of the MT5 demo account and instrument specifications.

Nothing here can trade: the terminal object is wrapped so that only an allowlist of read functions is
reachable (``order_send``, ``order_check``, ``positions_*`` and friends raise immediately). The account
must report DEMO before any instrument is read. Credentials are used only if the terminal is not already
logged into the expected account, and they never appear in the output or in error messages.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

ALLOWED = frozenset({"initialize", "login", "shutdown", "last_error", "version", "terminal_info",
                     "account_info", "symbols_get", "symbol_info", "symbol_info_tick", "symbol_select"})
DEFAULT_PATTERNS = ("XAU*", "GOLD*", "*Volatility*", "*Boom*", "*Crash*", "*Step*", "*Jump*", "*Range Break*")
DEFAULT_TERMINAL = Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")
ACCOUNT_MODES = {0: "DEMO", 1: "CONCOURS", 2: "RÉEL"}
SYMBOL_MODES = {0: "désactivé", 1: "achats seulement", 2: "ventes seulement", 3: "fermeture seulement", 4: "complet"}
FILLING_BITS = ((1, "FOK"), (2, "IOC"))


class ReadOnlyMT5:
    """Expose a fixed set of read functions of the MetaTrader5 module and nothing else."""

    def __init__(self, module):
        self._module = module

    def __getattr__(self, name):
        if name.startswith("_") or name not in ALLOWED:
            if name.isupper():  # constants are harmless
                return getattr(self._module, name)
            raise PermissionError(f"MT5 function '{name}' is not allowed in read-only inspection")
        return getattr(self._module, name)


def _mask(login) -> str:
    text = str(login)
    return "*" * max(len(text) - 3, 0) + text[-3:]


def _symbol_row(mt5, info) -> dict:
    mode = getattr(info, "trade_mode", None)
    filling = getattr(info, "filling_mode", 0) or 0
    return {
        "name": info.name, "description": getattr(info, "description", ""),
        "path": getattr(info, "path", ""), "visible_in_market_watch": bool(getattr(info, "visible", False)),
        "digits": getattr(info, "digits", None), "point": getattr(info, "point", None),
        "spread_points": getattr(info, "spread", None), "spread_floating": getattr(info, "spread_float", None),
        "tick_size": getattr(info, "trade_tick_size", None), "tick_value": getattr(info, "trade_tick_value", None),
        "contract_size": getattr(info, "trade_contract_size", None),
        "volume_min": getattr(info, "volume_min", None), "volume_max": getattr(info, "volume_max", None),
        "volume_step": getattr(info, "volume_step", None),
        "stops_level_points": getattr(info, "trade_stops_level", None),
        "freeze_level_points": getattr(info, "trade_freeze_level", None),
        "trading": SYMBOL_MODES.get(mode, str(mode)),
        "filling_modes": [label for bit, label in FILLING_BITS if filling & bit],
        "currency_profit": getattr(info, "currency_profit", None),
    }


def inspect(module, *, expected_login: int, server: str, password: str | None,
            patterns=DEFAULT_PATTERNS, terminal_path: str | None = None, max_symbols: int = 40,
            select_symbols: bool = False, timeout_ms: int = 20000) -> dict:
    """Return a JSON-friendly report. Raises RuntimeError with a safe message on any refusal."""
    mt5 = ReadOnlyMT5(module)
    options = {"timeout": timeout_ms}
    if terminal_path:
        options["path"] = terminal_path
    if not mt5.initialize(**options):
        code = mt5.last_error()[0]
        # -6: the terminal answers but has no authorised account yet. Log in through the official API with the
        # credentials from the server-side configuration; they are passed to MetaTrader only.
        if code != -6 or not password:
            raise RuntimeError(f"MT5 terminal could not be initialised (code {code})")
        if not mt5.initialize(**options, login=expected_login, password=password, server=server):
            raise RuntimeError(f"MT5 login refused (code {mt5.last_error()[0]})")
    try:
        account = mt5.account_info()
        if account is None or getattr(account, "login", None) != expected_login:
            if not password:
                raise RuntimeError("Terminal is not logged into the expected account and no password is configured")
            if not mt5.login(expected_login, password=password, server=server, timeout=timeout_ms):
                raise RuntimeError(f"MT5 login refused (code {mt5.last_error()[0]})")
            account = mt5.account_info()
        if account is None or getattr(account, "login", None) != expected_login:
            raise RuntimeError("MT5 account identity mismatch")
        mode = ACCOUNT_MODES.get(getattr(account, "trade_mode", None), "INCONNU")
        if account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise RuntimeError(f"Account is {mode}, not DEMO: inspection stopped before reading anything else")
        terminal = mt5.terminal_info()
        report = {
            "account": {"login_masked": _mask(account.login), "type": mode, "server": getattr(account, "server", server),
                        "currency": getattr(account, "currency", None), "leverage": getattr(account, "leverage", None),
                        "balance": getattr(account, "balance", None), "trade_allowed": getattr(account, "trade_allowed", None),
                        "expert_trading_allowed": getattr(account, "trade_expert", None)},
            "terminal": {"connected": getattr(terminal, "connected", None),
                         "algo_trading_allowed": getattr(terminal, "trade_allowed", None),
                         "build": getattr(terminal, "build", None), "ping_ms": (getattr(terminal, "ping_last", 0) or 0) / 1000},
            "demo_verified": True, "orders_sent": 0,
        }
        wanted = [p.lower() for p in patterns]
        rows = []
        for info in mt5.symbols_get() or ():
            text = f"{info.name} {getattr(info, 'description', '')}".lower()
            if any(fnmatch.fnmatch(info.name.lower(), p) or fnmatch.fnmatch(text, f"*{p.strip('*')}*") for p in wanted):
                rows.append(info)
        rows.sort(key=lambda i: i.name)
        symbols = []
        for info in rows[:max_symbols]:
            row = _symbol_row(mt5, info)
            if select_symbols and not row["visible_in_market_watch"]:
                mt5.symbol_select(info.name, True)
                row["visible_in_market_watch"] = True
            tick = mt5.symbol_info_tick(info.name) if row["visible_in_market_watch"] else None
            row["last_tick"] = None if tick is None else {"time_utc_epoch": getattr(tick, "time", None),
                                                          "bid": getattr(tick, "bid", None), "ask": getattr(tick, "ask", None)}
            symbols.append(row)
        report["symbols_found"] = len(rows)
        report["symbols"] = symbols
        report["notes"] = ["Les horaires de session du courtier ne sont pas exposés par l'API Python : à relever dans MT5.",
                           "Commissions et glissement ne figurent pas dans l'API : à relever auprès du courtier."]
        return report
    finally:
        mt5.shutdown()


def credentials_from_env(environ=None) -> tuple[int, str, str | None]:
    env = os.environ if environ is None else environ
    login, server = env.get("TIP_MT5_DEMO_LOGIN", ""), env.get("TIP_MT5_DEMO_SERVER", "")
    if not login.isdecimal() or not server:
        raise RuntimeError("TIP_MT5_DEMO_LOGIN (numeric) and TIP_MT5_DEMO_SERVER are required")
    return int(login), server, env.get("TIP_MT5_DEMO_PASSWORD") or None
