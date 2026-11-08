import io

from notes_cli.cli import main
from notes_cli.storage import MemoStore


def seeded(tmp_path):
    store = MemoStore(tmp_path / "memos.json")
    store.add("Plan trip", "book flights", ("travel",))
    store.add("Groceries", "milk and eggs", ("home", "errand"))
    store.add("Reading list", "travel guides", ())
    return store


def titles(memos):
    return [memo.title for memo in memos]


def test_search_finds_a_memo_by_its_tag(tmp_path):
    assert titles(seeded(tmp_path).search("errand")) == ["Groceries"]


def test_tag_search_ignores_case(tmp_path):
    assert titles(seeded(tmp_path).search("ERRAND")) == ["Groceries"]


def test_tag_search_accepts_part_of_a_tag(tmp_path):
    assert titles(seeded(tmp_path).search("trav")) == ["Plan trip", "Reading list"]


def test_title_and_body_search_still_work(tmp_path):
    store = seeded(tmp_path)
    assert titles(store.search("groceries")) == ["Groceries"]
    assert titles(store.search("flights")) == ["Plan trip"]


def test_a_query_that_matches_nothing_finds_nothing(tmp_path):
    assert seeded(tmp_path).search("holiday") == []


def test_cli_search_prints_the_memo_with_the_matching_tag(tmp_path):
    seeded(tmp_path)
    out = io.StringIO()
    code = main(["--store", str(tmp_path / "memos.json"), "memo", "search", "errand"], stdout=out)
    assert code == 0
    assert "Groceries" in out.getvalue()
    assert "Plan trip" not in out.getvalue()
