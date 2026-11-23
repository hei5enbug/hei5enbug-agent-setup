import io
from datetime import date

from shop.cli import main
from shop.orders import place_order

DAY = date(2026, 3, 2)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def stored(data_file):
    place_order(data_file, 1, [("AB-100", 4)], placed_on=DAY)
    place_order(data_file, 1, [("AB-100", 8)], placed_on=DAY)
    place_order(data_file, 2, [("AB-100", 4)], placed_on=DAY)


def test_the_statement_has_one_line_per_order_of_the_customer(data_file):
    stored(data_file)
    code, out, _ = run("--store", str(data_file), "statement", "1")
    assert (code, out) == (0, "order 1: net 45.00 tax 3.60 total 48.60\norder 2: net 90.00 tax 7.20 total 97.20\n")


def test_a_customer_without_orders_prints_nothing(data_file):
    assert run("--store", str(data_file), "statement", "3")[:2] == (0, "")


def test_an_unknown_customer_is_a_user_error(data_file):
    code, out, err = run("--store", str(data_file), "statement", "9")
    assert (code, out) == (2, "")
    assert "unknown customer: 9" in err


def test_one_changed_rate_changes_the_statement_and_the_sales_report(data_file, monkeypatch):
    stored(data_file)
    monkeypatch.setenv("SHOP_TAX_PERCENT", "20")
    statement = run("--store", str(data_file), "statement", "1")[1]
    sales = run("--store", str(data_file), "sales")[1]
    assert statement == "order 1: net 45.00 tax 9.00 total 54.00\norder 2: net 90.00 tax 18.00 total 108.00\n"
    assert "customer 1: orders 2 net 135.00 tax 27.00" in sales
