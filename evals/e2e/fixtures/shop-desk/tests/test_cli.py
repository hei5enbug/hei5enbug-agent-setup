import io

from shop.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_place_prints_the_amounts(data_file):
    code, out, _ = run("--store", str(data_file), "place", "1", "AB-100:4")
    assert (code, out) == (0, "order 1: subtotal 50.00 discount 5.00 total 45.00\n")


def test_lookup_prints_name_and_tier(data_file):
    assert run("--store", str(data_file), "lookup", "3")[:2] == (0, "Carol Shaw (silver)\n")


def test_sales_prints_one_line_per_customer(data_file):
    run("--store", str(data_file), "place", "2", "AB-100:4")
    assert run("--store", str(data_file), "sales")[1] == "customer 2: orders 1 net 50.00 tax 4.00\n"


def test_price_prints_the_unit_price():
    assert run("price", "AB-100")[:2] == (0, "12.50\n")


def test_a_user_error_exits_with_two(data_file):
    code, out, err = run("--store", str(data_file), "lookup", "9")
    assert (code, out) == (2, "")
    assert "unknown customer: 9" in err
