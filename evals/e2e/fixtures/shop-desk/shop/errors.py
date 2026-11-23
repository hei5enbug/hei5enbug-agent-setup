"""Exception hierarchy. Every error raised on purpose for a user mistake derives from ShopError."""

from __future__ import annotations


class ShopError(Exception):
    """Base class for errors that are reported to the user without a traceback."""


class ValidationError(ShopError, ValueError):
    """An argument failed validation."""


class UnknownSku(ShopError):
    def __init__(self, sku: str) -> None:
        super().__init__(f"unknown SKU: {sku}")
        self.sku = sku


class UnknownCustomer(ShopError):
    def __init__(self, customer_id: int) -> None:
        super().__init__(f"unknown customer: {customer_id}")
        self.customer_id = customer_id
