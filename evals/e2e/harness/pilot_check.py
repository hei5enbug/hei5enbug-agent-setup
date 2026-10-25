"""Validate that finished runs used the exported plugin, the mod marker was present, and no bypass flags were used."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from . import collect, metrics, transcript
from .config import APPROVER_TOOL, FORBIDDEN_ARGS, MOD_MARKER
from .matrix import campaign_dir, read_json

REQUIRED_FLAGS = ("--plugin-dir", "--settings", "--permission-prompt-tool", "--max-budget-usd")


def command_problems(argv: list[str]) -> list[str]:
    options = argv[:len(argv) - 1 - argv[::-1].index("--")] if "--" in argv else argv
    problems = [f"missing {flag}" for flag in REQUIRED_FLAGS if flag not in options]
    problems += [f"forbidden {arg}" for arg in options if arg in FORBIDDEN_ARGS or arg.startswith("--permission-mode")]
    if APPROVER_TOOL not in options:
        problems.append("approver tool not wired")
    return problems


def check_run(result_dir: Path) -> list[tuple[str, bool, str]]:
    run = read_json(result_dir / "run.json", {})
    events = transcript.read_jsonl(result_dir / "stream.jsonl")
    facts = metrics.stream_facts(events)
    main = transcript.read_jsonl(result_dir / "transcripts" / "main.jsonl")
    subagents = collect.load_subagents(result_dir / "transcripts" / "subagents")
    expected = str((run.get("plugin") or {}).get("path", ""))
    plugin = metrics.plugin_checks(facts, expected, main, subagents)
    argv = (read_json(result_dir / "command.json", {}) or {}).get("argv", [])
    problems = command_problems(argv)
    return [
        ("result message present", facts["has_result"], str(run.get("status"))),
        ("plugin loaded from the exported directory", plugin["loaded_from_export"], expected),
        ("installed plugin absent", plugin["installed_absent"], ""),
        ("mod marker in the main transcript", plugin["mod_marker_present"], MOD_MARKER),
        ("permission mode recorded", bool(facts["permission_mode"]), str(facts["permission_mode"])),
        ("command line without bypass flags", not problems, ", ".join(problems)),
    ]


def pilot_check(run_root: Path, campaign: str, run_ids: frozenset[str], out: TextIO) -> int:
    failures = 0
    for run_json in sorted(campaign_dir(run_root, campaign).glob("results/*/*/rep*/run.json")):
        run = read_json(run_json, {})
        if run_ids and run.get("run_id") not in run_ids:
            continue
        out.write(f"{run.get('run_id')}\n")
        for name, passed, detail in check_run(run_json.parent):
            failures += 0 if passed else 1
            out.write(f"  {'PASS' if passed else 'FAIL'} {name}{': ' + detail if detail and not passed else ''}\n")
    return 1 if failures else 0
