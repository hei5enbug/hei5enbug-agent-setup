"""Day and week labels."""

from __future__ import annotations

from datetime import date


def week_label(day: date) -> str:
    return day.strftime("%Y-W%W")
