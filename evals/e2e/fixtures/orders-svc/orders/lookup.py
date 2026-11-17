"""Customer lookup and the snapshot file of customers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def find_customer(conn: sqlite3.Connection, customer_id: str) -> tuple[str, str] | None:
    """The (name, tier) of a customer, or None when the customer is unknown."""
    row = conn.execute("SELECT name, tier FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
    return None if row is None else (row["name"], row["tier"])


def save_snapshot(conn: sqlite3.Connection, path: str | Path) -> None:
    """Write every customer as `{"<id>": ["<name>", "<tier>"]}`."""
    ids = [row["customer_id"] for row in conn.execute("SELECT customer_id FROM customers ORDER BY customer_id")]
    Path(path).write_text(json.dumps({cid: list(find_customer(conn, cid)) for cid in ids}, indent=2), encoding="utf-8")


def load_snapshot(path: str | Path) -> dict[str, tuple[str, str]]:
    """The customers of a snapshot file, each as `find_customer` returns it."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {cid: (name, tier) for cid, (name, tier) in raw.items()}
