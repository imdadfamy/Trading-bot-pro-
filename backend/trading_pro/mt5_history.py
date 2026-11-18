"""Read-only export of closed candles from the MT5 demo account, with the real spread.

MetaTrader candles are built from bid prices; each bar also records the spread in points, so ``ask`` is
rebuilt as ``bid + spread * point``. Bar times are in the broker server's clock: the offset to UTC is
measured from a fresh tick (never assumed) or must be given explicitly when the market is closed.
Only read functions are reachable (see ``mt5_status.ReadOnlyMT5``); no order is ever sent.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .market import Candle
from .mt5_status import ReadOnlyMT5, connect_demo

TIMEFRAMES = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
MAX_BARS = 50000


def server_offset_seconds(mt5: ReadOnlyMT5, symbol: str, *, now_epoch: float, explicit_hours: float | None,
                          wait_seconds: float = 0, sleep=time.sleep, clock=time.time) -> int:
    """Seconds to subtract from broker-clock timestamps to obtain UTC.

    A symbol just added to Market Watch has no live tick yet: wait up to ``wait_seconds``. The tick must be
    recent AND advance while we watch (a live feed): a stale tick whose age is a whole number of hours would
    otherwise be mistaken for a server offset.
    """
    if explicit_hours is not None:
        if not -14 <= explicit_hours <= 14:
            raise ValueError("Server offset must be between -14 and +14 hours")
        return int(round(explicit_hours * 3600))
    started, first_time, first_offset = clock(), None, None
    while True:
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None:
            raw = tick.time - (now_epoch + (clock() - started))
            offset = int(round(raw / 3600.0)) * 3600  # broker servers use whole-hour offsets
            if abs(raw - offset) <= 30 and abs(offset) <= 14 * 3600:
                if first_time is None or offset != first_offset:
                    first_time, first_offset = tick.time, offset
                elif tick.time > first_time:
                    return offset
            else:
                first_time = first_offset = None
        if clock() - started >= wait_seconds:
            break
        sleep(1)
    raise RuntimeError("No live tick to measure the server clock (market closed, or symbol just added): "
                       "retry in a few seconds or pass the server offset explicitly")


def fetch(module, *, symbol: str, timeframe: str, count: int, expected_login: int, server: str,
          password: str | None, terminal_path: str | None = None, select: bool = False,
          utc_offset_hours: float | None = None, now_epoch: float | None = None,
          timeout_ms: int = 20000, wait_seconds: float = 8, sleep=time.sleep) -> tuple[list[Candle], dict]:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Timeframe must be one of {', '.join(TIMEFRAMES)}")
    if not 2 <= count <= MAX_BARS:
        raise ValueError(f"Count must be between 2 and {MAX_BARS}")
    mt5 = ReadOnlyMT5(module)
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
        point = float(info.point)
        if point <= 0:
            raise RuntimeError("Invalid point size")
        now = now_epoch if now_epoch is not None else time.time()
        offset = server_offset_seconds(mt5, symbol, now_epoch=now, explicit_hours=utc_offset_hours,
                                      wait_seconds=wait_seconds, sleep=sleep)
        frame = getattr(mt5, f"TIMEFRAME_{timeframe}")
        rates = mt5.copy_rates_from_pos(symbol, frame, 0, count + 1)  # position 0 is the bar still forming
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No bars returned (code {mt5.last_error()[0]}); open the chart once or widen history")
        step = TIMEFRAMES[timeframe]
        candles: list[Candle] = []
        spreads: list[float] = []
        for rate in rates:
            opened = datetime.fromtimestamp(int(rate["time"]) - offset, tz=timezone.utc)
            closed = opened + timedelta(seconds=step)
            if closed.timestamp() > now:
                continue  # still forming
            close = float(rate["close"])
            spread = max(int(rate["spread"]), 0) * point
            candles.append(Candle(symbol, opened, closed, float(rate["open"]), float(rate["high"]),
                                  float(rate["low"]), close, close, round(close + spread, 10),
                                  server, int(rate["tick_volume"])))
            spreads.append(round(spread, 8))
        if len(candles) < 2:
            raise RuntimeError("Fewer than two closed bars returned")
        if any(a.closed_at > b.opened_at for a, b in zip(candles, candles[1:])):
            raise RuntimeError("Bars are not chronological")
        if len({c.opened_at for c in candles}) != len(candles):
            raise RuntimeError("Duplicate bar times")
        spreads.sort()
        meta = {"symbol": symbol, "timeframe": timeframe, "bars": len(candles),
                "first_open": candles[0].opened_at.isoformat(), "last_close": candles[-1].closed_at.isoformat(),
                "server_offset_hours": offset / 3600, "median_spread": spreads[len(spreads) // 2],
                "max_spread": spreads[-1], "zero_spread_bars": sum(1 for s in spreads if s == 0),
                "orders_sent": 0}
        return candles, meta
    finally:
        mt5.shutdown()
