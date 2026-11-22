"""Mailing labels."""

from __future__ import annotations

import os

from .customers import lookup_customer


def mailing_label(path: str | os.PathLike[str], customer_id: int) -> str:
    customer = lookup_customer(path, customer_id)
    return f"{customer['name']} (customer {customer['id']})"
