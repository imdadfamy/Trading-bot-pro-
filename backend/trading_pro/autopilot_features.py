"""Numeric features and skill packs for the automatic research agents.

Features are computed by code from closed candles only (the specification: numbers by code, never by the
model). A skill pack is a small, reproducible selection of the project's own skill files, chosen from the
cycle id so that an experiment can later measure what each skill adds. Nothing here reaches a broker.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from statistics import mean

from .market import Candle, session_label

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"
SECTIONS = ("Objective", "Method", "Evidence", "Decision rules", "Limits", "Abstention")
MAX_NOTE_CHARS = 3200  # per skill
SYNTHETIC_HINTS = ("volatility", "boom", "crash", "step", "jump", "range break", "dex", "drift")
SPIKE_FAMILIES = ("boom", "crash", "jump", "dex")


def has_family_word(symbol: str, names=SPIKE_FAMILIES) -> bool:
    """Whole-word match: the word "Index" must not be read as the DEX family."""
    return any(re.search(rf"\b{name}\b", symbol.lower()) for name in names)


def is_synthetic(symbol: str) -> bool:
    return has_family_word(symbol, SYNTHETIC_HINTS)


def atr(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    ranges = []
    for previous, bar in zip(candles[-period - 1:-1], candles[-period:]):
        ranges.append(max(bar.high - bar.low, abs(bar.high - previous.close), abs(bar.low - previous.close)))
    return mean(ranges)


def _swings(candles: list[Candle], width: int = 3) -> tuple[list[float], list[float]]:
    highs, lows = [], []
    for i in range(width, len(candles) - width):
        window = candles[i - width:i + width + 1]
        if candles[i].high == max(c.high for c in window):
            highs.append(candles[i].high)
        if candles[i].low == min(c.low for c in window):
            lows.append(candles[i].low)
    return highs, lows


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[-period - 1:-1], closes[-period:]):
        gains += max(b - a, 0.0)
        losses += max(a - b, 0.0)
    return 100.0 if losses == 0 else round(100 - 100 / (1 + gains / losses), 2)


def spike_stats(candles: list[Candle], k: float = 5.0) -> dict | None:
    """Spikes of a Boom/Crash/Jump/DEX style index: description only (a spike is never 'due')."""
    symbol = candles[-1].symbol.lower()
    if not has_family_word(symbol) or len(candles) < 110:
        return None
    direction = "up" if "boom" in symbol else "down" if "crash" in symbol else "both"
    closes = [c.close for c in candles]
    moves = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    flagged, sizes = [], []
    for i in range(101, len(closes)):
        recent = sorted(abs(x) for x in moves[i - 101:i - 1])
        scale = recent[len(recent) // 2] or 1e-12
        ratio = moves[i - 1] / scale
        hit = ratio >= k if direction == "up" else ratio <= -k if direction == "down" else abs(ratio) >= k
        if hit:
            flagged.append(i)
            sizes.append(abs(moves[i - 1]))
    gaps = [b - a for a, b in zip(flagged, flagged[1:])]
    sizes.sort()
    return {"direction": direction, "window_bars": len(closes) - 101, "count": len(flagged),
            "mean_interval_bars": round(mean(gaps), 2) if gaps else None,
            "bars_since_last_spike": (len(closes) - 1 - flagged[-1]) if flagged else None,
            "median_move_pct": round(sizes[len(sizes) // 2] * 100, 4) if sizes else None,
            "p90_move_pct": round(sizes[int(0.9 * (len(sizes) - 1))] * 100, 4) if sizes else None,
            "enough_for_statistics": len(flagged) >= 30,
            "note": "description only: spike waiting times behave like a memoryless process"}


def ma_rsi_setup(candles: list[Candle], value: float | None) -> dict | None:
    """Conditions of the circulated SMA20/SMA50 + RSI14 swing method, exactly as the project tested it."""
    closes = [c.close for c in candles]
    if len(closes) < 60 or not value:
        return None
    s20, s50 = mean(closes[-20:]), mean(closes[-50:])
    since = None
    for back in range(0, 100):
        end = len(closes) - back
        if end < 51:
            break
        now_up = mean(closes[end - 20:end]) > mean(closes[end - 50:end])
        before_up = mean(closes[end - 21:end - 1]) > mean(closes[end - 51:end - 1])
        if now_up != before_up:
            since = back
            break
    r = rsi(closes)
    prev = candles[-1]
    p20 = mean(closes[-21:-1])
    tolerance = 0.2 * mean(c.high - c.low for c in candles[-14:])
    recent_cross = since is not None and since <= 30
    buy = bool(recent_cross and s20 > s50 and r is not None and 50 < r < 70 and prev.low <= p20 + tolerance and prev.close > p20)
    sell = bool(recent_cross and s20 < s50 and r is not None and 30 < r < 50 and prev.high >= p20 - tolerance and prev.close < p20)
    return {"sma20": round(s20, 6), "sma50": round(s50, 6), "sma20_above_sma50": s20 > s50, "bars_since_cross": since,
            "rsi14": r, "buy_conditions_met": buy, "sell_conditions_met": sell,
            "note": "hypothesis only: the project's own test found no edge against random entries"}


def drift_stats(closes: list[float], window: int = 60) -> dict | None:
    if len(closes) < window + 1:
        return None
    moves = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - window, len(closes))]
    deviation = (sum((x - mean(moves)) ** 2 for x in moves) / (len(moves) - 1)) ** 0.5
    t = mean(moves) / (deviation / len(moves) ** 0.5) if deviation > 0 else None
    return {"window_bars": window, "mean_return_per_bar": round(mean(moves), 8), "t_statistic": round(t, 2) if t is not None else None}


def features(candles: list[Candle]) -> dict:
    """Reproducible numeric description of the last closed bars (no look-ahead)."""
    if len(candles) < 30:
        return {"available": False, "reason": "fewer than 30 closed candles"}
    last = candles[-1]
    value = atr(candles)
    recent = candles[-20:]
    high20, low20 = max(c.high for c in recent), min(c.low for c in recent)
    highs, lows = _swings(candles[-120:])
    structure = "mixed"
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            structure = "higher_highs_and_higher_lows"
        elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            structure = "lower_highs_and_lower_lows"
    history = [atr(candles[:i]) for i in range(30, len(candles) + 1, 5)]
    history = [h for h in history if h]
    percentile = (sum(h <= value for h in history) / len(history)) if history and value else None
    volumes = [c.tick_volume for c in candles[-21:-1]]
    spread = max(last.ask - last.bid, 0.0)
    return {
        "available": True,
        "atr_14": round(value, 6) if value else None,
        "atr_percentile": round(percentile, 3) if percentile is not None else None,
        "range_20": {"high": high20, "low": low20,
                     "position_0_to_1": round((last.close - low20) / (high20 - low20), 3) if high20 > low20 else None},
        "swing_highs": [round(h, 6) for h in highs[-3:]], "swing_lows": [round(l, 6) for l in lows[-3:]],
        "structure": structure,
        "tick_volume_ratio": round(last.tick_volume / mean(volumes), 3) if volumes and mean(volumes) > 0 else None,
        "spread": round(spread, 6), "spread_to_atr": round(spread / value, 4) if value else None,
        "rsi_14": rsi([c.close for c in candles]), "drift": drift_stats([c.close for c in candles]),
        "spikes": spike_stats(candles), "setup_ma_rsi": ma_rsi_setup(candles, value),
        "session": session_label(last.closed_at),
        "last_closed_at": last.closed_at.isoformat(),
        "candles_ohlcv": [[c.open, c.high, c.low, c.close, c.tick_volume] for c in candles[-40:]],
    }


def _section(text: str, name: str) -> str:
    match = re.search(rf"^## {name}\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return " ".join(match.group(1).split()) if match else ""


def load_skill(skill_id: str, root: Path = SKILLS_ROOT) -> dict:
    text = (root / skill_id / "SKILL.md").read_text(encoding="utf-8")
    body = "\n".join(f"{name}: {_section(text, name)}" for name in SECTIONS if _section(text, name))
    return {"id": skill_id, "note": body[:MAX_NOTE_CHARS]}


def eligible_skills(agent: str, symbol: str, root: Path = SKILLS_ROOT) -> list[dict]:
    """Catalogue entries a given agent may receive for this instrument family."""
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    synthetic = is_synthetic(symbol)
    chosen = []
    for entry in catalog:
        if agent not in entry.get("agents", [entry["owner"]]):
            continue
        if synthetic != (entry.get("scope") == "synthetic"):
            continue  # synthetic indices get synthetic skills only; gold gets the core catalogue
        if entry.get("families") and not has_family_word(symbol, tuple(entry["families"])):
            continue  # a skill about spikes is not offered for a constant-volatility index
        chosen.append(entry)
    return chosen


def skill_pack(agent: str, symbol: str, cycle_id: str, *, size: int = 3, root: Path = SKILLS_ROOT) -> dict:
    """Deterministic subset of ``size`` eligible skills, seeded by the cycle (so a result can be replayed)."""
    pool = sorted(eligible_skills(agent, symbol, root), key=lambda e: e["id"])
    ranked = sorted(pool, key=lambda e: sha256(f"{cycle_id}:{agent}:{e['id']}".encode()).hexdigest())
    picked = sorted(ranked[:size], key=lambda e: e["id"])
    notes = [load_skill(e["id"], root) for e in picked]
    text = "\n\n".join(f"[{item['id']}]\n{item['note']}" for item in notes)
    return {"skills": [f"{e['id']}@{e['version']}" for e in picked], "text": text,
            "sha256": sha256(text.encode("utf-8")).hexdigest() if text else ""}
