from helpers_orders import rows, run_cli, seeded_db

CSV = (
    "order_id,customer_id,placed_at,sku,unit_price_cents,quantity\n"
    "ord-1001,c-1,2026-02-01T10:00:00,tea,450,2\n"
    "ord-1002,c-2,2026-02-02T11:00:00,mug,1200,1\n"
    "ord-1003,c-1,2026-02-03T12:00:00,tea,450,1\n"
)


def stored(db):
    return (rows(db, "SELECT order_id, customer_id, status, placed_at FROM orders ORDER BY order_id"),
            rows(db, "SELECT order_id, sku, unit_price_cents, quantity FROM lines ORDER BY order_id"))


def test_import_stores_each_row_as_a_placed_order_with_its_line(tmp_path):
    db, source = seeded_db(tmp_path / "orders.db"), tmp_path / "orders.csv"
    source.write_text(CSV, encoding="utf-8")

    result = run_cli("import", str(source), db=db)

    assert result.returncode == 0, result.stderr
    assert stored(db) == ([("ord-1001", "c-1", "placed", "2026-02-01T10:00:00"),
                           ("ord-1002", "c-2", "placed", "2026-02-02T11:00:00"),
                           ("ord-1003", "c-1", "placed", "2026-02-03T12:00:00")],
                          [("ord-1001", "tea", 450, 2), ("ord-1002", "mug", 1200, 1), ("ord-1003", "tea", 450, 1)])


def test_importing_the_same_file_twice_leaves_the_result_of_the_first_run(tmp_path):
    db, source = seeded_db(tmp_path / "orders.db"), tmp_path / "orders.csv"
    source.write_text(CSV, encoding="utf-8")
    assert run_cli("import", str(source), db=db).returncode == 0
    first = stored(db)

    second = run_cli("import", str(source), db=db)

    assert second.returncode == 0, second.stderr
    assert stored(db) == first
