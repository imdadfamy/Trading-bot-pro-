"""Produce deterministic synthetic OHLC CSV strictly for software tests."""
import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main():
    path = Path(__file__).resolve().parents[1] / "examples" / "synthetic_xauusd.csv"
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["symbol", "opened_at", "closed_at", "open", "high", "low", "close", "bid", "ask", "broker", "tick_volume"])
        start = datetime(2025, 1, 6, 8, tzinfo=timezone.utc)
        last = 2000
        for i in range(240):
            opened = start + timedelta(minutes=5*i)
            closed = opened + timedelta(minutes=5)
            price = 2000 + 6*math.sin(i/9) + .02*i
            writer.writerow(["XAUUSD", opened.isoformat(), closed.isoformat(), round(last, 4),
                             round(max(last, price)+1, 4), round(min(last, price)-1, 4), round(price, 4),
                             round(price-.1, 4), round(price+.1, 4), "SYNTHETIC-NOT-A-BROKER", 10+i%7])
            last = price
    print(path)


if __name__ == "__main__":
    main()
