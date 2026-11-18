"""Immutable-cycle research orchestration; abstains until evidence is sufficient."""
from dataclasses import replace
from uuid import uuid4
from .agents import graph_agent, news_agent, quant_agent, risk_agent
from .core import Director, Snapshot, utcnow
from .store import ResearchStore


def analyze(store: ResearchStore, *, symbol: str, broker: str, bid: float, ask: float,
            closed_prices: list[float], source_urls: tuple[str, ...] = (), critical_event=False,
            observed_at=None):
    quote = Snapshot(str(uuid4()), symbol, bid, ask, observed_at or utcnow(), broker, critical_event,
                     False, source_urls)
    store.snapshot(quote)
    reports = [graph_agent(closed_prices), news_agent(quote), quant_agent(closed_prices), risk_agent()]
    for report in reports:
        store.analysis(quote.cycle_id, report)
    decision = Director().decide(quote, reports, at=quote.observed_at)
    store.signal(decision)
    return {"snapshot": quote, "agents": reports, "signal": decision}
