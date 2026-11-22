import io

from shop import store
from shop.cli import main

HEADER = "ref,customer_id,sku,quantity,placed_on\n"
ROWS = ["R-1,1,AB-100,2,2026-03-02", "R-2,2,CD-200,1,2026-03-02", "R-3,3,EF-300,3,2026-03-03"]


def csv_file(tmp_path, rows=ROWS):
    path = tmp_path / "orders.csv"
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def run_import(data_file, csv_path):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--store", str(data_file), "import-orders", str(csv_path)], stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def refs(data_file):
    return [order["ref"] for order in store.load(data_file)["orders"]]


def test_the_import_stores_one_order_per_row(data_file, tmp_path):
    code, out, _ = run_import(data_file, csv_file(tmp_path))
    orders = store.load(data_file)["orders"]
    assert (code, out) == (0, "imported 3\n")
    assert [(order["ref"], order["customer_id"], order["placed_on"]) for order in orders] == [
        ("R-1", 1, "2026-03-02"), ("R-2", 2, "2026-03-02"), ("R-3", 3, "2026-03-03")]
    assert orders[0]["lines"] == [{"sku": "AB-100", "quantity": 2, "unit_cents": 1250}]


def test_running_the_same_file_again_adds_nothing(data_file, tmp_path):
    path = csv_file(tmp_path)
    run_import(data_file, path)
    code, out, _ = run_import(data_file, path)
    assert (code, out) == (0, "imported 0\n")
    assert sorted(refs(data_file)) == ["R-1", "R-2", "R-3"]


def test_a_rerun_after_a_partial_import_adds_only_the_missing_orders(data_file, tmp_path):
    run_import(data_file, csv_file(tmp_path, ROWS[:2]))
    code, out, _ = run_import(data_file, csv_file(tmp_path))
    assert (code, out) == (0, "imported 1\n")
    assert sorted(refs(data_file)) == ["R-1", "R-2", "R-3"]
