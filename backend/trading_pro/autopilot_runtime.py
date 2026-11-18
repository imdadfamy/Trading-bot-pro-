"""Real-world plumbing for the pilot: read-only MT5 candles and the optional model provider."""
from __future__ import annotations

import time
from dataclasses import replace

from .autopilot import ModelSetup
from .mt5_status import DEFAULT_TERMINAL, credentials_from_env

OFFSET_TTL_SECONDS = 3600


def mt5_fetcher(*, module=None, environ=None, clock=time.time):
    """Return ``fetch(symbol, timeframe, count) -> (candles, meta)`` over the read-only MT5 history reader.

    The broker-clock offset is measured from a live tick and reused for an hour, so a closed market only
    makes the data stale (which the pilot reports) instead of making every fetch fail.
    """
    from . import mt5_history
    if module is None:
        import MetaTrader5 as module  # type: ignore
    login, server, password = credentials_from_env(environ)
    path = str(DEFAULT_TERMINAL) if DEFAULT_TERMINAL.is_file() else None
    cache: dict[str, tuple[float, float]] = {}

    def fetch(symbol: str, timeframe: str, count: int):
        known = cache.get(symbol)
        offset = known[0] if known and clock() - known[1] < OFFSET_TTL_SECONDS else None
        try:
            candles, meta = mt5_history.fetch(module, symbol=symbol, timeframe=timeframe, count=count,
                                              expected_login=login, server=server, password=password,
                                              terminal_path=path, select=True, utc_offset_hours=offset)
        except RuntimeError:
            if known is None or offset is not None:
                raise
            candles, meta = mt5_history.fetch(module, symbol=symbol, timeframe=timeframe, count=count,
                                              expected_login=login, server=server, password=password,
                                              terminal_path=path, select=True, utc_offset_hours=known[0])
        cache[symbol] = (meta["server_offset_hours"], clock())
        return candles, meta

    return fetch


def model_setup_provider(service, environ=None):
    """Callable evaluated each cycle: a ModelSetup, or a short reason string when models cannot run."""
    from .openai_provider import provider_from_env

    def provider():
        try:
            client = provider_from_env(environ)
        except ValueError as exc:
            return f"models unavailable: {exc}"[:200]
        configured = service.settings()["settings"]["model_by_agent"]
        models = {name: configured.get(name, "") for name in ("graph", "quant", "news")}
        if not any(models.values()):
            return "models unavailable: no model chosen in Settings"
        return ModelSetup(client, models, replace(service.model_budget(), max_call_usd=0.25))

    return provider
