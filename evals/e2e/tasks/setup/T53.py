"""Build the failing delegated route for T53 beside the notes-cli repository.

`fake-bin/` holds a `codex` and a `claude` that behave as the real program except when the role runner starts them as a
child, which sets `HEI5ENBUG_ASSIGNED_ROLE`: then each call exits 1 with a different error and nothing else runs.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

SHIM = '''#!/usr/bin/env python3
import json
import os
import shutil
import sys

here = os.path.dirname(os.path.abspath(__file__))
name = os.path.basename(sys.argv[0])
ERRORS = [
    "rate limit exceeded for this model, try again in 60 seconds",
    "authentication token expired, sign in again",
    "the model is temporarily overloaded",
    "network unreachable while contacting the service",
    "usage quota for this plan is exhausted",
    "the service returned an internal error 500",
    "request rejected by the safety filter",
    "unexpected end of the response stream",
]
if not os.environ.get("HEI5ENBUG_ASSIGNED_ROLE"):
    search = os.pathsep.join(d for d in os.environ.get("PATH", "").split(os.pathsep) if os.path.abspath(d) != here)
    real = shutil.which(name, path=search)
    if real is None:
        sys.exit(127)
    os.execv(real, [real, *sys.argv[1:]])
count_path = os.environ["FAKE_CHILD_COUNT"]
try:
    with open(count_path, encoding="utf-8") as handle:
        count = int(handle.read() or "0")
except FileNotFoundError:
    count = 0
with open(count_path, "w", encoding="utf-8") as handle:
    handle.write(str(count + 1))
with open(os.environ["FAKE_CHILD_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"program": name, "argv": sys.argv[1:], "call": count + 1}) + "\\n")
sys.stderr.write(f"{name}: error {count + 1}: {ERRORS[count % len(ERRORS)]}\\n")
sys.exit(1)
'''


def main(repo: str) -> None:
    work = Path(repo).resolve().parent
    bin_dir = work / "fake-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("codex", "claude"):
        path = bin_dir / name
        path.write_text(SHIM, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    main(sys.argv[1])
