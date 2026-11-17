"""Candidate text of the testing rules of issue #95 and the code that applies or detects it.

The candidate is applied to the instruction files and their Korean mirrors only for the items a record keeps. Run
`python3 evals/e2e/harness/testing_candidates.py apply restraint,boundaries` from the repository root to apply items, and
`... show` to print which items each file holds. Applying `restraint` also moves `changed_assertions.py` from the candidate
folder to `scripts/`, so the script exists in exactly one place and only where its item is kept.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable

LANGUAGES = ("en", "ko")
CANDIDATES = Path(__file__).resolve().parent.parent / "candidates" / "95.json"
REPO_ROOT = Path(__file__).resolve().parents[3]


def load(path: Path = CANDIDATES) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def edits_of(candidates: dict[str, Any], file_key: str) -> list[tuple[str, dict[str, Any]]]:
    """The (item, edit) pairs for one file, in the canonical order of the items."""
    return [(name, edit) for name, item in candidates["items"].items() for edit in item["edits"] if edit["file"] == file_key]


def apply(text: str, language: str, file_key: str, items: Iterable[str], candidates: dict[str, Any] | None = None) -> str:
    """The text with the candidate lines of `items` added to the file `file_key`. An item already present is not added twice,
    and a later item goes after the earlier items' lines that follow the same anchor."""
    candidates = candidates or load()
    chosen = set(items)
    unknown = sorted(chosen - set(candidates["items"]))
    if unknown:
        raise ValueError(f"unknown item: {', '.join(unknown)}")
    placed: dict[str, str] = {}
    for name, edit in edits_of(candidates, file_key):
        anchor, line = edit["insert_after"][language], edit["text"][language]
        prefix = placed.get(anchor, "")
        if line in text:
            placed[anchor] = prefix + line
            continue
        if name not in chosen:
            continue
        head = anchor + prefix
        if text.count(head) != 1:
            raise ValueError(f"the line to insert after is not in {file_key} exactly once")
        text = text.replace(head, head + line)
        placed[anchor] = prefix + line
    return text


def held_items(text: str, language: str, file_key: str, candidates: dict[str, Any] | None = None) -> list[str]:
    """The items whose lines the file holds, each only when every line of the item that belongs to this file is present."""
    candidates = candidates or load()
    held = []
    for name, item in candidates["items"].items():
        lines = [edit["text"][language] for edit in item["edits"] if edit["file"] == file_key]
        if lines and all(line in text for line in lines):
            held.append(name)
    return held


def script_paths(candidates: dict[str, Any] | None = None) -> tuple[Path, Path]:
    script = (candidates or load())["script"]
    return REPO_ROOT / script["candidate"], REPO_ROOT / script["installed"]


def main(argv: list[str]) -> int:
    candidates = load()
    if argv[:1] == ["show"]:
        for file_key, paths in candidates["files"].items():
            for language in LANGUAGES:
                text = (REPO_ROOT / paths[language]).read_text(encoding="utf-8")
                print(f"{paths[language]}: {held_items(text, language, file_key, candidates)}")
        candidate, installed = script_paths(candidates)
        print(f"script: candidate={candidate.is_file()} installed={installed.is_file()}")
        return 0
    if len(argv) == 2 and argv[0] == "apply":
        items = [name for name in argv[1].split(",") if name]
        for file_key, paths in candidates["files"].items():
            for language in LANGUAGES:
                path = REPO_ROOT / paths[language]
                path.write_text(apply(path.read_text(encoding="utf-8"), language, file_key, items, candidates), encoding="utf-8")
        candidate, installed = script_paths(candidates)
        if any(candidates["items"][name]["script"] for name in items if name in candidates["items"]) and candidate.is_file():
            installed.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
            installed.chmod(candidate.stat().st_mode)
            candidate.unlink()
        return 0
    print("usage: testing_candidates.py show | apply ITEM[,ITEM]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
