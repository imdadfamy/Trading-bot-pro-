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


def basket_performance(store: ResearchStore, symbol: str | None = None) -> dict:
    """Simulated baskets against the single position of the same decision (paired when both were resolved)."""
    query = ("SELECT d.decision_id, d.arm, d.detail, o.r_multiple, o.result, o.bars_held FROM decisions d "
             "JOIN decision_outcomes o USING(decision_id) WHERE d.arm LIKE 'basket:%' AND d.status='resolved'")
    args: tuple = ()
    if symbol:
        query += " AND d.symbol=?"
        args = (symbol,)
    with store.journal.connect() as db:
        twins = [dict(r) for r in db.execute(query, args)]
        origins = {}
        ids = sorted({json.loads(t["detail"]).get("twin_of") for t in twins} - {None})
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for r in db.execute("SELECT decision_id, r_multiple, result FROM decision_outcomes WHERE decision_id IN (%s)"
                                % ",".join("?" * len(chunk)), chunk):
                origins[r["decision_id"]] = dict(r)
        counts = {}
        for r in db.execute("SELECT arm, status, COUNT(*) AS n FROM decisions WHERE arm LIKE 'basket:%' GROUP BY arm, status"):
            counts.setdefault(r["arm"], {})[r["status"]] = r["n"]
    arms = {}
    for twin_arm in sorted({t["arm"] for t in twins} | set(counts)):
        rows = [t for t in twins if t["arm"] == twin_arm]
        details = [json.loads(t["detail"]) for t in rows]
        values = [t["r_multiple"] for t in rows]
        usd = [t["r_multiple"] * d["basket"]["risk_money"] for t, d in zip(rows, details)]
        pairs = [(t["r_multiple"], origins[d["twin_of"]]["r_multiple"]) for t, d in zip(rows, details)
                 if d.get("twin_of") in origins]
        paired = {"n": len(pairs), "mean_r_basket": None, "mean_r_single": None, "difference": None,
                  "difference_interval": None, "underpowered": len(pairs) < MIN_SAMPLE, "clearly_helps": False, "clearly_hurts": False}
        if pairs:
            paired["mean_r_basket"] = round(mean(p[0] for p in pairs), 4)
            paired["mean_r_single"] = round(mean(p[1] for p in pairs), 4)
        if len(pairs) >= 2:
            diffs = [a - b for a, b in pairs]
            half = NormalDist().inv_cdf(0.975) * stdev(diffs) / sqrt(len(diffs))
            paired["difference"] = round(mean(diffs), 4)
            paired["difference_interval"] = [round(mean(diffs) - half, 4), round(mean(diffs) + half, 4)]
            paired["clearly_helps"] = bool(not paired["underpowered"] and paired["difference_interval"][0] > 0)
            paired["clearly_hurts"] = bool(not paired["underpowered"] and paired["difference_interval"][1] < 0)
        last = details[-1]["basket"] if details else {}
        c = counts.get(twin_arm, {})
        arms[twin_arm] = {**summarize(values), "arm": twin_arm[len("basket:"):], "positions": last.get("positions"),
                          "target_usd": last.get("target_usd"), "target_r": last.get("target_r"),
                          "usd_total": round(sum(usd), 2), "usd_mean": round(mean(usd), 2) if usd else None,
                          "ended_on": {k: sum(t["result"] == k for t in rows) for k in ("target", "stop", "timeout")},
                          "still_open": c.get("open", 0), "skipped_open": c.get("skipped_open", 0), "paired": paired}
    return {"arms": arms,
            "reading_guide": ("Simulation sur les vraies bougies : le panier ferme en bloc quand son gain atteint la cible ; le "
                              "risque total du panier est celui d'une position. Le suivi réel se fait toutes les quelques "
                              "secondes, la simulation bougie par bougie : les résultats réels peuvent différer un peu.")}


