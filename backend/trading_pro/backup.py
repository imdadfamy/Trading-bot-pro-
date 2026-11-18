"""Consistent SQLite local backup and non-destructive restore verification."""
from __future__ import annotations
import sqlite3
from contextlib import closing
from pathlib import Path
from .journal import Journal


def backup_database(source: str, destination: str) -> dict:
    src, dest = Path(source).resolve(), Path(destination).resolve()
    if src == dest or not src.is_file():
        raise ValueError("Existing source and distinct destination required")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(src))) as origin, closing(sqlite3.connect(str(dest))) as target:
        origin.backup(target)
    result = verify_backup(str(dest))
    if not result["valid"]:
        raise RuntimeError("Backup integrity verification failed")
    return {"path": str(dest), **result}


def verify_backup(path: str) -> dict:
    target = Path(path)
    if not target.is_file():
        raise ValueError("Backup not found")
    with closing(sqlite3.connect(str(target))) as db:
        db.row_factory = sqlite3.Row
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        audit_rows = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        prior = "0" * 64
        audit_valid = True
        for row in db.execute("SELECT audit.*,audit_integrity.previous_hash,audit_integrity.digest "
                              "FROM audit LEFT JOIN audit_integrity USING(seq) ORDER BY audit.seq"):
            if row["previous_hash"] != prior or row["digest"] != Journal._digest(prior, row):
                audit_valid = False
                break
            prior = row["digest"]
    return {"valid": integrity == "ok" and audit_valid,
            "sqlite_integrity": integrity, "audit_integrity": audit_valid,
            "audit_rows": audit_rows}
