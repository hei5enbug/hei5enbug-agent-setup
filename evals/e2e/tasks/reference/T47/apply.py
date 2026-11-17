import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "timesheet/cli.py", '    listing.add_argument("--on")\n', '    listing.add_argument("--on")\n    listing.add_argument("--project")\n    remove = sub.add_parser("delete")\n    remove.add_argument("id", type=int)\n')
replace(repo, "timesheet/cli.py", 'def list_lines(entries: list[dict[str, Any]], on: str | None = None) -> list[str]:', 'def list_lines(entries: list[dict[str, Any]], on: str | None = None, project: str | None = None) -> list[str]:')
replace(repo, "timesheet/cli.py", '    chosen = [entry for entry in entries if wanted is None or entry["date"] == wanted]', '    chosen = [entry for entry in entries if (wanted is None or entry["date"] == wanted) and (project is None or entry["project"] == project)]')
replace(repo, "timesheet/cli.py", 'list_lines(store.load_cached(), args.on))', 'list_lines(store.load_cached(), args.on, args.project))')
replace(repo, "timesheet/cli.py", '    elif args.command == "totals":', '''    elif args.command == "delete":
        if not store.delete(args.id):
            sys.stderr.write(f"no such entry: {args.id}\\n")
            return 1
        out.write(f"deleted {args.id}\\n")
    elif args.command == "totals":''')
replace(repo, "README.md", "| `list [--on DATE]` | Prints entries, one per line, oldest date first. |", "| `list [--on DATE] [--project NAME]` | Prints entries, one per line, oldest date first; `--project` keeps the entries whose project is exactly `NAME`. |\n| `delete ID` | Deletes the entry with that id. |")
replace(repo, "docs/ko/README.ko.md", "| `list [--on DATE]` | 기록을 한 줄씩, 날짜가 이른 것부터 보여 줍니다. |", "| `list [--on DATE] [--project NAME]` | 기록을 한 줄씩, 날짜가 이른 것부터 보여 줍니다. `--project`는 프로젝트가 `NAME`과 정확히 같은 기록만 남깁니다. |\n| `delete ID` | 그 id의 기록을 지웁니다. |")
