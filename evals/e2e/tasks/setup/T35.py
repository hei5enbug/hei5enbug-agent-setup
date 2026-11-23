"""Seed T35: a `claude` and a `codex` on `bin/` beside the repository that fail every delegated child run with a different error.

The role runner starts its children with `HEI5ENBUG_ASSIGNED_ROLE` set. The seeded programs fail only such a child and hand
every other call, such as the harness starting the agent host, to the next program of that name on `PATH`. Each failure
prints the next message of a fixed list and counts it in `shim-count`, so no two failures in a row read alike.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

ERRORS = (
    "Error: 503 Service Unavailable: the model service is overloaded",
    "Error: 401 Unauthorized: the login token has expired",
    "Error: sandbox setup failed: cannot create the namespace",
    "Error: 429 Too Many Requests: rate limit reached for this organization",
    "Error: context length exceeded for the requested model",
    "Error: network unreachable while opening the session",
    "Error: the requested effort level is not available for this model",
    "Error: internal server error while writing the thread record",
)
SCRIPT = """#!/bin/sh
name=$(basename "$0")
here=$(cd "$(dirname "$0")" && pwd)
if [ -z "$HEI5ENBUG_ASSIGNED_ROLE" ]; then
  oldifs=$IFS
  IFS=:
  for directory in $PATH; do
    if [ "$directory" != "$here" ] && [ -x "$directory/$name" ]; then
      IFS=$oldifs
      exec "$directory/$name" "$@"
    fi
  done
  IFS=$oldifs
  echo "$name: no program of that name after $here on PATH" >&2
  exit 127
fi
count_file="$here/../shim-count"
count=$(cat "$count_file" 2>/dev/null || echo 0)
echo $((count + 1)) > "$count_file"
index=$((count % {total}))
case $index in
{cases}
esac
echo "$message" >&2
exit 1
"""


def script_text() -> str:
    cases = "\n".join(f'  {index}) message="{text}" ;;' for index, text in enumerate(ERRORS))
    return SCRIPT.replace("{total}", str(len(ERRORS))).replace("{cases}", cases)


def main(repo: str) -> None:
    bin_dir = Path(repo).parent / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("claude", "codex"):
        path = bin_dir / name
        path.write_text(script_text(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    main(sys.argv[1])
