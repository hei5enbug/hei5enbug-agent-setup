"""Shared helpers of the hidden T37 tests."""

import io
import json
import subprocess
import sys
from pathlib import Path

from notes_cli.cli import main
from notes_cli.settings import Settings

REPO = Path(__file__).resolve().parents[2]

LEGACY = [
    {"id": 1, "title": "Plan trip", "body": "book flights", "tags": ["travel"], "created_at": "2026-01-02T03:04:05+00:00"},
    {"id": 2, "title": "Taxes", "body": "file by April", "tags": [], "created_at": "2026-01-03T03:04:05+00:00"},
]


def run(*argv, store):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--store", str(store), *argv], stdout=out, stderr=err, settings=Settings(page_size=50))
    return code, out.getvalue(), err.getvalue()


def run_process(*argv, cwd):
    return subprocess.run([sys.executable, "-B", "-m", "notes_cli", *argv], cwd=cwd, env={"PYTHONPATH": str(REPO)},
                          capture_output=True, text=True, timeout=60)


def write_legacy(path):
    path.write_text(json.dumps(LEGACY, indent=2) + "\n", encoding="utf-8")
