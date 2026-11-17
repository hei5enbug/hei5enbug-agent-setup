import csv
import io

import pytest

from notes_cli.cli import main
from notes_cli.export import export_memos
from notes_cli.memo import make_memo
from notes_cli.settings import Settings
from notes_cli.storage import MemoStore


def sample():
    return [
        make_memo(1, "Plan trip", "book flights", ("travel", "fun")),
        make_memo(2, 'Say "hi", then go', "", ()),
        make_memo(3, "Groceries", "milk", ("home",)),
    ]


def run(*argv, store):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--store", str(store), *argv], stdout=out, stderr=err, settings=Settings(page_size=10))
    return code, out.getvalue(), err.getvalue()


def seeded(tmp_path):
    store = MemoStore(tmp_path / "memos.json")
    store.add("Plan trip", "book flights", ("travel", "fun"))
    store.add("Groceries", "milk", ("home",))
    store.add("Reading", "", ("Travel",))
    return tmp_path / "memos.json"


def test_csv_has_a_header_and_one_row_per_memo():
    memos = sample()
    text = export_memos(memos, "csv")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["id", "title", "tags", "created_at"]
    assert rows[1] == ["1", "Plan trip", "travel;fun", memos[0].created_at]
    assert len(rows) == 4
    assert text.endswith("\n") and "\r" not in text


def test_csv_quotes_a_title_with_commas_and_quotes():
    rows = list(csv.reader(io.StringIO(export_memos(sample(), "csv"))))
    assert rows[2][1] == 'Say "hi", then go'
    assert rows[2][2] == ""


def test_csv_of_no_memos_is_only_the_header():
    assert export_memos([], "csv") == "id,title,tags,created_at\n"


def test_markdown_lists_title_tags_and_body():
    lines = export_memos(sample(), "markdown").splitlines()
    assert lines[0] == "## 1. Plan trip"
    assert lines[1] == "Tags: travel, fun"
    assert lines[2] == "" and lines[3] == "book flights"
    assert "## 2. Say \"hi\", then go" in lines
    assert "Tags: home" in lines and "milk" in lines


def test_markdown_leaves_out_empty_tags_and_body_and_ends_with_one_newline():
    text = export_memos([make_memo(2, "Plain")], "markdown")
    assert text == "## 2. Plain\n"
    assert export_memos(sample(), "markdown").endswith("milk\n")


def test_markdown_separates_memos_by_one_blank_line():
    text = export_memos([make_memo(1, "A"), make_memo(2, "B")], "markdown")
    assert text == "## 1. A\n\n## 2. B\n"


def test_markdown_of_no_memos_is_empty():
    assert export_memos([], "markdown") == ""


def test_unknown_format_raises_value_error():
    with pytest.raises(ValueError):
        export_memos(sample(), "xml")


def test_cli_exports_csv_by_default(tmp_path):
    store = seeded(tmp_path)
    code, out, _ = run("memo", "export", store=store)
    rows = list(csv.reader(io.StringIO(out)))
    assert code == 0
    assert rows[0] == ["id", "title", "tags", "created_at"] and len(rows) == 4


def test_cli_exports_markdown_on_request(tmp_path):
    store = seeded(tmp_path)
    code, out, _ = run("memo", "export", "--format", "markdown", store=store)
    assert code == 0
    assert out.splitlines()[0] == "## 1. Plan trip"
    assert out.count("## ") == 3


def test_cli_tag_filter_ignores_case(tmp_path):
    store = seeded(tmp_path)
    _, out, _ = run("memo", "export", "--format", "markdown", "--tag", "TRAVEL", store=store)
    assert out.count("## ") == 2
    assert "Groceries" not in out
