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
UNCHECKED_NOTICE = "the command was blocked because it could not be checked"


def main() -> int:
    raw = sys.stdin.read()
    if not GIT_OR_GH.search(raw):
        return 0
    root = Path(__file__).resolve().parents[1]
    scanner = root / SCANNER_DIR
    if not (scanner / SCANNER_MODULE).is_file():
        print(f"public boundary: the scanner folder is missing from the plugin; {UNCHECKED_NOTICE}", file=sys.stderr)
        return BLOCK_EXIT
    sys.path.insert(0, str(scanner))
    try:
        import boundary_agent

        return boundary_agent.run(raw, str(root), project=False)
    except Exception as error:
        print(f"public boundary: the check failed ({type(error).__name__}); {UNCHECKED_NOTICE}", file=sys.stderr)
        return BLOCK_EXIT


if __name__ == "__main__":
    sys.exit(main())
