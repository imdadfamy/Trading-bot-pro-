"""Observed XAUUSD trading schedule on the Deriv demo server.

Derived from 5,000 real M5 bars (23 Oct to 18 Nov 2026) and tied to New York time, so it follows the US
daylight-saving change (the break moved from 21:00 to 22:00 UTC on 1 Nov 2026):

* weekdays Monday to Thursday: no bars from 17:00 to 18:05 New York time;
* weekend: last bar closes Friday about 16:45, first bar opens Sunday about 18:10.

This is an observation, not a statement from the broker: confirm the sessions in the MT5 symbol
specification or with Deriv. Holidays and unplanned closures are NOT listed, so they stay unexplained gaps.
"""
from __future__ import annotations

from datetime import datetime, time

from .market import _local_time

ZONE = "America/New_York"
TOLERANCE_MINUTES = 10  # one M5 bar of slack on each edge


def _minutes(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def _near(moment: datetime, hour: int, minute: int) -> bool:
    return abs(_minutes(moment) - (hour * 60 + minute)) <= TOLERANCE_MINUTES


def explained_gap(previous_close: datetime, next_open: datetime) -> bool:
    """True when the gap matches the daily break or the weekend closure of the observed schedule."""
    start, end = _local_time(previous_close, ZONE), _local_time(next_open, ZONE)
    if start.weekday() <= 3:  # Monday to Thursday: daily break, same calendar day
        return end.date() == start.date() and _near(start, 17, 0) and _near(end, 18, 5)
    if start.weekday() == 4:  # Friday: weekend closure until Sunday evening
        return (end - start).days in (1, 2) and end.weekday() == 6 and _near(start, 16, 45) and _near(end, 18, 10)
    return False


def schedule_for(symbol: str, broker: str):
    """Gap explainer for symbols whose schedule has been observed, else None (every gap stays unexplained)."""
    if symbol.upper().startswith("XAU") and broker.lower().startswith("deriv"):
        return explained_gap
    return None