def exit_performance(store: ResearchStore, symbol: str | None = None) -> dict:
    """Horizon and target compared on the SAME entries: every variant is followed from the same decision."""
    query = ("SELECT d.cycle_id, d.arm, d.detail, o.r_multiple, o.result, o.bars_held FROM decisions d "
             "JOIN decision_outcomes o USING(decision_id) WHERE d.arm LIKE 'exit:%' AND d.status='resolved'")
    args: tuple = ()
    if symbol:
        query += " AND d.symbol=?"
        args = (symbol,)
    with store.journal.connect() as db:
        rows = [dict(r) for r in db.execute(query, args)]
    from .autopilot import get_config
    config = get_config(store)
    baseline = (int(config.get("horizon_bars", 48)), float(config.get("reward_multiple", 2.0)))
    by_base: dict[str, dict[tuple, dict]] = {}
    for row in rows:
        detail = json.loads(row["detail"])
        key = (detail["exit"]["horizon_bars"], detail["exit"]["reward_multiple"])
        entry = by_base.setdefault(detail["twin_arm"], {}).setdefault(key, {"by_cycle": {}, "rows": []})
        entry["by_cycle"][row["cycle_id"]] = row["r_multiple"]
        entry["rows"].append(row)
    out = {}
    for base, variants in by_base.items():
        reference = variants.get(baseline) or variants.get(max(variants, key=lambda k: len(variants[k]["by_cycle"])))
        used = baseline if baseline in variants else None
        z_comparisons = max(len(variants) - 1, 1)
        table = []
        for (horizon, reward), data in sorted(variants.items()):
            values = [r["r_multiple"] for r in data["rows"]]
            ended = {k: sum(r["result"] == k for r in data["rows"]) for k in ("target", "stop", "timeout")}
            paired = {"n": 0, "difference": None, "difference_interval": None, "underpowered": True,
                      "clearly_better": False, "clearly_worse": False}
            if data is not reference:
                diffs = [r - reference["by_cycle"][c] for c, r in data["by_cycle"].items() if c in reference["by_cycle"]]
                paired["n"] = len(diffs)
                if len(diffs) >= 2:
                    half = NormalDist().inv_cdf(1 - 0.025 / z_comparisons) * stdev(diffs) / sqrt(len(diffs))
                    paired.update(difference=round(mean(diffs), 4),
                                  difference_interval=[round(mean(diffs) - half, 4), round(mean(diffs) + half, 4)],
                                  underpowered=len(diffs) < MIN_SAMPLE)
                    paired["clearly_better"] = bool(not paired["underpowered"] and paired["difference_interval"][0] > 0)
                    paired["clearly_worse"] = bool(not paired["underpowered"] and paired["difference_interval"][1] < 0)
            table.append({"horizon_bars": horizon, "reward_multiple": reward, "baseline": data is reference,
                          **summarize(values, z_comparisons), "ended_on": ended,
                          "mean_bars_held": round(mean(r["bars_held"] for r in data["rows"]), 1), "paired_vs_baseline": paired})
        out[base] = {"variants": table, "baseline_is_current_setting": used is not None}
    return {"arms": out, "baseline": {"horizon_bars": baseline[0], "reward_multiple": baseline[1]},
            "reading_guide": ("Chaque décision est suivie sous plusieurs délais et objectifs, depuis la MÊME entrée : l'écart est "
                              "mesuré pair par pair. R est exprimé en distance du stop, donc comparable d'un objectif à l'autre. "
                              "Les intervalles sont élargis pour le nombre de variantes comparées ; il faut au moins 30 paires.")}


def performance(store: ResearchStore, symbol: str | None = None) -> dict:
    resolved, counts = _load(store, symbol)
    # basket and exit-study twins are reported on their own: they must not widen the multiple-comparison corrections
    resolved = [r for r in resolved if not r["arm"].startswith(("basket:", "exit:"))]
    counts = {arm: c for arm, c in counts.items() if not arm.startswith(("basket:", "exit:"))}
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
    skills_effect_forced = {}  # forced with the skills against forced without them: what the skills add
    for agent in ("graph", "quant", "news", "director"):
        with_skills, without = group("forced", agent), group("plainforced", agent)
        if with_skills or without:
            skills_effect_forced[agent] = _difference(with_skills, without, 4)
    forced_vs_random = {}
    for agent in ("graph", "quant", "news", "director"):
        forced = group("forced", agent)
        if forced or random_values:
            forced_vs_random[agent] = _difference(forced, random_values, 4)
    ai = group("ai", "director")
    ai_director_vs = {"vs_vote": _difference(ai, group("skills", "director"), 2),
                      "vs_coin": _difference(ai, random_values, 2)} if ai else {}
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
        "skills_vs_plain": skills_vs_plain, "forced_vs_random": forced_vs_random, "ai_director_vs": ai_director_vs,
        "skill_effects": skill_effects, "basket": basket_performance(store, symbol), "exit_study": exit_performance(store, symbol),
        "skills_effect_forced": skills_effect_forced,
        "direction": direction_performance(store),
        "reading_guide": (
            "R = gain or loss as a multiple of the initial stop distance, after spread. Intervals are widened for the "
            "number of groups compared. 'Significantly positive' needs at least 30 trades and a lower bound above 0. "
            "A shadow trade is a simulation on real bars, not an order. Few trades prove nothing; two weeks is a diagnostic."),
    }


