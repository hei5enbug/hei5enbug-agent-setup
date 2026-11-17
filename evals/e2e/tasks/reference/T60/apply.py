import sys

from handoff_tools import report

report(sys.argv[1], "The default page_size in config/settings.toml is 20. Kept worktree login-spike: it has an "
                    "uncommitted change.")
