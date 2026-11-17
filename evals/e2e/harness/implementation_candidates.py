"""Candidate text of the implementation rules of issue #93 and the code that renders, applies, and detects it.

The rules file `instructions/implementation-rules.md`, its Korean mirror, and the two entry lines that send an implementer to it
exist only while a record keeps at least one rule. Run `python3 evals/e2e/harness/implementation_candidates.py apply a,c` from the
repository root to write the file with exactly those rules and add the entry lines, `apply ''` to remove all three, and
`... show` to print what the repository holds. The extra item `scan` adds the line for the change-scan script and moves
`change_scan.py` from the candidate folder to `scripts/`; it is a candidate measured beside the rules and is not a rule.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable

LANGUAGES = ("en", "ko")
CANDIDATES = Path(__file__).resolve().parent.parent / "candidates" / "93.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN = "scan"


def load(path: Path = CANDIDATES) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def render(language: str, rules: Iterable[str], candidates: dict[str, Any] | None = None) -> str | None:
    """The rules file with exactly the given rules in the canonical order, grouped by condition; None when there are none."""
    candidates = candidates or load()
    chosen = [name for name in candidates["rules"] if name in set(rules)]
    unknown = sorted(set(rules) - set(candidates["rules"]))
    if unknown:
        raise ValueError(f"unknown rule: {', '.join(unknown)}")
    if not chosen:
        return None
    document = candidates["document"]
    parts = [document["title"][language] + "\n\n"]
    if document["source_note"][language]:
        parts.append(document["source_note"][language] + "\n")
    parts.append(document["intro"][language])
    for section, heading in document["sections"].items():
        texts = [candidates["rules"][name]["text"][language] for name in chosen if candidates["rules"][name]["section"] == section]
        if texts:
            parts.append("\n" + heading[language] + "\n\n" + "".join(texts))
    return "".join(parts)


def held_rules(text: str, language: str, candidates: dict[str, Any] | None = None) -> list[str]:
    """The rules whose bullet the rules file holds, in the canonical order."""
    candidates = candidates or load()
    return [name for name, rule in candidates["rules"].items() if rule["text"][language] in text]


def apply_entry(text: str, language: str, entry: dict[str, Any], keep: bool) -> str:
    """The text with the entry line present when `keep` and absent otherwise."""
    anchor, line = entry["insert_after"][language], entry["text"][language]
    if line in text:
        text = text.replace(anchor + line, anchor)
    if not keep:
        return text
    if text.count(anchor) != 1:
        raise ValueError("the line to insert after is not in the file exactly once")
    return text.replace(anchor, anchor + line)


def script_paths(candidates: dict[str, Any] | None = None) -> tuple[Path, Path]:
    scan = (candidates or load())["scan"]
    return REPO_ROOT / scan["candidate"], REPO_ROOT / scan["installed"]


def apply(rules: Iterable[str], root: Path = REPO_ROOT, candidates: dict[str, Any] | None = None, scan: bool | None = None) -> None:
    """Make the repository under `root` hold exactly `rules`: the rules file and its mirror, and both entry lines. `scan`, when not
    None, adds or removes the change-scan line of the execution file and its mirror."""
    candidates = candidates or load()
    rules = list(rules)
    for language in LANGUAGES:
        target = root / candidates["files"]["rules"][language]
        text = render(language, rules, candidates)
        if text is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        for key in ("execution", "delegation"):
            path = root / candidates["files"][key][language]
            path.write_text(apply_entry(path.read_text(encoding="utf-8"), language, candidates["entries"][key], bool(rules)), encoding="utf-8")
        if scan is not None:
            path = root / candidates["files"][candidates["scan"]["file"]][language]
            path.write_text(apply_entry(path.read_text(encoding="utf-8"), language, candidates["scan"], scan), encoding="utf-8")
    if scan:
        candidate, installed = script_paths(candidates)
        if candidate.is_file():
            installed.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
            installed.chmod(candidate.stat().st_mode)
            candidate.unlink()


def repository_state(root: Path = REPO_ROOT, candidates: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the repository under `root` holds: the rules of each language's file, or None for a missing file, and whether each
    entry line is present."""
    candidates = candidates or load()
    state: dict[str, Any] = {"rules": {}, "entries": {}}
    for language in LANGUAGES:
        path = root / candidates["files"]["rules"][language]
        state["rules"][language] = held_rules(path.read_text(encoding="utf-8"), language, candidates) if path.is_file() else None
        for key in ("execution", "delegation"):
            text = (root / candidates["files"][key][language]).read_text(encoding="utf-8")
            state["entries"][f"{key}:{language}"] = candidates["entries"][key]["text"][language] in text
    return state


def main(argv: list[str]) -> int:
    candidates = load()
    if argv[:1] == ["show"]:
        print(json.dumps(repository_state(candidates=candidates), ensure_ascii=False, indent=2))
        return 0
    if len(argv) == 2 and argv[0] == "apply":
        names = [name for name in argv[1].split(",") if name]
        apply([name for name in names if name != SCAN], candidates=candidates, scan=True if SCAN in names else None)
        return 0
    print("usage: implementation_candidates.py show | apply RULE[,RULE][,scan]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
