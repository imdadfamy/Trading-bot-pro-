"""Fail-closed quality gate for broker candle batches."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Callable
from .market import Candle


@dataclass(frozen=True)
class QualityReport:
    accepted: bool
    reasons: tuple[str, ...]
    candle_count: int
    coverage: float
    latest_age_seconds: float | None


def assess(candles: list[Candle], as_of: datetime, *, expected_seconds: int,
           max_age_seconds: float, max_gap_intervals: int = 0,
           explained_gap: Callable[[datetime, datetime], bool] | None = None) -> QualityReport:
    """``explained_gap(previous_close, next_open)`` may admit planned closures; any other gap is refused."""
    if as_of.tzinfo is None or expected_seconds <= 0 or max_age_seconds <= 0 or max_gap_intervals < 0:
        raise ValueError("Invalid quality gate parameters")
    if not candles:
        return QualityReport(False, ("No market data",), 0, 0, None)
    reasons = []
    ordered = sorted(candles, key=lambda c: c.opened_at)
    if ordered != candles:
        reasons.append("Candles out of order")
    if len({(c.broker, c.symbol, c.opened_at) for c in candles}) != len(candles):
        reasons.append("Duplicate candle")
    if len({(c.broker, c.symbol) for c in candles}) != 1:
        reasons.append("Mixed broker or symbol")
    if any(c.closed_at > as_of for c in candles):
        reasons.append("Unclosed or future candle")
    if any((c.closed_at-c.opened_at).total_seconds() != expected_seconds for c in candles):
        reasons.append("Unexpected timeframe")
    gaps = sum(max(0, round((b.opened_at-a.closed_at).total_seconds()/expected_seconds))
               for a,b in zip(ordered, ordered[1:])
               if not (explained_gap is not None and b.opened_at > a.closed_at and explained_gap(a.closed_at, b.opened_at)))
    if any(a.closed_at > b.opened_at for a,b in zip(ordered,ordered[1:])):
        reasons.append("Overlapping candles")
    if gaps > max_gap_intervals:
        reasons.append("Unexplained market gaps")
    age = (as_of-ordered[-1].closed_at).total_seconds()
    if age < 0 or age > max_age_seconds:
        reasons.append("Stale market data")
    # Detect gross data errors, not ordinary market volatility. Never auto-correct.
    closes = [c.close for c in candles]
    baseline = median(closes)
    if baseline <= 0 or any(abs(v/baseline-1) > .5 for v in closes):
        reasons.append("Extreme price outlier")
    coverage = len(candles)/(len(candles)+gaps) if len(candles)+gaps else 0
    return QualityReport(not reasons, tuple(reasons), len(candles), coverage, age)
