"""Branch with a stock export that adds four columns, the team's writing rules, and the local check log."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventory_common import add_writing_rules, commit, write  # noqa: E402

EXPORT = '''"""CSV export of the stock position per item."""

from __future__ import annotations

import csv
import io

from . import audit
from .models import ORDER_PLACED, Database
from .reports import total_quantities

COLUMNS = ("sku", "name", "total_quantity", "warehouse_count", "open_order_units", "last_movement_at")


def export_rows(db: Database) -> list[dict[str, object]]:
    totals = total_quantities(db)
    open_units: dict[str, int] = {}
    for order in db.orders.values():
        if order.status == ORDER_PLACED:
            for line in order.lines:
                open_units[line.sku] = open_units.get(line.sku, 0) + line.quantity
    rows = []
    for item in sorted(db.items.values(), key=lambda item: item.sku):
        movements = audit.entries_for(db, sku=item.sku)
        rows.append({
            "sku": item.sku,
            "name": item.name,
            "total_quantity": totals.get(item.sku, 0),
            "warehouse_count": sum(1 for levels in db.stock.values() if levels.get(item.sku, 0) > 0),
            "open_order_units": open_units.get(item.sku, 0),
            "last_movement_at": max((entry.at for entry in movements), default=None),
        })
    return rows


def export_csv(db: Database) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\\n")
    writer.writeheader()
    for row in export_rows(db):
        row = {**row, "last_movement_at": row["last_movement_at"].isoformat() if row["last_movement_at"] else ""}
        writer.writerow(row)
    return buffer.getvalue()
'''

TEST = '''from decimal import Decimal

from inventory import export


def test_columns_follow_the_documented_order():
    assert export.COLUMNS[2:] == ("total_quantity", "warehouse_count", "open_order_units", "last_movement_at")


def test_export_counts_stock_and_open_orders(app):
    app.orders.create_order("kim@example.com", [("WIDGET", 3)])
    row = next(item for item in export.export_rows(app.db) if item["sku"] == "WIDGET")
    assert (row["total_quantity"], row["warehouse_count"], row["open_order_units"]) == (22, 2, 3)


def test_export_csv_has_a_header_and_one_row_per_item(app):
    lines = export.export_csv(app.db).splitlines()
    assert lines[0].split(",") == list(export.COLUMNS)
    assert len(lines) == 4


def test_item_without_movement_has_an_empty_timestamp(app):
    app.catalog.add_item("NUT", "Nut", Decimal("0.10"))
    row = next(item for item in export.export_rows(app.db) if item["sku"] == "NUT")
    assert row["last_movement_at"] is None
'''

CHECK_LOG = """Local check results, oldest first
2026-11-04 10:12  commit 1 of 3  python3 -m pytest tests/test_export.py  2 failed
2026-11-04 11:40  commit 2 of 3  python3 -m pytest tests/test_export.py  1 failed
2026-11-04 14:05  commit 3 of 3  python3 -m pytest tests/test_export.py  4 passed
2026-11-04 14:07  commit 3 of 3  python3 -m pytest -q                   full suite passed
"""


def main(repo: str) -> None:
    root = Path(repo)
    add_writing_rules(root)
    subprocess.run(["git", "checkout", "-q", "-b", "feature/report-columns"], cwd=root, check=True)
    write(root, "inventory/export.py", EXPORT)
    write(root, "tests/test_export.py", TEST)
    write(root, "review/check-log.txt", CHECK_LOG)
    commit(root, "feat: add the stock export")


if __name__ == "__main__":
    main(sys.argv[1])
