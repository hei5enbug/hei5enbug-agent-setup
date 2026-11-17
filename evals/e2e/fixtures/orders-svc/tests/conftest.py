import pytest

from orders import db
from orders.service import OrderService


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDERS_DB", str(tmp_path / "orders.db"))
    connection = db.connect()
    with connection:
        connection.executemany("INSERT INTO customers VALUES (?, ?, ?)",
                               [("c-1", "Ada Lovelace", "gold"), ("c-2", "Alan Turing", "silver")])
    return connection


@pytest.fixture()
def service(conn):
    return OrderService(conn, now=lambda: "2026-01-15T09:00:00")
