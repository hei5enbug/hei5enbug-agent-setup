import io

from orders import lookup
from orders.cli import main


def test_an_unknown_customer_is_not_found(conn):
    assert lookup.find_customer(conn, "c-9") is None


def test_whoami_prints_the_name_and_tier(conn):
    out, err = io.StringIO(), io.StringIO()
    assert main(["whoami", "c-1"], stdout=out, stderr=err) == 0
    assert out.getvalue() == "Ada Lovelace (gold)\n"


def test_whoami_exits_with_one_for_an_unknown_customer(conn):
    out, err = io.StringIO(), io.StringIO()
    assert main(["whoami", "c-9"], stdout=out, stderr=err) == 1
    assert "unknown customer" in err.getvalue()
