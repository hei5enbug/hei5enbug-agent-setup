"""Custom check for T39: the result holds a test that fails on the base source and passes on the result."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test)\.py$")
TEST_FAILED = 1
TIMEOUT_SECONDS = 300


def fails_on_base(ctx):
    changed_tests = sorted(path for path in ctx.changes if TEST_FILE.search(path) and ctx.changes[path] in "AM")
    if not changed_tests:
        return False, "no test file was added or changed", {"changed_tests": []}
    root = Path(ctx.work) / "base-source"
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(ctx.repo, root, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"))
    for path, status in ctx.changes.items():
        if TEST_FILE.search(path) or path.startswith("tests/"):
            continue
        target = root / path
        if status == "A":
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(ctx.git("show", f"{ctx.base}:{path}"), encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        code = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=root, env=env,
                              capture_output=True, text=True, timeout=TIMEOUT_SECONDS).returncode
    except subprocess.TimeoutExpired:
        code = -1
    return code == TEST_FAILED, f"the tests exit {code} on the base source", {"base_exit": code, "changed_tests": changed_tests}
