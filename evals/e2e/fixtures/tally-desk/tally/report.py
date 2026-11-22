"""Hours per team."""

from __future__ import annotations

from typing import Any, Iterable


def team_hours(entries: Iterable[dict[str, Any]]) -> dict[str, float]:
    """Total hours per team over the given entries, sorted by team name."""
    totals: dict[str, float] = {}
    for entry in entries:
        totals[entry["team"]] = totals.get(entry["team"], 0.0) + float(entry["hours"])
    return dict(sorted(totals.items()))


def format_row(team: str, hours: float) -> str:
    return f"{team} {hours:.1f}"
