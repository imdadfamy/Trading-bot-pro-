"""Versioned, explainable analysis baseline. No LLM broker access."""
from statistics import mean, pstdev
from .core import Action, Report, Snapshot


def graph_agent(closed_prices: list[float]) -> Report:
    if len(closed_prices) < 20 or any(x <= 0 for x in closed_prices):
        return Report("graph", Action.WAIT, "At least 20 closed candles required")
    fast, slow = mean(closed_prices[-5:]), mean(closed_prices[-20:])
    if abs(fast - slow) / slow < 0.0005:
        return Report("graph", Action.WAIT, "Trend below threshold")
    action = Action.BUY if fast > slow else Action.SELL
    return Report("graph", action, "Five versus twenty closed-candle mean; research only", score=abs(fast-slow)/slow)


def news_agent(snapshot: Snapshot) -> Report:
    if snapshot.critical_event or not snapshot.source_urls:
        return Report("news", Action.WAIT, "Critical event or no verified source coverage", snapshot.source_urls)
    return Report("news", Action.WAIT, "Source URLs alone do not establish directional impact", snapshot.source_urls)


def quant_agent(closed_prices: list[float]) -> Report:
    if len(closed_prices) < 30:
        return Report("quant", Action.WAIT, "Insufficient distribution sample")
    returns = [b/a-1 for a,b in zip(closed_prices[-30:-1], closed_prices[-29:])]
    volatility = pstdev(returns)
    return Report("quant", Action.WAIT, f"Observed return volatility {volatility:.6f}; no calibrated edge")


def risk_agent() -> Report:
    return Report("risk", Action.WAIT, "Risk engine alone determines sizing and veto")
