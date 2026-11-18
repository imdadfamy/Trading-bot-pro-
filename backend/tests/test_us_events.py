import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from trading_pro import us_events as u
from trading_pro import us_events_refresh as refresh
from trading_pro.core import Action, Director, Instrument, Limits, RiskState, Signal, Snapshot, check_risk
from trading_pro.orchestrator import analyze
from trading_pro.store import ResearchStore

UTC = timezone.utc


def doc(events, **extra):
    base = {"schema": 1, "retrieved_on": "2026-11-18", "events": events,
            "windows": {"NFP": {"before": 30, "after": 60}}}
    base.update(extra)
    return base


def calendar(*pairs):
    return u.parse(doc([{"kind": k, "date": d, "time_et": "08:30"} for k, d in pairs]))


OFFICIAL_ICS = """BEGIN:VCALENDAR
PRODID:-//Department of Labor//Bureau of Labor Statistics//EN
VERSION:2.0
BEGIN:VEVENT
SEQUENCE:1
CLASS:PUBLIC
UID:7c88ae35-a2f2-4df6-ae5e-33e6bab7c345
DTSTART;TZID=US-Eastern:20260109T083000
DURATION:PT0M
SUMMARY:Employment Situation
LOCATION:Washington\\, DC
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20261210T083000
SUMMARY:Consumer Price Index
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20261215T083000
SUMMARY:Producer Price
  Index
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20261217T083000
SUMMARY:Real Earnings
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/Paris:20261218T083000
SUMMARY:Employment Situation
END:VEVENT
END:VCALENDAR
"""
FED_PAGE = """<h4><a id="x">2026 FOMC Meetings</a></h4>
<div class="fomc-meeting__month"><strong>October</strong></div><div class="fomc-meeting__date">27-28</div>
<div class="fomc-meeting__month"><strong>December</strong></div><div class="fomc-meeting__date">8-9*</div>
<div class="fomc-meeting__month"><strong>August</strong></div><div class="fomc-meeting__date">22 (notation vote)</div>
<h4><a id="y">2027 FOMC Meetings</a></h4>
<div class="fomc-meeting__month"><strong>January</strong></div><div class="fomc-meeting__date">26-27</div>
<p>Note: A two-day meeting is scheduled for January 25-26, 2028. Each meeting date is tentative.</p>
Back to Top
<h4><a id="z">2019 FOMC Meetings</a></h4>
<div class="fomc-meeting__month"><strong>January</strong></div><div class="fomc-meeting__date">29-30</div>"""


class TimeConversionTests(unittest.TestCase):
    def test_eastern_to_utc_follows_the_dst_calendar(self):
        cases = {"2026-11-06": "13:30", "2026-07-02": "12:30", "2026-03-06": "13:30", "2026-03-09": "12:30",
                 "2026-10-30": "12:30", "2026-11-02": "13:30", "2027-03-12": "13:30", "2027-03-15": "12:30"}
        for day, expected in cases.items():
            self.assertEqual(u.et_to_utc(date.fromisoformat(day), "08:30").strftime("%H:%M"), expected, day)
        self.assertEqual(u.et_to_utc(date(2026, 12, 9), "14:00").hour, 19)  # FOMC statement in winter
        self.assertEqual(u.et_to_utc(date(2026, 6, 17), "14:00").hour, 18)  # and in summer
        with self.assertRaises(ValueError):
            u.et_to_utc(date(2006, 1, 1), "08:30")


class CalendarLogicTests(unittest.TestCase):
    def setUp(self):
        self.cal = calendar(("NFP", "2026-12-04"))  # 13:30 UTC, window 13:00 to 14:30

    def test_window_boundaries_are_inclusive_and_outside_is_clear(self):
        at = datetime(2026, 12, 4, 13, 30, tzinfo=UTC)
        self.assertIsNone(self.cal.active(at - timedelta(minutes=31)))
        self.assertIsNotNone(self.cal.active(at - timedelta(minutes=30)))
        self.assertIsNotNone(self.cal.active(at + timedelta(minutes=60)))
        self.assertIsNone(self.cal.active(at + timedelta(minutes=61)))
        with self.assertRaises(ValueError):
            self.cal.active(datetime(2026, 12, 4, 13, 30))

    def test_halt_reason_is_specific_and_strict_mode_catches_an_expired_calendar(self):
        inside = datetime(2026, 12, 4, 13, 40, tzinfo=UTC)
        self.assertEqual(self.cal.halt_reason(inside), "Scheduled US announcement: NFP at 13:30 UTC")
        later = datetime(2030, 1, 1, tzinfo=UTC)
        self.assertIsNone(self.cal.halt_reason(later))                      # replay or analysis: no halt
        self.assertIn("missing or expired", self.cal.halt_reason(later, strict=True) or "")

    def test_coverage_statuses_warn_before_the_list_runs_out(self):
        cal = calendar(("NFP", "2026-12-04"), ("CPI", "2027-06-10"), ("PPI", "2026-11-01"))
        now = datetime(2026, 11, 18, tzinfo=UTC)
        status = {k: v["status"] for k, v in cal.coverage(now).items()}
        self.assertEqual(status, {"NFP": "expires_soon", "CPI": "ok", "PPI": "expired", "FOMC": "empty"})
        self.assertFalse(cal.covered(now))  # FOMC missing: not fully covered

    def test_upcoming_lists_future_events_in_order(self):
        cal = calendar(("NFP", "2026-12-04"), ("CPI", "2026-12-10"), ("NFP", "2026-11-06"))
        names = [e.kind + e.at.strftime("%m%d") for e in cal.upcoming(datetime(2026, 11, 18, tzinfo=UTC))]
        self.assertEqual(names, ["NFP1204", "CPI1210"])


