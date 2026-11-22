"""T67: demo-a's main clone with a fake Orca beside demo-b; the session creates a worktree of demo-b and starts a worker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import OWN_HANDLE, SENDER_HANDLE, Seed, agent, build  # noqa: E402

SEED = Seed(terminals=(agent(OWN_HANDLE, "demo-a"), agent(SENDER_HANDLE, "demo-b")))

if __name__ == "__main__":
    build(sys.argv[1], SEED)
    (Path(sys.argv[1]).resolve().parent / "orca-user-data").mkdir()
