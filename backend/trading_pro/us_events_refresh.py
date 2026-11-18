"""Refresh ``config/us_events.json`` from the official sources.

* Federal Reserve FOMC calendar: fetched from the Fed's public page by an explicit command.
* BLS release calendar: bls.gov refuses scripted downloads (HTTP 403), so the official ``bls.ics`` file is
  downloaded by a person in a browser and imported from disk. No access restriction is bypassed.
Nothing here is scheduled; every refresh is an explicit command whose result is validated before writing.
"""
from __future__ import annotations

import html
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener

from .integrations import _NoRedirect
from .us_events import KINDS, parse

FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_TIME_ET = "14:00"
BLS_SUMMARIES = {"Employment Situation": "NFP", "Consumer Price Index": "CPI", "Producer Price Index": "PPI"}
MONTHS = {name: i for i, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"), 1)}


def fetch_fed_page(opener=None) -> str:
    request = Request(FED_URL, headers={"User-Agent": "TradingProResearch/1.0 (personal research script)"})
    transport = opener if opener is not None else build_opener(_NoRedirect()).open
    with transport(request, timeout=20) as response:
        if response.status != 200:
            raise ValueError("Federal Reserve calendar request failed")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Federal Reserve page too large")
    return raw.decode("utf-8", errors="replace")


def parse_fed_calendar(page: str, since_year: int | None = None) -> list[dict]:
    """FOMC decision days (second day of each meeting, statement at 14:00 ET), from ``since_year`` on."""
    events = []
    for year_text, body in re.findall(r"<h4><a id=\"[^\"]*\">(\d{4}) FOMC Meetings</a></h4>(.*?)(?=<h4>|Back to Top|\Z)", page, re.S):
        rows = re.findall(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)</div>", body, re.S)
        if since_year is not None and int(year_text) < since_year:
            continue
        for month, days in rows:
            month, days = month.strip(), days.strip().rstrip("*")
            match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", days)
            if month in MONTHS and not match and re.fullmatch(r"\d{1,2}\*?(\s*\(.*\))?", days):
                continue  # single-day entries (notation votes, unscheduled calls) are not scheduled decisions
            if month not in MONTHS or not match:
                raise ValueError(f"Unreadable FOMC row: {month} {days}")
            events.append({"kind": "FOMC", "date": date(int(year_text), MONTHS[month], int(match.group(2))).isoformat(),
                           "time_et": FED_TIME_ET})
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))
    for month, _, end, year in re.findall(r"two-day meeting is scheduled for (\w+) (\d{1,2})-(\d{1,2}), (\d{4})", text):
        if month in MONTHS:
            events.append({"kind": "FOMC", "date": date(int(year), MONTHS[month], int(end)).isoformat(), "time_et": FED_TIME_ET})
    if not events:
        raise ValueError("No FOMC meeting found: the Fed page layout may have changed")
    unique = {(e["kind"], e["date"]): e for e in events}
    return sorted(unique.values(), key=lambda e: e["date"])


def parse_bls_ics(text: str) -> tuple[list[dict], int]:
    """Employment Situation, CPI and PPI releases from the official BLS iCalendar. Returns (events, ignored)."""
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    events, ignored = [], 0
    for block in unfolded.split("BEGIN:VEVENT")[1:]:
        summary = re.search(r"^SUMMARY:(.*)$", block, re.M)
        start = re.search(r"^DTSTART;TZID=([^:]+):(\d{8})T(\d{4})\d{2}", block, re.M)
        if not summary or summary.group(1).strip() not in BLS_SUMMARIES:
            continue
        if not start or "eastern" not in start.group(1).lower():
            ignored += 1  # never guess a time zone
            continue
        day = start.group(2)
        events.append({"kind": BLS_SUMMARIES[summary.group(1).strip()],
                       "date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "time_et": f"{start.group(3)[:2]}:{start.group(3)[2:]}"})
    if not events:
        raise ValueError("No BLS release found in the calendar file")
    unique = {(e["kind"], e["date"]): e for e in events}
    return sorted(unique.values(), key=lambda e: e["date"]), ignored


def merge(document: dict, new_events: list[dict]) -> tuple[dict, dict]:
    """Replace, for each kind present, the existing events from the earliest new date onward."""
    updated = json.loads(json.dumps(document))
    summary = {}
    for kind in {e["kind"] for e in new_events}:
        fresh = [e for e in new_events if e["kind"] == kind]
        earliest = min(e["date"] for e in fresh)
        kept = [e for e in updated["events"] if not (e["kind"] == kind and e["date"] >= earliest)]
        summary[kind] = {"replaced_from": earliest, "removed": len(updated["events"]) - len(kept), "added": len(fresh)}
        updated["events"] = kept + fresh
    updated["events"].sort(key=lambda e: (e["date"], e["time_et"], e["kind"]))
    updated["retrieved_on"] = datetime.now(timezone.utc).date().isoformat()
    parse(updated)  # refuse to write anything invalid
    return updated, summary


def save(path: Path, document: dict) -> None:
    parse(document)
    handle, temp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
