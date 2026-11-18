"""Explicit server-side provider setup. Credentials never enter read models."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .news import NewsEvent, normalize_event
from .relevance import classify


def credential_status(environ=None) -> dict:
    env = os.environ if environ is None else environ
    return {
        "mt5_demo_account_configured": bool(env.get("TIP_MT5_DEMO_LOGIN") and env.get("TIP_MT5_DEMO_SERVER")),
        "openai_key_present": bool(env.get("OPENAI_API_KEY")),
        "newsapi_key_present": bool(env.get("TIP_NEWSAPI_KEY")),
        "tradingeconomics_key_present": bool(env.get("TIP_TRADING_ECONOMICS_KEY")),
        "verified": False,
        "note": "A configured credential is not proof of account type, coverage, licence or a working integration",
    }


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Provider timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Provider timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def normalize_newsapi(payload: dict, *, received_at: datetime) -> list[NewsEvent]:
    """Headlines are unconfirmed context, never a directional signal or corroboration."""
    if received_at.tzinfo is None or not isinstance(payload, dict) or payload.get("status") != "ok":
        raise ValueError("Invalid NewsAPI response or reception time")
    articles = payload.get("articles")
    if not isinstance(articles, list) or len(articles) > 100:
        raise ValueError("Invalid NewsAPI article batch")
    events = []
    for article in articles:
        if not isinstance(article, dict) or not isinstance(article.get("source"), dict):
            raise ValueError("Invalid NewsAPI article")
        source = article["source"].get("name")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("NewsAPI source missing")
        headline = article.get("title") or ""
        relevance, topics = classify(headline)
        events.append(normalize_event(
            source=source.strip(), url=article.get("url", ""),
            headline=headline, published_at=_parse_time(article.get("publishedAt")),
            received_at=received_at, status="unconfirmed", severity="low", assets=(),
            relevance=relevance, topics=topics))
    return events


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Provider redirect refused to protect credentials")


def fetch_newsapi(*, query: str, api_key: str, opener=None) -> list[NewsEvent]:
    """One bounded, manually triggered call. No background polling or broker actions."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200 or "\n" in query:
        raise ValueError("Invalid news search")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("NewsAPI key missing")
    url = "https://newsapi.org/v2/everything?" + urlencode({
        "q": query.strip(), "searchIn": "title", "language": "en", "sortBy": "publishedAt",
        "pageSize": 100})
    request = Request(url, headers={"X-Api-Key": api_key, "Accept": "application/json"})
    transport = opener if opener is not None else build_opener(_NoRedirect()).open
    with transport(request, timeout=8) as response:
        if response.status != 200:
            raise ValueError("NewsAPI request failed")
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("NewsAPI response too large")
    return normalize_newsapi(json.loads(raw), received_at=datetime.now(timezone.utc))


@dataclass(frozen=True)
class EconomicRelease:
    calendar_id: str
    country: str
    event: str
    scheduled_at: datetime
    received_at: datetime
    importance: int
    actual: str | None
    forecast: str | None
    previous: str | None


def normalize_calendar(payload: list, *, received_at: datetime) -> list[EconomicRelease]:
    """Provider UTC calendar timestamps; no retrospective overwrite or trade decision."""
    if received_at.tzinfo is None or not isinstance(payload, list) or len(payload) > 500:
        raise ValueError("Invalid calendar batch")
    results = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("Invalid calendar row")
        raw_time = row.get("Date")
        if not isinstance(raw_time, str):
            raise ValueError("Calendar date missing")
        scheduled = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        # Trading Economics describes Date in UTC, including when the JSON omits the suffix.
        scheduled = scheduled.replace(tzinfo=timezone.utc) if scheduled.tzinfo is None else scheduled.astimezone(timezone.utc)
        importance = row.get("Importance")
        if isinstance(importance, bool) or str(importance) not in {"0", "1", "2", "3"}:
            raise ValueError("Invalid calendar importance")
        identifier = str(row.get("CalendarId") or "")
        country, event = row.get("Country"), row.get("Event")
        if not identifier.isdecimal() or not isinstance(country, str) or not country.strip() or not isinstance(event, str) or not event.strip():
            raise ValueError("Calendar identity missing")
        def brief(field):
            value = row.get(field)
            return None if value is None else str(value)[:100]
        results.append(EconomicRelease(identifier, country[:100], event[:300], scheduled,
                                       received_at.astimezone(timezone.utc), int(importance),
                                       brief("Actual"), brief("Forecast"), brief("Previous")))
    return results


def fetch_calendar(*, api_key: str, opener=None) -> list[EconomicRelease]:
    """One explicit US-calendar snapshot. A paid licence and quota must be checked first."""
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("Trading Economics key missing")
    request = Request("https://api.tradingeconomics.com/calendar/country/united%20states",
                      headers={"Authorization": api_key, "Accept": "application/json"})
    transport = opener if opener is not None else build_opener(_NoRedirect()).open
    with transport(request, timeout=8) as response:
        if response.status != 200:
            raise ValueError("Calendar request failed")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Calendar response too large")
    return normalize_calendar(json.loads(raw), received_at=datetime.now(timezone.utc))
