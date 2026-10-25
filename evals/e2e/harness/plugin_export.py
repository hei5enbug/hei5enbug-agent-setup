"""Export a plugin revision from git into the run root so a run loads exactly that code."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from .config import PLUGIN_NAME

SHA_LENGTH = 7
EXPORT_RECORD = "plugin-export.json"
EXCLUDED_PATHS = ("evals",)


class ExportError(RuntimeError):
    pass


def _git(repo_root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, check=True)
    except (subprocess.CalledProcessError, OSError) as error:
        detail = getattr(error, "stderr", b"") or b""
        raise ExportError(f"git {' '.join(args)} failed: {detail.decode(errors='replace').strip() or error}") from error
    return completed.stdout


def resolve_ref(repo_root: Path, ref: str) -> str:
    """Return the full commit sha for a ref."""
    return _git(repo_root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()


def export_dir(run_root: Path, sha: str) -> Path:
    return run_root / "plugins" / sha[:SHA_LENGTH] / PLUGIN_NAME


def export_plugin(repo_root: Path, run_root: Path, ref: str) -> dict[str, Any]:
    """Extract `git archive <ref>` once per sha and return {ref, sha, path}; an existing export is reused.

    The evaluation folder is left out, so an agent that reads the plugin source cannot see hidden tests."""
    sha = resolve_ref(repo_root, ref)
    target = export_dir(run_root, sha)
    record = target.parent / EXPORT_RECORD
    if record.is_file() and target.is_dir():
        return {**json.loads(record.read_text(encoding="utf-8")), "path": str(target)}
    staging = target.parent.with_name(f".{sha[:SHA_LENGTH]}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        excludes = [f":(exclude){path}" for path in EXCLUDED_PATHS]
        archive = _git(repo_root, "archive", "--format=tar", sha, "--", ".", *excludes)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(staging / PLUGIN_NAME, filter="data")
        info = {"ref": ref, "sha": sha, "excluded": list(EXCLUDED_PATHS)}
        (staging / EXPORT_RECORD).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(target.parent, ignore_errors=True)
        os.replace(staging, target.parent)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {**info, "path": str(target)}
