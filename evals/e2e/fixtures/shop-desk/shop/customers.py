"""Customer lookup."""

from __future__ import annotations

import os

from . import store
from .errors import UnknownCustomer


def lookup_customer(path: str | os.PathLike[str], customer_id: int) -> dict:
    raw = store.load(path)["customers"].get(str(customer_id))
    if raw is None:
        raise UnknownCustomer(customer_id)
    return {"id": customer_id, "name": raw["name"], "tier": raw["tier"]}
