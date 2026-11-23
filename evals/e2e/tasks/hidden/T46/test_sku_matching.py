import io
from datetime import date

from shop.cli import main
from shop.orders import place_order

DAY = date(2026, 3, 2)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_reported_command_accepts_a_lowercase_sku(data_file):
    code, out, _ = run("--store", str(data_file), "place", "2", "ab-100:2")
    assert (code, out) == (0, "order 1: subtotal 25.00 discount 0.00 total 25.00\n")


def test_the_price_command_ignores_case_and_surrounding_spaces(data_file):
    assert run("price", "ab-100")[:2] == (0, "12.50\n")
    assert run("price", " Cd-200 ")[:2] == (0, "7.99\n")


def test_placing_an_order_from_code_ignores_case_and_spaces(data_file):
    order = place_order(data_file, 2, [("ef-300", 1), (" ab-100", 2)], placed_on=DAY)
    assert order["subtotal_cents"] == 4999 + 2500


def test_a_sku_that_is_not_listed_is_still_rejected(data_file):
    code, out, err = run("price", "zz-999")
    assert (code, out) == (2, "")
    assert "unknown SKU" in err
