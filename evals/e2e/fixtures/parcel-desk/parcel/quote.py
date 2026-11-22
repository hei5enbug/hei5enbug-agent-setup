"""Build the quote of one parcel."""

from __future__ import annotations

from .models import Parcel, Quote
from .rates import base_fee_cents, billable_grams
from .surcharges import fuel_surcharge_cents, insurance_cents


def build_quote(parcel: Parcel) -> Quote:
    base = base_fee_cents(parcel.weight_grams, parcel.zone)
    return Quote(
        billed_grams=billable_grams(parcel.weight_grams),
        base_cents=base,
        fuel_cents=fuel_surcharge_cents(base),
        insurance_cents=insurance_cents(parcel.declared_value_cents),
    )
