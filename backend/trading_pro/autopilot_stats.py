"""What the automatic agents learned: results by arm, session, instrument, skill pack and single skill.

Every figure comes from resolved shadow trades (R multiples after spread and the project's stop model).
Small samples are flagged and nothing is called significant without a corrected confidence interval,
because comparing many groups on few trades produces false winners by chance alone.
"""
from __future__ import annotations

import json
from math import sqrt
from statistics import NormalDist, mean, stdev

from .store import ResearchStore

MIN_SAMPLE = 30
ANSWERED = ("wait", "open", "resolved", "skipped_open", "expired", "skipped_no_atr")


def wilson(wins: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = wins / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def summarize(values: list[float], comparisons: int = 1) -> dict:
    """Summary of R multiples. ``comparisons`` widens the interval (Bonferroni) for multi-group reading."""
    n = len(values)
    z = NormalDist().inv_cdf(1 - 0.025 / max(comparisons, 1))
    result = {"trades": n, "small_sample": n < MIN_SAMPLE}
    if n == 0:
        return {**result, "mean_r": None, "total_r": 0.0, "win_rate": None, "profit_factor": None,
                "win_rate_interval": None, "mean_r_interval": None, "significantly_positive": False}
    wins = sum(v > 0 for v in values)
    gains, losses = sum(v for v in values if v > 0), -sum(v for v in values if v < 0)
    interval = None
    if n >= 2:
        half = z * stdev(values) / sqrt(n)
        interval = [round(mean(values) - half, 4), round(mean(values) + half, 4)]
    return {**result, "mean_r": round(mean(values), 4), "total_r": round(sum(values), 4),
            "win_rate": round(wins / n, 4), "win_rate_interval": wilson(wins, n, z),
            "profit_factor": round(gains / losses, 3) if losses else None, "mean_r_interval": interval,
            "significantly_positive": bool(interval and n >= MIN_SAMPLE and interval[0] > 0)}


def _difference(with_values: list[float], without_values: list[float], comparisons: int) -> dict:
    out = {"n_with": len(with_values), "n_without": len(without_values),
           "mean_r_with": round(mean(with_values), 4) if with_values else None,
           "mean_r_without": round(mean(without_values), 4) if without_values else None,
           "difference": None, "difference_interval": None}
    underpowered = min(len(with_values), len(without_values)) < MIN_SAMPLE
    out["underpowered"] = underpowered
    if len(with_values) >= 2 and len(without_values) >= 2:
        z = NormalDist().inv_cdf(1 - 0.025 / max(comparisons, 1))
        diff = mean(with_values) - mean(without_values)
        half = z * sqrt(stdev(with_values) ** 2 / len(with_values) + stdev(without_values) ** 2 / len(without_values))
        out["difference"] = round(diff, 4)
        out["difference_interval"] = [round(diff - half, 4), round(diff + half, 4)]
    out["clearly_helps"] = bool(out["difference_interval"] and not underpowered and out["difference_interval"][0] > 0)
    out["clearly_hurts"] = bool(out["difference_interval"] and not underpowered and out["difference_interval"][1] < 0)
    return out


def _load(store: ResearchStore, symbol: str | None):
    query = ("SELECT d.arm, d.symbol, d.session, d.action, d.detail, o.r_multiple, o.result, o.bars_held "
             "FROM decisions d JOIN decision_outcomes o USING(decision_id) WHERE d.status='resolved'")
    args: tuple = ()
    if symbol:
        query += " AND d.symbol=?"
        args = (symbol,)
    with store.journal.connect() as db:
        resolved = [dict(r) for r in db.execute(query, args)]
        counts = {}
        for row in db.execute("SELECT arm, status, COUNT(*) AS n FROM decisions"
                              + (" WHERE symbol=?" if symbol else "") + " GROUP BY arm, status", args):
            counts.setdefault(row["arm"], {})[row["status"]] = row["n"]
    for row in resolved:
        row["detail"] = json.loads(row["detail"])
    return resolved, counts


def performance(store: ResearchStore, symbol: str | None = None) -> dict:
    resolved, counts = _load(store, symbol)
    arms = sorted(set(counts) | {r["arm"] for r in resolved})
    sessions = sorted({r["session"] for r in resolved})
    symbols = sorted({r["symbol"] for r in resolved})
    cells = len(arms) * max(len(sessions), 1)

    by_arm = {}
    for arm in arms:
        c = counts.get(arm, {})
        answered = sum(c.get(s, 0) for s in ANSWERED)
        values = [r["r_multiple"] for r in resolved if r["arm"] == arm]
        by_arm[arm] = {**summarize(values, len(arms)),
                       "answers": answered, "waits": c.get("wait", 0), "model_failures": c.get("model_failed", 0),
                       "abstention_rate": round(c.get("wait", 0) / answered, 4) if answered else None,
                       "still_open": c.get("open", 0), "expired": c.get("expired", 0)}
    by_arm_session = [
        {"arm": arm, "session": session,
         **summarize([r["r_multiple"] for r in resolved if r["arm"] == arm and r["session"] == session], cells)}
        for arm in arms for session in sessions
        if any(r["arm"] == arm and r["session"] == session for r in resolved)]
    by_arm_symbol = [
        {"arm": arm, "symbol": sym,
         **summarize([r["r_multiple"] for r in resolved if r["arm"] == arm and r["symbol"] == sym], len(arms) * len(symbols))}
        for arm in arms for sym in symbols if any(r["arm"] == arm and r["symbol"] == sym for r in resolved)]

    def group(prefix, agent):
        return [r["r_multiple"] for r in resolved if r["arm"] == f"{prefix}:{agent}"]

    skills_vs_plain = {}
    for agent in ("graph", "quant", "news", "director"):
        plain, skilled = group("plain", agent), group("skills", agent)
        if plain or skilled:
            skills_vs_plain[agent] = _difference(skilled, plain, 4)
    random_values = group("random", "coin")
    forced_vs_random = {}
    for agent in ("graph", "quant", "news", "director"):
        forced = group("forced", agent)
        if forced or random_values:
            forced_vs_random[agent] = _difference(forced, random_values, 4)
    skill_ids = sorted({s.split("@")[0] for r in resolved if r["arm"].startswith("skills:")
                        and r["arm"] != "skills:director" for s in r["detail"].get("skills", [])})
    skill_effects = []
    for skill in skill_ids:
        with_values, without_values = [], []
        for arm in {r["arm"] for r in resolved if r["arm"].startswith("skills:") and r["arm"] != "skills:director"}:
            rows = [r for r in resolved if r["arm"] == arm]
            has = [skill in {s.split("@")[0] for s in r["detail"].get("skills", [])} for r in rows]
            if not any(has):
                continue
            with_values += [r["r_multiple"] for r, h in zip(rows, has) if h]
            without_values += [r["r_multiple"] for r, h in zip(rows, has) if not h]
        skill_effects.append({"skill": skill, **_difference(with_values, without_values, len(skill_ids))})
    skill_effects.sort(key=lambda e: (e["difference"] is None, -(e["difference"] or 0)))
    return {
        "scope": symbol or "all", "resolved_trades": len(resolved), "arms": by_arm,
        "by_arm_session": by_arm_session, "by_arm_symbol": by_arm_symbol,
        "skills_vs_plain": skills_vs_plain, "forced_vs_random": forced_vs_random, "skill_effects": skill_effects,
        "reading_guide": (
            "R = gain or loss as a multiple of the initial stop distance, after spread. Intervals are widened for the "
            "number of groups compared. 'Significantly positive' needs at least 30 trades and a lower bound above 0. "
            "A shadow trade is a simulation on real bars, not an order. Few trades prove nothing; two weeks is a diagnostic."),
    }


def recent_decisions(store: ResearchStore, limit: int = 60) -> list[dict]:
    with store.journal.connect() as db:
        rows = db.execute(
            "SELECT d.decision_id, d.at, d.symbol, d.session, d.arm, d.action, d.status, d.detail, "
            "o.result, o.r_multiple FROM decisions d LEFT JOIN decision_outcomes o USING(decision_id) "
            "WHERE d.action IN ('BUY','SELL') OR d.status='model_failed' ORDER BY d.at DESC, d.arm LIMIT ?",
            (min(max(limit, 1), 300),))
        result = []
        for row in rows:
            item = dict(row)
            detail = json.loads(item.pop("detail"))
            item["rationale"] = detail.get("rationale", "")
            item["skills"] = detail.get("skills", [])
            result.append(item)
        return result
