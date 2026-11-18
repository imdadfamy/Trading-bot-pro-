"""Descriptive, observation-only study of one broker's synthetic-index candles."""
from __future__ import annotations

from math import expm1, isfinite, log, sqrt
from statistics import mean, median, pstdev

from .market import Candle


FAMILIES = frozenset({"volatility", "boom", "crash", "step", "range_break", "jump", "other"})


def _wilson(successes: int, trials: int) -> list[float] | None:
    if trials == 0:
        return None
    z = 1.96
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    margin = z * sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def describe(candles: list[Candle], *, family: str, jump_threshold_pct: float = 1.0) -> dict:
    """Describe closed-bar returns; never claim predictability or produce orders."""
    if family not in FAMILIES:
        raise ValueError("Unknown synthetic-index family")
    if not isfinite(jump_threshold_pct) or jump_threshold_pct <= 0:
        raise ValueError("Jump threshold must be positive and finite")
    if len(candles) < 2:
        raise ValueError("At least two closed candles required")
    if len({(c.broker, c.symbol) for c in candles}) != 1:
        raise ValueError("Do not mix brokers or symbols")
    if any(a.closed_at > b.opened_at for a, b in zip(candles, candles[1:])):
        raise ValueError("Candles must be chronological and non-overlapping")
    periods = {(c.closed_at - c.opened_at).total_seconds() for c in candles}
    if len(periods) != 1:
        raise ValueError("Mixed timeframes")
    returns = [log(b.close / a.close) for a, b in zip(candles, candles[1:])]
    threshold = jump_threshold_pct / 100

    def segment(values: list[float]) -> dict:
        n = len(values)
        up = sum(expm1(r) >= threshold for r in values)
        down = sum(expm1(r) <= -threshold for r in values)
        jumps = up + down
        return {
            "observations": n,
            "median_return_pct": 100 * median(values) if n else None,
            "return_std_pct_per_bar": 100 * pstdev(values) if n > 1 else None,
            "mean_absolute_return_pct": 100 * mean(abs(r) for r in values) if n else None,
            "largest_up_move_pct": 100 * expm1(max(values)) if n else None,
            "largest_down_move_pct": 100 * expm1(min(values)) if n else None,
            "absolute_jump_count": jumps,
            "absolute_jump_frequency": jumps / n if n else None,
            "jump_frequency_wilson_95": _wilson(jumps, n),
            "up_jump_count": up,
            "up_jump_frequency": up / n if n else None,
            "up_jump_wilson_95": _wilson(up, n),
            "down_jump_count": down,
            "down_jump_frequency": down / n if n else None,
            "down_jump_wilson_95": _wilson(down, n),
        }

    split = max(1, int(len(returns) * .8))
    broker, symbol = candles[0].broker, candles[0].symbol
    spreads = sorted(c.ask - c.bid for c in candles)
    execution_cost = None
    typical_move = 100 * mean(abs(r) for r in returns) if returns else 0
    if spreads[-1] > 0 and typical_move > 0:
        spread_pct = 100 * spreads[len(spreads) // 2] / median(c.close for c in candles)
        execution_cost = {"median_spread": spreads[len(spreads) // 2], "max_spread": spreads[-1],
                          "median_spread_pct_of_price": spread_pct,
                          "mean_absolute_bar_move_pct": typical_move,
                          "spread_as_share_of_a_typical_bar_move": spread_pct / typical_move,
                          "note": "A round trip pays about one spread. A share above 1 means the spread alone costs "
                                  "more than the typical move of one bar."}
    return {
        "mode": "observation", "action": "WAIT", "family": family,
        "broker": broker, "symbol": symbol, "timeframe_seconds": int(next(iter(periods))),
        "jump_threshold_pct": jump_threshold_pct,
        "all": segment(returns), "earlier_80_pct": segment(returns[:split]),
        "later_20_pct": segment(returns[split:]),
        "statistically_sufficient": len(returns) >= 100 and len(returns[split:]) >= 30,
        "execution_cost": execution_cost,
        "interpretation": "Descriptive historical frequencies only; confidence interval assumes independent observations and may be misleading for dependent ticks. No prediction, trade signal or broker execution.",
        "feed_note": "Use broker-specific bid/ask and contract metadata before any execution study; public data may differ from the MT5 account.",
    }
