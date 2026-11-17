"""Text for the party an invoice is billed to."""

from __future__ import annotations

import sqlite3

from .errors import UnknownCustomer
from .lookup import find_customer


def bill_to(conn: sqlite3.Connection, customer_id: str) -> str:
    found = find_customer(conn, customer_id)
    if found is None:
        raise UnknownCustomer(f"unknown customer {customer_id}")
    name, tier = found
    return f"{name} ({tier})"
