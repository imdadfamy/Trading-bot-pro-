"""Provider boundary with budget enforcement and strict, non-executable output."""
from __future__ import annotations
import json
from dataclasses import dataclass
from math import isfinite
from typing import Protocol
from .core import Action, Report
from .store import ResearchStore


class Provider(Protocol):
    def classify(self, agent: str, snapshot: dict, model: str) -> tuple[dict, dict]:
        """Return structured output and usage metadata; no broker methods."""


class UnconfiguredProvider:
    def classify(self, agent: str, snapshot: dict, model: str):
        raise RuntimeError("Provider API not configured")


@dataclass(frozen=True)
class Budget:
    daily_usd: float
    experiment_usd: float
    max_call_usd: float = 1.0


def _report(agent: str, content: dict) -> Report:
    if set(content) != {"action", "rationale", "evidence", "score"}:
        raise ValueError("Invalid provider output schema")
    action = Action(content["action"])
    rationale = content["rationale"]
    evidence = content["evidence"]
    score = content["score"]
    if (not isinstance(rationale, str) or not 1 <= len(rationale) <= 2000
            or not isinstance(evidence, list) or len(evidence) > 20
            or any(not isinstance(s, str) or len(s) > 500 for s in evidence)
            or (score is not None and (not isinstance(score, (int, float)) or not isfinite(score)))):
        raise ValueError("Invalid provider output fields")
    return Report(agent, action, rationale, tuple(evidence), score)


def run_model(store: ResearchStore, provider: Provider, *, agent: str, model: str,
              snapshot: dict, budget: Budget, projected_cost_usd: float) -> Report:
    if not 0 < projected_cost_usd <= budget.max_call_usd:
        return Report(agent, Action.WAIT, "Call cost above configured cap")
    costs = store.costs()
    if costs["today_usd"] + projected_cost_usd > budget.daily_usd or costs["total_usd"] + projected_cost_usd > budget.experiment_usd:
        store.journal.log("budget.exceeded", snapshot.get("cycle_id", "unknown"), {"agent": agent})
        return Report(agent, Action.WAIT, "Model budget exhausted")
    try:
        output, usage = provider.classify(agent, snapshot, model)
        report = _report(agent, output)
        cost = usage["cost_usd"]
        tokens_in, tokens_out = usage["input_tokens"], usage["output_tokens"]
        if (not isfinite(cost) or cost < 0
                or not isinstance(tokens_in, int) or not isinstance(tokens_out, int)
                or tokens_in < 0 or tokens_out < 0):
            raise ValueError("Invalid provider usage")
        store.record_usage(agent=agent, provider=type(provider).__name__, model=model,
                           input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=cost)
        if (cost > budget.max_call_usd or costs["today_usd"] + cost > budget.daily_usd
                or costs["total_usd"] + cost > budget.experiment_usd):
            store.journal.log("budget.exceeded", snapshot.get("cycle_id", "unknown"), {"agent": agent})
            return Report(agent, Action.WAIT, "Actual model cost exceeded budget")
        return report
    except Exception as exc:
        store.journal.log("model.invalid", snapshot.get("cycle_id", "unknown"),
                          {"agent": agent, "error_type": type(exc).__name__})
        return Report(agent, Action.WAIT, "Provider unavailable or invalid structured output")
