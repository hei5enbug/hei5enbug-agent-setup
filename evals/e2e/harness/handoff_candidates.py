"""Candidate text of the handoff fields of issue #94 and the code that applies or detects it.

The candidate is applied to the instruction file and its Korean mirror only for the fields a record keeps. Run
`python3 evals/e2e/harness/handoff_candidates.py apply constraints,behavior` from the repository root to apply fields,
and `... show` to print which fields each file holds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable

LANGUAGES = ("en", "ko")
CANDIDATES = Path(__file__).resolve().parent.parent / "candidates" / "94.json"
REPO_ROOT = Path(__file__).resolve().parents[3]


def load(path: Path = CANDIDATES) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def apply(text: str, language: str, fields: Iterable[str], candidates: dict[str, Any] | None = None) -> str:
    """The instruction text with the candidate lines of `fields` added, and the main-owned sentence widened when any field is
    added. A field already present is not added twice."""
    candidates = candidates or load()
    chosen = [name for name in candidates["fields"] if name in set(fields)]
    unknown = sorted(set(fields) - set(candidates["fields"]))
    if unknown:
        raise ValueError(f"unknown field: {', '.join(unknown)}")
    anchor = candidates["insert_after"][language]
    if text.count(anchor) != 1:
        raise ValueError("the line to insert after is not in the text exactly once")
    lines = "".join(candidates["fields"][name][language] for name in chosen
                    if candidates["fields"][name][language] not in text)
    text = text.replace(anchor, anchor + lines)
    if chosen:
        old, new = (candidates["main_owned"][key][language] for key in ("old", "new"))
        if old in text:
            text = text.replace(old, new)
    return text


def held_fields(text: str, language: str, candidates: dict[str, Any] | None = None) -> dict[str, Any]:
    """Which candidate fields the text holds, and whether it holds the widened main-owned sentence."""
    candidates = candidates or load()
    return {"fields": [name for name, line in candidates["fields"].items() if line[language] in text],
            "main_owned": candidates["main_owned"]["new"][language] in text}


def main(argv: list[str]) -> int:
    candidates = load()
    if argv[:1] == ["show"]:
        for language in LANGUAGES:
            path = REPO_ROOT / candidates["files"][language]
            print(f"{candidates['files'][language]}: {held_fields(path.read_text(encoding='utf-8'), language, candidates)}")
        return 0
    if len(argv) == 2 and argv[0] == "apply":
        fields = [name for name in argv[1].split(",") if name]
        for language in LANGUAGES:
            path = REPO_ROOT / candidates["files"][language]
            path.write_text(apply(path.read_text(encoding="utf-8"), language, fields, candidates), encoding="utf-8")
        return 0
    print("usage: handoff_candidates.py show | apply FIELD[,FIELD]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
