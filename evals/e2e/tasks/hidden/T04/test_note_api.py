import io

import pytest

from notes_cli.cli import main
from notes_cli.note import Note, make_note, note_from_dict, note_to_dict
from notes_cli.settings import Settings
from notes_cli.storage import NoteNotFound, NoteStore


def run(*argv, store, page_size=3):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--store", str(store), *argv], stdout=out, stderr=err, settings=Settings(page_size=page_size))
    return code, out.getvalue(), err.getvalue()


def test_make_note_cleans_title_and_tags():
    note = make_note(1, "  Buy milk ", " 2 liters ", (" Home", "home", "", "Errand"))
    assert isinstance(note, Note)
    assert (note.title, note.body, note.tags) == ("Buy milk", "2 liters", ("home", "errand"))


def test_make_note_requires_a_title():
    with pytest.raises(ValueError):
        make_note(1, "   ")


def test_matches_and_tags_ignore_case():
    note = Note(1, "Weekly Report", "send to the TEAM", ("work",))
    assert note.matches("report") and note.matches("team") and not note.matches("budget")
    assert note.has_tag("WORK")


def test_dict_round_trip():
    note = make_note(7, "Call dentist", "after 3pm", ("health",))
    assert note_from_dict(note_to_dict(note)) == note


def test_store_ids_survive_removal(tmp_path):
    store = NoteStore(tmp_path / "n.json")
    first, second = store.add("one"), store.add("two")
    store.remove(first.id)
    third = store.add("three")
    assert (first.id, second.id, third.id) == (1, 2, 3)
    assert [note.title for note in store.all()] == ["two", "three"]


def test_store_reports_unknown_ids(tmp_path):
    store = NoteStore(tmp_path / "n.json")
    with pytest.raises(NoteNotFound):
        store.get(5)
    with pytest.raises(NoteNotFound):
        store.remove(5)


def test_store_search_and_unicode(tmp_path):
    path = tmp_path / "n.json"
    store = NoteStore(path)
    store.add("Groceries", "milk and eggs")
    store.add("회의 준비", "안건 정리")
    assert [note.title for note in store.search("MILK")] == ["Groceries"]
    assert "회의 준비" in path.read_text(encoding="utf-8")


def test_cli_add_and_show(tmp_path):
    store = tmp_path / "n.json"
    code, out, _ = run("note", "add", "Plan trip", "--body", "book flights", "--tag", "travel", store=store)
    assert (code, out.strip()) == (0, "Saved note #1")
    code, out, _ = run("note", "show", "1", store=store)
    assert code == 0
    assert out.startswith("Note #1: Plan trip") and "Tags: travel" in out and "book flights" in out


def test_cli_list_pages_filter_remove_and_search(tmp_path):
    store = tmp_path / "n.json"
    for index in range(1, 8):
        run("note", "add", f"note {index}", "--tag", "odd" if index % 2 else "even", store=store)
    _, first, _ = run("note", "list", store=store)
    _, third, _ = run("note", "list", "--page", "3", store=store)
    assert "page 1/3, 7 notes" in first and "note 7" in third
    assert "4 notes" in run("note", "list", "--tag", "odd", store=store)[1]
    assert run("note", "remove", "1", store=store)[1].strip() == "Removed note #1"
    assert run("note", "search", "note 1", store=store)[1].strip() == "No notes."
    assert "note 2" in run("note", "search", "NOTE 2", store=store)[1]


def test_cli_errors_exit_with_one(tmp_path):
    store = tmp_path / "n.json"
    code, out, err = run("note", "show", "9", store=store)
    assert code == 1 and out == "" and "no note with id 9" in err


def test_old_subcommand_is_gone(tmp_path):
    with pytest.raises(SystemExit) as raised:
        run("memo", "list", store=tmp_path / "n.json")
    assert raised.value.code == 2
