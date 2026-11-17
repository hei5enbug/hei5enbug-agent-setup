import io

from orders.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_place_then_list_shows_the_order(conn):
    assert run("place", "c-1", "tea:450:2") == (0, "ord-0001\n", "")
    code, out, _ = run("list")
    assert code == 0 and out.startswith("ord-0001  ") and out.rstrip().endswith("placed  c-1")


def test_a_rejected_order_exits_with_one(conn):
    code, out, err = run("place", "c-1", "tea:450:1", "--discount", "50")
    assert (code, out) == (1, "") and "discount must be between" in err


def test_a_shipped_order_cannot_be_cancelled(conn):
    run("place", "c-1", "tea:450:1")
    run("ship", "ord-0001")
    code, _, err = run("cancel", "ord-0001")
    assert code == 1 and "is not a placed order" in err


def test_report_invoice_prints_the_total(conn):
    run("place", "c-1", "tea:1000:10")
    code, out, _ = run("report", "invoice", "ord-0001")
    assert code == 0 and out.splitlines()[-1] == "Total: $107.25"
