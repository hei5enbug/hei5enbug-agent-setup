import sys

from handoff_tools import orca

repo = sys.argv[1]
orca(repo, "terminal", "send", "--terminal", "term_demo_b_shell", "--text", "claude", "--enter")
orca(repo, "terminal", "send", "--terminal", "term_demo_b_shell", "--enter", "--text",
     "Report the first line of README.md to term_demo_a. This terminal belongs to the handoff; close it after your "
     "report.")
