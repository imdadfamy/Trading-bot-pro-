"""Application read models shared by the API and CLI."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from .market import session_label, sessions_at
from .store import ResearchStore


class Service:
    def __init__(self, database: str, skills_root: str | None = None):
        self.store = ResearchStore(database)
        self.skills_root = Path(skills_root) if skills_root else Path(__file__).resolve().parents[2] / "skills"

    def dashboard(self):
        quote = self.store.latest_snapshot()
        return {"mode": "observation", "broker": "disconnected", "kill_switch": self.store.killed(),
                "symbol": "XAUUSD", "live_trading": False, "snapshot": quote,
                "pending_order_intents": len(self.store.journal.pending_intents()),
                "agents": ["graph", "news", "quant", "risk", "director"],
                "events": self.store.journal.events(30),
                "signal_count": len(self.store.recent("signals", 500)),
                "costs": self.store.costs()}

    def settings(self):
        with self.store.journal.connect() as db:
            row = db.execute("SELECT version,payload FROM settings ORDER BY version DESC LIMIT 1").fetchone()
            return {"version": row["version"], "settings": json.loads(row["payload"])} if row else {
                "version": 0, "settings": {"mode": "observation", "model_by_agent": {},
                                             "daily_ai_limit_usd": 5, "experiment_ai_limit_usd": 50,
                                             "quote_max_age_seconds": 5}}

    def model_budget(self):
        from .models import Budget
        config = self.settings()["settings"]
        return Budget(config["daily_ai_limit_usd"], config["experiment_ai_limit_usd"])

    def update_settings(self, data: dict, expected_version: int, author: str):
        allowed = {"mode", "model_by_agent", "daily_ai_limit_usd", "experiment_ai_limit_usd", "quote_max_age_seconds"}
        if set(data) != allowed or data.get("mode") != "observation":
            raise ValueError("Only complete observation-mode settings are supported")
        models = data.get("model_by_agent")
        if not isinstance(models, dict) or set(models) - {"graph", "news", "quant", "risk", "director"}:
            raise ValueError("Unknown model assignment")
        if any(not isinstance(v, str) or len(v) > 100 for v in models.values()):
            raise ValueError("Invalid model name")
        for key, maximum in (("daily_ai_limit_usd", 10000), ("experiment_ai_limit_usd", 10000), ("quote_max_age_seconds", 60)):
            number = data[key]
            minimum = 0 if key != "quote_max_age_seconds" else 0.001
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not minimum <= number <= maximum:
                raise ValueError(f"Invalid {key}")
        if not isinstance(author, str) or not 1 <= len(author) <= 100:
            raise ValueError("Operator identity required")
        with self.store.journal.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT COALESCE(MAX(version),0) FROM settings").fetchone()[0]
            if current != expected_version:
                raise RuntimeError("Configuration version changed")
            version = current + 1
            db.execute("INSERT INTO settings VALUES(?,?,?)", (version, datetime.now(timezone.utc).isoformat(), json.dumps(data)))
        self.store.journal.log("settings.changed", "settings", {"version": version, "author": author})
        return {"version": version}

    def read(self, path: str):
        if path == "/health":
            return {"status": "ok", "mode": "observation", "live_trading": False}
        if path == "/readiness":
            from .experiments import GATES
            from .integrations import credential_status
            return {"ready_for_local_review": True, "ready_for_14_day_demo": False,
                    "execution_mode": "observation", "kill_switch": self.store.killed(),
                    "credentials": credential_status(),
                    "blocked_gates": list(GATES),
                    "note": "Gates need independent evidence; this endpoint does not attest external integrations"}
        if path == "/dashboard":
            return self.dashboard()
        if path == "/orders/intents":
            return self.store.journal.pending_intents()
        if path == "/market/snapshot":
            return {"snapshot": self.store.latest_snapshot(), "live": False}
        if path == "/market/candles":
            rows = self.store.recent("candles", 120)
            return {"candles": [json.loads(row["payload"]) for row in reversed(rows)],
                    "live": False, "source": "local research import"}
        if path == "/news/events":
            from .core import utcnow
            return self.store.news_as_of(utcnow())
        if path == "/calendar/events":
            from .core import utcnow
            return self.store.calendar_as_of(utcnow())[-100:]
        if path == "/signals":
            return [json.loads(row["payload"]) for row in self.store.recent("signals")]
        if path == "/agents":
            return [json.loads(row["payload"]) for row in self.store.recent("agent_runs")]
        if path == "/positions":
            return {"positions": [], "connected": False, "reason": "MT5 reconciliation not configured"}
        if path == "/sessions":
            from .core import utcnow
            now = utcnow()
            return {"as_of": now.isoformat(), "active": sessions_at(now),
                    "primary": session_label(now), "broker_hours_verified": False}
        if path == "/costs":
            costs = self.store.costs()
            configured = self.settings()["settings"]
            daily_limit = configured["daily_ai_limit_usd"]
            experiment_limit = configured["experiment_ai_limit_usd"]
            return {**costs, "daily_limit_usd": daily_limit,
                    "experiment_limit_usd": experiment_limit,
                    "daily_ratio": costs["today_usd"]/daily_limit if daily_limit else None,
                    "experiment_ratio": costs["total_usd"]/experiment_limit if experiment_limit else None,
                    "new_model_calls_blocked": (daily_limit == 0 or experiment_limit == 0 or
                                                costs["today_usd"] >= daily_limit or costs["total_usd"] >= experiment_limit)}
        if path == "/performance":
            return {"metrics": None, "reason": "No validated demo fills or equity snapshots"}
        if path == "/backtests":
            return self.store.backtests()
        if path == "/experiments":
            from .experiments import ExperimentManager
            return ExperimentManager(self.store).list()
        if path == "/skills":
            return json.loads((self.skills_root / "catalog.json").read_text(encoding="utf-8"))
        if path == "/memory":
            return [dict(row) for row in self.store.recent("memory")]
        if path == "/alerts":
            return [dict(row) for row in self.store.recent("alerts")]
        raise KeyError(path)
