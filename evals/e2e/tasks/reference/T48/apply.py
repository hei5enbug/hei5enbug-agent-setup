import sys

from patch_tools import append, replace

repo = sys.argv[1]

replace(repo, "shop/dates.py", 'return day.strftime("%Y-W%W")', 'return day.strftime("%Y-W%U")')
append(repo, "tests/test_dates.py", '''

def test_a_week_starts_on_sunday():
    assert week_label(date(2026, 2, 28)) == "2026-W08"
    assert week_label(date(2026, 3, 1)) == "2026-W09"
''')
