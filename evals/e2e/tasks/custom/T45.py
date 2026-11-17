"""Custom checks for T45: the agent's own tests must pass on a reference limit and fail on four faulty copies of it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

IMPL = ("hidden", "T45", "impl")
REFERENCE = "reference"
FAULTS = ("fault-boundary-low", "fault-boundary-high", "fault-error-type", "fault-error-message")
TEST_FAILED = 1
TIMEOUT_SECONDS = 300


def run_tests_on(ctx, name: str, overlays: tuple[str, ...]) -> int:
    """Exit code of the repository's own tests after the named implementation folders are copied over `shop/`."""
    root = Path(ctx.work) / "faults" / name
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(ctx.repo, root, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"))
    for overlay in overlays:
        shutil.copytree(Path(ctx.tasks_root).joinpath(*IMPL, overlay), root, dirs_exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=root, env=env,
                                   capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return -1
    return completed.returncode


def tests_catch_faults(ctx):
    on_reference = run_tests_on(ctx, REFERENCE, (REFERENCE,))
    exits = {fault: run_tests_on(ctx, fault, (REFERENCE, fault)) for fault in FAULTS}
    missed = [fault for fault, code in exits.items() if code != TEST_FAILED]
    ok = on_reference == 0 and not missed
    return ok, f"reference exit {on_reference}; faults the tests did not fail on: {missed}", {
        "reference_exit": on_reference, "fault_exits": exits, "missed": missed}
