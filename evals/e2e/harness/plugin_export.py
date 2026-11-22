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

from . import markdown_parts
from .config import MODEL_CAP, PLUGIN_NAME

SHA_LENGTH = 7
EXPORT_RECORD = "plugin-export.json"
EXCLUDED_PATHS = ("evals", "docs/ko/evals", "tests/test_e2e_eval_*.py")
CAP_REPLACEMENTS = {r"claude-fable-\d+(?:-\d+)*": "claude-opus-5-5", r"gpt-\d+(?:\.\d+)*-(?:astra|terra)": "gpt-6.1-sol"}
CAP_PATHS = ("config/model-registry.json", "agents", ".codex", "skills", "instructions")
CAP_SUFFIXES = (".md", ".json", ".toml", ".yaml", ".yml", ".txt")
REVIEW_SCRIPT = "scripts/text_review.py"
REVIEW_MODEL_LITERAL = "gpt-6.1-sol"
REVIEW_STAND_IN_MODEL = "claude-sonnet-5-5"
REVIEW_STAND_IN_SUFFIX = "-claude-review"
MODEL_TOKEN = re.compile(r"\b(?:claude-(?:opus|sonnet|haiku|fable)-\d+(?:-\d+)*|gpt-\d+(?:\.\d+)*(?:-[a-z]+)?)")


REMOVAL_KEYS = frozenset({"file", "start", "heading"})
STOCK_PLUGIN = "none"
DIGEST_LENGTH = 8


class ExportError(RuntimeError):
    pass


def stock_record() -> dict[str, Any]:
    """The plugin record of a run that loads no plugin: no revision, no folder."""
    return {"ref": None, "sha": None, "path": None, "stock": True, "removed": [], "cap_transform": None,
            "review_stand_in": None, "content_digest": None}


def normalize_removals(removals: Any) -> list[dict[str, str]]:
    """The `remove` entries of a variant as a list of {file, start} or {file, heading}; raises ExportError on a bad entry."""
    if not isinstance(removals, (list, tuple)):
        raise ExportError("'remove' must be a list")
    entries: list[dict[str, str]] = []
    for index, entry in enumerate(removals):
        label = f"remove[{index}]"
        if not isinstance(entry, dict) or set(entry) - REMOVAL_KEYS or not isinstance(entry.get("file"), str):
            raise ExportError(f"{label}: an entry is {{file, start}} or {{file, heading}}")
        selectors = [key for key in ("start", "heading") if key in entry]
        if len(selectors) != 1 or not isinstance(entry[selectors[0]], str) or not entry[selectors[0]].strip():
            raise ExportError(f"{label}: an entry needs exactly one non-empty 'start' or 'heading'")
        path = Path(entry["file"])
        if path.is_absolute() or ".." in path.parts or not entry["file"].strip():
            raise ExportError(f"{label}: file must be a relative path inside the plugin")
        entries.append({"file": path.as_posix(), selectors[0]: entry[selectors[0]]})
    return entries


def revision_label(sha: str, removals: Any = ()) -> str:
    """What a record calls the revision a run loaded: the sha, followed by `-` and the digest of its `remove` entries when
    parts were cut out, so a removal variant never carries the label of the whole plugin at the same sha."""
    key = removals_key(removals)
    return f"{sha}-{key}" if key else sha


def short_revision(label: str, length: int = 12) -> str:
    """A revision label cut to `length` characters of its sha, keeping the removal digest."""
    head, _, key = label.partition("-")
    return f"{head[:length]}-{key}" if key else head[:length]


def revision_of(plugin: Any) -> str | None:
    """The revision label a run's plugin record holds, or None for a run with no plugin or no stored revision."""
    if not isinstance(plugin, dict):
        return None
    return str(plugin.get("revision") or plugin.get("sha") or "") or None


def removals_key(removals: Any) -> str:
    """Short digest that names an export with parts removed; empty when nothing is removed."""
    entries = normalize_removals(removals)
    if not entries:
        return ""
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()[:DIGEST_LENGTH]


def apply_removals(root: Path, removals: Any) -> list[dict[str, Any]]:
    """Cut each named bullet, paragraph, or section out of its file under `root`. An entry that matches nothing or more than
    one part, or names a missing file, raises ExportError. Every entry is matched against the file as exported, and entries
    of one file may not overlap. Returns one record per entry with the bytes it removed."""
    entries = normalize_removals(removals)
    by_file: dict[str, list[tuple[int, dict[str, str]]]] = {}
    for index, entry in enumerate(entries):
        by_file.setdefault(entry["file"], []).append((index, entry))
    records: dict[int, dict[str, Any]] = {}
    for name, items in by_file.items():
        text = read_text(root / name)
        if text is None:
            raise ExportError(f"remove: cannot read {name} in the exported plugin")
        spans = []
        for index, entry in items:
            try:
                spans.append(markdown_parts.span_of(text, entry.get("start"), entry.get("heading"), f"remove[{index}] {name}"))
            except markdown_parts.PartError as error:
                raise ExportError(str(error)) from error
        try:
            cut = markdown_parts.cut_spans(text, spans)
        except markdown_parts.PartError as error:
            raise ExportError(f"remove {name}: {error}") from error
        (root / name).write_text(cut, encoding="utf-8")
        for (index, entry), span in zip(items, spans):
            lines = text.split("\n")[span[0]:span[1]]
            records[index] = {**entry, "bytes": len("\n".join(lines).encode("utf-8")) + 1}
    return [records[index] for index in sorted(records)]


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


