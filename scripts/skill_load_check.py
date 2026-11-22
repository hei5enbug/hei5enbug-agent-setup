from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

EXIT_ACCEPTED = 0
EXIT_REJECTED = 1
EXIT_USAGE = 2
EXIT_EVIDENCE = 4
CODEX_CALL_TYPES = frozenset({"function_call", "local_shell_call", "custom_tool_call"})
SKILL_FILE = re.compile(r"([A-Za-z0-9][\w.-]*)/SKILL\.md")


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


def bare(name: str) -> str:
    """The skill name without its plugin prefix."""
    return name.rsplit(":", 1)[-1]


def read_entries(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """Every JSON object line of the host records, skipping blank and malformed lines."""
    entries: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def claude_loads(entry: dict[str, Any]) -> set[str]:
    """Skills a Claude Code transcript entry loads with the Skill tool."""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if entry.get("type") != "assistant" or not isinstance(content, list):
        return set()
    loaded = set()
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
            skill = (block.get("input") or {}).get("skill")
            if isinstance(skill, str) and skill:
                loaded.add(bare(skill))
    return loaded


def codex_loads(entry: dict[str, Any]) -> set[str]:
    """Skills a Codex rollout entry loads by reading `<skill>/SKILL.md` in a tool call."""
    payload = entry.get("payload")
    if entry.get("type") != "response_item" or not isinstance(payload, dict) or payload.get("type") not in CODEX_CALL_TYPES:
        return set()
    text = json.dumps([payload.get(key) for key in ("arguments", "input", "action")], ensure_ascii=False)
    return set(SKILL_FILE.findall(text))


def loaded_skills(entries: Iterable[dict[str, Any]]) -> set[str]:
    loaded: set[str] = set()
    for entry in entries:
        loaded |= claude_loads(entry) | codex_loads(entry)
    return loaded


def result_lists(result: str, skill: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(bare(skill))}(?![\w-])", result) is not None


def evaluate(entries: list[dict[str, Any]], result: str, skills: list[str]) -> dict[str, Any]:
    """Accept a worker result only when the host record shows each named skill loaded and the result lists it."""
    loaded = loaded_skills(entries)
    not_loaded = [skill for skill in skills if bare(skill) not in loaded]
    not_listed = [skill for skill in skills if not result_lists(result, skill)]
    return {
        "accepted": not not_loaded and not not_listed,
        "named": skills,
        "loaded": sorted(loaded),
        "not_loaded": not_loaded,
        "not_listed": not_listed,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="skill_load_check.py", add_help=False)
    parser.add_argument("--record", action="append", default=[], type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--skill", action="append", default=[])
    return parser


def main(argv: list[str]) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.skill and (not args.record or args.result is None):
            raise UsageError("--skill needs --record and --result")
    except UsageError as error:
        print(json.dumps({"accepted": False, "error": str(error)}))
        return EXIT_USAGE
    if not args.skill:
        print(json.dumps({"accepted": True, "named": [], "loaded": [], "not_loaded": [], "not_listed": []}))
        return EXIT_ACCEPTED
    try:
        entries = read_entries(args.record)
        result = args.result.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        print(json.dumps({"accepted": False, "error": f"cannot read {error.filename}: {error.strerror}"}))
        return EXIT_EVIDENCE
    report = evaluate(entries, result, args.skill)
    print(json.dumps(report))
    return EXIT_ACCEPTED if report["accepted"] else EXIT_REJECTED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
