from helpers_orders import run_cli, seeded_db

ORDERS = (
    ("ord-0001", "c-1", "placed", "2026-03-03T08:00:00", 0, [("tea", 450, 1)]),
    ("ord-0002", "c-1", "placed", "2026-01-01T08:00:00", 0, [("tea", 450, 1)]),
    ("ord-0003", "c-2", "cancelled", "2026-02-02T08:00:00", 0, [("tea", 450, 1)]),
    ("ord-0004", "c-2", "placed", "2026-01-15T08:00:00", 0, [("tea", 450, 1)]),
    ("ord-0005", "c-1", "placed", "2026-04-04T08:00:00", 0, [("tea", 450, 1)]),
)


def oldest(tmp_path, count):
    db = seeded_db(tmp_path / "orders.db", ORDERS)
    result = run_cli("oldest", str(count), db=db)
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


def test_oldest_prints_the_oldest_open_orders_oldest_first(tmp_path):
    assert oldest(tmp_path, 2) == ["ord-0002", "ord-0004"]


def test_oldest_leaves_out_orders_that_are_not_open_and_stops_at_the_last_one(tmp_path):
    assert oldest(tmp_path, 10) == ["ord-0002", "ord-0004", "ord-0001", "ord-0005"]
