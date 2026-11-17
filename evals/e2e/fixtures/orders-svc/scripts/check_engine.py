"""Compare the SQL day formatting with `orders.dates.format_day` on the real SQLite engine."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orders import dates  # noqa: E402

SAMPLES = ("2026-01-15T09:00:00", "2026-12-31T23:59:59", "2024-02-29T00:00:00", "2026-07-04T00:00:01")


def main() -> int:
    conn = sqlite3.connect(":memory:")
    mismatches = []
    for sample in SAMPLES:
        engine = conn.execute(f"SELECT {dates.day_expression('?')}", (sample,)).fetchone()[0]
        python = dates.format_day(sample)
        if engine != python:
            mismatches.append(f"{sample}: engine {engine!r}, python {python!r}")
    print("engine check: " + ("ok" if not mismatches else "; ".join(mismatches)))
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
