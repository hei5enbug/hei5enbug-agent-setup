import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "timesheet/cli.py", "    return [entry_line(entry) for entry in sorted(chosen, key=lambda entry: entry[\"date\"])]", "    return [entry_line(entry) for entry in chosen]")
replace(repo, "README.md", "one per line, oldest date first.", "one per line, in the order the data file holds them.")
replace(repo, "docs/ko/README.ko.md", "기록을 한 줄씩, 날짜가 이른 것부터 보여 줍니다.", "기록을 한 줄씩, 데이터 파일에 있는 순서대로 보여 줍니다.")
