import sys

from handoff_tools import orca, report, worktree_id

repo = sys.argv[1]
orca(repo, "worktree", "rm", "--worktree", f"id:{worktree_id(repo, 'docs cleanup')}", "--delete-branch")
report(repo, "The default page_size in config/settings.toml is 20. Removed worktree docs-cleanup; none kept.")
orca(repo, "terminal", "close", "--terminal", "term_demo_a")
