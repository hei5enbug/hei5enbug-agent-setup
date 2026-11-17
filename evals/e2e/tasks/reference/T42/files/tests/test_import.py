import io
import json

from notes_cli.cli import main
from notes_cli.settings import Settings


def run(*argv, store):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--store", str(store), *argv], stdout=out, stderr=err, settings=Settings(page_size=3))
    return code, out.getvalue(), err.getvalue()


def test_import_appends_memos_with_new_ids(tmp_path):
    store, source = tmp_path / "m.json", tmp_path / "other.json"
    run("memo", "add", "mine", store=store)
    run("memo", "add", "theirs", store=source)
    code, out, _ = run("memo", "import", str(source), store=store)
    assert (code, out.strip()) == (0, "Imported 1 memos")
    assert [memo["id"] for memo in json.loads(store.read_text(encoding="utf-8"))["memos"]] == [1, 2]


def test_import_of_a_missing_file_exits_with_three_and_prints_nothing(tmp_path):
    assert run("memo", "import", str(tmp_path / "absent.json"), store=tmp_path / "m.json") == (3, "", "")


def test_a_plain_list_file_is_still_read(tmp_path):
    store = tmp_path / "m.json"
    store.write_text(json.dumps([{"id": 1, "title": "old", "body": "", "tags": [], "created_at": ""}]), encoding="utf-8")
    assert "old" in run("memo", "list", store=store)[1]
