"""Reproducible metrics with explicit treatment of empty samples."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class TradeResult:
    pnl: float
    risk_cash: float
    fees: float
    session: str
    strategy: str


def performance(trades: list[TradeResult], initial_equity: float) -> dict:
    if not isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("Positive starting equity required")
    if any(not isfinite(t.pnl) or t.risk_cash <= 0 or not isfinite(t.risk_cash) for t in trades):
        raise ValueError("Invalid trade result")
    gross_wins = sum(max(0, t.pnl) for t in trades)
    gross_losses = -sum(min(0, t.pnl) for t in trades)
    peak = initial_equity
    equity = initial_equity
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak-equity)/peak)
    count = len(trades)
    return {
        "trades": count, "net_pnl": sum(t.pnl for t in trades),
        "win_rate": sum(t.pnl > 0 for t in trades)/count if count else None,
        "profit_factor": gross_wins/gross_losses if gross_losses else None,
        "expectancy_r": sum(t.pnl/t.risk_cash for t in trades)/count if count else None,
        "max_drawdown": max_drawdown, "total_fees": sum(t.fees for t in trades),
        "small_sample": count < 30,
    }


def by_session(trades: list[TradeResult], initial_equity: float) -> dict[str, dict]:
    labels = sorted({trade.session for trade in trades})
    return {label: performance([t for t in trades if t.session == label], initial_equity) for label in labels}
