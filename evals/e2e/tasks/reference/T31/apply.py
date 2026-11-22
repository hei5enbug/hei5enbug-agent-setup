import sys
from pathlib import Path

from handoff_tools import orca, worktree_id

repo = Path(sys.argv[1])
orca(repo, "worktree", "rm", "--worktree", f"id:{worktree_id(repo, 'docs cleanup')}", "--delete-branch")
orca(repo, "orchestration", "send", "--to", "term_sender", "--from", "term_demo_a", "--subject", "Result",
     "--body", "page_size is 20", "--type", "status")
orca(repo, "terminal", "close", "--terminal", "term_demo_a")