def apply_review_stand_in(root: Path) -> dict[str, str]:
    """Replace the reviewer model literal of the exported text review script by the Claude stand-in, the same for every variant.
    The literal must appear exactly once; any other count rejects the export. Returns what was replaced."""
    path = root / REVIEW_SCRIPT
    text = read_text(path)
    if text is None:
        raise ExportError(f"review stand-in: {REVIEW_SCRIPT} is missing from the export")
    count = text.count(REVIEW_MODEL_LITERAL)
    if count != 1:
        raise ExportError(f"review stand-in: {REVIEW_SCRIPT} names {REVIEW_MODEL_LITERAL} {count} times, expected exactly once")
    path.write_text(text.replace(REVIEW_MODEL_LITERAL, REVIEW_STAND_IN_MODEL), encoding="utf-8")
    return {"model": REVIEW_STAND_IN_MODEL, "file": REVIEW_SCRIPT, "replaced": REVIEW_MODEL_LITERAL}


def content_digest(root: Path) -> str:
    """Digest of every file name and content of the transformed export."""
    hasher = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        hasher.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return hasher.hexdigest()


def export_dir(run_root: Path, sha: str, review_stand_in: bool = False, removals: Any = ()) -> Path:
    """Where a revision is exported; an export with the stand-in or with parts removed has its own folder."""
    key = removals_key(removals)
    suffix = (REVIEW_STAND_IN_SUFFIX if review_stand_in else "") + (f"-{key}" if key else "")
    return run_root / "plugins" / f"{sha[:SHA_LENGTH]}{suffix}" / PLUGIN_NAME


def export_for_variant(repo_root: Path, run_root: Path, variant: dict[str, Any], review_stand_in: bool = False) -> dict[str, Any]:
    """The plugin record a variant runs with: nothing for a stock variant, else its revision exported with its `remove` entries."""
    if variant.get("plugin") == STOCK_PLUGIN:
        return stock_record()
    return export_plugin(repo_root, run_root, variant["ref"], review_stand_in=review_stand_in, removals=variant.get("remove") or ())


def planned_path(repo_root: Path, run_root: Path, variant: dict[str, Any], review_stand_in: bool = False) -> str | None:
    """Where the variant's export goes, or None for a stock variant; nothing is exported."""
    if variant.get("plugin") == STOCK_PLUGIN:
        return None
    sha = resolve_ref(repo_root, variant["ref"])
    return str(export_dir(run_root, sha, review_stand_in, variant.get("remove") or ()))


def export_plugin(repo_root: Path, run_root: Path, ref: str, review_stand_in: bool = False, removals: Any = ()) -> dict[str, Any]:
    """Extract `git archive <ref>` once per sha and return {ref, sha, path}; an existing export is reused.

    The evaluation folder, its Korean mirror, and its unit tests are left out, so an agent that reads the plugin source cannot see hidden
    tests or reference answers. The cap transform then replaces every model above the model cap and rejects an export that still
    names one. With `review_stand_in`, the export also gets the reviewer model stand-in and lives in its own folder.
    `removals` cuts bullets, paragraphs, or sections out of the exported files (see `apply_removals`) and gives the export its
    own folder. An export made with a different exclusion list or transform is rebuilt."""
    removals = normalize_removals(removals)
    sha = resolve_ref(repo_root, ref)
    target = export_dir(run_root, sha, review_stand_in, removals)
    record = target.parent / EXPORT_RECORD
    if record.is_file() and target.is_dir():
        existing = json.loads(record.read_text(encoding="utf-8"))
        if (existing.get("excluded") == list(EXCLUDED_PATHS) and (existing.get("cap_transform") or {}).get("rules_digest") == cap_rules_digest()
                and bool(existing.get("review_stand_in")) == review_stand_in):
            return {**existing, "path": str(target)}
    staging = target.parent.with_name(f".{target.parent.name}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        excludes = [f":(exclude){path}" for path in EXCLUDED_PATHS]
        archive = _git(repo_root, "archive", "--format=tar", sha, "--", ".", *excludes)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(staging / PLUGIN_NAME, filter="data")
        removed = apply_removals(staging / PLUGIN_NAME, removals)
        transform = apply_cap_transform(staging / PLUGIN_NAME)
        stand_in = apply_review_stand_in(staging / PLUGIN_NAME) if review_stand_in else None
        info = {"ref": ref, "sha": sha, "revision": revision_label(sha, removals), "excluded": list(EXCLUDED_PATHS), "removed": removed, "cap_transform": transform,
                "review_stand_in": stand_in,
                "content_digest": content_digest(staging / PLUGIN_NAME)}
        (staging / EXPORT_RECORD).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(target.parent, ignore_errors=True)
        os.replace(staging, target.parent)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {**info, "path": str(target)}
