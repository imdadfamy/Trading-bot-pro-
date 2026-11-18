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
SECTIONS = ("Objective", "Method", "Limits", "Abstention")
MAX_NOTE_CHARS = 1800  # per skill
SYNTHETIC_HINTS = ("volatility", "boom", "crash", "step", "jump", "range break", "dex", "drift")


def is_synthetic(symbol: str) -> bool:
    lowered = symbol.lower()
    return any(hint in lowered for hint in SYNTHETIC_HINTS)


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
        "spread": round(spread, 6), "session": session_label(last.closed_at),
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
        if entry["owner"] != agent:
            continue
        if entry.get("scope") == "synthetic" and not synthetic:
            continue
        if synthetic and entry.get("scope") != "synthetic" and agent == "news":
            continue
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
