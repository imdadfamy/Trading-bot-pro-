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


def _announcement_halt(parser, when):
    """Reason to suspend entries at ``when`` because of a scheduled US announcement, or None."""
    from . import us_events
    try:
        return us_events.load().halt_reason(when)
    except FileNotFoundError:
        return None
    except ValueError as exc:
        parser.error(f"config/us_events.json is invalid: {exc}")


def _model_cycle(args, parser, store, candles, critical, verified_urls, halt_reason=""):
    """Explicit, budget-capped model run. Fails before any network call if configuration is incomplete."""
    from dataclasses import replace
    from .ai_orchestrator import analyze_with_models
    from .openai_provider import provider_from_env
    from .service import Service
    try:
        provider = provider_from_env()
    except ValueError as exc:
        parser.error(str(exc))
    last = candles[-1]
    service = Service(args.database)
    configured = service.settings()["settings"]["model_by_agent"]
    agents = tuple(name.strip() for name in args.agents.split(",") if name.strip())
    models = {name: (args.model or configured.get(name, "")) for name in agents}
    budget = replace(service.model_budget(), max_call_usd=args.max_call_usd)
    headlines = [{"headline": e["headline"], "source": e["source"], "status": e["status"],
                  "relevance": e.get("relevance", "unclassified"), "published_at": e["published_at"]}
                 for e in store.news_as_of(last.closed_at)
                 if e.get("relevance") in ("medium", "high")][-10:]
    try:
        return analyze_with_models(store, provider, symbol=last.symbol, broker=last.broker, bid=last.bid,
                                   ask=last.ask, closed_prices=[c.close for c in candles], headlines=headlines,
                                   models=models, budget=budget, agents=agents, source_urls=verified_urls,
                                   critical_event=critical, observed_at=last.closed_at, halt_reason=halt_reason)
    except ValueError as exc:
        parser.error(str(exc))


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
    us = sub.add_parser("us-events", help="Show the scheduled US announcements and caution windows; read-only")
    us.add_argument("--at", help="UTC time to check, ISO 8601 (default: now)")
    us.add_argument("--limit", type=int, default=8)
    refresh = sub.add_parser("refresh-us-events", help="Update config/us_events.json from official sources")
    refresh.add_argument("--fed", action="store_true", help="Fetch the Federal Reserve FOMC calendar page (one request)")
    refresh.add_argument("--bls-ics", help="Official bls.ics downloaded by a person from bls.gov (scripts are refused)")
    refresh.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    mt5 = sub.add_parser("mt5-status", help="READ-ONLY check of the MT5 demo account and symbol specifications; no order")
    mt5.add_argument("--terminal-path", default=None, help="Path to terminal64.exe (default: standard install folder)")
    mt5.add_argument("--pattern", action="append", help="Symbol name pattern such as XAU* (repeatable)")
    mt5.add_argument("--max-symbols", type=int, default=40)
    mt5.add_argument("--select", action="store_true", help="Also add the found symbols to Market Watch (to read ticks)")
    fm = sub.add_parser("fetch-mt5-candles",
                        help="READ-ONLY export of closed candles with the real spread from the MT5 demo account")
    fm.add_argument("symbol", help="Exact MT5 symbol, for example XAUUSD")
    fm.add_argument("output", help="New CSV file; refuses to overwrite unless --overwrite")
    fm.add_argument("--timeframe", default="M5", help="M1, M5, M15, M30, H1, H4 or D1 (default M5)")
    fm.add_argument("--count", type=int, default=5000, help="Closed bars requested (default 5000)")
    fm.add_argument("--select", action="store_true", help="Add the symbol to Market Watch if it is not there")
    fm.add_argument("--overwrite", action="store_true")
    fm.add_argument("--server-utc-offset-hours", type=float, default=None,
                    help="Broker clock offset to UTC; measured from a fresh tick when omitted")
    fm.add_argument("--terminal-path", default=None)
    models = sub.add_parser("analyze-with-models",
                            help="One explicit model-assisted cycle: paid provider calls, budget capped, no orders")
    models.add_argument("csv", help="Closed candles, same format as the cycle command")
    models.add_argument("--agents", default="graph,news,quant", help="Comma list among graph, news, quant")
    models.add_argument("--model", help="Model name for every chosen agent (default: versioned settings)")
    models.add_argument("--max-call-usd", type=float, default=0.05, help="Hard cap for one call (default 0.05)")
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
    if args.command == "us-events":
        from datetime import timezone
        from . import us_events
        when = datetime.fromisoformat(args.at) if args.at else datetime.now(timezone.utc)
        if when.tzinfo is None:
            parser.error("--at must include a timezone, for example 2026-12-04T13:45:00+00:00")
        try:
            calendar = us_events.load()
        except (FileNotFoundError, ValueError) as exc:
            parser.error(f"US events file unavailable: {exc}")
        print(json.dumps(us_events.describe(calendar, when, args.limit), indent=2, ensure_ascii=False))
        return
    if args.command == "refresh-us-events":
        from datetime import timezone
        from . import us_events, us_events_refresh as refresh_module
        if not args.fed and not args.bls_ics:
            parser.error("Choose --fed and/or --bls-ics FILE")
        path = us_events.DEFAULT_PATH
        document = json.loads(path.read_text(encoding="utf-8"))
        fresh, notes = [], {}
        try:
            if args.fed:
                fresh += refresh_module.parse_fed_calendar(refresh_module.fetch_fed_page(),
                                                           since_year=datetime.now(timezone.utc).year)
            if args.bls_ics:
                events, ignored = refresh_module.parse_bls_ics(Path(args.bls_ics).read_text(encoding="utf-8"))
                fresh += events
                notes["bls_ignored_non_eastern"] = ignored
            updated, summary = refresh_module.merge(document, fresh)
        except (ValueError, OSError) as exc:
            parser.error(f"Refresh refused, nothing written: {exc}")
        if not args.dry_run:
            refresh_module.save(path, updated)
        print(json.dumps({"written": not args.dry_run, "changes": summary, **notes,
                          "coverage": us_events.parse(updated).coverage(datetime.now(timezone.utc))}, indent=2))
        return
    if args.command == "fetch-mt5-candles":
        from . import mt5_history, mt5_status
        from .deriv_history import write_csv
        try:
            import MetaTrader5 as terminal_module
        except ImportError:
            parser.error("Package MetaTrader5 missing: python -m pip install MetaTrader5==5.0.6231")
        try:
            login, server, password = mt5_status.credentials_from_env()
            default_path = str(mt5_status.DEFAULT_TERMINAL) if mt5_status.DEFAULT_TERMINAL.is_file() else None
            candles, meta = mt5_history.fetch(terminal_module, symbol=args.symbol, timeframe=args.timeframe,
                                              count=args.count, expected_login=login, server=server,
                                              password=password, terminal_path=args.terminal_path or default_path,
                                              select=args.select, utc_offset_hours=args.server_utc_offset_hours)
            saved = write_csv(candles, args.output, overwrite=args.overwrite)
        except (RuntimeError, ValueError, FileExistsError) as exc:
            parser.error(str(exc))
        print(json.dumps({"saved": str(saved), **meta, "broker": server,
                          "note": "Bid-based bars; ask = bid + recorded spread. Market data of the broker: keep it out of Git."},
                         indent=2))
        return
    if args.command == "mt5-status":
        from . import mt5_status
        try:
            import MetaTrader5 as terminal_module
        except ImportError:
            parser.error("Package MetaTrader5 missing: python -m pip install MetaTrader5==5.0.6231")
        try:
            login, server, password = mt5_status.credentials_from_env()
            default_path = str(mt5_status.DEFAULT_TERMINAL) if mt5_status.DEFAULT_TERMINAL.is_file() else None
            report = mt5_status.inspect(terminal_module, expected_login=login, server=server, password=password,
                                        patterns=tuple(args.pattern) if args.pattern else mt5_status.DEFAULT_PATTERNS,
                                        terminal_path=args.terminal_path or default_path,
                                        max_symbols=args.max_symbols, select_symbols=args.select)
        except RuntimeError as exc:
            parser.error(str(exc))
        print(json.dumps(report, indent=2, ensure_ascii=False))
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
            from .broker_hours import schedule_for
            quality = assess(candles, last.closed_at,
                             expected_seconds=int((candles[0].closed_at-candles[0].opened_at).total_seconds()),
                             max_age_seconds=1, explained_gap=schedule_for(last.symbol, last.broker))
            if not quality.accepted:
                parser.error(f"Market quality gate failed: {', '.join(quality.reasons)}")
            relevant = [e for e in store.news_as_of(last.closed_at) if last.symbol in e["assets"]]
            critical = any(e["severity"] == "critical" and e["status"] != "retracted" for e in relevant)
            verified_urls = tuple(e["url"] for e in relevant if e["status"] == "confirmed")
            halt = _announcement_halt(parser, last.closed_at) or ""
            critical = critical or bool(halt)
            if args.command == "analyze-with-models":
                result = _model_cycle(args, parser, store, candles, critical, verified_urls, halt)
            else:
                result = analyze(store, symbol=last.symbol, broker=last.broker, bid=last.bid,
                                 ask=last.ask, closed_prices=[c.close for c in candles],
                                 observed_at=last.closed_at, critical_event=critical, source_urls=verified_urls,
                                 halt_reason=halt)
    print(json.dumps(result, default=lambda x: asdict(x) if hasattr(x, "__dataclass_fields__") else str(x), indent=2))


if __name__ == "__main__":
    main()
