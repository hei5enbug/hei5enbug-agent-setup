"""Export a plugin revision from git into the run root so a run loads exactly that code."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from .config import MODEL_CAP, PLUGIN_NAME

SHA_LENGTH = 7
EXPORT_RECORD = "plugin-export.json"
EXCLUDED_PATHS = ("evals", "docs/ko/evals", "tests/test_e2e_eval_*.py")
CAP_REPLACEMENTS = {r"claude-fable-\d+(?:-\d+)*": "claude-opus-5-5", r"gpt-\d+(?:\.\d+)*-(?:astra|terra)": "gpt-6.1-sol"}
CAP_PATHS = ("config/model-registry.json", "agents", ".codex", "skills", "instructions")
CAP_SUFFIXES = (".md", ".json", ".toml", ".yaml", ".yml", ".txt")
MODEL_TOKEN = re.compile(r"\b(?:claude-(?:opus|sonnet|haiku|fable)-\d+(?:-\d+)*|gpt-\d+(?:\.\d+)*(?:-[a-z]+)?)")


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


def cap_rules_digest() -> str:
    rules = {"replacements": CAP_REPLACEMENTS, "paths": CAP_PATHS, "suffixes": CAP_SUFFIXES}
    return hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()


def stand_in(model: str) -> str | None:
    """The in-cap model that replaces a model above the cap of the same family, or None when the model is not above the cap."""
    return next((target for pattern, target in CAP_REPLACEMENTS.items() if re.fullmatch(pattern, model)), None)


def cap_files(root: Path) -> list[Path]:
    """Text files of the export that name models: the registry, agents, Codex roles, skills, and instructions."""
    found: list[Path] = []
    for name in CAP_PATHS:
        base = root / name
        candidates = [base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []
        found += [item for item in candidates if item.is_file() and item.suffix in CAP_SUFFIXES]
    return found


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def apply_cap_transform(root: Path) -> dict[str, Any]:
    """Replace each model above the cap by its in-cap stand-in in every exported revision, the same for every variant,
    then scan again and reject the export when any model outside the cap is left. Returns what was replaced."""
    replaced: dict[str, int] = {}
    for path in cap_files(root):
        text = read_text(path)
        if text is None:
            continue
        def swap(match: re.Match[str]) -> str:
            model = match.group(0)
            target = stand_in(model)
            if target is None:
                return model
            replaced[model] = replaced.get(model, 0) + 1
            return target
        swapped = MODEL_TOKEN.sub(swap, text)
        if swapped != text:
            path.write_text(swapped, encoding="utf-8")
    left = sorted({(path.relative_to(root).as_posix(), model) for path in cap_files(root)
                   for model in MODEL_TOKEN.findall(read_text(path) or "") if model not in MODEL_CAP})
    if left:
        cap = ", ".join(sorted(MODEL_CAP))
        raise ExportError("model cap: " + "; ".join(
            f"plugin export: role defined in {path} would run {model}, which is outside the model cap ({cap})" for path, model in left))
    return {"replacements": dict(CAP_REPLACEMENTS), "replaced": dict(sorted(replaced.items())), "count": sum(replaced.values()),
            "rules_digest": cap_rules_digest()}


def content_digest(root: Path) -> str:
    """Digest of every file name and content of the transformed export."""
    hasher = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        hasher.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return hasher.hexdigest()


def export_dir(run_root: Path, sha: str) -> Path:
    return run_root / "plugins" / sha[:SHA_LENGTH] / PLUGIN_NAME


def export_plugin(repo_root: Path, run_root: Path, ref: str) -> dict[str, Any]:
    """Extract `git archive <ref>` once per sha and return {ref, sha, path}; an existing export is reused.

    The evaluation folder, its Korean mirror, and its unit tests are left out, so an agent that reads the plugin source cannot see hidden
    tests or reference answers. The cap transform then replaces every model above the model cap and rejects an export that still
    names one. An export made with a different exclusion list or transform is rebuilt."""
    sha = resolve_ref(repo_root, ref)
    target = export_dir(run_root, sha)
    record = target.parent / EXPORT_RECORD
    if record.is_file() and target.is_dir():
        existing = json.loads(record.read_text(encoding="utf-8"))
        if existing.get("excluded") == list(EXCLUDED_PATHS) and (existing.get("cap_transform") or {}).get("rules_digest") == cap_rules_digest():
            return {**existing, "path": str(target)}
    staging = target.parent.with_name(f".{sha[:SHA_LENGTH]}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        excludes = [f":(exclude){path}" for path in EXCLUDED_PATHS]
        archive = _git(repo_root, "archive", "--format=tar", sha, "--", ".", *excludes)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(staging / PLUGIN_NAME, filter="data")
        transform = apply_cap_transform(staging / PLUGIN_NAME)
        info = {"ref": ref, "sha": sha, "excluded": list(EXCLUDED_PATHS), "cap_transform": transform,
                "content_digest": content_digest(staging / PLUGIN_NAME)}
        (staging / EXPORT_RECORD).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(target.parent, ignore_errors=True)
        os.replace(staging, target.parent)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {**info, "path": str(target)}
