"""Untrusted event normalization. Source adapters will be added after API credentials."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlparse


@dataclass(frozen=True)
class NewsEvent:
    event_id: str
    source: str
    url: str
    headline: str
    published_at: datetime
    received_at: datetime
    verified_at: datetime | None
    status: str  # unconfirmed / confirmed / retracted
    severity: str  # low / medium / critical
    assets: tuple[str, ...]
    corroborations: tuple[str, ...] = ()

    @property
    def pauses_entries(self) -> bool:
        return self.severity == "critical" and self.status != "retracted"


def normalize_event(*, source: str, url: str, headline: str, published_at: datetime,
                    received_at: datetime, status="unconfirmed", severity="low",
                    assets=(), corroborations=(), verified_at=None) -> NewsEvent:
    if not all(x.tzinfo is not None for x in (published_at, received_at)):
        raise ValueError("UTC-aware event timestamps required")
    published_at = published_at.astimezone(timezone.utc)
    received_at = received_at.astimezone(timezone.utc)
    verified_at = verified_at.astimezone(timezone.utc) if verified_at else None
    if published_at > received_at or (verified_at is not None and verified_at < received_at):
        raise ValueError("Impossible event chronology")
    if urlparse(url).scheme != "https" or not urlparse(url).netloc or not source or not headline.strip():
        raise ValueError("Source URL and headline required")
    if status not in {"confirmed", "unconfirmed", "retracted"} or severity not in {"low", "medium", "critical"}:
        raise ValueError("Invalid classification")
    if status == "confirmed" and verified_at is None:
        raise ValueError("Confirmation requires verification timestamp")
    normalized = " ".join(headline.casefold().split())
    event_id = sha256(f"{source.casefold()}|{normalized}|{published_at.isoformat()}".encode()).hexdigest()[:32]
    return NewsEvent(event_id, source, url, headline[:500], published_at, received_at,
                     verified_at, status, severity, tuple(assets), tuple(corroborations))


def active_halt(events: list[NewsEvent], symbol: str, as_of: datetime) -> bool:
    if as_of.tzinfo is None:
        raise ValueError("Aware decision time required")
    # Do not use a later retraction or verification when replaying historical decisions.
    return any(e.received_at <= as_of and e.severity == "critical" and symbol in e.assets
               and (e.status != "retracted" or (e.verified_at is not None and e.verified_at > as_of))
               for e in events)
