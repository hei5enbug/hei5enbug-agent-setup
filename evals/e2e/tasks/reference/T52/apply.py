import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "timesheet/cli.py", '    listing.add_argument("--on")\n', '    listing.add_argument("--on")\n    listing.add_argument("--since")\n')
replace(repo, "timesheet/cli.py", 'def list_lines(entries: list[dict[str, Any]], on: str | None = None) -> list[str]:', 'def list_lines(entries: list[dict[str, Any]], on: str | None = None, since: str | None = None) -> list[str]:')
replace(repo, "timesheet/cli.py", '    chosen = [entry for entry in entries if wanted is None or entry["date"] == wanted]', '    floor = parse_date(since).isoformat() if since else None\n    chosen = [e for e in entries if (wanted is None or e["date"] == wanted) and (floor is None or e["date"] >= floor)]')
replace(repo, "timesheet/cli.py", 'list_lines(store.load_cached(), args.on))', 'list_lines(store.load_cached(), args.on, args.since))')
replace(repo, "README.md", "| `list [--on DATE]` | Prints entries, one per line, oldest date first. |", "| `list [--on DATE] [--since DATE]` | Prints entries, one per line, oldest date first; `--since` keeps the entries on or after `DATE`. |")
replace(repo, "docs/ko/README.ko.md", "| `list [--on DATE]` | 기록을 한 줄씩, 날짜가 이른 것부터 보여 줍니다. |", "| `list [--on DATE] [--since DATE]` | 기록을 한 줄씩, 날짜가 이른 것부터 보여 줍니다. `--since`는 `DATE` 이후(그날 포함)의 기록만 남깁니다. |")
