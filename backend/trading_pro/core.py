from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from math import isfinite
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


@dataclass(frozen=True)
class Snapshot:
    cycle_id: str
    symbol: str
    bid: float
    ask: float
    observed_at: datetime
    broker: str = "unconnected"
    critical_event: bool = False
    event_confirmed: bool = False
    source_urls: tuple[str, ...] = ()
    halt_reason: str = ""  # why new entries are suspended (scheduled announcement, critical news...)

    def __post_init__(self):
        if (self.observed_at.tzinfo is None or not all(isfinite(x) for x in (self.bid, self.ask))
                or self.bid <= 0 or self.ask < self.bid or not self.cycle_id or not self.symbol):
            raise ValueError("Invalid UTC-aware quote")


@dataclass(frozen=True)
class Report:
    agent: str
    action: Action
    rationale: str
    evidence: tuple[str, ...] = ()
    score: float | None = None  # qualitative; never interpreted as probability


@dataclass(frozen=True)
class Signal:
    signal_id: str
    cycle_id: str
    symbol: str
    action: Action
    created_at: datetime
    expires_at: datetime
    strategy: str
    strategy_version: str
    rationale: str
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    sources: tuple[str, ...] = ()
    status: str = "candidate"
    session: str = "unassigned"
    order_type: str = "market"
    horizon: str = "unspecified"
    invalidation: str = ""
    hypotheses: tuple[str, ...] = ()
    risk_status: str = "not_checked"


class Director:
    """Conservative deterministic director until a validated model adapter is configured."""

    def decide(self, snapshot: Snapshot, reports: list[Report], at: datetime | None = None) -> Signal:
        names = {r.agent for r in reports}
        required = {"graph", "news", "quant", "risk"}
        choices = {r.action for r in reports}
        action = Action.WAIT
        reason = "Insufficient or conflicting independent analyses"
        if snapshot.critical_event:
            reason = snapshot.halt_reason or "Critical event: suspend new entries"
        elif names == required and len(reports) == 4 and len(choices) == 1:
            action = next(iter(choices))
            reason = "Agreement across all four agents; deterministic risk check still required"
        now = at or utcnow()
        from datetime import timedelta
        from .market import session_label
        return Signal(str(uuid4()), snapshot.cycle_id, snapshot.symbol, action, now,
                      now + timedelta(seconds=60), "consensus", "0.1.0", reason,
                      sources=snapshot.source_urls, session=session_label(now),
                      invalidation="New critical event, stale quote or changed market snapshot")


@dataclass(frozen=True)
class Instrument:
    tick_size: float
    tick_value: float  # in account currency, per lot
    volume_min: float
    volume_max: float
    volume_step: float
    commission_per_lot_round_trip: float | None = None
    expected_slippage_ticks: float | None = None


@dataclass(frozen=True)
class Limits:
    risk_per_trade: float = 0.005
    max_daily_loss: float = 0.02
    max_open_risk: float = 0.01
    max_positions: int = 2
    max_spread: float = 0.5  # XAUUSD quote units, configurable after broker validation
    max_quote_age_seconds: float = 5
    max_ai_spend: float = 50


@dataclass(frozen=True)
class RiskState:
    equity: float
    daily_start_equity: float
    open_risk: float = 0
    open_positions: int = 0
    ai_spend: float = 0
    killed: bool = True
    broker_connected: bool = False
    demo_account: bool = False


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    volume: float = 0


def check_risk(signal: Signal, quote: Snapshot, instrument: Instrument,
               state: RiskState, limits: Limits, now: datetime | None = None,
               announcement_halt: str | None = None) -> RiskDecision:
    now = now or utcnow()
    def reject(reason: str) -> RiskDecision:
        return RiskDecision(False, reason)
    if state.killed or not state.broker_connected or not state.demo_account:
        return reject("Demo-only execution disabled or broker unavailable")
    if signal.action == Action.WAIT:
        return reject("WAIT cannot execute")
    if announcement_halt:
        return reject(announcement_halt)
    if signal.status != "validated":
        return reject("Signal is not validated")
    numeric = (state.equity, state.daily_start_equity, state.open_risk, state.ai_spend,
               limits.risk_per_trade, limits.max_daily_loss, limits.max_open_risk,
               limits.max_spread, limits.max_quote_age_seconds, limits.max_ai_spend,
               instrument.tick_size, instrument.tick_value, instrument.volume_min,
               instrument.volume_max, instrument.volume_step)
    if not all(isfinite(v) for v in numeric) or any(v < 0 for v in numeric):
        return reject("Non-finite or negative risk metadata")
    if limits.risk_per_trade <= 0 or limits.max_open_risk <= 0 or limits.max_positions <= 0:
        return reject("Invalid risk configuration")
    if now.tzinfo is None or quote.observed_at.tzinfo is None or signal.expires_at.tzinfo is None:
        return reject("Timezone missing")
    if now >= signal.expires_at or signal.cycle_id != quote.cycle_id or signal.symbol != quote.symbol:
        return reject("Expired or mismatched snapshot")
    if signal.created_at.tzinfo is None or signal.created_at > now:
        return reject("Signal timestamp invalid")
    age = (now - quote.observed_at).total_seconds()
    if age < -1 or age > limits.max_quote_age_seconds:
        return reject("Quote stale or clock out of sync")
    if quote.critical_event:
        return reject(quote.halt_reason or "Critical event")
    if quote.ask - quote.bid > limits.max_spread:
        return reject("Spread too wide")
    if state.ai_spend >= limits.max_ai_spend:
        return reject("AI budget exceeded")
    if state.equity <= 0 or state.daily_start_equity <= 0:
        return reject("Invalid equity")
    if state.daily_start_equity - state.equity >= state.daily_start_equity * limits.max_daily_loss:
        return reject("Daily loss limit")
    if state.open_positions >= limits.max_positions or state.open_risk >= state.equity * limits.max_open_risk:
        return reject("Aggregate exposure limit")
    entry = quote.ask if signal.action == Action.BUY else quote.bid
    stop = signal.stop_loss
    take = signal.take_profit
    if (stop is None or take is None or not all(isfinite(x) for x in (stop, take))
            or not (stop < entry < take if signal.action == Action.BUY else take < entry < stop)):
        return reject("Invalid broker-side stop or target")
    if instrument.tick_size <= 0 or instrument.tick_value <= 0 or instrument.volume_step <= 0 or instrument.volume_min <= 0:
        return reject("Invalid instrument metadata")
    if (instrument.commission_per_lot_round_trip is None or instrument.expected_slippage_ticks is None
            or not isfinite(instrument.commission_per_lot_round_trip) or not isfinite(instrument.expected_slippage_ticks)
            or instrument.commission_per_lot_round_trip < 0 or instrument.expected_slippage_ticks < 0):
        return reject("Broker commission and slippage assumptions required")
    cash_risk = min(state.equity * limits.risk_per_trade,
                    state.equity * limits.max_open_risk - state.open_risk)
    risk_per_lot = ((abs(entry - stop) / instrument.tick_size + instrument.expected_slippage_ticks)
                    * instrument.tick_value + instrument.commission_per_lot_round_trip)
    if cash_risk <= 0 or risk_per_lot <= 0:
        return reject("No risk capacity")
    raw = Decimal(str(cash_risk / risk_per_lot))
    step = Decimal(str(instrument.volume_step))
    volume = float((raw / step).to_integral_value(rounding=ROUND_DOWN) * step)
    volume = min(volume, instrument.volume_max)
    if volume < instrument.volume_min:
        return reject("Minimum volume exceeds risk limit")
    return RiskDecision(True, "Approved for demo preflight only", volume)
