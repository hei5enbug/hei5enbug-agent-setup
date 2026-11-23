from datetime import date

import pytest

from shop import store
from shop.errors import UnknownCustomer, UnknownSku, ValidationError
from shop.orders import parse_lines, place_order


def test_parse_lines_reads_sku_and_quantity_pairs():
    assert parse_lines("AB-100:2,CD-200:1") == [("AB-100", 2), ("CD-200", 1)]


def test_a_malformed_line_is_rejected():
    with pytest.raises(ValidationError):
        parse_lines("AB-100")


def test_an_order_is_stored_with_its_amounts(data_file):
    order = place_order(data_file, 2, [("AB-100", 2)], placed_on=date(2026, 3, 2))
    assert (order["id"], order["subtotal_cents"], order["discount_cents"]) == (1, 2500, 0)
    assert store.load(data_file)["orders"][0]["placed_on"] == "2026-03-02"


def test_the_tier_discount_is_taken_from_the_subtotal(data_file):
    order = place_order(data_file, 1, [("AB-100", 4)], placed_on=date(2026, 3, 2))
    assert (order["subtotal_cents"], order["discount_cents"]) == (5000, 500)


def test_an_unknown_sku_or_customer_is_rejected(data_file):
    with pytest.raises(UnknownSku):
        place_order(data_file, 1, [("ZZ-999", 1)])
    with pytest.raises(UnknownCustomer):
        place_order(data_file, 9, [("AB-100", 1)])
