import io
from datetime import date
from pathlib import Path

from timesheet import store
from timesheet.cli import main


def test_two_totals_calls_in_one_process_read_the_data_file_once(home, monkeypatch):
    store.add(date(2026, 11, 2), "alpha", 30)
    store.clear_cache()
    data_file = home / "data" / "entries.json"
    reads = []
    original = Path.read_text

    def counting(self, *args, **kwargs):
        if self == data_file:
            reads.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    first, second = io.StringIO(), io.StringIO()
    main(["totals"], stdout=first)
    main(["totals"], stdout=second)
    assert first.getvalue() == second.getvalue() == "alpha 30\n"
    assert len(reads) == 1


def test_an_add_is_still_visible_to_the_next_totals_call():
    store.add(date(2026, 11, 2), "alpha", 30)
    main(["totals"], stdout=io.StringIO())
    store.add(date(2026, 11, 3), "alpha", 15)
    out = io.StringIO()
    main(["totals"], stdout=out)
    assert out.getvalue() == "alpha 45\n"
