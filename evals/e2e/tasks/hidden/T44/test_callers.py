import io
import json
from datetime import date

from shop.cli import main
from shop.mailing import mailing_label
from shop.orders import place_order

VERSION_1_FILE = {
    "customers": {"1": {"name": "Ada Lovelace", "tier": "gold"}, "2": {"name": "Brian Kernighan", "tier": "basic"}},
    "orders": [{"id": 1, "ref": None, "customer_id": 2, "lines": [{"sku": "AB-100", "quantity": 2, "unit_cents": 1250}],
                "subtotal_cents": 2500, "discount_cents": 0, "placed_on": "2026-02-02"}],
}


def written_by_the_previous_version(tmp_path):
    path = tmp_path / "old-data.json"
    path.write_text(json.dumps(VERSION_1_FILE, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_the_mailing_label_still_names_the_customer(data_file):
    assert mailing_label(data_file, 1) == "Ada Lovelace (customer 1)"


def test_placing_an_order_still_takes_the_tier_discount(data_file):
    order = place_order(data_file, 1, [("AB-100", 4)], placed_on=date(2026, 3, 2))
    assert (order["subtotal_cents"], order["discount_cents"]) == (5000, 500)


def test_a_file_stored_by_the_previous_version_still_works_in_every_caller(tmp_path):
    path = written_by_the_previous_version(tmp_path)
    assert mailing_label(path, 1) == "Ada Lovelace (customer 1)"
    assert place_order(path, 1, [("AB-100", 4)], placed_on=date(2026, 3, 2))["discount_cents"] == 500
    out = io.StringIO()
    assert main(["--store", str(path), "lookup", "2"], stdout=out, stderr=io.StringIO()) == 0
    assert out.getvalue() == "Brian Kernighan (basic)\n"
    assert main(["--store", str(path), "sales"], stdout=out, stderr=io.StringIO()) == 0
