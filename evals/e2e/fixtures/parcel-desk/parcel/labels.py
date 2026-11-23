"""Plain-text label and quote rendering."""

from __future__ import annotations

from .models import Parcel, Quote
from .rates import billable_grams


def format_cents(cents: int) -> str:
    return f"{cents // 100:,}.{cents % 100:02d}"


def format_label(parcel: Parcel) -> str:
    billed = billable_grams(parcel.weight_grams)
    return "\n".join([f"Zone {parcel.zone}", f"Weight: {parcel.weight_grams} g (billed as {billed} g)"])


def format_quote(quote: Quote) -> str:
    return "\n".join([
        f"Base: {format_cents(quote.base_cents)}",
        f"Fuel: {format_cents(quote.fuel_cents)}",
        f"Insurance: {format_cents(quote.insurance_cents)}",
        f"Total: {format_cents(quote.total_cents)}",
    ])
