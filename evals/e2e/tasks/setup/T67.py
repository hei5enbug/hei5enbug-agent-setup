"""T67: demo-a's main clone with a fake Orca beside demo-b; the session creates a worktree of demo-b and starts a worker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import build  # noqa: E402

if __name__ == "__main__":
    build(sys.argv[1])
