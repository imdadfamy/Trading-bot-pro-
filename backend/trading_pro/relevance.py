"""Transparent keyword relevance labels for news headlines.

This is a coarse, deterministic triage to keep noise out of the research store. It never assigns
an asset, a direction or a severity: a "high" label only means the headline is about the global
gold market in the wording below, not that it is true, confirmed or tradable.
"""
from __future__ import annotations

import re
from collections import Counter

LEVELS = ("none", "low", "medium", "high")

_GOLD_MARKET = {
    "xauusd": r"\bxau\s?/?\s?usd\b",
    "spot_gold": r"\bspot gold\b",
    "gold_price": r"\b(gold|bullion)\s+(price|prices|futures|rate|rates|etfs?|rally|rallies|slump|surge|surges|"
                  r"drops?|falls?|rises?|hits?|settles?|extends?|steadies|edges|climbs?|slides?|tumbles?|"
                  r"jumps?|retreats?|rebounds?|holds?|record|outlook|forecast)\b",
    "price_of_gold": r"\bprice of gold\b",
    "gold_bullion": r"\b(gold bullion|bullion)\b",
    "comex_gold": r"\bcomex\b.*\bgold\b|\bgold\b.*\bcomex\b",
    "gold_ounce": r"\bgold\b.*\b(per ounce|an ounce|/oz)\b",
    "gold_reserves": r"\b(central bank|central banks)\b.*\bgold\b|\bgold (reserves?|purchases|buying|holdings)\b",
    "gold_etf": r"\bgold[- ]backed\b|\bspdr gold\b|\bgld\b",
}
_MACRO = {
    "fed": r"\b(federal reserve|fomc|the fed)\b|\bfed (holds?|cuts?|raises?|hikes?|signals?|minutes|chair|officials?|rates?|policy)\b",
    "rates": r"\b(interest rates?|rate cuts?|rate hikes?)\b",
    "inflation": r"\b(inflation|cpi|pce)\b",
    "yields": r"\b(treasury yields?|bond yields?)\b",
    "dollar": r"\b(dollar index|dxy|us dollar)\b",
    "jobs": r"\b(nonfarm|non-farm|payrolls?|jobs report)\b",
    "geopolitics": r"\b(geopolitical|sanctions?|tariffs?|safe[- ]haven)\b",
}
# Headlines using "gold" in another sense (sport, places, entertainment) or selling products.
_NOISE = re.compile(
    r"\bgold (medals?|coast|cup|glove|record|card|standard|stars?|rush game)\b|\bgolden\b|\bolympi|"
    r"\b(jewell?ery|jewelers?|jewellers?)\b|\bgold[- ]plated\b|\bwedding\b|\bgold diggers?\b|"
    r"\bfree shipping\b|\b\d+% off\b|\bdeals? at\b|\bcoupon\b|\bbullion coins?\b",
    re.IGNORECASE)
# Local retail price pages (rupees, tola, carat...) concern jewellery rates, not the XAUUSD market.
_RETAIL_LOCAL = re.compile(
    r"₹|\brs\.?\s?\d|\brupees?\b|\btola\b|\blakh\b|\bcarat\b|\b(18|20|22|24)\s?k\b|\b10 gram\b|\bper gram\b",
    re.IGNORECASE)
# Mining company news is about equities, only indirectly about the metal.
_MINERS = re.compile(
    r"\b(shares?|stocks?|resources|mining|miners?|producers?|explorers?|asx|sedar|ni 43-101|"
    r"production|quarterly|dividend)\b",
    re.IGNORECASE)
_GOLD_WORD = re.compile(r"\bgold\b", re.IGNORECASE)
_COMPILED_MARKET = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in _GOLD_MARKET.items()}
_COMPILED_MACRO = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in _MACRO.items()}


def classify(headline: str) -> tuple[str, tuple[str, ...]]:
    """Return (level, matched topics) for one headline."""
    text = " ".join(str(headline).split())
    market = tuple(sorted(n for n, rx in _COMPILED_MARKET.items() if rx.search(text)))
    macro = tuple(sorted(n for n, rx in _COMPILED_MACRO.items() if rx.search(text)))
    if market:
        if _NOISE.search(text):
            return "none", ()
        if _RETAIL_LOCAL.search(text):
            return "medium", market + ("retail_local",)
        if _MINERS.search(text):
            return "medium", market + ("miners",)
        return "high", market
    if _NOISE.search(text):
        return "none", ()
    if macro:
        return "medium", macro
    if _GOLD_WORD.search(text):
        return "low", ("gold_word",)
    return "none", ()


def select(events, *, minimum: str = "medium", max_per_source: int = 5):
    """Keep events at or above ``minimum`` and cap each source; return (kept, report)."""
    if minimum not in LEVELS[1:]:
        raise ValueError("Minimum relevance must be low, medium or high")
    if max_per_source < 1:
        raise ValueError("At least one article per source must be allowed")
    floor = LEVELS.index(minimum)
    per_source: Counter = Counter()
    kept, below, capped = [], 0, 0
    labels = Counter()
    for event in events:
        labels[event.relevance] += 1
        if LEVELS.index(event.relevance) < floor:
            below += 1
        elif per_source[event.source] >= max_per_source:
            capped += 1
        else:
            per_source[event.source] += 1
            kept.append(event)
    return kept, {"received": sum(labels.values()), "kept": len(kept), "dropped_below_relevance": below,
                  "dropped_by_source_cap": capped, "relevance_counts": dict(labels)}
