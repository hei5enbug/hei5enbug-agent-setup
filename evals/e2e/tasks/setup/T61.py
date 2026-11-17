"""T61: a session that hands one result to demo-b, whose workspace holds one never-used shell terminal only.

The session's own workspace also holds a shell terminal that runs a dev server, which no command may reach.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handoff_common import PROMPT_LINE, shell_terminal, build  # noqa: E402

SHELL_HANDLE = "term_demo_b_shell"

if __name__ == "__main__":
    build(sys.argv[1], extra_terminals=lambda main_a, main_b: [
        shell_terminal(SHELL_HANDLE, main_b["id"], [PROMPT_LINE]),
        {**shell_terminal("term_demo_a_dev", main_a["id"], [f"{PROMPT_LINE} npm run dev", "ready on port 3000"]),
         "process": True}])
