"""T32: a session in a terminal that already ran an agent, with a child worktree that holds an uncommitted change."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import OWN_HANDLE, SENDER_HANDLE, Child, Seed, agent, build  # noqa: E402

SEED = Seed(
    children=(Child("login-spike", "login-spike", "login spike", status="in-progress", dirty=True),),
    terminals=(agent(OWN_HANDLE, "demo-a"), agent(SENDER_HANDLE, "demo-b")),
)

if __name__ == "__main__":
    build(sys.argv[1], SEED)
