"""Text for money."""

from __future__ import annotations


def format_cents(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"
