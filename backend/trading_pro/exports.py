"""Safe local CSV export of recorded research signals."""
import csv
import io
from .store import ResearchStore

SIGNAL_COLUMNS = ("signal_id", "cycle_id", "symbol", "action", "created_at",
                  "expires_at", "strategy", "strategy_version", "status", "session", "rationale")


def _cell(value):
    text = "" if value is None else str(value)
    # Spreadsheet formula injection: preserve the literal value as text.
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def signals_csv(store: ResearchStore) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(SIGNAL_COLUMNS)
    for signal in reversed([__import__("json").loads(row["payload"]) for row in store.recent("signals", 500)]):
        writer.writerow([_cell(signal.get(key)) for key in SIGNAL_COLUMNS])
    return stream.getvalue().encode("utf-8-sig")
