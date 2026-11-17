"""Print the issue tracker a repository declares in its issue-target.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

USAGE = "usage: find_tracker.py <repository-path>"


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0
    for argument in argv:
        if argument.startswith("-"):
            print(f"error: unknown option {argument}", file=sys.stderr)
            return 2
    if not argv:
        print("error: a repository path is required", file=sys.stderr)
        return 2
    target = Path(argv[0]) / "issue-target.json"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: {target} does not exist", file=sys.stderr)
        return 1
    print(json.dumps(data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
