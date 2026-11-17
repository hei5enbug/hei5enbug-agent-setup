"""CSV export of time entries."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

FILE_NAME = "export.csv"
COLUMNS = ("id", "date", "project", "minutes")


def export_entries(entries: Iterable[dict[str, Any]], folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / FILE_NAME
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({column: entry[column] for column in COLUMNS} for entry in entries)
    return target
