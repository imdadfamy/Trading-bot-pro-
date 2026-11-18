"""Point-in-time market data, closed candles and local exchange sessions."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from math import isfinite
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from calendar import monthrange


@dataclass(frozen=True)
class Candle:
    symbol: str
    opened_at: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    bid: float
    ask: float
    broker: str
    tick_volume: int = 0

    def __post_init__(self):
        if self.opened_at.tzinfo is None or self.closed_at.tzinfo is None or self.closed_at <= self.opened_at:
            raise ValueError("Candle requires an aware, increasing interval")
        if not all(isfinite(v) and v > 0 for v in (self.open, self.high, self.low, self.close, self.bid, self.ask)):
            raise ValueError("Non-finite or non-positive market price")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.ask < self.bid:
            raise ValueError("Inconsistent OHLC or spread")
        if not self.symbol or not self.broker or self.tick_volume < 0:
            raise ValueError("Missing source identity or negative volume")


# Indicative forex sessions, not an assertion about the broker's XAUUSD hours.
SESSION_WINDOWS = {
    "Sydney": ("Australia/Sydney", 8, 17),
    "Tokyo": ("Asia/Tokyo", 9, 18),
    "London": ("Europe/London", 8, 17),
    "New York": ("America/New_York", 8, 17),
}


def _sunday(year: int, month: int, ordinal: int) -> int:
    days = [day for day in range(1, monthrange(year, month)[1]+1)
            if datetime(year, month, day).weekday() == 6]
    return days[ordinal-1 if ordinal > 0 else ordinal]


@lru_cache(maxsize=None)
def _zone(name: str):
    """IANA zone, or None when the tz database is not installed (remembered: the lookup is slow to fail)."""
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return None


def _local_time(instant: datetime, zone: str) -> datetime:
    known = _zone(zone)
    if known is not None:
        return instant.astimezone(known)
    # Windows may omit IANA tzdb. Current statutory rules only (since 2007).
    # Production pins tzdata; old backtests require the full historical database.
    utc = instant.astimezone(timezone.utc)
    year = utc.year
    if year < 2007:
        raise ValueError("Historical IANA tzdata required before 2007")
    if zone == "Asia/Tokyo":
        offset = 9
    elif zone == "Europe/London":
        start = datetime(year, 3, _sunday(year, 3, -1), 1, tzinfo=timezone.utc)
        end = datetime(year, 10, _sunday(year, 10, -1), 1, tzinfo=timezone.utc)
        offset = 1 if start <= utc < end else 0
    elif zone == "America/New_York":
        start = datetime(year, 3, _sunday(year, 3, 2), 7, tzinfo=timezone.utc)
        end = datetime(year, 11, _sunday(year, 11, 1), 6, tzinfo=timezone.utc)
        offset = -4 if start <= utc < end else -5
    elif zone == "Australia/Sydney":
        april_end = datetime(year, 4, _sunday(year, 4, 1), 16, tzinfo=timezone.utc)-timedelta(days=1)
        october_start = datetime(year, 10, _sunday(year, 10, 1), 16, tzinfo=timezone.utc)-timedelta(days=1)
        offset = 11 if utc < april_end or utc >= october_start else 10
    else:
        raise ZoneInfoNotFoundError(f"No time zone found with key {zone}")
    return utc.astimezone(timezone(timedelta(hours=offset)))


def sessions_at(instant: datetime) -> tuple[str, ...]:
    if instant.tzinfo is None:
        raise ValueError("UTC aware instant required")
    active = []
    for name, (zone, start, end) in SESSION_WINDOWS.items():
        local = _local_time(instant, zone)
        if local.weekday() < 5 and start <= local.hour < end:
            active.append(name)
    return tuple(active)


def session_label(instant: datetime) -> str:
    active = sessions_at(instant)
    if "London" in active and "New York" in active:
        return "London/New York overlap"
    # Fixed priority ensures one primary attribution; preserve active sessions separately.
    for name in ("New York", "London", "Tokyo", "Sydney"):
        if name in active:
            return name
    return "Outside indicative sessions"


def closed_as_of(candles: list[Candle], instant: datetime) -> list[Candle]:
    if instant.tzinfo is None:
        raise ValueError("Aware decision time required")
    seen = set()
    result = []
    for candle in sorted(candles, key=lambda c: c.closed_at):
        if candle.closed_at > instant:
            continue
        key = (candle.broker, candle.symbol, candle.opened_at)
        if key in seen:
            raise ValueError("Duplicate candle; resolve before analysis")
        seen.add(key)
        result.append(candle)
    return result
