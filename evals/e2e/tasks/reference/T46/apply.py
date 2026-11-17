import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "timesheet/summary.py", "from typing import Any, Iterable\n", "from datetime import date, timedelta\nfrom typing import Any, Iterable\n")
append(repo, "timesheet/summary.py", '''

def week_bounds(day: date) -> tuple[date, date]:
    """The Sunday that starts the week of `day` and the Saturday that ends it."""
    start = day - timedelta(days=(day.weekday() + 1) % 7)
    return start, start + timedelta(days=6)
''')
replace(repo, "timesheet/cli.py", '    sub.add_parser("report")\n', '    sub.add_parser("report")\n    weekly = sub.add_parser("weekly")\n    weekly.add_argument("--on", required=True)\n')
replace(repo, "timesheet/cli.py", '''    else:
        entries = store.load()
        start =''', '''    elif args.command == "weekly":
        first, last = summary.week_bounds(parse_date(args.on))
        week = [e for e in store.load() if first.isoformat() <= e["date"] <= last.isoformat()]
        out.writelines(f"{project} {minutes}\\n" for project, minutes in summary.project_totals(week).items())
    else:
        entries = store.load()
        start =''')
replace(repo, "timesheet/exporter.py", 'FILE_NAME = "export.csv"\n', 'FILE_PATTERN = "export-%Y%m%d-%H%M%S.csv"\n')
replace(repo, "timesheet/exporter.py", "import csv\n", "import csv\nfrom datetime import datetime\n")
replace(repo, "timesheet/exporter.py", "    target = folder / FILE_NAME\n", "    target = folder / datetime.now().strftime(FILE_PATTERN)\n")
replace(repo, "README.md", "| `report` | Prints the list, then the totals. |\n", "| `report` | Prints the list, then the totals. |\n| `weekly --on DATE` | Prints the minutes of each project in the week of `DATE`, which starts on Sunday. |\n")
replace(repo, "README.md", "Writes the entries to a CSV file in the export folder. |", "Writes the entries to `export-YYYYMMDD-HHMMSS.csv` in the export folder. |")
replace(repo, "docs/ko/README.ko.md", "| `report` | 목록을 보여 준 뒤 합계를 보여 줍니다. |\n", "| `report` | 목록을 보여 준 뒤 합계를 보여 줍니다. |\n| `weekly --on DATE` | `DATE`가 속한 주(일요일에 시작)의 프로젝트별 분을 보여 줍니다. |\n")
replace(repo, "docs/ko/README.ko.md", "기록을 내보내기 폴더의 CSV 파일에 씁니다. |", "기록을 내보내기 폴더의 `export-YYYYMMDD-HHMMSS.csv`에 씁니다. |")
