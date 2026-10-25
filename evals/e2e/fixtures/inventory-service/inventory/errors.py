"""Exception hierarchy. Every error the service raises on purpose derives from InventoryError."""

from __future__ import annotations


class InventoryError(Exception):
    """Base class for errors that are reported to the user without a traceback."""


class ValidationError(InventoryError, ValueError):
    """An argument failed validation before any state changed."""


class ConfigError(InventoryError):
    """An environment variable holds a value the service cannot use."""


class UnknownItem(InventoryError):
    def __init__(self, sku: str) -> None:
        super().__init__(f"unknown item: {sku}")
        self.sku = sku


class UnknownWarehouse(InventoryError):
    def __init__(self, code: str) -> None:
        super().__init__(f"unknown warehouse: {code}")
        self.code = code


class UnknownOrder(InventoryError):
    def __init__(self, order_id: int) -> None:
        super().__init__(f"unknown order: {order_id}")
        self.order_id = order_id


class InsufficientStock(InventoryError):
    def __init__(self, sku: str, requested: int, available: int) -> None:
        super().__init__(f"insufficient stock for {sku}: requested {requested}, available {available}")
        self.sku = sku
        self.requested = requested
        self.available = available


class InvalidOrderState(InventoryError):
    def __init__(self, order_id: int, status: str, action: str) -> None:
        super().__init__(f"order {order_id} is {status} and cannot be {action}")
        self.order_id = order_id
        self.status = status
        self.action = action


class StorageError(InventoryError):
    """The data file could not be read or written."""