class ValidationTests(unittest.TestCase):
    def test_malformed_files_are_refused(self):
        good = {"kind": "NFP", "date": "2026-12-04", "time_et": "08:30"}
        for bad in ({"schema": 2, "retrieved_on": "2026-11-18", "events": []},
                    doc([{**good, "kind": "GDP"}]), doc([{**good, "time_et": "8h30"}]),
                    doc([{**good, "date": "2026-13-40"}]), doc([good, good]),
                    doc([good], windows={"NFP": {"before": -1, "after": 60}}),
                    doc([good], windows={"NFP": {"before": 30, "after": 5000}}),
                    {"schema": 1, "events": []}, "not a dict"):
            with self.assertRaises(ValueError):
                u.parse(bad)

    def test_shipped_calendar_is_valid_and_covers_the_announced_horizon(self):
        cal = u.load()
        kinds = {e.kind for e in cal.events}
        self.assertEqual(kinds, set(u.KINDS))
        self.assertGreaterEqual(len(cal.events), 90)
        self.assertEqual(list(cal.events), sorted(cal.events, key=lambda e: e.at))
        nfp = next(e for e in cal.events if e.kind == "NFP" and e.at.date() == date(2026, 12, 4))
        self.assertEqual(nfp.at, datetime(2026, 12, 4, 13, 30, tzinfo=UTC))
        fomc = next(e for e in cal.events if e.kind == "FOMC" and e.at.date() == date(2026, 12, 9))
        self.assertEqual((fomc.at.hour, fomc.before_minutes, fomc.after_minutes), (19, 30, 90))
        self.assertTrue(cal.covered(datetime(2027, 6, 1, tzinfo=UTC)))
        self.assertTrue(all(s.startswith("https://") for s in cal.sources.values()))


class RefreshTests(unittest.TestCase):
    def test_bls_calendar_is_parsed_with_folded_lines_and_only_eastern_times(self):
        events, ignored = refresh.parse_bls_ics(OFFICIAL_ICS)
        self.assertEqual(sorted((e["kind"], e["date"], e["time_et"]) for e in events),
                         [("CPI", "2026-12-10", "08:30"), ("NFP", "2026-01-09", "08:30"), ("PPI", "2026-12-15", "08:30")])
        self.assertEqual(ignored, 1)  # a non-Eastern zone is never guessed
        with self.assertRaises(ValueError):
            refresh.parse_bls_ics("BEGIN:VCALENDAR\nEND:VCALENDAR")

    def test_fed_page_gives_decision_days_and_skips_unscheduled_rows_and_old_years(self):
        events = refresh.parse_fed_calendar(FED_PAGE, since_year=2026)
        self.assertEqual([e["date"] for e in events], ["2026-10-28", "2026-12-09", "2027-01-27", "2028-01-26"])
        self.assertTrue(all(e["time_et"] == "14:00" and e["kind"] == "FOMC" for e in events))
        self.assertEqual(len(refresh.parse_fed_calendar(FED_PAGE)), 5)  # 2019 kept without a floor
        with self.assertRaises(ValueError):
            refresh.parse_fed_calendar("<html>layout changed</html>")

    def test_merge_replaces_only_from_the_earliest_new_date_and_validates(self):
        base = doc([{"kind": "NFP", "date": d, "time_et": "08:30"} for d in ("2026-01-09", "2026-12-04", "2027-01-08")])
        updated, summary = refresh.merge(base, [{"kind": "NFP", "date": "2026-12-05", "time_et": "08:30"}])
        self.assertEqual([e["date"] for e in updated["events"]], ["2026-01-09", "2026-12-04", "2026-12-05"])
        self.assertEqual(summary["NFP"], {"replaced_from": "2026-12-05", "removed": 1, "added": 1})
        later, _ = refresh.merge(base, [{"kind": "NFP", "date": "2026-12-03", "time_et": "08:30"}])
        self.assertEqual([e["date"] for e in later["events"]], ["2026-01-09", "2026-12-03"])  # 12-04 and later replaced
        self.assertEqual(len(base["events"]), 3)  # input untouched
        with self.assertRaises(ValueError):
            refresh.merge(base, [{"kind": "NFP", "date": "bad", "time_et": "08:30"}])

    def test_save_is_validated_and_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "us.json"
            refresh.save(path, doc([{"kind": "NFP", "date": "2026-12-04", "time_et": "08:30"}]))
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["events"]), 1)
            with self.assertRaises(ValueError):
                refresh.save(path, {"schema": 9})
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["events"]), 1)  # untouched
            self.assertEqual([p.name for p in Path(folder).iterdir()], ["us.json"])  # no temp file left

    def test_fed_fetch_checks_status_and_size(self):
        class Response:
            def __init__(self, status, body): self.status, self.body = status, body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return self.body[:n]
        self.assertEqual(refresh.fetch_fed_page(lambda r, timeout: Response(200, b"<p>ok</p>")), "<p>ok</p>")
        with self.assertRaises(ValueError):
            refresh.fetch_fed_page(lambda r, timeout: Response(403, b""))
        with self.assertRaises(ValueError):
            refresh.fetch_fed_page(lambda r, timeout: Response(200, b"x" * 2_000_001))


