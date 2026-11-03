"""Find the installed plugins that declare a public GitHub repository or a private word list.

Nothing here prints or copies a word; problems name the plugin and the reason only.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from public_boundary import PRIVATE_WORDS_ENV, PrivateWords, compile_private_words, env_word_list, read_word_file

TARGET_FILE = "issue-target.json"
WORDS_DECLARATION = "public-boundary.json"
WORDS_KEYS = {"version", "private_words_file"}
OWN_ROOT_VARIABLES = ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")
MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")
GITHUB_LOCATION = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
VERSION_CORE = re.compile(r"[0-9]+(?:\.[0-9]+)*")


@dataclass(frozen=True)
class WordSources:
    words: tuple[re.Pattern[str], ...]
    lists: int
    problems: tuple[str, ...]
    notes: tuple[str, ...] = ()


def _home(environ: dict[str, str], variable: str, default: str) -> Path:
    value = environ.get(variable)
    return Path(value).expanduser() if value else Path.home() / default


def _version_key(version: Path) -> tuple[int, ...] | None:
    core = re.split(r"[+-]", version.name, maxsplit=1)[0]
    if VERSION_CORE.fullmatch(core) is None:
        return None
    return tuple(int(part) for part in core.split("."))


def _newest(versions: list[Path]) -> Path:
    if all(_version_key(version) is not None for version in versions):
        return max(versions, key=lambda version: (_version_key(version), version.stat().st_mtime))
    return max(versions, key=lambda version: version.stat().st_mtime)


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _claude_roots(home: Path) -> list[Path]:
    installed = _read_json(home / "plugins" / "installed_plugins.json")
    plugins = installed.get("plugins") if isinstance(installed, dict) else None
    if not isinstance(plugins, dict):
        return []
    roots = []
    for installs in plugins.values():
        for install in installs if isinstance(installs, list) else []:
            path = install.get("installPath") if isinstance(install, dict) else None
            if isinstance(path, str) and path:
                roots.append(Path(path))
    return roots


def _codex_roots(home: Path) -> list[Path]:
    roots = []
    try:
        for plugin in sorted(home.glob("plugins/cache/*/*")):
            versions = [version for version in plugin.iterdir() if version.is_dir()] if plugin.is_dir() else []
            if versions:
                roots.append(_newest(versions))
    except OSError:
        return roots
    return roots


def installed_roots(environ: dict[str, str], own_roots: tuple[Path, ...] = ()) -> tuple[Path, ...]:
    """The running plugin's roots, then every Claude Code install and the newest cached Codex version of each plugin."""
    candidates = [Path(environ[name]) for name in OWN_ROOT_VARIABLES if environ.get(name)]
    candidates = [*own_roots, *candidates, *_claude_roots(_home(environ, "CLAUDE_CONFIG_DIR", ".claude"))]
    candidates.extend(_codex_roots(_home(environ, "CODEX_HOME", ".codex")))
    seen: dict[str, Path] = {}
    for root in candidates:
        try:
            seen.setdefault(os.path.realpath(root), root)
        except OSError:
            continue
    return tuple(seen.values())


def normalize_location(location: str) -> str:
    return location.strip().lower()


def declared_repository(root: Path) -> str | None:
    """The GitHub repository the plugin root declares public in issue-target.json, normalized."""
    data = _read_json(root / TARGET_FILE)
    tracker = data.get("tracker") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("public") is not True or not isinstance(tracker, dict):
        return None
    location = tracker.get("location")
    if tracker.get("kind") != "github" or not isinstance(location, str):
        return None
    return normalize_location(location) if GITHUB_LOCATION.fullmatch(location) else None


def protected_repositories(roots: tuple[Path, ...]) -> frozenset[str]:
    return frozenset(name for name in map(declared_repository, roots) if name)


def plugin_name(root: Path) -> str:
    for manifest in MANIFESTS:
        data = _read_json(root / manifest)
        name = data.get("name") if isinstance(data, dict) else None
        if isinstance(name, str) and name:
            return name
    return root.parent.name if _version_key(root) is not None else root.name


def declared_words_file(root: Path) -> tuple[Path | None, str | None]:
    """The word file the plugin root declares, and the reason its declaration cannot be used."""
    declaration = root / WORDS_DECLARATION
    if not declaration.exists():
        return None, None
    data = _read_json(declaration)
    if not isinstance(data, dict) or set(data) != WORDS_KEYS or data.get("version") != 1:
        return None, f"{WORDS_DECLARATION} must hold exactly version 1 and private_words_file"
    relative = data["private_words_file"]
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None, "private_words_file must be a path relative to the plugin root"
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        return None, "private_words_file must stay inside the plugin root"
    return resolved, None


@dataclass(frozen=True)
class DeclaredList:
    words: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...] = ()
    allowed_identity_emails: frozenset[str] = frozenset()


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def read_declared_list(path: Path) -> DeclaredList:
    """A declared list: one word or phrase per line, or, for a `.json` file, a `words` list of strings, an optional
    `patterns` list of `{"regex", "ignore_case"}` entries, and an optional `allowed_identity_emails` list."""
    if path.suffix != ".json":
        return DeclaredList(tuple(read_word_file(path)))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("a JSON word file holds one object")
    words, entries, emails = data.get("words"), data.get("patterns", []), data.get("allowed_identity_emails", [])
    if not _string_list(words) or not isinstance(entries, list) or not _string_list(emails):
        raise ValueError("a JSON word file needs a words list of strings and optional patterns and email lists")
    patterns = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("regex"), str):
            raise ValueError("each pattern needs a regex string")
        patterns.append(re.compile(entry["regex"], re.IGNORECASE if entry.get("ignore_case") is True else 0))
    kept = tuple(word.strip() for word in words if word.strip())
    return DeclaredList(kept, tuple(patterns), frozenset(email.strip().lower() for email in emails))


def _read_declared(root: Path) -> tuple[DeclaredList | None, str | None]:
    path, problem = declared_words_file(root)
    if path is None and problem is None:
        return None, None
    if problem is None:
        try:
            return read_declared_list(path), None
        except (OSError, UnicodeDecodeError):
            problem = "the word file could not be read"
        except (ValueError, re.error):
            problem = "the word file is not a valid word list"
    return None, f"{plugin_name(root)}: {problem}"


def word_sources(roots: tuple[Path, ...], environ: dict[str, str], exclude: Path) -> WordSources:
    """The environment list and every declared list, compiled, with the lists read and the problems found."""
    lists: dict[str, DeclaredList] = {}
    problems: list[str] = []
    notes: list[str] = []
    env_path, env_words, note = env_word_list(exclude, environ)
    if note:
        notes.append(note)
    if env_path is not None:
        lists[os.path.realpath(env_path)] = DeclaredList(tuple(env_words))
    for root in roots:
        found, problem = _read_declared(root)
        if problem:
            problems.append(problem)
        if found is not None:
            lists.setdefault(os.path.realpath(declared_words_file(root)[0]), found)
    merged = [word for found in lists.values() for word in found.words]
    patterns = compile_private_words(merged) + tuple(pattern for found in lists.values() for pattern in found.patterns)
    emails = frozenset(email for found in lists.values() for email in found.allowed_identity_emails)
    return WordSources(PrivateWords(patterns, emails), len(lists), tuple(problems), tuple(notes))


NO_LIST_NOTICE = (
    f"Public boundary: no private word list was found (neither {PRIVATE_WORDS_ENV} nor an installed plugin's "
    f"{WORDS_DECLARATION} provides one), so this public write was checked for home paths, secrets, and email "
    "addresses only, not for private names."
)
