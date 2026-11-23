import sys
from pathlib import Path

from handoff_tools import orca

repo = Path(sys.argv[1])
orca(repo, "terminal", "send", "--terminal", "term_shell_b", "--text", "claude", "--enter")
orca(repo, "terminal", "wait", "--terminal", "term_shell_b", "--for", "tui-idle", "--timeout-ms", "60000")
orca(repo, "terminal", "send", "--terminal", "term_shell_b", "--enter", "--text",
     "Read the first line of README.md and report it to terminal term_demo_a with orca orchestration send. "
     "Change no file. This terminal belongs to the handoff; close it after your report.")
