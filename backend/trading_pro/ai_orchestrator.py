"""Model-assisted research cycle.

The deterministic baseline always runs. Optional model agents (graph, news, quant) receive only the
fields their role needs, answer in strict JSON through ``run_model`` (budget caps, schema checks, WAIT
on any failure), and are compared with the baseline. Disagreements and failures go to the research
memory for a human to read; nothing here changes parameters, strategy or any order path. The risk
agent and the director stay deterministic.
"""
from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

from .agents import graph_agent, news_agent, quant_agent, risk_agent
from .core import Director, Report, Snapshot, utcnow
from .models import Budget, Provider, run_model
from .prompts import MODEL_AGENTS, build_inputs, prompt_tag
from .store import ResearchStore

FALLBACKS = {
    "Call cost above configured cap": "cost_cap",
    "Model budget exhausted": "budget_exhausted",
    "Actual model cost exceeded budget": "budget_exceeded",
    "Provider unavailable or invalid structured output": "unavailable",
}


def analyze_with_models(store: ResearchStore, provider: Provider, *, symbol: str, broker: str, bid: float,
                        ask: float, closed_prices: list[float], headlines: list[dict] | None,
                        models: dict[str, str], budget: Budget, agents=MODEL_AGENTS,
                        source_urls: tuple[str, ...] = (), critical_event: bool = False, observed_at=None):
    agents = tuple(agents)
    if not agents or set(agents) - set(MODEL_AGENTS):
        raise ValueError("Model agents must be chosen among graph, news and quant")
    missing = [agent for agent in agents if not isinstance(models.get(agent), str) or not models[agent].strip()]
    if missing:
        raise ValueError(f"Model not configured for: {', '.join(missing)}")
    estimate = getattr(provider, "estimate_cost", None)
    if estimate is None:
        raise ValueError("Provider must project the cost of each call before it is made")

    cycle_id = str(uuid4())
    quote = Snapshot(cycle_id, symbol, bid, ask, observed_at or utcnow(), broker, critical_event, False, source_urls)
    store.snapshot(quote)
    baseline = {"graph": graph_agent(closed_prices), "news": news_agent(quote),
                "quant": quant_agent(closed_prices), "risk": risk_agent()}
    final = dict(baseline)
    comparisons = []
    for agent in agents:
        inputs = build_inputs(agent, cycle_id=cycle_id, symbol=symbol, observed_at=quote.observed_at,
                              closed_prices=closed_prices, headlines=headlines)
        report = run_model(store, provider, agent=agent, model=models[agent], snapshot=inputs,
                           budget=budget, projected_cost_usd=estimate(agent, inputs))
        report = replace(report, evidence=report.evidence + (prompt_tag(agent),))
        final[agent] = report
        failure = FALLBACKS.get(report.rationale)
        agree = baseline[agent].action == report.action
        comparisons.append({"agent": agent, "baseline": baseline[agent].action.value,
                            "model": report.action.value, "agree": agree,
                            "model_status": failure or "answered", "prompt": prompt_tag(agent)})
        store.journal.log("model.compared", cycle_id, comparisons[-1])
        if failure:
            store.remember(cause=f"{agent}: model unavailable ({failure})",
                           evidence=json.dumps({"rationale": report.rationale, "prompt": prompt_tag(agent)}),
                           recommendation="Check budget, prices, key and provider status; the cycle fell back to WAIT.",
                           cycle_id=cycle_id)
        elif not agree:
            store.remember(cause=f"{agent}: model {report.action.value} differs from baseline "
                                 f"{baseline[agent].action.value}",
                           evidence=json.dumps({"baseline": baseline[agent].rationale[:300],
                                                "model": report.rationale[:500], "prompt": prompt_tag(agent)}),
                           recommendation="Read both rationales; no automatic change of strategy or parameters.",
                           cycle_id=cycle_id)
        store.analysis(cycle_id, replace(baseline[agent], agent=f"{agent}:baseline"))
    for name, report in final.items():
        store.analysis(cycle_id, report)
    decision = Director().decide(quote, [final["graph"], final["news"], final["quant"], final["risk"]],
                                 at=quote.observed_at)
    store.signal(decision)
    return {"snapshot": quote, "agents": list(final.values()), "signal": decision,
            "comparisons": comparisons, "costs": store.costs()}
