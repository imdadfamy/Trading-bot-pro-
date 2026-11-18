"""Fourteen-day protocol state; refuses activation without complete operational gates."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from uuid import uuid4
from .store import ResearchStore

GATES = (
    "broker_demo_verified", "broker_hours_verified", "market_freshness_verified",
    "news_licence_verified", "news_coverage_verified", "risk_tests_passed",
    "idempotency_reconciliation_passed", "stops_verified", "kill_switch_worker_connected",
    "operator_approved_limits", "strategy_frozen", "model_budget_frozen",
    "backup_restore_tested", "alerts_tested",
)


class ExperimentManager:
    def __init__(self, store: ResearchStore):
        self.store = store

    def draft(self, frozen_config: dict) -> str:
        if frozen_config.get("mode") != "demo" or not frozen_config.get("strategy_version"):
            raise ValueError("Demo mode and explicit strategy version required")
        experiment_id = str(uuid4())
        with self.store.journal.connect() as db:
            db.execute("INSERT INTO experiments VALUES(?,?,?,?,?,?,?)",
                       (experiment_id, datetime.now(timezone.utc).isoformat(), None, None,
                        "draft", 14, json.dumps(frozen_config, sort_keys=True)))
        self.store.journal.log("experiment.drafted", experiment_id, {"duration_days": 14})
        return experiment_id

    def preflight(self, gates: dict[str, bool]) -> dict:
        missing = sorted(set(GATES) - {name for name in GATES if gates.get(name) is True})
        return {"ready": not missing, "missing": missing}

    def start(self, experiment_id: str, gates: dict[str, bool], *, verified_demo_account: bool):
        check = self.preflight(gates)
        if not check["ready"] or not verified_demo_account:
            raise RuntimeError(f"Experiment blocked: {check['missing'] or ['demo account not verified']}")
        # Activation is intentionally unimplemented until the durable worker and
        # signed outbound MT5 bridge have been integrated and independently tested.
        raise RuntimeError("Demo worker and reconciliation bridge not commissioned")

    def list(self):
        with self.store.journal.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM experiments ORDER BY created_at DESC")]
