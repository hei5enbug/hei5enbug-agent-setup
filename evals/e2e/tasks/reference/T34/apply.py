import sys
from pathlib import Path

from handoff_tools import orca

repo = Path(sys.argv[1])
orca(repo, "terminal", "close", "--terminal", "term_shell_empty")
