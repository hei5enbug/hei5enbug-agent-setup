import io

from shop.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_quote_prints_the_total_with_shipping():
    assert run("quote", "1000x2", "500x1") == (0, "Total: $30.00\n", "")


def test_quote_applies_the_discount():
    assert run("quote", "2000x3", "--discount", "10") == (0, "Total: $54.00\n", "")


def test_a_malformed_item_exits_with_one():
    code, out, err = run("quote", "tea")
    assert (code, out) == (1, "")
    assert "item must look like" in err


def test_a_discount_above_one_hundred_exits_with_one():
    code, _, err = run("quote", "1000x1", "--discount", "150")
    assert code == 1 and "between 0 and 100" in err
