"""Whole-cent arithmetic and text for money."""

from __future__ import annotations


def percent_of(amount: int, percent: int) -> int:
    """A whole percentage of an amount, rounded down to whole cents."""
    return amount * percent // 100


def format_cents(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"
