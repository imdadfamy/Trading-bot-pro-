"""Scheduled US announcements and the caution windows around them.

Dates come from official calendars (BLS for employment, CPI and PPI; the Federal Reserve for FOMC
decisions) kept in ``config/us_events.json``. Inside a window the system must not open new entries.
Only scheduled events can be listed: unscheduled shocks are covered by the critical-news halt, the
spread limit and the stale-quote limit, not by this calendar.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .market import _sunday

KINDS = ("NFP", "CPI", "PPI", "FOMC")
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "us_events.json"
DEFAULT_WINDOWS = {"NFP": (30, 60), "CPI": (30, 60), "FOMC": (30, 90), "PPI": (15, 30)}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def et_to_utc(day: date, hhmm: str) -> datetime:
    """US Eastern wall-clock time to UTC with the statutory DST rule in force since 2007."""
    if day.year < 2007:
        raise ValueError("Eastern time rules before 2007 are not supported")
    hour, minute = (int(part) for part in hhmm.split(":"))
    local = datetime.combine(day, time(hour, minute))
    start = datetime(day.year, 3, _sunday(day.year, 3, 2), 2)   # second Sunday of March, 02:00
    end = datetime(day.year, 11, _sunday(day.year, 11, 1), 2)   # first Sunday of November, 02:00
    offset = 4 if start <= local < end else 5
    return (local + timedelta(hours=offset)).replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Announcement:
    kind: str
    name: str
    at: datetime              # UTC
    before_minutes: int
    after_minutes: int

    @property
    def window_start(self) -> datetime:
        return self.at - timedelta(minutes=self.before_minutes)

    @property
    def window_end(self) -> datetime:
        return self.at + timedelta(minutes=self.after_minutes)


@dataclass(frozen=True)
class Calendar:
    events: tuple[Announcement, ...]
    retrieved_on: date
    sources: dict

    def active(self, when: datetime) -> Announcement | None:
        _require_aware(when)
        for event in self.events:
            if event.window_start <= when <= event.window_end:
                return event
        return None

    def upcoming(self, when: datetime, limit: int = 8) -> list[Announcement]:
        _require_aware(when)
        return [e for e in self.events if e.window_end >= when][:limit]

    def coverage(self, when: datetime, warn_days: int = 30) -> dict:
        _require_aware(when)
        today = when.astimezone(timezone.utc).date()
        result = {}
        for kind in KINDS:
            dates = [e.at.date() for e in self.events if e.kind == kind]
            if not dates:
                result[kind] = {"last_event": None, "days_left": None, "status": "empty"}
                continue
            left = (max(dates) - today).days
            result[kind] = {"last_event": max(dates).isoformat(), "days_left": left,
                            "status": "expired" if left < 0 else "expires_soon" if left <= warn_days else "ok"}
        return result

    def covered(self, when: datetime) -> bool:
        """True when ``when`` lies between the first and the earliest last date of all series."""
        _require_aware(when)
        series = {k: [e.at for e in self.events if e.kind == k] for k in KINDS}
        if not all(series.values()):
            return False
        return max(min(v) for v in series.values()) <= when <= min(max(v) for v in series.values()) + timedelta(days=1)

    def halt_reason(self, when: datetime, *, strict: bool = False) -> str | None:
        """Why new entries must stop at ``when``. ``strict`` also halts when the calendar does not cover it."""
        event = self.active(when)
        if event is not None:
            return f"Scheduled US announcement: {event.kind} at {event.at.strftime('%H:%M')} UTC"
        if strict and not self.covered(when):
            return "US announcement calendar missing or expired"
        return None


def _require_aware(when: datetime) -> None:
    if when.tzinfo is None:
        raise ValueError("Aware time required")


def parse(data: dict) -> Calendar:
    """Validate and convert the JSON document; any malformed entry refuses the whole file."""
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("Unsupported US events file")
    names = data.get("names", {})
    windows = {**{k: {"before": v[0], "after": v[1]} for k, v in DEFAULT_WINDOWS.items()}, **data.get("windows", {})}
    events, seen = [], set()
    for entry in data.get("events", []):
        kind = entry.get("kind")
        if kind not in KINDS:
            raise ValueError(f"Unknown announcement kind: {kind}")
        if not _TIME.match(str(entry.get("time_et", ""))):
            raise ValueError("Invalid Eastern time")
        try:
            day = date.fromisoformat(entry["date"])
        except (KeyError, ValueError):
            raise ValueError("Invalid announcement date") from None
        if (kind, day) in seen:
            raise ValueError(f"Duplicate announcement: {kind} {day}")
        seen.add((kind, day))
        window = windows[kind]
        before, after = window["before"], window["after"]
        if not all(isinstance(m, int) and not isinstance(m, bool) and 0 <= m <= 720 for m in (before, after)):
            raise ValueError("Window minutes must be integers between 0 and 720")
        events.append(Announcement(kind, names.get(kind, kind), et_to_utc(day, entry["time_et"]), before, after))
    events.sort(key=lambda e: e.at)
    try:
        retrieved = date.fromisoformat(data["retrieved_on"])
    except (KeyError, ValueError):
        raise ValueError("retrieved_on date required") from None
    return Calendar(tuple(events), retrieved, dict(data.get("sources", {})))


def load(path: str | Path | None = None) -> Calendar:
    return parse(json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8")))


def describe(calendar: Calendar, when: datetime, limit: int = 8) -> dict:
    """JSON-friendly summary for the API, the CLI and the interface."""
    active = calendar.active(when)
    return {
        "now_utc": when.astimezone(timezone.utc).isoformat(),
        "blackout": None if active is None else {"kind": active.kind, "name": active.name,
                                                 "at_utc": active.at.isoformat(),
                                                 "until_utc": active.window_end.isoformat()},
        "halt_reason": calendar.halt_reason(when),
        "upcoming": [{"kind": e.kind, "name": e.name, "at_utc": e.at.isoformat(),
                      "window_start_utc": e.window_start.isoformat(), "window_end_utc": e.window_end.isoformat(),
                      "before_minutes": e.before_minutes, "after_minutes": e.after_minutes}
                     for e in calendar.upcoming(when, limit)],
        "coverage": calendar.coverage(when),
        "retrieved_on": calendar.retrieved_on.isoformat(),
        "sources": calendar.sources,
        "note": "Scheduled announcements only. Unscheduled events are handled by the critical-news halt, the "
                "spread limit and the stale-quote limit.",
    }
