import tempfile
import unittest
import io
import json
from email.message import Message
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_pro.core import Action, Instrument, Limits, RiskState, Signal, Snapshot, check_risk
from trading_pro.experiments import ExperimentManager, GATES
from trading_pro.models import Budget, run_model
from trading_pro.store import ResearchStore
from trading_pro.server import handler_factory
from trading_pro.service import Service
from trading_pro.backup import backup_database, verify_backup
from trading_pro.exports import _cell, signals_csv


class OperationsTests(unittest.TestCase):
    def test_experiment_requires_all_gates_and_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp)/"db.sqlite"))
            manager = ExperimentManager(store)
            identifier = manager.draft({"mode": "demo", "strategy_version": "1.0"})
            self.assertEqual(manager.list()[0]["status"], "draft")
            self.assertEqual(len(manager.preflight({})["missing"]), len(GATES))
            with self.assertRaises(RuntimeError):
                manager.start(identifier, {name: True for name in GATES}, verified_demo_account=True)

    def test_model_budget_and_strict_schema(self):
        class Provider:
            def classify(self, agent, snapshot, model):
                return ({"action": "WAIT", "rationale": "No edge", "evidence": [], "score": None},
                        {"cost_usd": .01, "input_tokens": 20, "output_tokens": 5})
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp)/"db.sqlite"))
            budget = Budget(.02, .02)
            self.assertEqual(run_model(store, Provider(), agent="news", model="test",
                                       snapshot={"cycle_id": "a"}, budget=budget,
                                       projected_cost_usd=.01).action, Action.WAIT)
            self.assertEqual(store.costs()["calls"], 1)
            self.assertIn("budget", run_model(store, Provider(), agent="news", model="test",
                                               snapshot={"cycle_id": "b"}, budget=budget,
                                               projected_cost_usd=.02).rationale.lower())

    def test_model_timeout_abstains(self):
        class TimedOut:
            def classify(self, agent, snapshot, model):
                raise TimeoutError("secret endpoint detail")
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp)/"db.sqlite"))
            result = run_model(store, TimedOut(), agent="news", model="test",
                               snapshot={"cycle_id": "c"}, budget=Budget(10, 10), projected_cost_usd=.01)
            self.assertEqual(result.action, Action.WAIT)
            self.assertNotIn("secret endpoint", str(store.journal.events()))

    def test_budget_read_model_respects_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp)/"db.sqlite"))
            settings = service.settings()["settings"]
            settings["daily_ai_limit_usd"] = 0
            service.update_settings(settings, 0, "test")
            self.assertEqual(service.model_budget().daily_usd, 0)
            self.assertTrue(service.read("/costs")["new_model_calls_blocked"])

    def test_readiness_never_claims_demo_without_integrations(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp)/"db.sqlite"))
            report = service.read("/readiness")
            self.assertTrue(report["ready_for_local_review"])
            self.assertFalse(report["ready_for_14_day_demo"])
            self.assertIn("broker_demo_verified", report["blocked_gates"])

    def test_nan_and_future_signal_never_approved(self):
        now = datetime.now(timezone.utc)
        quote = Snapshot("a", "XAUUSD", 2000, 2000.1, now)
        signal = Signal("a", "a", "XAUUSD", Action.BUY, now, now+timedelta(minutes=1),
                        "test", "1", "test", 2000, 1998, 2004, status="validated")
        instrument = Instrument(.01, 1, .01, 10, .01, 7, 2)
        state = RiskState(10000, 10000, killed=False, demo_account=True, broker_connected=True)
        self.assertFalse(check_risk(signal, quote, instrument, replace(state, equity=float("nan")), Limits()).approved)
        self.assertFalse(check_risk(replace(signal, created_at=now+timedelta(seconds=10)), quote,
                                    instrument, state, Limits(), now).approved)

    def test_http_handler_reads_and_rejects_unauthorized_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp)/"db.sqlite"))
            cls = handler_factory(service, "test-only-key")
            handler = cls.__new__(cls)
            handler.wfile = io.BytesIO()
            handler.rfile = io.BytesIO()
            handler.request_version = "HTTP/1.1"
            handler.requestline = "GET /skills HTTP/1.1"
            handler.command = "GET"
            handler.path = "/skills"
            handler.headers = Message()
            handler.do_GET()
            self.assertIn(b'"risk-management"', handler.wfile.getvalue())
            handler.wfile = io.BytesIO()
            handler.path = "/"
            handler.do_GET()
            self.assertIn(b"TRADING INTELLIGENCE PRO", handler.wfile.getvalue())
            handler.wfile = io.BytesIO()
            handler.command = "POST"
            handler.path = "/risk/kill-switch"
            handler.do_POST()
            self.assertIn(b"403", handler.wfile.getvalue())
            handler.wfile = io.BytesIO()
            handler.command = "GET"
            handler.path = "/orders/intents"
            handler.do_GET()
            self.assertIn(b"403", handler.wfile.getvalue())

    def test_http_handler_settings_and_stop_with_operator_key(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service(str(Path(temp)/"db.sqlite"))
            cls = handler_factory(service, "local-test-key")
            handler = cls.__new__(cls)
            handler.wfile = io.BytesIO()
            handler.request_version = "HTTP/1.1"
            handler.requestline = "PATCH /settings HTTP/1.1"
            handler.command = "PATCH"
            handler.path = "/settings"
            payload = json.dumps({"settings": service.settings()["settings"], "expected_version": 0}).encode()
            handler.rfile = io.BytesIO(payload)
            headers = Message()
            headers["X-Operator-Key"] = "local-test-key"
            headers["Content-Length"] = str(len(payload))
            handler.headers = headers
            handler.do_PATCH()
            self.assertIn(b'"version": 1', handler.wfile.getvalue())
            handler.wfile = io.BytesIO()
            handler.command = "POST"
            handler.path = "/risk/kill-switch"
            handler.do_POST()
            self.assertIn(b'"killed": true', handler.wfile.getvalue())
            self.assertTrue(service.store.killed())
            handler.wfile = io.BytesIO()
            handler.command = "GET"
            handler.path = "/orders/intents"
            handler.do_GET()
            self.assertIn(b"200", handler.wfile.getvalue())
            self.assertIn(b"[]", handler.wfile.getvalue())

    def test_consistent_backup_and_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            source = str(Path(temp)/"source.db")
            destination = str(Path(temp)/"backup.db")
            store = ResearchStore(source)
            store.journal.log("test", "cycle", {"safe": True})
            result = backup_database(source, destination)
            self.assertTrue(result["valid"])
            self.assertEqual(result["audit_rows"], 1)
            self.assertTrue(verify_backup(destination)["valid"])

    def test_csv_export_escapes_spreadsheet_formulas(self):
        self.assertEqual(_cell("=SUM(1,2)"), "'=SUM(1,2)")
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp)/"db.sqlite"))
            self.assertIn(b"signal_id,cycle_id", signals_csv(store))


if __name__ == "__main__":
    unittest.main()