def _direction_rows(store: ResearchStore):
    with store.journal.connect() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT d.arm, d.symbol, d.session, d.detail, s.score, s.horizon_bars FROM decisions d "
            "JOIN direction_scores s USING(decision_id)")]
    for row in rows:
        row["detail"] = json.loads(row["detail"])
    return rows


def direction_performance(store: ResearchStore) -> dict:
    """Quality of the direction at a fixed horizon (signed move in stop distances, after the spread)."""
    rows = _direction_rows(store)
    arms = sorted({r["arm"] for r in rows})

    def values(arm):
        return [r["score"] for r in rows if r["arm"] == arm]

    out = {"observations": len(rows), "arms": {arm: summarize(values(arm), max(len(arms), 1)) for arm in arms},
           "skills_vs_plain": {}, "forced_vs_random": {}, "ai_director_vs": {}}
    if values("ai:director"):
        out["ai_director_vs"] = {"vs_vote": _difference(values("ai:director"), values("skills:director"), 2),
                                 "vs_coin": _difference(values("ai:director"), values("random:coin"), 2)}
    out["skills_effect_forced"], out["plainforced_vs_random"] = {}, {}
    for agent in ("graph", "quant", "news", "director"):
        plain, skilled, forced = values(f"plain:{agent}"), values(f"skills:{agent}"), values(f"forced:{agent}")
        if forced or values(f"plainforced:{agent}"):
            out["skills_effect_forced"][agent] = _difference(forced, values(f"plainforced:{agent}"), 4)
        if values(f"plainforced:{agent}"):
            out["plainforced_vs_random"][agent] = _difference(values(f"plainforced:{agent}"), values("random:coin"), 4)
        if plain or skilled:
            out["skills_vs_plain"][agent] = _difference(skilled, plain, 4)
        if forced or values("random:coin"):
            out["forced_vs_random"][agent] = _difference(forced, values("random:coin"), 4)
    return out


def recent_analyses(store: ResearchStore, limit: int = 40) -> list[dict]:
    """The latest real answers of the AI analysts and director, WAIT included (the ledger of what they said)."""
    with store.journal.connect() as db:
        rows = db.execute(
            "SELECT at, symbol, session, arm, action, detail FROM decisions "
            "WHERE arm IN ('skills:graph','skills:quant','skills:news','ai:director') AND status<>'model_failed' "
            "ORDER BY at DESC, arm LIMIT ?", (min(max(limit, 1), 200),))
        out = []
        for row in rows:
            item = dict(row)
            detail = json.loads(item.pop("detail"))
            item["rationale"] = detail.get("rationale", "")
            item["skills"] = detail.get("skills", [])
            out.append(item)
        return out


def recent_decisions(store: ResearchStore, limit: int = 60) -> list[dict]:
    with store.journal.connect() as db:
        rows = db.execute(
            "SELECT d.decision_id, d.at, d.symbol, d.session, d.arm, d.action, d.status, d.detail, "
            "o.result, o.r_multiple FROM decisions d LEFT JOIN decision_outcomes o USING(decision_id) "
            "WHERE (d.action IN ('BUY','SELL') OR d.status='model_failed') AND d.arm NOT LIKE 'basket:%' AND d.arm NOT LIKE 'exit:%' "
            "ORDER BY d.at DESC, d.arm LIMIT ?",
            (min(max(limit, 1), 300),))
        result = []
        for row in rows:
            item = dict(row)
            detail = json.loads(item.pop("detail"))
            item["rationale"] = detail.get("rationale", "")
            item["skills"] = detail.get("skills", [])
            result.append(item)
        return result
