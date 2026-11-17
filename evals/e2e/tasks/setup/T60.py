"""T60: a handoff session in a terminal that already ran an agent, with a child worktree holding an uncommitted change."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import build  # noqa: E402

if __name__ == "__main__":
    build(sys.argv[1], child="login-spike", dirty_child=True)
