import io

from timesheet import store
from timesheet.cli import list_lines, main


def test_list_lines_keep_the_order_of_the_entries_given():
    entries = [
        {"id": 1, "date": "2026-11-10", "project": "alpha", "minutes": 90},
        {"id": 2, "date": "2026-11-03", "project": "beta", "minutes": 30},
    ]
    assert list_lines(entries) == ["1 2026-11-10 alpha 90", "2 2026-11-03 beta 30"]


def test_list_prints_the_data_file_in_file_order(home):
    (home / "data").mkdir()
    (home / "data" / "entries.json").write_text(
        '[{"id": 1, "date": "2026-11-10", "project": "a", "minutes": 1},'
        ' {"id": 2, "date": "2026-11-03", "project": "b", "minutes": 2}]\n',
        encoding="utf-8",
    )
    store.clear_cache()
    out = io.StringIO()
    main(["list"], stdout=out)
    assert out.getvalue().splitlines() == ["1 2026-11-10 a 1", "2 2026-11-03 b 2"]
