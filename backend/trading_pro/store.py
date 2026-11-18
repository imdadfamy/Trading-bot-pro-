"""Local research persistence. PostgreSQL migration required for distributed deployment."""
from __future__ import annotations
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from .core import Report, Signal, Snapshot
from .journal import Journal
from .market import Candle
from .news import NewsEvent


class ResearchStore:
    def __init__(self, path: str):
        self.journal = Journal(path)
        with self.journal.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS candles (
              broker TEXT NOT NULL, symbol TEXT NOT NULL, opened_at TEXT NOT NULL,
              closed_at TEXT NOT NULL, payload TEXT NOT NULL,
              PRIMARY KEY (broker,symbol,opened_at));
            CREATE INDEX IF NOT EXISTS candles_time ON candles(symbol,closed_at);
            CREATE TABLE IF NOT EXISTS snapshots (
              cycle_id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, symbol TEXT NOT NULL,
              payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS news_events (
              event_id TEXT PRIMARY KEY, received_at TEXT NOT NULL, status TEXT NOT NULL,
              severity TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS news_event_versions (
              event_id TEXT NOT NULL, received_at TEXT NOT NULL, status TEXT NOT NULL,
              payload TEXT NOT NULL, PRIMARY KEY(event_id,received_at,status));
            CREATE TABLE IF NOT EXISTS calendar_event_versions (
              calendar_id TEXT NOT NULL, received_at TEXT NOT NULL, scheduled_at TEXT NOT NULL,
              payload TEXT NOT NULL, PRIMARY KEY(calendar_id,received_at));
            CREATE INDEX IF NOT EXISTS calendar_scheduled_at ON calendar_event_versions(scheduled_at);
            CREATE TABLE IF NOT EXISTS agent_runs (
              cycle_id TEXT NOT NULL, agent TEXT NOT NULL, at TEXT NOT NULL,
              payload TEXT NOT NULL, PRIMARY KEY(cycle_id,agent));
            CREATE TABLE IF NOT EXISTS signals (
              signal_id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL UNIQUE,
              at TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL,
              payload TEXT NOT NULL, FOREIGN KEY(cycle_id) REFERENCES snapshots(cycle_id));
            CREATE TABLE IF NOT EXISTS risk_checks (
              id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id TEXT NOT NULL, at TEXT NOT NULL,
              approved INTEGER NOT NULL, reason TEXT NOT NULL, volume REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS model_usage (
              id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, agent TEXT NOT NULL,
              provider TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL,
              output_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS experiments (
              id TEXT PRIMARY KEY, created_at TEXT NOT NULL, started_at TEXT,
              stopped_at TEXT, status TEXT NOT NULL, duration_days INTEGER NOT NULL,
              frozen_config TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS backtests (
              id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
              dataset TEXT NOT NULL, research_only INTEGER NOT NULL,
              result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memory (
              id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, cycle_id TEXT,
              cause TEXT NOT NULL, evidence TEXT NOT NULL, recommendation TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS synthetic_reports (
              id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, family TEXT NOT NULL,
              broker TEXT NOT NULL, symbol TEXT NOT NULL, report TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alerts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL,
              message TEXT NOT NULL, acknowledged_at TEXT);
            CREATE TABLE IF NOT EXISTS operational_state (
              name TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO operational_state(name,value) VALUES ('kill_switch','true');
            """)

    def _insert(self, table: str, values: tuple):
        # table is selected only by internal code, never from user input.
        statements = {
            "candles": "INSERT OR IGNORE INTO candles VALUES(?,?,?,?,?)",
            "snapshots": "INSERT INTO snapshots VALUES(?,?,?,?)",
            "news_events": "INSERT OR IGNORE INTO news_events VALUES(?,?,?,?,?)",
            "agent_runs": "INSERT INTO agent_runs VALUES(?,?,?,?)",
            "signals": "INSERT INTO signals VALUES(?,?,?,?,?,?)",
        }
        with self.journal.connect() as db:
            return db.execute(statements[table], values).rowcount == 1

    def candle(self, value: Candle) -> bool:
        return self._insert("candles", (value.broker, value.symbol, value.opened_at.isoformat(),
                                        value.closed_at.isoformat(), json.dumps(asdict(value), default=str)))

    def snapshot(self, value: Snapshot):
        self._insert("snapshots", (value.cycle_id, value.observed_at.isoformat(), value.symbol,
                                   json.dumps(asdict(value), default=str)))
        self.journal.log("market.snapshot", value.cycle_id, {"symbol": value.symbol, "broker": value.broker})

    def news(self, value: NewsEvent) -> bool:
        payload = json.dumps(asdict(value), default=str)
        with self.journal.connect() as db:
            latest = db.execute("SELECT payload FROM news_event_versions WHERE event_id=? "
                                "ORDER BY received_at DESC LIMIT 1", (value.event_id,)).fetchone()
            if latest is not None:
                previous = json.loads(latest["payload"])
                current = json.loads(payload)
                previous.pop("received_at", None)
                current.pop("received_at", None)
                if previous == current:  # re-polling the same state must not create a new version
                    return False
            inserted = db.execute("INSERT OR IGNORE INTO news_event_versions VALUES(?,?,?,?)",
                                  (value.event_id, value.received_at.isoformat(), value.status, payload)).rowcount == 1
            db.execute("INSERT OR IGNORE INTO news_events VALUES(?,?,?,?,?)",
                       (value.event_id, value.received_at.isoformat(), value.status, value.severity, payload))
        if inserted:
            self.journal.log("news.critical" if value.pauses_entries else "news.received", value.event_id,
                             {"source": value.source, "status": value.status, "severity": value.severity})
        return inserted

    def news_as_of(self, as_of: datetime):
        if as_of.tzinfo is None:
            raise ValueError("Aware decision time required")
        with self.journal.connect() as db:
            rows = db.execute("SELECT payload FROM news_event_versions WHERE received_at<=? ORDER BY received_at",
                              (as_of.isoformat(),))
            latest = {}
            for row in rows:
                event = json.loads(row["payload"])
                latest[event["event_id"]] = event
            return list(latest.values())

    def calendar(self, value):
        from .integrations import EconomicRelease
        if not isinstance(value, EconomicRelease):
            raise ValueError("Normalized calendar release required")
        with self.journal.connect() as db:
            inserted = db.execute("INSERT OR IGNORE INTO calendar_event_versions VALUES(?,?,?,?)",
                                  (value.calendar_id, value.received_at.isoformat(),
                                   value.scheduled_at.isoformat(), json.dumps(asdict(value), default=str))).rowcount == 1
        if inserted:
            self.journal.log("calendar.received", value.calendar_id, {"country": value.country,
                                                                        "importance": value.importance})
        return inserted

    def calendar_as_of(self, as_of: datetime):
        if as_of.tzinfo is None:
            raise ValueError("Aware calendar decision time required")
        with self.journal.connect() as db:
            rows = db.execute("SELECT payload FROM calendar_event_versions WHERE received_at<=? ORDER BY received_at",
                              (as_of.astimezone(timezone.utc).isoformat(),))
            latest = {}
            for row in rows:
                value = json.loads(row["payload"])
                latest[value["calendar_id"]] = value
            return sorted(latest.values(), key=lambda item: item["scheduled_at"])

    def analysis(self, cycle_id: str, report: Report):
        self._insert("agent_runs", (cycle_id, report.agent, datetime.now(timezone.utc).isoformat(),
                                    json.dumps(asdict(report), default=str)))

    def signal(self, value: Signal):
        self._insert("signals", (value.signal_id, value.cycle_id, value.created_at.isoformat(),
                                 value.action.value, value.status, json.dumps(asdict(value), default=str)))
        self.journal.log("signal.created", value.signal_id, {"cycle_id": value.cycle_id,
                                                              "action": value.action.value, "status": value.status})

    def recent(self, table: str, limit=100) -> list[dict]:
        allowed = {"candles": "closed_at", "snapshots": "observed_at", "news_events": "received_at",
                   "agent_runs": "at", "signals": "at", "model_usage": "at", "alerts": "at", "memory": "at"}
        if table not in allowed:
            raise ValueError("Unknown read model")
        with self.journal.connect() as db:
            rows = db.execute(f"SELECT * FROM {table} ORDER BY {allowed[table]} DESC LIMIT ?", (min(max(limit, 0), 500),))
            return [dict(row) for row in rows]

    def latest_snapshot(self):
        rows = self.recent("snapshots", 1)
        return json.loads(rows[0]["payload"]) if rows else None

    def set_killed(self):
        with self.journal.connect() as db:
            db.execute("UPDATE operational_state SET value='true' WHERE name='kill_switch'")
        self.journal.log("risk.kill_switch", "global", {"enabled": True})

    def killed(self) -> bool:
        with self.journal.connect() as db:
            return db.execute("SELECT value FROM operational_state WHERE name='kill_switch'").fetchone()[0] == "true"

    def record_usage(self, *, agent, provider, model, input_tokens, output_tokens, cost_usd):
        if min(input_tokens, output_tokens, cost_usd) < 0:
            raise ValueError("Negative usage")
        with self.journal.connect() as db:
            db.execute("INSERT INTO model_usage(at,agent,provider,model,input_tokens,output_tokens,cost_usd) VALUES(?,?,?,?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(), agent, provider, model, input_tokens, output_tokens, cost_usd))

    def costs(self):
        with self.journal.connect() as db:
            total = db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM model_usage").fetchone()[0]
            daily = db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM model_usage WHERE at>=?",
                               (datetime.now(timezone.utc).strftime("%Y-%m-%d"),)).fetchone()[0]
            return {"total_usd": total, "today_usd": daily, "calls": len(self.recent("model_usage", 500))}

    def backtest(self, dataset: str, result: dict):
        with self.journal.connect() as db:
            db.execute("INSERT INTO backtests(at,dataset,research_only,result) VALUES(?,?,1,?)",
                       (datetime.now(timezone.utc).isoformat(), dataset, json.dumps(result)))
        self.journal.log("backtest.completed", "research", {"dataset": dataset,
                                                           "trades": result["metrics"]["trades"]})

    def backtests(self, limit=20):
        with self.journal.connect() as db:
            return [{**dict(row), "result": json.loads(row["result"])} for row in db.execute(
                "SELECT * FROM backtests ORDER BY id DESC LIMIT ?", (min(limit, 100),))]

    def synthetic_report(self, report: dict) -> int:
        """Persist one offline descriptive study; it never feeds the director or any order path."""
        if report.get("action") != "WAIT" or report.get("mode") != "observation":
            raise ValueError("Only observation-mode WAIT reports can be stored")
        with self.journal.connect() as db:
            identifier = db.execute(
                "INSERT INTO synthetic_reports(at,family,broker,symbol,report) VALUES(?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), report["family"], report["broker"],
                 report["symbol"], json.dumps(report))).lastrowid
        self.journal.log("synthetic.reported", str(identifier), {"family": report["family"],
                                                               "symbol": report["symbol"]})
        return identifier

    def synthetic_reports(self, limit=20):
        with self.journal.connect() as db:
            return [{**dict(row), "report": json.loads(row["report"])} for row in db.execute(
                "SELECT * FROM synthetic_reports ORDER BY id DESC LIMIT ?", (min(max(limit, 0), 100),))]

    def remember(self, *, cause: str, evidence: str, recommendation: str, cycle_id: str | None = None):
        if not all(isinstance(value, str) and 1 <= len(value) <= 2000 for value in (cause, evidence, recommendation)):
            raise ValueError("Documented cause, evidence and recommendation required")
        with self.journal.connect() as db:
            db.execute("INSERT INTO memory(at,cycle_id,cause,evidence,recommendation) VALUES(?,?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(), cycle_id, cause, evidence, recommendation))
        self.journal.log("memory.recorded", cycle_id or "research", {"cause": cause})
