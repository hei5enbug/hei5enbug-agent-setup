"""Date parsing shared by every command that takes a date."""

from __future__ import annotations

from datetime import date


class DateError(ValueError):
    """The text is not a date in YYYY-MM-DD form."""


def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise DateError(f"expected YYYY-MM-DD, got {text!r}") from exc
