"""Cents formatting."""

from __future__ import annotations


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"
