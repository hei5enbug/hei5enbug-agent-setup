import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "timesheet/cli.py", "summary.project_totals(store.load())", "summary.project_totals(store.load_cached())")
