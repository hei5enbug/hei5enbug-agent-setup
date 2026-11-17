from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from role_runner_evidence import json_lines  # noqa: E402


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_ACCEPTED = 4
LISTING = re.compile(r"^\s*Skills loaded:\s*(.*)$", re.IGNORECASE | re.MULTILINE)
CODEX_CALL_KINDS = ("function_call", "custom_tool_call", "local_shell_call")


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="verify_skill_load.py", add_help=False)
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument("--record", type=Path)
    parser.add_argument("--result", type=Path)
    return parser


def claude_loads(entry: dict) -> set[str]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if entry.get("type") != "assistant" or not isinstance(content, list):
        return set()
    names = set()
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
            skill = block.get("input", {}).get("skill") if isinstance(block.get("input"), dict) else None
            if isinstance(skill, str):
                names.add(skill.rsplit(":", 1)[-1])
    return names


def codex_reads(entry: dict, skills: list[str]) -> set[str]:
    payload = entry.get("payload")
    if not isinstance(payload, dict) or payload.get("type") not in CODEX_CALL_KINDS:
        return set()
    call = json.dumps(payload, ensure_ascii=False)
    return {skill for skill in skills if f"/{skill}/SKILL.md" in call}


def loaded_in_record(record: Path, skills: list[str]) -> set[str]:
    loaded: set[str] = set()
    for entry in json_lines(record):
        loaded |= claude_loads(entry) | codex_reads(entry, skills)
    return loaded & set(skills)


def listed_in_result(result: Path) -> set[str]:
    text = result.read_text(encoding="utf-8", errors="replace")
    names: set[str] = set()
    for line in LISTING.findall(text):
        names |= {part.strip().strip("`") for part in line.split(",") if part.strip()}
    return names


def verify(skills: list[str], record: Path | None, result: Path | None) -> dict:
    if not skills:
        return {"accepted": True, "checked": [], "no_load_in_record": [], "not_listed_in_result": []}
    no_load = sorted(set(skills) - loaded_in_record(record, skills)) if record else []
    not_listed = sorted(set(skills) - listed_in_result(result)) if result else sorted(skills)
    return {
        "accepted": not no_load and not not_listed,
        "checked": sorted(set(skills)),
        "no_load_in_record": no_load,
        "not_listed_in_result": not_listed,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        for path in (args.record, args.result):
            if path is not None and not path.is_file():
                raise UsageError(f"{path} is not a file")
    except UsageError as error:
        print(json.dumps({"accepted": False, "error": str(error)}, ensure_ascii=False))
        return EXIT_USAGE
    outcome = verify(args.skill, args.record, args.result)
    print(json.dumps(outcome, ensure_ascii=False))
    return EXIT_OK if outcome["accepted"] else EXIT_NOT_ACCEPTED


if __name__ == "__main__":
    raise SystemExit(main())
