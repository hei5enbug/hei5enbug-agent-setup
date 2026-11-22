import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "tally/report.py", "tuple[str, ...]", "list[str]")
replace(repo, "tally/report.py", "return tuple(ranked[:limit])", "return ranked[:limit]")
replace(repo, "tests/test_report.py", '== ("cccc", "aa")', '== ["cccc", "aa"]')
