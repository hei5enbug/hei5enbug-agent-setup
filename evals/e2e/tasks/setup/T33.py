"""T33: a session that must hand one result to a workspace whose only terminal is a never-used shell terminal."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import OWN_HANDLE, Seed, Terminal, agent, build  # noqa: E402

SEED = Seed(terminals=(agent(OWN_HANDLE, "demo-a"), Terminal("term_shell_b", "demo-b")))

if __name__ == "__main__":
    build(sys.argv[1], SEED)
