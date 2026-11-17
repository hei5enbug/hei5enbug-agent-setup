"""T62: a session started in demo-a's main clone that also holds a never-used shell terminal and one with typed input."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import PROMPT_LINE, build, shell_terminal  # noqa: E402

if __name__ == "__main__":
    build(sys.argv[1], extra_terminals=lambda main_a, main_b: [
        shell_terminal("term_idle", main_a["id"], [PROMPT_LINE]),
        shell_terminal("term_typed", main_a["id"], [f"{PROMPT_LINE} git sta"])])
