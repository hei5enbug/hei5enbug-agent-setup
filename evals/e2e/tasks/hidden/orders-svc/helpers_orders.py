"""Helpers of the hidden tests of the orders-svc tasks. They use only the commands and tables the fixture defines."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CUSTOMERS = (("c-1", "Ada Lovelace", "gold"), ("c-2", "Alan Turing", "silver"))
SETTINGS = "[orders]\nmax_lines = 20\n\n[discounts]\nmax_percent = 30\n{extra}"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def seeded_db(path, orders=()):
    """A database with the repository's schema, two customers, and `orders` rows of
    (order_id, customer_id, status, placed_at, discount_cents, [(sku, unit_price_cents, quantity), ...])."""
    from orders import db

    conn = db.connect(path)
    with conn:
        conn.executemany("INSERT INTO customers VALUES (?, ?, ?)", CUSTOMERS)
        for order_id, customer_id, status, placed_at, discount, lines in orders:
            conn.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", (order_id, customer_id, status, placed_at, discount))
            conn.executemany("INSERT INTO lines VALUES (?, ?, ?, ?)", [(order_id, *line) for line in lines])
    conn.close()
    return Path(path)


def environment(db_path, **extra):
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env.update({"ORDERS_DB": str(db_path), "PYTHONDONTWRITEBYTECODE": "1"}, **extra)
    return env


def run_cli(*args, db, cwd=REPO, **extra):
    """Run `python3 -m orders ARGS` against the database `db`; `extra` are more environment variables."""
    return subprocess.run([sys.executable, "-m", "orders", *args], cwd=cwd, env=environment(db, **extra),
                          capture_output=True, text=True, timeout=120)


def rows(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()
