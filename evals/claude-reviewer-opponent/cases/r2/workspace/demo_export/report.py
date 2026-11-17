"""Report export. `export_report` is the public entry point of the package."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping

COLUMNS = ("id", "name", "total")


def render_csv(rows: Iterable[Mapping[str, object]]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([row[column] for column in COLUMNS])
    return out.getvalue().encode("utf-8")


def export_report(rows: Iterable[Mapping[str, object]], *, fmt: str = "csv") -> bytes:
    if fmt != "csv":
        raise ValueError(f"unsupported format: {fmt}")
    return render_csv(rows)
