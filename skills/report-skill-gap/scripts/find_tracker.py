#!/usr/bin/env python3
"""Find and validate the issue tracker that the plugin owning a path declares for skill and instruction gaps."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

MANIFEST_DIRS = (".claude-plugin", ".codex-plugin")
MANIFEST_NAME = "plugin.json"
DECLARATION_NAME = "issue-target.json"
ALLOWED_KEYS = (
    "version",
    "tracker",
    "language",
    "body_format",
    "labels",
    "public",
    "write_approval",
    "content_rules",
    "recommend",
)
OPTIONAL_KEYS = ("content_rules", "recommend")
REQUIRED_KEYS = tuple(key for key in ALLOWED_KEYS if key not in OPTIONAL_KEYS)
TRACKER_KINDS = ("github", "gitlab", "jira", "other")
BODY_FORMATS = ("markdown", "jira-wiki", "plain", "html")
WRITE_APPROVALS = ("preview", "direct")
GITHUB_LOCATION = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
SKILL_PLACEHOLDER = "{skill}"
LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
UNREADABLE_JSON = (ValueError, RecursionError)
EXIT_OK = 0
EXIT_INVALID = 1
EXIT_USAGE = 2


class UsageError(Exception):
    """The arguments do not identify a plugin."""


def find_plugin_root(path: Path) -> Path:
    start = path if path.is_dir() else path.parent
    for candidate in (start, *start.parents):
        if any((candidate / folder / MANIFEST_NAME).is_file() for folder in MANIFEST_DIRS):
            return candidate
    raise UsageError(f"no plugin root above: {path}")


def load_json(path: Path) -> Any:
    return json.loads(path.read_bytes().decode("utf-8"))


def read_plugin_name(root: Path) -> str | None:
    for folder in MANIFEST_DIRS:
        manifest = root / folder / MANIFEST_NAME
        try:
            name = load_json(manifest).get("name")
        except (OSError, AttributeError, *UNREADABLE_JSON):
            continue
        if isinstance(name, str) and name:
            return name
    return None


def find_declaration(root: Path) -> Path | None:
    candidate = root / DECLARATION_NAME
    return candidate if candidate.is_file() else None


def is_text(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def check_keys(data: dict[str, Any]) -> list[str]:
    unknown = [f"unknown key: {key}" for key in data if key not in ALLOWED_KEYS]
    missing = [f"missing required key: {key}" for key in REQUIRED_KEYS if key not in data]
    return [*unknown, *missing]


def check_version(value: Any) -> list[str]:
    valid = isinstance(value, int) and not isinstance(value, bool) and value == 1
    return [] if valid else ["version: must be the integer 1"]


def check_tracker(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["tracker: must be an object"]
    problems = []
    if set(value) != {"kind", "location"}:
        problems.append("tracker: keys must be exactly kind and location")
    kind = value.get("kind")
    if kind not in TRACKER_KINDS or not isinstance(kind, str):
        problems.append("tracker.kind: must be one of github, gitlab, jira, other")
    problems.extend(check_location(kind, value.get("location")))
    return problems


def check_location(kind: Any, location: Any) -> list[str]:
    if not is_text(location) or location != location.strip():
        return ["tracker.location: must be a non-empty string without surrounding whitespace"]
    if kind == "github" and not GITHUB_LOCATION.fullmatch(location):
        return ["tracker.location: a github location must be owner/repo"]
    return []


def check_language(value: Any) -> list[str]:
    valid = isinstance(value, str) and LANGUAGE.fullmatch(value) is not None
    return [] if valid else ["language: must be a language tag such as en or pt-BR"]


def check_choice(field: str, value: Any, choices: Sequence[str]) -> list[str]:
    valid = isinstance(value, str) and value in choices
    return [] if valid else [f"{field}: must be one of {', '.join(choices)}"]


def check_labels(value: Any) -> list[str]:
    if isinstance(value, str):
        return check_label_template(value)
    if not isinstance(value, list):
        return ["labels: must be a list or a template string"]
    problems = []
    if not all(is_text(label) for label in value):
        problems.append("labels: every label must be a non-empty string")
    texts = [label for label in value if isinstance(label, str)]
    if len(set(texts)) != len(texts):
        problems.append("labels: must not contain duplicates")
    return problems


def check_label_template(value: str) -> list[str]:
    problems = []
    tags = [tag.strip() for tag in value.split(";")]
    if not all(tags):
        problems.append("labels: a template needs non-empty tags separated by ;")
    if len(set(tags)) != len(tags):
        problems.append("labels: a template must not contain duplicate tags")
    for placeholder in PLACEHOLDER.findall(value):
        if placeholder != SKILL_PLACEHOLDER:
            problems.append(f"labels: unknown placeholder {placeholder}; the only placeholder is {SKILL_PLACEHOLDER}")
    if re.search(r"[{}]", PLACEHOLDER.sub("", value)):
        problems.append("labels: unbalanced brace in the template")
    return problems


def check_public(value: Any) -> list[str]:
    return [] if isinstance(value, bool) else ["public: must be a boolean"]


def check_recommend(value: Any) -> list[str]:
    return [] if isinstance(value, bool) else ["recommend: must be a boolean"]


def resolve_content_rules(value: Any, root: Path) -> tuple[Path | None, list[str]]:
    if not is_text(value):
        return None, ["content_rules: must be a non-empty string"]
    if value.startswith("/") or "\\" in value:
        return None, ["content_rules: must be a relative POSIX path"]
    try:
        resolved = (root / value).resolve()
    except (OSError, ValueError, RuntimeError):
        return None, ["content_rules: path cannot be resolved"]
    if not resolved.is_relative_to(root):
        return None, ["content_rules: resolves outside the plugin root"]
    if not resolved.is_file():
        return None, ["content_rules: must name an existing regular file"]
    return resolved, []


def validate(data: Any, root: Path) -> tuple[Path | None, list[str]]:
    if not isinstance(data, dict):
        return None, ["top level: must be a JSON object"]
    problems = check_keys(data)
    checks = {
        "version": check_version,
        "tracker": check_tracker,
        "language": check_language,
        "body_format": lambda value: check_choice("body_format", value, BODY_FORMATS),
        "labels": check_labels,
        "public": check_public,
        "recommend": check_recommend,
        "write_approval": lambda value: check_choice("write_approval", value, WRITE_APPROVALS),
    }
    for field, check in checks.items():
        if field in data:
            problems.extend(check(data[field]))
    rules = None
    if "content_rules" in data:
        rules, rules_problems = resolve_content_rules(data["content_rules"], root)
        problems.extend(rules_problems)
    return rules, problems


def build_target(data: dict[str, Any], rules: Path | None) -> dict[str, Any]:
    return {
        "version": data["version"],
        "tracker": data["tracker"],
        "language": data["language"],
        "body_format": data["body_format"],
        "labels": data["labels"],
        "label_mode": "template" if isinstance(data["labels"], str) else "pick",
        "public": data["public"],
        "write_approval": data["write_approval"],
        "content_rules": str(rules) if rules is not None else None,
        "recommend": data.get("recommend", False),
        "preview_required": data["public"] or data["write_approval"] == "preview",
    }


def load_declaration(declaration: Path) -> tuple[Any, list[str]]:
    try:
        return load_json(declaration), []
    except OSError as error:
        return None, [f"declaration: cannot be read: {error.strerror or type(error).__name__}"]
    except UnicodeDecodeError:
        return None, ["declaration: is not valid UTF-8"]
    except UNREADABLE_JSON:
        return None, ["declaration: is not valid JSON"]


def report(root: Path, declaration: Path | None) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {
        "plugin_root": str(root),
        "plugin_name": read_plugin_name(root),
        "declaration": str(declaration) if declaration is not None else None,
        "status": "undeclared",
        "target": None,
        "problems": [],
    }
    if declaration is None:
        return result, EXIT_OK
    data, problems = load_declaration(declaration)
    rules = None
    if not problems:
        rules, problems = validate(data, root)
    if problems:
        return {**result, "status": "invalid", "problems": problems}, EXIT_INVALID
    return {**result, "status": "declared", "target": build_target(data, rules)}, EXIT_OK


def locate(argv: Sequence[str]) -> Path:
    if len(argv) != 1:
        raise UsageError("usage: find_tracker.py <path>")
    path = Path(argv[0])
    if not path.exists():
        raise UsageError(f"path does not exist: {argv[0]}")
    return find_plugin_root(path.resolve())


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: Sequence[str]) -> int:
    try:
        root = locate(argv)
    except UsageError as error:
        emit({"error": str(error)})
        print(str(error), file=sys.stderr)
        return EXIT_USAGE
    result, code = report(root, find_declaration(root))
    emit(result)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
