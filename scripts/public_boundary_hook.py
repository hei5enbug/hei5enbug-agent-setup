"""PreToolUse hook: block a git or gh write to a public repository an installed plugin declares, from any project.

The scanner lives in the plugin's .githooks folder. Nothing beyond the standard library loads until the
tool input names git or gh.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

GIT_OR_GH = re.compile(r"(?:\b|(?<=\\[nrt]))(?:git|gh)\b")
SCANNER_DIR = ".githooks"
SCANNER_MODULE = "boundary_agent.py"
BLOCK_EXIT = 2
UNCHECKED_NOTICE = "so the command was blocked because it could not be checked"
HOOK_LABEL = "hei5enbug-agent-setup public boundary hook"


def main() -> int:
    raw = sys.stdin.read()
    if not GIT_OR_GH.search(raw):
        return 0
    root = Path(__file__).resolve().parents[1]
    scanner = root / SCANNER_DIR
    if not (scanner / SCANNER_MODULE).is_file():
        print(
            f"{HOOK_LABEL}: the scanner folder is missing from the plugin, {UNCHECKED_NOTICE}. "
            "Reinstall the plugin, then run the command again.",
            file=sys.stderr,
        )
        return BLOCK_EXIT
    sys.path.insert(0, str(scanner))
    try:
        import boundary_agent

        return boundary_agent.run(raw, str(root), project=False)
    except Exception as error:
        print(
            f"{HOOK_LABEL}: the check failed ({type(error).__name__}), {UNCHECKED_NOTICE}. "
            "Run the command again; if it repeats, report the error name.",
            file=sys.stderr,
        )
        return BLOCK_EXIT


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hook_runtime

    sys.exit(hook_runtime.run("public_boundary_hook.py", main))
