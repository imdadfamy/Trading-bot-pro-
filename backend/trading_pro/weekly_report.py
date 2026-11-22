"""The report of a collection period: what the agents learned, instrument by instrument, with verdicts fixed in advance.

Everything comes from the journal (shadow trades, fixed-horizon direction scores, costs, orders). The three decision rules are
written here BEFORE the data are read, so the conclusion is not chosen after the fact:

1. An instrument is kept only if some method beats the coin on it, pair by pair (same consultation), with a confidence interval
   above zero after correction for the number of cells compared, on at least 30 pairs.
2. The skills are useful only if "forced with skills" beats "forced without skills" with an interval above zero.
3. The exit rule (horizon and target) is changed only if a variant beats the current setting pair by pair, clearly.

"Not enough data" is an answer; so is "no advantage shown".
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import sqrt
from statistics import NormalDist, mean, stdev

from .autopilot_stats import MIN_SAMPLE, basket_performance, exit_performance, summarize
from .store import ResearchStore

COIN = "random:coin"
METHODS = ("det:graph", "rule:sma_cross", "forced:graph", "forced:quant", "forced:director",
           "plainforced:graph", "plainforced:quant", "plainforced:director", "skills:director", "ai:director")
ALL_ARMS = (COIN, *METHODS)
AGENTS = ("graph", "quant", "director")


def paired(a: dict, b: dict, comparisons: int = 1) -> dict:
    """Difference a - b over the consultations where both have a value (same cycle)."""
    keys = sorted(set(a) & set(b))
    diffs = [a[k] - b[k] for k in keys]
    out = {"n": len(diffs), "mean_a": round(mean(a[k] for k in keys), 4) if keys else None,
           "mean_b": round(mean(b[k] for k in keys), 4) if keys else None, "difference": None, "interval": None,
           "underpowered": len(diffs) < MIN_SAMPLE, "clearly_better": False, "clearly_worse": False}
    if len(diffs) >= 2:
        z = NormalDist().inv_cdf(1 - 0.025 / max(comparisons, 1))
        half = z * stdev(diffs) / sqrt(len(diffs))
        out.update(difference=round(mean(diffs), 4), interval=[round(mean(diffs) - half, 4), round(mean(diffs) + half, 4)])
        out["clearly_better"] = bool(not out["underpowered"] and out["interval"][0] > 0)
        out["clearly_worse"] = bool(not out["underpowered"] and out["interval"][1] < 0)
    return out


def _window(days: int, now: datetime | None) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=days)).isoformat(), now.isoformat()


def _health(store: ResearchStore, since: str, until: str) -> dict:
    with store.journal.connect() as db:
        cycles = [(r["at"], r["payload"]) for r in db.execute(
            "SELECT at, payload FROM audit WHERE kind='autopilot.cycle' AND at>=? AND at<?", (since, until))]
        errors = {}
        for r in db.execute("SELECT payload FROM audit WHERE kind IN ('autopilot.error','autopilot.data_error') AND at>=? AND at<?",
                            (since, until)):
            message = json.loads(r["payload"]).get("message", "")[:80]
            errors[message] = errors.get(message, 0) + 1
        incidents = {r["kind"]: r["n"] for r in db.execute(
            "SELECT kind, COUNT(*) AS n FROM audit WHERE at>=? AND at<? AND kind IN ("
            "'autopilot.basket_cancelled','autopilot.basket_partial','autopilot.order_uncertain','autopilot.position_unprotected',"
            "'autopilot.order_refused','autopilot.basket_opened','autopilot.basket_target') GROUP BY kind", (since, until))}
        failed = db.execute("SELECT COUNT(*) FROM decisions WHERE status='model_failed' AND at>=? AND at<?", (since, until)).fetchone()[0]
        scored = db.execute("SELECT COUNT(*) FROM decisions WHERE arm='forced:director' AND at>=? AND at<?", (since, until)).fetchone()[0]
        alerts = {r["kind"]: r["n"] for r in db.execute("SELECT kind, COUNT(*) AS n FROM alerts WHERE at>=? AND at<? GROUP BY kind", (since, until))}
    times = sorted(datetime.fromisoformat(t) for t, _ in cycles)
    gaps = [(a, b) for a, b in zip(times, times[1:]) if (b - a) > timedelta(minutes=20)]
    per_symbol: dict[str, int] = defaultdict(int)
    for _, payload in cycles:
        per_symbol[json.loads(payload).get("symbol", "?")] += 1
    return {"cycles": len(cycles), "cycles_by_symbol": dict(per_symbol), "errors": dict(sorted(errors.items(), key=lambda kv: -kv[1])[:5]),
            "incidents": incidents, "model_failed": failed, "consultations": scored, "alerts": alerts,
            "interruptions": [{"from": a.isoformat(), "to": b.isoformat(), "minutes": round((b - a).total_seconds() / 60)} for a, b in gaps[:8]],
            "interruption_minutes": round(sum((b - a).total_seconds() for a, b in gaps) / 60)}


def _costs(store: ResearchStore, since: str, until: str, days: int) -> dict:
    with store.journal.connect() as db:
        total, calls = db.execute("SELECT COALESCE(SUM(cost_usd),0), COUNT(*) FROM model_usage WHERE at>=? AND at<?", (since, until)).fetchone()
        by_agent = {r["agent"]: {"calls": r["n"], "usd": round(r["s"], 3)} for r in db.execute(
            "SELECT agent, COUNT(*) AS n, SUM(cost_usd) AS s FROM model_usage WHERE at>=? AND at<? GROUP BY agent", (since, until))}
        by_day = {r["d"]: round(r["s"], 3) for r in db.execute(
            "SELECT substr(at,1,10) AS d, SUM(cost_usd) AS s FROM model_usage WHERE at>=? AND at<? GROUP BY d ORDER BY d", (since, until))}
    return {"total_usd": round(total, 3), "calls": calls, "per_day_usd": round(total / max(days, 1), 3), "by_agent": by_agent, "by_day": by_day}


def _results(store: ResearchStore, since: str, until: str) -> dict:
    """Shadow trades (R) and fixed-horizon direction scores, by symbol, arm and consultation."""
    marks = ",".join("?" * len(ALL_ARMS))
    with store.journal.connect() as db:
        shadow = db.execute(f"SELECT d.cycle_id, d.symbol, d.arm, o.r_multiple FROM decisions d JOIN decision_outcomes o USING(decision_id) "
                            f"WHERE d.status='resolved' AND d.at>=? AND d.at<? AND d.arm IN ({marks})", (since, until, *ALL_ARMS)).fetchall()
        direction = db.execute(f"SELECT d.cycle_id, d.symbol, d.arm, s.score FROM direction_scores s JOIN decisions d USING(decision_id) "
                               f"WHERE d.at>=? AND d.at<? AND d.arm IN ({marks})", (since, until, *ALL_ARMS)).fetchall()
    R: dict = defaultdict(lambda: defaultdict(dict))
    D: dict = defaultdict(lambda: defaultdict(dict))
    for row in shadow:
        R[row["symbol"]][row["arm"]][row["cycle_id"]] = row["r_multiple"]
    for row in direction:
        D[row["symbol"]][row["arm"]][row["cycle_id"]] = row["score"]
    return {"R": R, "D": D}


def _instruments(data: dict) -> tuple[dict, list]:
    symbols = sorted(set(data["R"]) | set(data["D"]))
    cells = max(sum(1 for s in symbols for arm in METHODS if data["R"][s].get(arm) or data["D"][s].get(arm)), 1)
    out = {}
    for symbol in symbols:
        rows = {}
        for arm in METHODS:
            r, d = data["R"][symbol].get(arm, {}), data["D"][symbol].get(arm, {})
            if not r and not d:
                continue
            rows[arm] = {"shadow": summarize(list(r.values()), cells), "direction": summarize(list(d.values()), cells),
                         "vs_coin_shadow": paired(r, data["R"][symbol].get(COIN, {}), cells),
                         "vs_coin_direction": paired(d, data["D"][symbol].get(COIN, {}), cells)}
        coin_r, coin_d = data["R"][symbol].get(COIN, {}), data["D"][symbol].get(COIN, {})
        out[symbol] = {"coin_shadow": summarize(list(coin_r.values())), "coin_direction": summarize(list(coin_d.values())), "methods": rows}
    return out, symbols


def _skills(data: dict) -> dict:
    out = {}
    for agent in AGENTS:
        with_name, without_name = f"forced:{agent}", f"plainforced:{agent}"
        pooled_r_a, pooled_r_b, pooled_d_a, pooled_d_b = {}, {}, {}, {}
        by_symbol = {}
        for symbol in sorted(set(data["R"]) | set(data["D"])):
            a_r, b_r = data["R"][symbol].get(with_name, {}), data["R"][symbol].get(without_name, {})
            a_d, b_d = data["D"][symbol].get(with_name, {}), data["D"][symbol].get(without_name, {})
            if not (a_r or b_r or a_d or b_d):
                continue
            by_symbol[symbol] = {"shadow": paired(a_r, b_r, 7), "direction": paired(a_d, b_d, 7)}
            pooled_r_a.update({(symbol, k): v for k, v in a_r.items()}); pooled_r_b.update({(symbol, k): v for k, v in b_r.items()})
            pooled_d_a.update({(symbol, k): v for k, v in a_d.items()}); pooled_d_b.update({(symbol, k): v for k, v in b_d.items()})
        if by_symbol:
            out[agent] = {"overall_shadow": paired(pooled_r_a, pooled_r_b, 3), "overall_direction": paired(pooled_d_a, pooled_d_b, 3),
                          "by_symbol": by_symbol}
    return out


def _real(store: ResearchStore, since: str, until: str) -> dict:
    with store.journal.connect() as db:
        singles = [dict(r) for r in db.execute(
            "SELECT symbol, COUNT(*) AS n, ROUND(SUM(profit),2) AS net, ROUND(AVG(profit>0),3) AS win FROM auto_orders "
            "WHERE state='closed' AND basket_id IS NULL AND opened_at>=? AND opened_at<? GROUP BY symbol", (since, until))]
        reasons = {r["close_reason"]: {"n": r["n"], "net": r["net"]} for r in db.execute(
            "SELECT close_reason, COUNT(*) AS n, ROUND(SUM(profit),2) AS net FROM auto_orders "
            "WHERE state='closed' AND basket_id IS NULL AND opened_at>=? AND opened_at<? GROUP BY close_reason", (since, until))}
        baskets = [dict(r) for r in db.execute(
            "SELECT substr(basket_id,1,8) AS id, symbol, COUNT(*) AS members, MIN(opened_at) AS opened, MAX(closed_at) AS closed, "
            "ROUND(SUM(profit),2) AS profit, GROUP_CONCAT(DISTINCT close_reason) AS reason FROM auto_orders "
            "WHERE basket_id IS NOT NULL AND state='closed' AND opened_at>=? AND opened_at<? GROUP BY basket_id ORDER BY opened", (since, until))]
    basket_total = round(sum(b["profit"] or 0 for b in baskets), 2)
    return {"single_orders": singles, "single_net": round(sum(s["net"] or 0 for s in singles), 2),
            "single_close_reasons": reasons, "baskets": baskets, "baskets_net": basket_total,
            "baskets_lost": sum(1 for b in baskets if (b["profit"] or 0) < -20)}


def _verdicts(instruments: dict, skills: dict, exits: dict) -> dict:
    keep, summary = {}, []
    for symbol, info in instruments.items():
        best, enough = None, False
        for arm, m in info["methods"].items():
            for key in ("vs_coin_shadow", "vs_coin_direction"):
                p = m[key]
                enough = enough or not p["underpowered"]
                if p["clearly_better"] and (best is None or p["difference"] > best[2]):
                    best = (arm, key, p["difference"])
        if best:
            keep[symbol] = {"verdict": "retenu", "method": best[0], "measure": "positions simulées" if best[1] == "vs_coin_shadow" else "direction à horizon fixe",
                            "difference": best[2]}
        elif enough:
            keep[symbol] = {"verdict": "aucun avantage démontré"}
        else:
            keep[symbol] = {"verdict": "trop peu de données"}
    kept = [s for s, v in keep.items() if v["verdict"] == "retenu"]
    summary.append(f"Règle 1 (instruments) : " + (f"retenus : {', '.join(kept)}." if kept else
                   "aucun instrument ne ressort (aucune méthode ne bat clairement la pièce de monnaie avec la correction des comparaisons)."))
    skills_verdict = {}
    for agent, data in skills.items():
        flags = []
        for key in ("overall_shadow", "overall_direction"):
            p = data[key]
            flags.append("aident" if p["clearly_better"] else "nuisent" if p["clearly_worse"] else "trop peu de données" if p["underpowered"] else "indistinguable")
        skills_verdict[agent] = flags
    helpful = [a for a, f in skills_verdict.items() if "aident" in f]
    harmful = [a for a, f in skills_verdict.items() if "nuisent" in f]
    summary.append("Règle 2 (compétences) : " + ("elles aident pour " + ", ".join(helpful) + ". " if helpful else "") +
                   ("elles nuisent pour " + ", ".join(harmful) + ". " if harmful else "") +
                   ("" if helpful or harmful else "aucun effet démontré (voir le détail : souvent trop peu de données)."))
    exit_choice = {}
    for base, data in (exits.get("arms") or {}).items():
        better = [v for v in data["variants"] if not v["baseline"] and v["paired_vs_baseline"]["clearly_better"]]
        if better:
            top = max(better, key=lambda v: v["paired_vs_baseline"]["difference"])
            exit_choice[base] = {"verdict": "changer", "horizon_bars": top["horizon_bars"], "reward_multiple": top["reward_multiple"],
                                 "difference": top["paired_vs_baseline"]["difference"]}
        else:
            exit_choice[base] = {"verdict": "garder le réglage actuel"}
    summary.append("Règle 3 (délai et objectif) : " + ("; ".join(
        f"{b} : " + (f"passer à {v['horizon_bars']} bougies et {v['reward_multiple']} fois le stop (écart {v['difference']:+.2f} R)" if v["verdict"] == "changer"
                     else "garder le réglage actuel") for b, v in exit_choice.items()) if exit_choice else "pas de données."))
    return {"instruments": keep, "skills": skills_verdict, "exit": exit_choice, "summary": summary}


def build_report(store: ResearchStore, *, days: int = 7, now: datetime | None = None) -> dict:
    days = max(1, min(int(days), 60))
    since, until = _window(days, now)
    data = _results(store, since, until)
    instruments, symbols = _instruments(data)
    skills = _skills(data)
    exits = exit_performance(store, since=since, until=until)
    exits_by_symbol = {s: exit_performance(store, symbol=s, since=since, until=until) for s in symbols}
    report = {"period": {"since": since, "until": until, "days": days},
              "health": _health(store, since, until), "costs": _costs(store, since, until, days),
              "instruments": instruments, "skills": skills, "exit_study": exits,
              "exit_study_by_symbol": {s: v for s, v in exits_by_symbol.items() if v["arms"]},
              "baskets_simulated": basket_performance(store, since=since, until=until), "real": _real(store, since, until)}
    report["verdicts"] = _verdicts(instruments, skills, exits)
    report["reading_guide"] = ("R = gain ou perte en multiple du stop initial, après écart d'achat-vente. Chaque comparaison est faite "
                               "pair par pair (même consultation). Les intervalles sont élargis pour le nombre de cases comparées ; "
                               "il faut au moins 30 paires. Une position simulée n'est pas un ordre. Peu de données ne prouvent rien.")
    report["markdown"] = render_markdown(report)
    return report


# ------------------------------------------------------------------ text rendering
def _n(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}".replace(".", ",")


def _ci(p):
    return "" if not p.get("interval") else f" [{_n(p['interval'][0])} ; {_n(p['interval'][1])}]"


def render_markdown(report: dict) -> str:
    p, h, c, v = report["period"], report["health"], report["costs"], report["verdicts"]
    lines = [f"# Rapport de collecte : {p['days']} jours", "",
             f"Période : du {p['since'][:16].replace('T', ' ')} au {p['until'][:16].replace('T', ' ')} UTC.", "", "## Conclusions (règles fixées à l'avance)", ""]
    lines += [f"- {s}" for s in v["summary"]]
    lines += ["", "## Verdict par instrument", "", "| Instrument | Verdict | Détail |", "|---|---|---|"]
    for symbol, item in v["instruments"].items():
        detail = f"{item['method']} (écart {_n(item['difference'])} sur les {item['measure']})" if item["verdict"] == "retenu" else ""
        lines.append(f"| {symbol} | {item['verdict']} | {detail} |")
    lines += ["", "## Résultats par instrument et par méthode",
              "", "Positions simulées (R moyen, réussite) et direction à horizon fixe ; « contre la pièce » = écart apparié avec le hasard.", ""]
    for symbol, info in report["instruments"].items():
        coin = info["coin_shadow"]
        lines += [f"### {symbol}", "", f"Pièce de monnaie : {coin['trades']} positions, R moyen {_n(coin['mean_r'])}.", "",
                  "| Méthode | Positions | R moyen | Réussite | Contre la pièce (R) | Direction juste | Contre la pièce (direction) |", "|---|---|---|---|---|---|---|"]
        for arm, m in info["methods"].items():
            s, d = m["shadow"], m["direction"]
            vs, vd = m["vs_coin_shadow"], m["vs_coin_direction"]
            lines.append(f"| {arm} | {s['trades']} | {_n(s['mean_r'])} | {_n((s['win_rate'] or 0) * 100, 0) if s['win_rate'] is not None else '—'} % | "
                         f"{_n(vs['difference'])}{_ci(vs)} (n={vs['n']}) | {_n((d['win_rate'] or 0) * 100, 0) if d['win_rate'] is not None else '—'} % | "
                         f"{_n(vd['difference'])}{_ci(vd)} (n={vd['n']}) |")
        lines.append("")
    lines += ["## Les compétences aident-elles ? (forcé avec contre forcé sans)", ""]
    if not report["skills"]:
        lines += ["Pas de données."]
    for agent, data in report["skills"].items():
        for label, key in (("positions simulées", "overall_shadow"), ("direction à horizon fixe", "overall_direction")):
            d = data[key]
            lines.append(f"- {agent}, {label} : avec {_n(d['mean_a'])} contre sans {_n(d['mean_b'])} ({d['n']} paires), écart {_n(d['difference'])}{_ci(d)}")
    lines += ["", "## Étude des sorties : délai et objectif", ""]
    base = report["exit_study"]["baseline"]
    lines.append(f"Référence : {base['horizon_bars']} bougies, objectif {_n(base['reward_multiple'], 1)} fois le stop.")
    for arm, data in report["exit_study"]["arms"].items():
        lines += ["", f"**{arm}**", "", "| Délai | Objectif | Suivis | R moyen | Réussite | Fin objectif/stop/délai | Contre la référence |", "|---|---|---|---|---|---|---|"]
        for var in data["variants"]:
            pp = var["paired_vs_baseline"]
            lines.append(f"| {var['horizon_bars']} | {_n(var['reward_multiple'], 1)} | {var['trades']} | {_n(var['mean_r'])} | "
                         f"{_n((var['win_rate'] or 0) * 100, 0) if var['win_rate'] is not None else '—'} % | "
                         f"{var['ended_on']['target']}/{var['ended_on']['stop']}/{var['ended_on']['timeout']} | "
                         f"{'référence' if var['baseline'] else f'{_n(pp['difference'])}{_ci(pp)} (n={pp['n']})'} |")
    r = report["real"]
    lines += ["", "## Ordres réels sur le compte démo", "",
              f"- Ordres simples fermés : {sum(s['n'] for s in r['single_orders'])}, résultat net {_n(r['single_net'])} $.",
              f"- Paniers fermés : {len(r['baskets'])}, résultat net {_n(r['baskets_net'])} $, dont {r['baskets_lost']} perdants.",
              f"- Fermetures des ordres simples : " + (", ".join(f"{k} {x['n']} ({_n(x['net'])} $)" for k, x in r["single_close_reasons"].items()) or "aucune")]
    bs = report["baskets_simulated"]["arms"]
    for arm, b in bs.items():
        lines.append(f"- Panier simulé {b['arm']} : {b['trades']} paniers, {_n(b['usd_mean'])} $ par panier (objectif {b['ended_on']['target']}, "
                     f"stop {b['ended_on']['stop']}, délai {b['ended_on']['timeout']}).")
    lines += ["", "## Santé du pilote", "",
              f"- Cycles d'analyse : {h['cycles']}, consultations du directeur : {h['consultations']}, appels IA en échec : {h['model_failed']}.",
              f"- Interruptions de plus de 20 minutes : {len(h['interruptions'])} (total environ {h['interruption_minutes']} minutes).",
              f"- Erreurs : " + ("; ".join(f"{m} (x{n})" for m, n in h["errors"].items()) or "aucune"),
              f"- Incidents d'exécution : " + (", ".join(f"{k.split('.')[-1]} x{n}" for k, n in h["incidents"].items()) or "aucun"),
              "", "## Coût de l'IA", "",
              f"- Total {_n(c['total_usd'], 2)} $ sur la période, {_n(c['per_day_usd'], 2)} $ par jour, {c['calls']} appels.",
              "", "## Comment lire ce rapport", "", report["reading_guide"], ""]
    return "\n".join(lines)
