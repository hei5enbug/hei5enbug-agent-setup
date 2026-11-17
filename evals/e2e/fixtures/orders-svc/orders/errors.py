"""Errors this package raises on purpose."""


class OrdersError(Exception):
    """Base class of the errors this package raises on purpose."""


class OrderRejected(OrdersError):
    """An order or a change to it breaks a rule."""


class UnknownOrder(OrdersError):
    """No order has this id."""


class UnknownCustomer(OrdersError):
    """No customer has this id."""
