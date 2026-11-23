"""Compare the week labels of shop/dates.py with the reporting database (SQLite) over 2020 to 2030."""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shop.dates import week_label  # noqa: E402

DATABASE_LABEL = "strftime('%Y', ?) || '-W' || printf('%02d', (strftime('%j', ?) + 6 - strftime('%w', ?)) / 7)"
FIRST, LAST = date(2020, 1, 1), date(2030, 12, 31)


def main() -> int:
    connection = sqlite3.connect(":memory:")
    day, mismatches = FIRST, []
    while day <= LAST:
        text = day.isoformat()
        expected = connection.execute(f"select {DATABASE_LABEL}", (text, text, text)).fetchone()[0]
        if week_label(day) != expected:
            mismatches.append((text, week_label(day), expected))
        day += timedelta(days=1)
    for text, ours, expected in mismatches[:5]:
        print(f"{text}: code gives {ours}, database gives {expected}")
    print(f"engine check: {'FAILED' if mismatches else 'ok'}, {len(mismatches)} mismatches")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
