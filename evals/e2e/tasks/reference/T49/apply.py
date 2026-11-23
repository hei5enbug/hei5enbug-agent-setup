import sys

from patch_tools import append, replace, write

repo = sys.argv[1]

write(repo, "tally/weekly.py", '''"""Hours per team for the week that contains a date; a week starts on Sunday."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from .errors import TallyError


class BadDate(TallyError):
    def __init__(self, value: str):
        super().__init__(f"not a date (YYYY-MM-DD): {value}")


def week_start(day: date) -> date:
    return day - timedelta(days=(day.weekday() + 1) % 7)


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BadDate(value) from exc


def weekly_hours(entries: Iterable[dict[str, Any]], day: str) -> dict[str, float]:
    start = week_start(parse_day(day))
    end = start + timedelta(days=7)
    teams = sorted({entry["team"] for entry in entries})
    totals = {team: 0.0 for team in teams}
    for entry in entries:
        if start <= date.fromisoformat(entry["day"]) < end:
            totals[entry["team"]] += float(entry["hours"])
    return totals
''')
write(repo, "tally/archive.py", '''"""Copy the entries file under a name that holds the date and time."""

from __future__ import annotations

import shutil
from pathlib import Path

from .clock import now
from .store import entries_path


def archive_entries(out_dir: str) -> Path:
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"entries-{now():%Y%m%d-%H%M}.json"
    shutil.copyfile(entries_path(), target)
    return target
''')
replace(repo, "tally/cli.py", "from .costs import team_cost\n", "from .archive import archive_entries\nfrom .costs import team_cost\n")
replace(repo, "tally/cli.py", "from .store import load_entries\n", "from .store import load_entries\nfrom .weekly import weekly_hours\n")
replace(repo, "tally/cli.py", '    cost = commands.add_parser("cost", help="the cost of a team\'s hours")\n    cost.add_argument("team")\n',
        '    cost = commands.add_parser("cost", help="the cost of a team\'s hours")\n    cost.add_argument("team")\n'
        '    weekly = commands.add_parser("weekly", help="hours per team for the week that contains a date")\n    weekly.add_argument("date")\n'
        '    archive = commands.add_parser("archive", help="copy the entries file into a folder")\n    archive.add_argument("out_dir")\n')
replace(repo, "tally/cli.py", "        else:\n            print(team_cost(args.team), file=out)\n",
        "        elif args.command == \"weekly\":\n            for team, hours in weekly_hours(load_entries(), args.date).items():\n                print(format_row(team, hours), file=out)\n"
        "        elif args.command == \"archive\":\n            print(archive_entries(args.out_dir), file=out)\n"
        "        else:\n            print(team_cost(args.team), file=out)\n")
write(repo, "tests/test_weekly.py", '''import io

from tally.cli import main


def test_weekly_starts_the_week_on_sunday():
    out = io.StringIO()
    assert main(["weekly", "2026-11-18"], stdout=out, stderr=io.StringIO()) == 0
    assert out.getvalue().splitlines() == ["alpha 6.0", "beta 10.0", "gamma 4.5"]


def test_archive_names_the_copy_after_the_date_and_time(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_NOW", "2026-11-16T09:05")
    assert main(["archive", str(tmp_path)], stdout=io.StringIO(), stderr=io.StringIO()) == 0
    assert (tmp_path / "entries-20261116-0905.json").is_file()
''')
replace(repo, "README.md", "- `tally cost TEAM`", "- `tally weekly DATE` prints `<team> <hours>` for every team for the week that contains DATE; a week starts on Sunday.\n"
        "- `tally archive OUT_DIR` copies the entries file to `OUT_DIR/entries-YYYYMMDD-HHMM.json` and prints the path.\n- `tally cost TEAM`")
replace(repo, "docs/ko/README.ko.md", "- `tally cost TEAM`", "- `tally weekly DATE`는 DATE가 속한 주의 모든 팀을 `<팀> <시간>`으로 출력합니다. 한 주는 일요일에 시작합니다.\n"
        "- `tally archive OUT_DIR`은 입력 파일을 `OUT_DIR/entries-YYYYMMDD-HHMM.json`으로 복사하고 경로를 출력합니다.\n- `tally cost TEAM`")
