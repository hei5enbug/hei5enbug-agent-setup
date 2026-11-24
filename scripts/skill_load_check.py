from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.e2e.harness import codex_calls  # noqa: E402

EXIT_ACCEPTED = 0
EXIT_REJECTED = 1
EXIT_USAGE = 2
EXIT_EVIDENCE = 4
SKILL_FILE = re.compile(r"([A-Za-z0-9][\w.-]*)/SKILL\.md")
SHELL_READ = re.compile(r"(?:^|[;&|\n])\s*(?:[^\s;&|]+/)?(?:cat|sed|head|tail|nl|bat|awk|grep|rg|less|more)\s+([^;&|\n]+)")
SHELL_EXIT = re.compile(r"\A(?:Chunk ID: [^\n]*\n)?(?:Wall time: [^\n]*\n)?Process exited with code (\d+)\b")


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


def claude_loads(entries: list[dict[str, Any]]) -> set[str]:
    calls: dict[str, str] = {}
    results: set[str] = set()
    for entry in entries:
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = entry.get("type"), block.get("type")
            if kind == ("user", "tool_result") and not block.get("is_error"):
                if isinstance(tool_use_id := block.get("tool_use_id"), str):
                    results.add(tool_use_id)
            if kind != ("assistant", "tool_use") or block.get("name") != "Skill":
                continue
            tool_input = block.get("input")
            skill = tool_input.get("skill") if isinstance(tool_input, dict) else None
            call_id = block.get("id")
            if isinstance(call_id, str) and isinstance(skill, str) and skill:
                calls[call_id] = bare(skill)
    return {skill for call_id, skill in calls.items() if call_id in results}


def successful_commands(call: dict[str, Any], result: dict[str, Any]) -> list[str]:
    commands = codex_calls.commands_of(call)
    if not commands or result.get("is_error"):
        return []
    output = result.get("output")
    if call["type"] == "custom_tool_call":
        statements = codex_calls.tool_statements(call["input"])
        items = codex_calls.exec_items(output)
        if items is None or len(items) != len(statements):
            return []
        chunks = [codex_calls.chunk_of(item) for (name, _), item in zip(statements, items) if name == "exec_command"]
        if len(chunks) != len(commands):
            return []
        return [command for command, chunk in zip(commands, chunks) if codex_calls.chunk_code(chunk) == 0]
    code = codex_calls.exit_code(output)
    if code is None:
        status = SHELL_EXIT.match(codex_calls.output_text(output))
        code = int(status[1]) if status else None
    return commands if code == 0 else []


def codex_loads(entries: list[dict[str, Any]]) -> set[str]:
    outputs = {}
    calls = []
    for entry in entries:
        item = entry.get("payload")
        if entry.get("type") != "response_item" or not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind in codex_calls.OUTPUT_TYPES and isinstance(call_id := item.get("call_id"), str):
            outputs.setdefault(call_id, item)
        elif kind in codex_calls.CALL_TYPES:
            calls.append(item)
    loaded: set[str] = set()
    for call in calls:
        call_id = call.get("call_id") or call.get("id")
        result = outputs.get(call_id, {}) if isinstance(call_id, str) else {}
        if result.get("type") != call["type"] + "_output":
            continue
        for command in successful_commands(call, result):
            for arguments in SHELL_READ.findall(command):
                loaded.update(SKILL_FILE.findall(arguments))
    return loaded


def loaded_skills(entries: list[dict[str, Any]]) -> set[str]:
    return claude_loads(entries) | codex_loads(entries)


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
