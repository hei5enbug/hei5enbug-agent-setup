import io
import json
from datetime import date

import pytest

from shop import store
from shop.cli import main
from shop.orders import place_order

DAY = date(2026, 3, 2)


def discounts(path, customer_id):
    return [order["discount_cents"] for order in store.load(path)["orders"] if order["customer_id"] == customer_id]


def test_a_discount_is_cut_to_what_is_left_of_the_limit(data_file, monkeypatch):
    monkeypatch.setenv("SHOP_DISCOUNT_LIMIT_CENTS", "700")
    for _ in range(3):
        place_order(data_file, 1, [("AB-100", 4)], placed_on=DAY)
    assert discounts(data_file, 1) == [500, 200, 0]


def test_the_limit_is_counted_per_customer(data_file, monkeypatch):
    monkeypatch.setenv("SHOP_DISCOUNT_LIMIT_CENTS", "300")
    place_order(data_file, 1, [("AB-100", 4)], placed_on=DAY)
    place_order(data_file, 3, [("AB-100", 4)], placed_on=DAY)
    place_order(data_file, 3, [("AB-100", 4)], placed_on=DAY)
    assert discounts(data_file, 1) == [300]
    assert discounts(data_file, 3) == [250, 50]


def test_the_default_limit_is_100_00(data_file):
    order = place_order(data_file, 1, [("EF-300", 30)], placed_on=DAY)
    assert (order["subtotal_cents"], order["discount_cents"]) == (149970, 10000)
    assert place_order(data_file, 1, [("AB-100", 4)], placed_on=DAY)["discount_cents"] == 0


def test_discounts_stored_before_the_limit_existed_count(data_file, monkeypatch):
    monkeypatch.setenv("SHOP_DISCOUNT_LIMIT_CENTS", "1000")
    data = store.load(data_file)
    data["orders"].append({"id": 1, "ref": None, "customer_id": 1, "lines": [], "subtotal_cents": 95000,
                           "discount_cents": 900, "placed_on": "2026-01-05"})
    store.save(data_file, data)
    assert place_order(data_file, 1, [("AB-100", 4)], placed_on=DAY)["discount_cents"] == 100


def test_the_command_prints_the_capped_discount(data_file):
    out = io.StringIO()
    assert main(["--store", str(data_file), "place", "1", "EF-300:30"], stdout=out, stderr=io.StringIO()) == 0
    assert out.getvalue() == "order 1: subtotal 1499.70 discount 100.00 total 1399.70\n"
