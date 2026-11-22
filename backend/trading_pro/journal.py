"""Append-only SQLite audit trail and durable order intent ledger."""
import json
import sqlite3
from hashlib import sha256
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Journal:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS audit (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                  kind TEXT NOT NULL, correlation_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit_integrity (
                  seq INTEGER PRIMARY KEY, previous_hash TEXT NOT NULL,
                  digest TEXT NOT NULL, FOREIGN KEY(seq) REFERENCES audit(seq));
                CREATE TABLE IF NOT EXISTS intents (
                  signal_id TEXT PRIMARY KEY, at TEXT NOT NULL, state TEXT NOT NULL,
                  broker_ticket TEXT, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (
                  version INTEGER PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
            """)
            # Backfill local prototype rows created before integrity chaining.
            prior = "0" * 64
            for row in db.execute("SELECT seq,at,kind,correlation_id,payload FROM audit ORDER BY seq"):
                digest = self._digest(prior, row)
                db.execute("INSERT OR IGNORE INTO audit_integrity VALUES(?,?,?)", (row["seq"], prior, digest))
                prior = digest

    @staticmethod
    def _digest(prior, row):
        data = json.dumps([prior, row["seq"], row["at"], row["kind"],
                           row["correlation_id"], row["payload"]], separators=(",", ":"))
        return sha256(data.encode("utf-8")).hexdigest()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def log(self, kind, correlation_id, payload):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT digest FROM audit_integrity ORDER BY seq DESC LIMIT 1").fetchone()
            prior = previous[0] if previous else "0" * 64
            cursor = db.execute("INSERT INTO audit(at,kind,correlation_id,payload) VALUES(?,?,?,?)",
                                (datetime.now(timezone.utc).isoformat(), kind, correlation_id,
                                 json.dumps(payload, default=str)))
            row = db.execute("SELECT * FROM audit WHERE seq=?", (cursor.lastrowid,)).fetchone()
            db.execute("INSERT INTO audit_integrity VALUES(?,?,?)", (row["seq"], prior, self._digest(prior, row)))

    def verify_audit(self) -> bool:
        with self.connect() as db:
            prior = "0" * 64
            for row in db.execute("SELECT audit.*, audit_integrity.previous_hash, audit_integrity.digest "
                                  "FROM audit LEFT JOIN audit_integrity USING(seq) ORDER BY audit.seq"):
                if row["previous_hash"] != prior or row["digest"] != self._digest(prior, row):
                    return False
                prior = row["digest"]
            return True

    def reserve(self, signal_id, detail):
        """Atomic idempotency reservation; uncertain sends remain reserved until reconciliation."""
        with self.connect() as db:
            cur = db.execute("INSERT OR IGNORE INTO intents VALUES(?,?,?,?,?)",
                             (signal_id, datetime.now(timezone.utc).isoformat(), "reserved", None, json.dumps(detail)))
            return cur.rowcount == 1

    def transition_intent(self, signal_id, expected_states, state, *, ticket=None, detail=""):
        """A stale worker cannot overwrite a newer broker observation."""
        allowed = {
            "reserved": {"preflight_rejected", "sending"},
            # preflight_rejected from sending: the last check before order_send failed, so nothing was sent
            "sending": {"uncertain", "accepted", "partial", "rejected", "simulated", "preflight_rejected"},
            "uncertain": {"deals_observed", "order_observed"},
            "accepted": {"deals_observed", "order_observed", "uncertain"},
            "partial": {"deals_observed", "order_observed", "uncertain"},
            "order_observed": {"deals_observed", "uncertain"},
        }
        expected_states = set(expected_states)
        if not expected_states or any(state not in allowed.get(previous, set()) for previous in expected_states):
            raise ValueError("Invalid order intent transition")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,broker_ticket FROM intents WHERE signal_id=?", (signal_id,)).fetchone()
            if row is None or row["state"] not in expected_states:
                raise RuntimeError("Intent state changed or does not exist")
            existing = row["broker_ticket"]
            if existing is not None and ticket is not None and existing != str(ticket):
                raise RuntimeError("Broker ticket mismatch")
            db.execute("UPDATE intents SET state=?, broker_ticket=?, detail=? WHERE signal_id=?",
                       (state, str(ticket) if ticket is not None else existing, detail, signal_id))

    def pending_intents(self, limit=100):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM intents WHERE state IN ('reserved','sending','uncertain','accepted','partial','order_observed') "
                "ORDER BY at LIMIT ?", (min(max(limit, 0), 500),))]

    def intent(self, signal_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM intents WHERE signal_id=?", (signal_id,)).fetchone()
            return dict(row) if row else None

    def events(self, limit=100):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (min(limit, 500),))]
