import io
from datetime import date

from shop import store
from shop.cli import main
from shop.orders import place_order

DAY = date(2026, 3, 2)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def stored(data_file):
    data = store.load(data_file)
    data["customers"]["4"] = {"name": "Dennis Ritchie", "tier": "basic"}
    store.save(data_file, data)
    place_order(data_file, 2, [("AB-100", 2)], placed_on=DAY)
    place_order(data_file, 4, [("AB-100", 8)], placed_on=DAY)
    place_order(data_file, 3, [("AB-100", 4)], placed_on=DAY)
    place_order(data_file, 1, [("AB-100", 5)], placed_on=DAY)


def test_customers_are_listed_from_the_highest_spend_down(data_file):
    stored(data_file)
    code, out, _ = run("--store", str(data_file), "top-customers", "--limit", "4")
    assert (code, out) == (0, "customer 4: 100.00\ncustomer 1: 56.25\ncustomer 3: 47.50\ncustomer 2: 25.00\n")


def test_the_default_is_the_top_three(data_file):
    stored(data_file)
    lines = run("--store", str(data_file), "top-customers")[1].splitlines()
    assert lines == ["customer 4: 100.00", "customer 1: 56.25", "customer 3: 47.50"]


def test_limit_cuts_the_list(data_file):
    stored(data_file)
    assert run("--store", str(data_file), "top-customers", "--limit", "1")[1] == "customer 4: 100.00\n"
