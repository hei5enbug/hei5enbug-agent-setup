"""Errors this package raises on purpose."""


class ShopError(Exception):
    """Base class of the errors this package raises on purpose."""


class InvalidQuantity(ShopError, ValueError):
    """A line quantity is not a whole number of at least 1."""


class QuantityLimitError(ShopError, ValueError):
    """A line quantity is above the limit."""


class InvalidItem(ShopError, ValueError):
    """An item argument is not written as UNIT_PRICE_CENTSxQUANTITY."""
