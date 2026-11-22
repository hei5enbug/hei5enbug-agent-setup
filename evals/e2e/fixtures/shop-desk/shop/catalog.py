"""The price list."""

from __future__ import annotations

from .errors import UnknownSku

PRICES = {"AB-100": 1250, "CD-200": 799, "EF-300": 4999}


def price_cents(sku: str) -> int:
    try:
        return PRICES[sku]
    except KeyError:
        raise UnknownSku(sku) from None
