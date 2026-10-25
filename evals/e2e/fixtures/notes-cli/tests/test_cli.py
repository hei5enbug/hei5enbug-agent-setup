import io

from notes_cli.cli import main
from notes_cli.settings import Settings


def run(*argv, store, page_size=3):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--store", str(store), *argv], stdout=out, stderr=err, settings=Settings(page_size=page_size))
    return code, out.getvalue(), err.getvalue()


def test_add_then_show(tmp_path):
    store = tmp_path / "m.json"
    code, out, _ = run("memo", "add", "Plan trip", "--body", "book flights", "--tag", "travel", store=store)
    assert (code, out.strip()) == (0, "Saved memo #1")
    code, out, _ = run("memo", "show", "1", store=store)
    assert code == 0
    assert out.startswith("Memo #1: Plan trip") and "Tags: travel" in out and "book flights" in out


def test_list_is_paged_by_the_page_size(tmp_path):
    store = tmp_path / "m.json"
    for index in range(1, 8):
        run("memo", "add", f"memo {index}", store=store)
    _, first, _ = run("memo", "list", store=store)
    _, third, _ = run("memo", "list", "--page", "3", store=store)
    assert first.count("memo ") == 3 and "page 1/3, 7 memos" in first
    assert "memo 7" in third and "page 3/3" in third


def test_list_filters_by_tag(tmp_path):
    store = tmp_path / "m.json"
    run("memo", "add", "a", "--tag", "work", store=store)
    run("memo", "add", "b", store=store)
    _, out, _ = run("memo", "list", "--tag", "work", store=store)
    assert "a" in out and "1 memos" in out


def test_remove_and_search(tmp_path):
    store = tmp_path / "m.json"
    run("memo", "add", "alpha note", store=store)
    run("memo", "add", "beta", store=store)
    assert run("memo", "remove", "1", store=store)[1].strip() == "Removed memo #1"
    assert run("memo", "search", "alpha", store=store)[1].strip() == "No memos."
    assert "beta" in run("memo", "search", "BETA", store=store)[1]


def test_errors_exit_with_one(tmp_path):
    store = tmp_path / "m.json"
    code, out, err = run("memo", "show", "9", store=store)
    assert code == 1 and out == "" and "no memo with id 9" in err
    code, _, err = run("memo", "add", "   ", store=store)
    assert code == 1 and "needs a title" in err
