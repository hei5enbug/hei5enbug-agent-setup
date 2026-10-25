"""Argument validation shared by the services and the CLI."""

from __future__ import annotations

import re

from .errors import ValidationError

SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
MAX_QUANTITY = 1_000_000


def validate_sku(sku: str) -> str:
    cleaned = sku.strip().upper()
    if not SKU_PATTERN.match(cleaned):
        raise ValidationError(f"invalid SKU: {sku!r}")
    return cleaned


def validate_warehouse_code(code: str) -> str:
    cleaned = code.strip().upper()
    if not CODE_PATTERN.match(cleaned):
        raise ValidationError(f"invalid warehouse code: {code!r}")
    return cleaned


def validate_quantity(quantity: int, *, allow_zero: bool = False) -> int:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValidationError(f"quantity must be an integer: {quantity!r}")
    minimum = 0 if allow_zero else 1
    if quantity < minimum or quantity > MAX_QUANTITY:
        raise ValidationError(f"quantity must be between {minimum} and {MAX_QUANTITY}: {quantity}")
    return quantity


def validate_name(name: str, *, field: str = "name") -> str:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > 80:
        raise ValidationError(f"{field} must be 1-80 characters")
    return cleaned