class DecisionIntegrationTests(unittest.TestCase):
    def test_snapshot_halt_reason_reaches_the_director_and_the_risk_check(self):
        now = datetime(2026, 12, 4, 13, 40, tzinfo=UTC)
        reason = "Scheduled US announcement: NFP at 13:30 UTC"
        quote = Snapshot("c", "XAUUSD", 2000, 2000.1, now, critical_event=True, halt_reason=reason)
        signal = Director().decide(quote, [], at=now)
        self.assertEqual((signal.action, signal.rationale), (Action.WAIT, reason))
        valid = Signal("s", "c", "XAUUSD", Action.BUY, now, now + timedelta(minutes=1), "x", "1", "t",
                       2000.1, 1999.1, 2002, status="validated")
        state = RiskState(10000, 10000, killed=False, broker_connected=True, demo_account=True)
        instrument = Instrument(.01, 1, .01, 10, .01, 7, 2)
        self.assertEqual(check_risk(valid, quote, instrument, state, Limits(), now).reason, reason)
        clear = Snapshot("c", "XAUUSD", 2000, 2000.1, now)
        self.assertTrue(check_risk(valid, clear, instrument, state, Limits(), now).approved)
        # defence in depth: the executor can pass the calendar verdict on its own
        rejected = check_risk(valid, clear, instrument, state, Limits(), now, announcement_halt=reason)
        self.assertFalse(rejected.approved)
        self.assertEqual(rejected.reason, reason)

    def test_analyze_records_the_blackout_and_stays_wait(self):
        at = datetime(2026, 12, 4, 13, 40, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as folder:
            store = ResearchStore(str(Path(folder) / "t.db"))
            result = analyze(store, symbol="XAUUSD", broker="demo", bid=2000, ask=2000.1,
                             closed_prices=[2000 + i for i in range(60)], critical_event=True, observed_at=at,
                             halt_reason="Scheduled US announcement: NFP at 13:30 UTC")
            self.assertEqual(result["signal"].action, Action.WAIT)
            self.assertIn("NFP", result["signal"].rationale)
            kinds = [e["kind"] for e in store.journal.events(20)]
            self.assertIn("announcement.blackout", kinds)
            self.assertTrue(store.journal.verify_audit())


class CommandTests(unittest.TestCase):
    def run_cli(self, *argv):
        from trading_pro import cli
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["cli", *argv]), \
                mock.patch("trading_pro.local_env.load_local_env", return_value=()), \
                contextlib.redirect_stdout(out):
            cli.main()
        return json.loads(out.getvalue())

    def test_us_events_command_reports_blackout_and_rejects_naive_time(self):
        report = self.run_cli("us-events", "--at", "2026-12-04T13:45:00+00:00", "--limit", "2")
        self.assertEqual(report["blackout"]["kind"], "NFP")
        self.assertEqual(len(report["upcoming"]), 2)
        clear = self.run_cli("us-events", "--at", "2026-12-04T16:00:00+00:00")
        self.assertIsNone(clear["blackout"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli("us-events", "--at", "2026-12-04T13:45:00")

    def test_refresh_dry_run_never_writes_and_needs_a_source(self):
        before = u.DEFAULT_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            ics = Path(folder) / "bls.ics"
            ics.write_text(OFFICIAL_ICS.replace("20261210", "20261211"), encoding="utf-8")
            report = self.run_cli("refresh-us-events", "--bls-ics", str(ics), "--dry-run")
        self.assertFalse(report["written"])
        self.assertIn("CPI", report["changes"])
        self.assertEqual(u.DEFAULT_PATH.read_bytes(), before)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli("refresh-us-events")


if __name__ == "__main__":
    unittest.main()
