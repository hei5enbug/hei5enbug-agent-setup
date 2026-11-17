import pytest

from helpers_orders import rows, run_cli, seeded_db

ORDERS = (
    ("ord-0001", "c-1", "shipped", "2026-01-15T09:00:00", 0, [("tea", 1000, 1)]),
    ("ord-0002", "c-1", "cancelled", "2026-01-16T09:00:00", 0, [("tea", 1000, 1)]),
    ("ord-0003", "c-1", "placed", "2026-01-17T09:00:00", 0, [("tea", 1000, 1)]),
)


def lines(db, order_id):
    return rows(db, "SELECT sku, unit_price_cents, quantity FROM lines WHERE order_id = ? ORDER BY rowid", (order_id,))


@pytest.mark.parametrize("order_id", ["ord-0001", "ord-0002"])
@pytest.mark.parametrize("command", [("amend", "tea", "5"), ("add-line", "mug", "2", "1200")], ids=["amend", "add-line"])
def test_a_shipped_or_cancelled_order_is_not_changed_by_either_command(tmp_path, order_id, command):
    db = seeded_db(tmp_path / "orders.db", ORDERS)

    result = run_cli(command[0], order_id, *command[1:], db=db)

    assert result.returncode == 1 and result.stderr.strip()
    assert lines(db, order_id) == [("tea", 1000, 1)]


def test_a_placed_order_can_still_be_amended_and_extended(tmp_path):
    db = seeded_db(tmp_path / "orders.db", ORDERS)

    assert run_cli("amend", "ord-0003", "tea", "5", db=db).returncode == 0
    assert run_cli("add-line", "ord-0003", "mug", "2", "1200", db=db).returncode == 0

    assert lines(db, "ord-0003") == [("tea", 1000, 5), ("mug", 1200, 2)]
