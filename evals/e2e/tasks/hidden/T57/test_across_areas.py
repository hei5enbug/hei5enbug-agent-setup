import io
import json

from inventory.cli import main


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


def test_a_tag_set_by_the_cli_is_stored_in_a_schema_two_file_and_seen_by_the_next_run(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    assert run("item", "tag", "WIDGET", "sale", data=data)[0] == 0
    stored = json.loads(data.read_text(encoding="utf-8"))
    assert stored["schema"] == 2
    assert {item["sku"]: item["tags"] for item in stored["items"]} == {"WIDGET": ["sale"], "BOLT": []}
    _, out, _ = run("item", "list", "--tag", "sale", data=data)
    assert "WIDGET" in out and "BOLT" not in out


def test_the_cli_tags_an_item_of_a_schema_one_file_and_saves_it_as_schema_two(tmp_path):
    data = tmp_path / "old.json"
    data.write_text(json.dumps({"schema": 1, "items": [
        {"sku": "WIDGET", "name": "Widget", "unit_price": "40.00", "category": "hardware", "active": True}]}), encoding="utf-8")
    assert run("item", "tag", "WIDGET", "sale", data=data)[0] == 0
    stored = json.loads(data.read_text(encoding="utf-8"))
    assert stored["schema"] == 2 and stored["items"][0]["tags"] == ["sale"]


def test_a_sixth_tag_through_the_cli_fails_and_stores_nothing_more(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    for tag in ("a", "b", "c", "d", "e"):
        assert run("item", "tag", "WIDGET", tag, data=data)[0] == 0
    code, out, err = run("item", "tag", "WIDGET", "f", data=data)
    assert (code, out) == (2, "") and "item WIDGET can have at most 5 tags" in err
    stored = json.loads(data.read_text(encoding="utf-8"))
    assert [item["tags"] for item in stored["items"] if item["sku"] == "WIDGET"] == [["a", "b", "c", "d", "e"]]


def test_deactivated_items_leave_the_tag_list_and_the_tag_table(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    run("item", "tag", "BOLT", "sale", data=data)
    run("item", "tag", "WIDGET", "sale", data=data)
    stored = json.loads(data.read_text(encoding="utf-8"))
    for item in stored["items"]:
        if item["sku"] == "BOLT":
            item["active"] = False
    data.write_text(json.dumps(stored), encoding="utf-8")
    _, listing, _ = run("item", "list", "--tag", "sale", data=data)
    _, table, _ = run("item", "tags", data=data)
    assert "BOLT" not in listing and "WIDGET" in listing
    assert [line.split() for line in table.splitlines()[2:]] == [["sale", "1"]]
