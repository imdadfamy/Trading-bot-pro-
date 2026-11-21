"""Real-world plumbing for the pilot: read-only MT5 candles and the optional model provider."""
from __future__ import annotations

import time
from dataclasses import replace

from .autopilot import ModelSetup
from .mt5_status import DEFAULT_TERMINAL, credentials_from_env

OFFSET_TTL_SECONDS = 3600
WARMUP_TRIES = 4
WARMUP_PAUSE_SECONDS = 3.0


def fetch_when_fresh(fetch_once, *, step_seconds: int, clock=time.time, sleep=time.sleep,
                     tries: int = WARMUP_TRIES, pause: float = WARMUP_PAUSE_SECONDS):
    """A symbol that was just added to Market Watch answers with old bars until its history has synchronised.

    Ask again a few times (about ten seconds in all) until the last closed bar is recent, then give up and
    return what we have: the pilot reports such data as stale rather than analysing it.
    """
    for attempt in range(max(tries, 1)):
        candles, meta = fetch_once()
        if candles and clock() - candles[-1].closed_at.timestamp() <= 3 * step_seconds:
            return candles, meta
        if attempt < tries - 1:
            sleep(pause)
    return candles, meta


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
    warmed: set[str] = set()

    def fetch(symbol: str, timeframe: str, count: int):
        if symbol in warmed:
            return fetch_once(symbol, timeframe, count)
        result = fetch_when_fresh(lambda: fetch_once(symbol, timeframe, count),
                                  step_seconds=mt5_history.TIMEFRAMES[timeframe], clock=clock)
        warmed.add(symbol)  # only the first fetch of a symbol waits: later stale data means a closed market
        return result

    def fetch_once(symbol: str, timeframe: str, count: int):
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


def mt5_executor(*, module=None, environ=None):
    """The only automatic path to order_send. Built once per server process, used by the pilot thread alone."""
    from .autopilot_exec import Executor
    if module is None:
        import MetaTrader5 as module  # type: ignore
    login, server, password = credentials_from_env(environ)
    path = str(DEFAULT_TERMINAL) if DEFAULT_TERMINAL.is_file() else None
    return Executor(module, login, server, password, path)


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
