import sys
from pathlib import Path

from handoff_tools import orca

repo = Path(sys.argv[1])
orca(repo, "orchestration", "send", "--to", "term_sender", "--from", "term_demo_a", "--subject", "Result",
     "--body", "page_size is 20. Kept worktree login spike: it has an uncommitted change.", "--type", "status")
