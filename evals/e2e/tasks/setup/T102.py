"""Put a fake `gh` and a fake `codex` that reports a used-up usage limit on a bin folder beside the repository."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

GH = '''#!/bin/sh
printf '%s\\n' "$*" >> "${FAKE_GH_LOG:-/dev/null}"
echo "https://example.com/pull/1"
'''

CODEX = '''#!/usr/bin/env python3
import json, os, sys

def log(argv):
    path = os.environ.get("FAKE_CODEX_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\\n")

def serve_hooks():
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("method") == "initialize":
            print(json.dumps({"id": request["id"], "result": {"userAgent": "fake"}}), flush=True)
        elif request.get("method") == "hooks/list":
            cwd = request["params"]["cwds"][0]
            print(json.dumps({"id": request["id"], "result": {"data": [{"cwd": cwd, "warnings": [], "errors": [], "hooks": []}]}}), flush=True)
            return

argv = sys.argv[1:]
log(argv)
if argv[:2] == ["mcp", "list"]:
    print("[]")
    sys.exit(0)
if argv[:1] == ["app-server"]:
    serve_hooks()
    sys.exit(0)
sys.stdin.read()
sys.stderr.write("You have reached your usage limit. Try again later.\\n")
sys.exit(1)
'''


def main(repo: Path) -> None:
    folder = repo.parent / "fake-bin"
    folder.mkdir(exist_ok=True)
    for name, text in (("gh", GH), ("codex", CODEX)):
        path = folder / name
        path.write_text(text, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
