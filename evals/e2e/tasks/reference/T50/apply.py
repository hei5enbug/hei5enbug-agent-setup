import sys

from patch_tools import replace, write

repo = sys.argv[1]

write(repo, "tally/busiest.py", '''"""The team with the most hours on one day."""

from __future__ import annotations

from typing import Any, Iterable


def busiest_team(entries: Iterable[dict[str, Any]], day: str) -> tuple[str, float] | None:
    totals: dict[str, float] = {}
    for entry in entries:
        if entry["day"] == day:
            totals[entry["team"]] = totals.get(entry["team"], 0.0) + float(entry["hours"])
    if not totals:
        return None
    team = min(totals, key=lambda name: (-totals[name], name))
    return team, totals[team]
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
replace(repo, "tally/cli.py", "from .costs import team_cost\n", "from .archive import archive_entries\nfrom .busiest import busiest_team\nfrom .costs import team_cost\n")
replace(repo, "tally/cli.py", '    cost = commands.add_parser("cost", help="the cost of a team\'s hours")\n    cost.add_argument("team")\n',
        '    cost = commands.add_parser("cost", help="the cost of a team\'s hours")\n    cost.add_argument("team")\n'
        '    busiest = commands.add_parser("busiest", help="the team with the most hours on a day")\n    busiest.add_argument("date")\n'
        '    archive = commands.add_parser("archive", help="copy the entries file into a folder")\n    archive.add_argument("out_dir")\n')
replace(repo, "tally/cli.py", "        else:\n            print(team_cost(args.team), file=out)\n",
        "        elif args.command == \"busiest\":\n            found = busiest_team(load_entries(), args.date)\n            print(format_row(*found) if found else \"no entries\", file=out)\n"
        "        elif args.command == \"archive\":\n            print(archive_entries(args.out_dir), file=out)\n"
        "        else:\n            print(team_cost(args.team), file=out)\n")
write(repo, "tests/test_busiest.py", '''import io

from tally.cli import main


def test_busiest_prints_the_team_with_the_most_hours():
    out = io.StringIO()
    assert main(["busiest", "2026-11-21"], stdout=out, stderr=io.StringIO()) == 0
    assert out.getvalue() == "alpha 4.0\\n"


def test_archive_names_the_copy_after_the_date_and_time(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_NOW", "2026-11-16T09:05")
    assert main(["archive", str(tmp_path)], stdout=io.StringIO(), stderr=io.StringIO()) == 0
    assert (tmp_path / "entries-20261116-0905.json").is_file()
''')
replace(repo, "README.md", "- `tally cost TEAM`", "- `tally busiest DATE` prints the team with the most hours on DATE, the earlier name on a tie, or `no entries`.\n"
        "- `tally archive OUT_DIR` copies the entries file to `OUT_DIR/entries-YYYYMMDD-HHMM.json` and prints the path.\n- `tally cost TEAM`")
replace(repo, "docs/ko/README.ko.md", "- `tally cost TEAM`", "- `tally busiest DATE`는 DATE에 시간이 가장 많은 팀을, 같으면 이름이 앞선 팀을 출력하고, 기록이 없으면 `no entries`를 출력합니다.\n"
        "- `tally archive OUT_DIR`은 입력 파일을 `OUT_DIR/entries-YYYYMMDD-HHMM.json`으로 복사하고 경로를 출력합니다.\n- `tally cost TEAM`")
