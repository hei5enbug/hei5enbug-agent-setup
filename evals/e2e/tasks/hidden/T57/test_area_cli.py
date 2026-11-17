import io
from decimal import Decimal

from inventory.cli import main
from inventory.formatting import render_items
from inventory.models import Item


def run(*argv, data):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--data", str(data), *argv], environ={}, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def seed(data):
    for argv in (
        ["item", "add", "WIDGET", "Widget", "40.00", "--category", "hardware"],
        ["item", "add", "BOLT", "Bolt", "0.40", "--category", "parts"],
    ):
        assert run(*argv, data=data)[0] == 0


def test_tag_and_untag_print_their_messages_and_fail_with_exit_code_two(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    assert run("item", "tag", "widget", "Sale", data=data) == (0, "Tagged WIDGET with sale\n", "")
    assert run("item", "untag", "WIDGET", "sale", data=data) == (0, "Removed tag sale from WIDGET\n", "")
    code, out, err = run("item", "untag", "WIDGET", "sale", data=data)
    assert (code, out) == (2, "") and "error: item WIDGET has no tag sale" in err
    code, _, err = run("item", "tag", "NOPE", "sale", data=data)
    assert code == 2 and "unknown item: NOPE" in err


def test_render_items_ends_with_a_tags_column():
    items = [Item("A1", "A", Decimal("1.00"), tags=["new", "sale"]), Item("B1", "B", Decimal("2.00"))]
    lines = render_items(items).splitlines()
    assert lines[0].split()[-1] == "TAGS"
    assert lines[2].split()[-1] == "new,sale"
    assert lines[3].split()[-1] == "-"


def test_item_list_filters_with_the_tag_option(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    run("item", "tag", "WIDGET", "sale", data=data)
    _, out, _ = run("item", "list", "--tag", "SALE", data=data)
    assert "WIDGET" in out and "BOLT" not in out
    _, out, _ = run("item", "list", data=data)
    assert "WIDGET" in out and "BOLT" in out


def test_item_tags_prints_a_two_column_table_sorted_by_tag(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    for sku, tag in (("WIDGET", "sale"), ("BOLT", "sale"), ("WIDGET", "new")):
        run("item", "tag", sku, tag, data=data)
    code, out, _ = run("item", "tags", data=data)
    lines = out.splitlines()
    assert code == 0 and lines[0].split() == ["TAG", "ITEMS"]
    assert [line.split() for line in lines[2:]] == [["new", "1"], ["sale", "2"]]
