"""T59: a handoff session whose terminal belongs to the handoff, with one finished child worktree in its repository."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import build  # noqa: E402

if __name__ == "__main__":
    build(sys.argv[1], child="docs-cleanup")
