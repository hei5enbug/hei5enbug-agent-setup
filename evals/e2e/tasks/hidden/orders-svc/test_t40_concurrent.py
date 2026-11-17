import sqlite3
import threading

import pytest

from helpers_orders import rows, seeded_db

CSV = (
    "order_id,customer_id,placed_at,sku,unit_price_cents,quantity\n"
    "ord-1001,c-1,2026-02-01T10:00:00,tea,450,2\n"
    "ord-1002,c-2,2026-02-02T11:00:00,mug,1200,1\n"
    "ord-1003,c-1,2026-02-03T12:00:00,tea,450,1\n"
)
WAIT_SECONDS = 1.5


def make_barrier_classes(barrier):
    """Connection and cursor classes that hold a thread right after each SELECT until the other thread has run one too, so
    two runs that check before they insert are forced to check at the same moment. A run that cannot reach its SELECT
    while the other one waits, such as one that takes a write lock first, lets the wait time out and goes on."""
    def pause(sql):
        if sql.lstrip().upper().startswith(("SELECT", "WITH")):
            try:
                barrier.wait(timeout=WAIT_SECONDS)
            except threading.BrokenBarrierError:
                pass

    class Cursor(sqlite3.Cursor):
        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            pause(sql)
            return result

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args):
            cursor = self.cursor()
            cursor.execute(sql, *args)
            return cursor

        def cursor(self, factory=Cursor):
            return super().cursor(factory)

    return Connection


def test_two_imports_at_the_same_time_leave_one_copy_of_each_order(tmp_path, monkeypatch):
    from orders.cli import main

    db, source = seeded_db(tmp_path / "orders.db"), tmp_path / "orders.csv"
    source.write_text(CSV, encoding="utf-8")
    monkeypatch.setenv("ORDERS_DB", str(db))
    barrier, real_connect = threading.Barrier(2), sqlite3.connect
    factory = make_barrier_classes(barrier)
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: real_connect(*args, **{**kwargs, "factory": factory}))
    results, errors = [], []

    def run():
        import io
        try:
            results.append(main(["import", str(source)], stdout=io.StringIO(), stderr=io.StringIO()))
        except BaseException as exc:  # a crash must fail the test with its cause
            errors.append(repr(exc))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == [] and results == [0, 0]
    assert rows(db, "SELECT COUNT(*), COUNT(DISTINCT order_id) FROM orders") == [(3, 3)]
    assert rows(db, "SELECT COUNT(*) FROM lines") == [(3,)]
