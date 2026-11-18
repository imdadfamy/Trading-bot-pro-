"""Offline research commands; all inputs explicitly user-supplied or local fixtures."""
import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from .backtest import BacktestConfig, load_candles, run_baseline, chronological_evaluation
from .orchestrator import analyze
from .store import ResearchStore
from .news import normalize_event
from .quality import assess
from .backup import backup_database, verify_backup
from datetime import datetime


def main():
    from .local_env import load_local_env
    load_local_env()
    parser = argparse.ArgumentParser(description="TRADING INTELLIGENCE PRO offline research")
    parser.add_argument("--database", default="data/trading.db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    ingest = sub.add_parser("import-candles")
    ingest.add_argument("csv")
    incoming = sub.add_parser("import-news")
    incoming.add_argument("json_file", help="List of event objects, each with source and UTC timestamps")
    provider_news = sub.add_parser("poll-newsapi", help="One explicit fetch; no trading or background worker")
    provider_news.add_argument("--query", default='"gold price" OR "spot gold" OR XAUUSD OR bullion OR "gold futures"',
                               help="Title search expression, not a trading signal")
    provider_news.add_argument("--min-relevance", choices=("low", "medium", "high"), default="medium",
                               help="Keyword relevance floor for storing headlines (default: medium)")
    provider_news.add_argument("--max-per-source", type=int, default=5,
                               help="Most articles stored per source in one poll (default: 5)")
    sub.add_parser("poll-calendar", help="One explicit Trading Economics calendar snapshot; no trading")
    synthetic = sub.add_parser("analyze-synthetic", help="Offline descriptive statistics only; no orders")
    synthetic.add_argument("csv", help="Closed candles from one broker and one synthetic symbol")
    synthetic.add_argument("--family", required=True,
                           choices=("volatility", "boom", "crash", "step", "range_break", "jump", "other"))
    synthetic.add_argument("--jump-threshold-pct", type=float, default=1.0)
    synthetic.add_argument("--save", action="store_true",
                           help="Store the report in the local database (--database) for the dashboard")
    deriv = sub.add_parser("fetch-deriv-candles",
                           help="One explicit public, unauthenticated Deriv history request saved to CSV; no trading")
    deriv.add_argument("symbol", help="Deriv symbol such as R_75, BOOM500, CRASH500, stpRNG")
    deriv.add_argument("output", help="New CSV file; refuses to overwrite unless --overwrite")
    deriv.add_argument("--granularity", type=int, default=60, help="Seconds per candle: 60, 300, 3600...")
    deriv.add_argument("--count", type=int, default=1000, help="Candles requested, 2 to 5000")
    deriv.add_argument("--overwrite", action="store_true")
    backtest = sub.add_parser("backtest")
    backtest.add_argument("csv")
    backtest.add_argument("--report", help="Optional JSON output path")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("csv", help="Chronological 60/20/20 evaluation of a fixed baseline")
    cycle = sub.add_parser("cycle")
    cycle.add_argument("csv", help="Closed bars from the same broker and symbol")
    memory = sub.add_parser("memory")
    memory.add_argument("--cause", required=True)
    memory.add_argument("--evidence", required=True)
    memory.add_argument("--recommendation", required=True)
    memory.add_argument("--cycle-id")
    backup = sub.add_parser("backup")
    backup.add_argument("destination")
    verify = sub.add_parser("verify-backup")
    verify.add_argument("path")
    args = parser.parse_args()
    if args.command == "verify-backup":
        result = verify_backup(args.path)
        print(json.dumps(result, indent=2))
        return
    if args.command == "fetch-deriv-candles":
        from .deriv_history import fetch_candles, write_csv
        candles = fetch_candles(args.symbol, granularity=args.granularity, count=args.count)
        path = write_csv(candles, args.output, overwrite=args.overwrite)
        print(json.dumps({"saved": str(path), "symbol": args.symbol, "candles": len(candles),
                          "first_open": candles[0].opened_at.isoformat(),
                          "last_close": candles[-1].closed_at.isoformat(), "broker": candles[0].broker,
                          "note": "Public candles without bid/ask; research only, never execution costs."}, indent=2))
        return
    if args.command == "analyze-synthetic":
        from .synthetic_research import describe
        result = describe(load_candles(args.csv), family=args.family,
                          jump_threshold_pct=args.jump_threshold_pct)
        if args.save:
            result["saved_report_id"] = ResearchStore(args.database).synthetic_report(result)
        print(json.dumps(result, indent=2))
        return
    store = ResearchStore(args.database)
    if args.command == "backup":
        result = backup_database(args.database, args.destination)
    elif args.command == "memory":
        store.remember(cause=args.cause, evidence=args.evidence,
                       recommendation=args.recommendation, cycle_id=args.cycle_id)
        result = {"recorded": True, "strategy_changed": False}
    elif args.command == "import-news":
        records = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        if not isinstance(records, list):
            parser.error("News JSON must contain an array")
        inserted = 0
        for entry in records:
            event = normalize_event(source=entry["source"], url=entry["url"], headline=entry["headline"],
                                    published_at=datetime.fromisoformat(entry["published_at"]),
                                    received_at=datetime.fromisoformat(entry["received_at"]),
                                    verified_at=datetime.fromisoformat(entry["verified_at"]) if entry.get("verified_at") else None,
                                    status=entry.get("status", "unconfirmed"), severity=entry.get("severity", "low"),
                                    assets=entry.get("assets", []), corroborations=entry.get("corroborations", []))
            inserted += store.news(event)
        result = {"imported_versions": inserted, "total": len(records)}
    elif args.command == "poll-newsapi":
        from .integrations import fetch_newsapi
        from .relevance import select
        events = fetch_newsapi(query=args.query, api_key=os.getenv("TIP_NEWSAPI_KEY", ""))
        kept, report = select(events, minimum=args.min_relevance, max_per_source=args.max_per_source)
        result = {**report, "imported_versions": sum(store.news(event) for event in kept),
                  "classification": "unconfirmed, keyword relevance only, no asset assignment, no trading"}
    elif args.command == "poll-calendar":
        from .integrations import fetch_calendar
        releases = fetch_calendar(api_key=os.getenv("TIP_TRADING_ECONOMICS_KEY", ""))
        result = {"received": len(releases), "imported_versions": sum(store.calendar(item) for item in releases),
                  "effect": "research only; no automatic economic-event veto or trade"}
    elif args.command == "status":
        from .integrations import credential_status
        result = {"kill_switch": store.killed(), "snapshots": len(store.recent("snapshots", 500)),
                  "signals": len(store.recent("signals", 500)), "costs": store.costs(),
                  "broker": "disconnected", "mode": "observation", "credentials": credential_status()}
    else:
        candles = load_candles(args.csv)
        if args.command == "import-candles":
            result = {"imported": sum(store.candle(c) for c in candles), "total": len(candles)}
        elif args.command == "backtest":
            result = run_baseline(candles)
            store.backtest(str(Path(args.csv).name), result)
            if args.report:
                Path(args.report).parent.mkdir(parents=True, exist_ok=True)
                Path(args.report).write_text(json.dumps(result, indent=2), encoding="utf-8")
        elif args.command == "evaluate":
            result = chronological_evaluation(candles)
        else:
            if not candles:
                parser.error("CSV has no candles")
            last = candles[-1]
            quality = assess(candles, last.closed_at,
                             expected_seconds=int((candles[0].closed_at-candles[0].opened_at).total_seconds()),
                             max_age_seconds=1)
            if not quality.accepted:
                parser.error(f"Market quality gate failed: {', '.join(quality.reasons)}")
            relevant = [e for e in store.news_as_of(last.closed_at) if last.symbol in e["assets"]]
            critical = any(e["severity"] == "critical" and e["status"] != "retracted" for e in relevant)
            verified_urls = tuple(e["url"] for e in relevant if e["status"] == "confirmed")
            result = analyze(store, symbol=last.symbol, broker=last.broker, bid=last.bid,
                             ask=last.ask, closed_prices=[c.close for c in candles],
                             observed_at=last.closed_at, critical_event=critical, source_urls=verified_urls)
    print(json.dumps(result, default=lambda x: asdict(x) if hasattr(x, "__dataclass_fields__") else str(x), indent=2))


if __name__ == "__main__":
    main()
