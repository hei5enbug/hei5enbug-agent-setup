import sys

from handoff_tools import orca

repo = sys.argv[1]
orca(repo, "worktree", "current")
orca(repo, "terminal", "close", "--terminal", "term_idle")
