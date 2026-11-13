"""Fingerprint the inputs of a campaign so a resume cannot mix implementations, tasks, or hidden tests."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import plugin_export
from .command import ConfigError, load_task, load_variant
from .config import HarnessConfig

TREES = ("hidden", "custom")
TASK_FILE = re.compile(r"T\d+\.py")
IGNORED_PARTS = frozenset({"__pycache__", ".pytest_cache", ".git"})


def _digest(chunks: Iterable[bytes]) -> str:
    hasher = hashlib.sha256()
    for chunk in chunks:
        hasher.update(chunk)
    return hasher.hexdigest()


def file_digest(path: Path) -> str:
    try:
        return _digest([path.read_bytes()])
    except OSError:
        return "missing"


def tree_digest(root: Path) -> str:
    """Digest of every file name and content below `root` (or of the single file `root`), ignoring caches."""
    if root.is_file():
        return file_digest(root)
    chunks: list[bytes] = []
    files = (item for item in root.rglob("*") if item.is_file() and not IGNORED_PARTS & set(item.relative_to(root).parts))
    for path in sorted(files):
        chunks += [path.relative_to(root).as_posix().encode(), b"\0", path.read_bytes(), b"\0"]
    return _digest(chunks)


def compute_inputs(
    cfg: HarnessConfig, task_ids: list[str], variant_names: list[str], exports: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolved variant shas plus a digest per variant, task, prompt, fixture tree, hidden-test folder, and custom check.

    `exports` maps a variant name to its plugin export record; the digest of each transformed export is part of the inputs."""
    variant_shas = {name: variant_sha(cfg, name) for name in variant_names}
    parts: dict[str, str] = {f"variant:{name}": file_digest(cfg.variants_root / f"{name}.json") for name in variant_names}
    for name, export in sorted((exports or {}).items()):
        if export.get("content_digest"):
            parts[f"export:{name}"] = str(export["content_digest"])
    for task_id in task_ids:
        parts[f"task:{task_id}"] = file_digest(cfg.tasks_root / f"{task_id}.json")
        parts.update(task_content_parts(cfg, task_id))
        for tree in TREES:
            folder = cfg.tasks_root / tree
            for candidate in sorted(folder.iterdir()) if folder.is_dir() else []:
                if candidate.stem == task_id:
                    parts[f"{tree}:{candidate.name}"] = tree_digest(candidate)
    custom = cfg.tasks_root / "custom"
    for shared in sorted(custom.glob("*.py")) if custom.is_dir() else []:
        if not TASK_FILE.fullmatch(shared.name):
            parts[f"custom:{shared.name}"] = file_digest(shared)
    setup = cfg.tasks_root / "setup"
    for shared in sorted(setup.glob("*.py")) if setup.is_dir() else []:
        if not TASK_FILE.fullmatch(shared.name):
            parts[f"setup:{shared.name}"] = file_digest(shared)
    grader = cfg.repo_root / "scripts" / "text_review.py"
    if grader.is_file():
        parts["grader:scripts/text_review.py"] = file_digest(grader)
    shas = {f"sha:{name}": sha for name, sha in variant_shas.items()}
    fingerprint = _digest(f"{key}={value}\n".encode() for key, value in sorted({**parts, **shas}.items()))
    return {"variant_shas": variant_shas, "parts": parts, "fingerprint": fingerprint}


def task_content_parts(cfg: HarnessConfig, task_id: str) -> dict[str, str]:
    """Digests of the task's prompt file and fixture tree; none when the task file cannot be read."""
    try:
        task = load_task(cfg.tasks_root, task_id)
    except ConfigError:
        return {}
    return {
        f"prompt:{task_id}": file_digest(cfg.tasks_root / task["prompt_file"]),
        **({f"setup:{task_id}": file_digest(cfg.tasks_root / task["setup"])} if task.get("setup") else {}),
        f"fixture:{task['fixture']}": tree_digest(cfg.fixtures_root / task["fixture"]),
    }


def variant_sha(cfg: HarnessConfig, name: str) -> str:
    return plugin_export.resolve_ref(cfg.repo_root, load_variant(cfg.variants_root, name)["ref"])


def changed_inputs(stored: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """Names of the inputs present in both records whose sha or digest differs."""
    changes = [
        f"variant sha {name}: {stored['variant_shas'][name][:7]} -> {sha[:7]}"
        for name, sha in sorted(current["variant_shas"].items())
        if name in stored.get("variant_shas", {}) and stored["variant_shas"][name] != sha
    ]
    changes += [
        key for key, digest in sorted(current["parts"].items())
        if key in stored.get("parts", {}) and stored["parts"][key] != digest
    ]
    return changes


def check_inputs(stored: Mapping[str, Any] | None, current: Mapping[str, Any], allow_changed: bool) -> list[str]:
    """Return the changed inputs; refuse them unless `allow_changed`. A campaign with no record has no changes."""
    changes = changed_inputs(stored, current) if stored else []
    if changes and not allow_changed:
        raise ConfigError(
            "inputs changed since the campaign began: " + "; ".join(changes)
            + ". Resuming would mix implementations or tasks; pass --allow-changed-inputs to continue and record it."
        )
    return changes
