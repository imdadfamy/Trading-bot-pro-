import json
import unittest
from datetime import datetime, timezone, timedelta

from trading_pro.integrations import credential_status, fetch_newsapi, normalize_newsapi, normalize_calendar, fetch_calendar
from trading_pro.openai_provider import OpenAIProvider
from trading_pro.models import Budget, run_model
from trading_pro.store import ResearchStore
from trading_pro.core import Action
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
from trading_pro.local_env import load_local_env


class IntegrationTests(unittest.TestCase):
    def test_local_env_loads_only_known_keys_and_never_overrides_process(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, {"OPENAI_API_KEY": "existing"}, clear=True):
            path = Path(temp)/".env.local"
            path.write_text("# local\nOPENAI_API_KEY=ignored\nTIP_NEWSAPI_KEY=example-secret\nTIP_MT5_DEMO_LOGIN=\n",
                            encoding="utf-8")
            self.assertEqual(load_local_env(path), ("TIP_NEWSAPI_KEY",))
            self.assertEqual(os.environ["OPENAI_API_KEY"], "existing")
            self.assertEqual(os.environ["TIP_NEWSAPI_KEY"], "example-secret")
            path.write_text("UNSAFE_VARIABLE=hidden-secret\n", encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                load_local_env(path)
            self.assertNotIn("hidden-secret", str(raised.exception))

    def test_credentials_report_presence_not_secret_or_verified_connection(self):
        status = credential_status({"OPENAI_API_KEY": "very-secret", "TIP_NEWSAPI_KEY": "other-secret",
                                    "TIP_MT5_DEMO_LOGIN": "123", "TIP_MT5_DEMO_SERVER": "demo"})
        self.assertTrue(status["openai_key_present"])
        self.assertTrue(status["mt5_demo_account_configured"])
        self.assertFalse(status["verified"])
        self.assertNotIn("secret", str(status))

    def test_newsapi_normalization_is_unconfirmed_and_non_directional(self):
        now = datetime.now(timezone.utc)
        article = {"source": {"name": "Publisher"}, "title": "Gold rises", "url": "https://example.org/a",
                   "publishedAt": (now-timedelta(minutes=2)).isoformat()}
        events = normalize_newsapi({"status": "ok", "articles": [article]}, received_at=now)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "unconfirmed")
        self.assertEqual(events[0].severity, "low")
        self.assertEqual(events[0].assets, ())
        with self.assertRaises(ValueError):
            normalize_newsapi({"status": "ok", "articles": [{**article, "publishedAt": "2026-11-18T11:00:00"}]},
                              received_at=now)

    def test_explicit_fetch_uses_header_and_bounded_payload(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                self_size = size
                assert self_size == 1_000_001
                return json.dumps({"status": "ok", "articles": []}).encode()
        def transport(request, *, timeout):
            self.assertEqual(timeout, 8)
            self.assertEqual(request.get_header("X-api-key"), "secret")
            self.assertNotIn("secret", request.full_url)
            self.assertEqual(request.full_url.split("?", 1)[0], "https://newsapi.org/v2/everything")
            return Response()
        self.assertEqual(fetch_newsapi(query="gold", api_key="secret", opener=transport), [])
        with self.assertRaises(ValueError):
            fetch_newsapi(query="gold", api_key="", opener=transport)

    def test_structured_model_adapter_and_cost_overrun_are_recorded(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                return json.dumps({"status": "completed", "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": json.dumps({"action": "WAIT", "rationale": "No edge",
                                                                  "evidence": [], "score": None})}]}],
                    "usage": {"input_tokens": 100, "output_tokens": 100}}).encode()
        def transport(request, *, timeout):
            self.assertEqual(timeout, 20)
            self.assertNotIn("secret", request.full_url)
            body = json.loads(request.data)
            self.assertTrue(body["text"]["format"]["strict"])
            self.assertFalse(body["store"])
            self.assertEqual(body["max_output_tokens"], 512)
            return Response()
        provider = OpenAIProvider(api_key="secret", input_usd_per_million=1000,
                                  output_usd_per_million=1000, opener=transport)
        with TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp)/"db.sqlite"))
            report = run_model(store, provider, agent="news", model="configured-model",
                               snapshot={"cycle_id": "cycle"}, budget=Budget(1, 1, max_call_usd=.1),
                               projected_cost_usd=.01)
            self.assertEqual(report.action, Action.WAIT)
            self.assertIn("budget", report.rationale.lower())
            self.assertAlmostEqual(store.costs()["total_usd"], .2)

    def test_calendar_revisions_are_point_in_time(self):
        start = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)
        row = {"CalendarId": 123, "Date": "2026-11-19T13:30:00", "Country": "United States",
               "Event": "Inflation", "Importance": 3, "Actual": None, "Forecast": "2.3%"}
        early = normalize_calendar([row], received_at=start)[0]
        later = normalize_calendar([{**row, "Actual": "2.4%"}], received_at=start+timedelta(days=1))[0]
        self.assertEqual(early.scheduled_at.tzinfo, timezone.utc)
        with TemporaryDirectory() as temp:
            store = ResearchStore(str(Path(temp)/"db.sqlite"))
            store.calendar(early); store.calendar(later)
            self.assertIsNone(store.calendar_as_of(start)[0]["actual"])
            self.assertEqual(store.calendar_as_of(start+timedelta(days=1))[0]["actual"], "2.4%")
        with self.assertRaises(ValueError):
            normalize_calendar([{**row, "Importance": 8}], received_at=start)

    def test_calendar_fetch_sends_key_only_in_header(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b"[]"
        def transport(request, *, timeout):
            self.assertEqual(timeout, 8)
            self.assertEqual(request.get_header("Authorization"), "secret")
            self.assertNotIn("secret", request.full_url)
            return Response()
        self.assertEqual(fetch_calendar(api_key="secret", opener=transport), [])


if __name__ == "__main__":
    unittest.main()
