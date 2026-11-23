import io

from notes_cli.cli import main
from notes_cli.settings import Settings


def run(*argv, store):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--store", str(store), *argv], stdout=out, stderr=err, settings=Settings(page_size=3))
    return code, out.getvalue(), err.getvalue()


def test_count_prints_only_the_number_of_memos(tmp_path):
    store = tmp_path / "m.json"
    for index in range(1, 5):
        run("memo", "add", f"memo {index}", store=store)
    code, out, _ = run("memo", "count", store=store)
    assert (code, out) == (0, "4\n")


def test_count_is_zero_without_a_store_file(tmp_path):
    code, out, _ = run("memo", "count", store=tmp_path / "none.json")
    assert (code, out) == (0, "0\n")


def test_count_filters_by_tag(tmp_path):
    store = tmp_path / "m.json"
    run("memo", "add", "a", "--tag", "work", store=store)
    run("memo", "add", "b", "--tag", "work", "--tag", "home", store=store)
    run("memo", "add", "c", "--tag", "home", store=store)
    run("memo", "add", "d", store=store)
    assert run("memo", "count", "--tag", "work", store=store)[1] == "2\n"
    assert run("memo", "count", "--tag", "home", store=store)[1] == "2\n"
    assert run("memo", "count", "--tag", "none", store=store)[1] == "0\n"
