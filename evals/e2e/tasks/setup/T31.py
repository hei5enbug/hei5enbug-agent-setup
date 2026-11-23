"""T31: a delegate whose terminal belongs to the handoff, in a repository with one finished child worktree."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import OWN_HANDLE, SENDER_HANDLE, Child, Seed, agent, build  # noqa: E402

SEED = Seed(
    children=(Child("docs-cleanup", "docs-cleanup", "docs cleanup"),),
    terminals=(agent(OWN_HANDLE, "demo-a"), agent(SENDER_HANDLE, "demo-b")),
)

if __name__ == "__main__":
    build(sys.argv[1], SEED)
