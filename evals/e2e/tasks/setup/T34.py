"""T34: a session started in a workspace that also holds a never-used shell terminal and one with typed input."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import OWN_HANDLE, Seed, Terminal, agent, build  # noqa: E402

SEED = Seed(terminals=(
    agent(OWN_HANDLE, "demo-a"),
    Terminal("term_shell_empty", "demo-a"),
    Terminal("term_shell_typed", "demo-a", typed="git sta"),
))

if __name__ == "__main__":
    build(sys.argv[1], SEED)
