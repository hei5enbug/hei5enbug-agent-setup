"""Day text for order dates. Stored timestamps look like 2026-01-15T09:00:00."""

from __future__ import annotations

SQL_DAY = "strftime('%Y-%m-%d', {column})"


def day_expression(column: str) -> str:
    """The SQL that formats a timestamp column as day text."""
    return SQL_DAY.format(column=column)


def format_day(value: str) -> str:
    """The same day text for a timestamp already read into Python."""
    return value[:10]
