import json
import re

from helpers_orders import run_cli, seeded_db

ORDERS = (
    ("ord-0001", "c-1", "placed", "2026-01-15T09:00:00", 0, [("tea", 450, 2)]),
    ("ord-0002", "c-2", "shipped", "2026-01-16T09:00:00", 0, [("mug", 1200, 1)]),
)


def test_export_stores_every_order_as_json_under_orders_json(tmp_path):
    db = seeded_db(tmp_path / "orders.db", ORDERS)
    store = tmp_path / "store"

    result = run_cli("export", db=db, ORDERS_STORAGE_DIR=str(store))

    assert result.returncode == 0
    stored = json.loads((store / "orders.json").read_text(encoding="utf-8"))
    assert [item["order_id"] for item in stored] == ["ord-0001", "ord-0002"]


def test_a_failing_storage_client_makes_the_command_fail_and_say_so(tmp_path):
    db = seeded_db(tmp_path / "orders.db", ORDERS)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a folder is needed", encoding="utf-8")

    result = run_cli("export", db=db, ORDERS_STORAGE_DIR=str(blocker / "store"))

    assert result.returncode != 0
    assert re.search(r"fail|error|cannot|StorageError", result.stdout + result.stderr, re.IGNORECASE)
