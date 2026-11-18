import io
import json
import re
import tempfile
import unittest
from email.message import Message
from pathlib import Path

from trading_pro.experiments import GATES
from trading_pro.server import handler_factory
from trading_pro.service import Service

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend" / "trading_pro"
LABELS = json.loads((ROOT / "web" / "preview" / "labels.json").read_text(encoding="utf-8"))


def sources():
    return {path.name: path.read_text(encoding="utf-8") for path in SOURCE.glob("*.py")}


class LabelCoverageTests(unittest.TestCase):
    """Every technical word the interface can show needs a French label; new code must extend labels.json."""

    def test_every_experiment_gate_has_a_title_and_an_explanation(self):
        for gate in GATES:
            self.assertIn(gate, LABELS["gates"], gate)
            title, explanation = LABELS["gates"][gate]
            self.assertTrue(title.strip() and explanation.strip(), gate)

    def test_every_journal_event_kind_is_labelled(self):
        kinds = set()
        for text in sources().values():
            kinds |= set(re.findall(r'\.log\(\s*"([a-z_]+\.[a-z_]+)"', text))
            kinds |= set(re.findall(r'\.log\(\s*"([a-z_]+\.[a-z_]+)" if', text))
        self.assertTrue(kinds)
        self.assertEqual(sorted(kinds - set(LABELS["events"])), [])

    def test_actions_roles_statuses_and_levels_are_labelled(self):
        self.assertEqual(set(LABELS["actions"]), {"BUY", "SELL", "WAIT"})
        for agent in ("graph", "news", "quant", "risk", "director"):
            self.assertIn(agent, LABELS["roles"])
            self.assertIn(agent, LABELS["roleHelp"])
        for key in ("unconfirmed", "confirmed", "retracted", "candidate"):
            self.assertIn(key, LABELS["status"])
        self.assertEqual(set(LABELS["severity"]), {"low", "medium", "critical"})
        self.assertEqual(set(LABELS["relevance"]), {"high", "medium", "low", "none", "unclassified"})
        from trading_pro.synthetic_research import FAMILIES
        self.assertEqual(sorted(set(FAMILIES) - set(LABELS["families"])), [])
        for key in ("disconnected", "observation"):
            self.assertIn(key, LABELS["values"])

    def test_fixed_rationale_strings_have_a_translation(self):
        code = sources()
        found = set()
        for name in ("agents.py", "models.py"):
            found |= set(re.findall(r'Report\([^()]*?,\s*Action\.\w+,\s*"([^"]+)"', code[name]))
        found |= set(re.findall(r'(?:reason =|reason=)\s*"([^"]+)"', code["core.py"]))
        found |= set(re.findall(r'^\s+reason = "([^"]+)"', code["core.py"], re.M))
        found = {text for text in found if text}
        self.assertGreaterEqual(len(found), 8)
        self.assertEqual(sorted(text for text in found if text not in LABELS["rationales"]), [])
        self.assertRegex("Observed return volatility 0.000114; no calibrated edge", LABELS["rationalePatterns"][0][0])

    def test_labels_are_served_by_the_local_server(self):
        with tempfile.TemporaryDirectory() as temp:
            cls = handler_factory(Service(str(Path(temp) / "db.sqlite")), "test-only-key")
            handler = cls.__new__(cls)
            handler.wfile, handler.rfile = io.BytesIO(), io.BytesIO()
            handler.request_version, handler.requestline = "HTTP/1.1", "GET /labels.json HTTP/1.1"
            handler.command, handler.path, handler.headers = "GET", "/labels.json", Message()
            handler.do_GET()
            payload = handler.wfile.getvalue().split(b"\r\n\r\n", 1)[1]
            self.assertEqual(json.loads(payload), LABELS)


if __name__ == "__main__":
    unittest.main()
