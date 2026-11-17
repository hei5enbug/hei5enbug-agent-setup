"""Totals over time entries."""

from __future__ import annotations

from typing import Any, Iterable


def project_totals(entries: Iterable[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for entry in entries:
        totals[entry["project"]] = totals.get(entry["project"], 0) + entry["minutes"]
    return dict(sorted(totals.items()))
