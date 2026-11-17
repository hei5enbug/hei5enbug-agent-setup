"""Validate that finished runs used the exported plugin, the mod marker was present, and no bypass flags were used."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TextIO

from . import codex_host, collect, metrics, transcript
from .config import APPROVER_TOOL, FORBIDDEN_ARGS, HOST_CLAUDE, HOST_CODEX, MOD_MARKER
from .matrix import campaign_dir, read_json

AUTO_MEMORY_OFF_ENV = "CLAUDE_CODE_DISABLE_AUTO_MEMORY"
PLUGIN_DIR_FLAG = "--plugin-dir"
REQUIRED_FLAGS = ("--plugin-dir", "--settings", "--permission-prompt-tool", "--max-budget-usd", "--strict-mcp-config", "--setting-sources")


def own_roots(*paths: Any) -> list[Path]:
    """The given folders by their given and their resolved path; a path that is empty names no folder."""
    return [root for path in paths if path for root in (Path(os.path.abspath(str(path))), Path(str(path)).resolve())]


def command_problems(argv: list[str], loaded: bool = True) -> list[str]:
    """Problems of a Claude Code command line; a run that loads no plugin must not pass `--plugin-dir`."""
    options = argv[:len(argv) - 1 - argv[::-1].index("--")] if "--" in argv else argv
    problems = [f"missing {flag}" for flag in REQUIRED_FLAGS if flag not in options and (loaded or flag != PLUGIN_DIR_FLAG)]
    problems += [f"{PLUGIN_DIR_FLAG} passed to a run that loads no plugin"] if not loaded and PLUGIN_DIR_FLAG in options else []
    problems += [f"forbidden {arg}" for arg in options if arg in FORBIDDEN_ARGS or arg.startswith("--permission-mode")]
    if APPROVER_TOOL not in options:
        problems.append("approver tool not wired")
    sources = options[options.index("--setting-sources") + 1] if "--setting-sources" in options[:-1] else ""
    if "user" in sources.split(","):
        problems.append("user setting source loaded")
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
    loaded = bool(expected)
    problems = command_problems(argv, loaded)
    isolation = (read_json(result_dir / "env.json", {}) or {}).get("instruction_isolation") or {}
    events = [*main, *(event for record in subagents for event in record["events"])]
    user_files = metrics.user_instruction_files(events)
    cwd = (read_json(result_dir / "command.json", {}) or {}).get("cwd")
    outside = metrics.instruction_files_outside(events, own_roots(cwd, expected))
    return [
        ("result message present", facts["has_result"], str(run.get("status"))),
        ("plugin loaded from the exported directory" if loaded else "no plugin loaded",
         plugin["loaded_from_export"] if loaded else not plugin["loaded_from_export"], expected),
        ("installed plugin absent", plugin["installed_absent"], ""),
        ("no plugin besides the variant", not plugin["extra_plugins"], ", ".join(plugin["extra_plugins"])),
        ("no user-level memory or rule file loaded", not user_files, ", ".join(user_files)),
        ("no instruction file outside the trial repo and the exported plugin", not outside, ", ".join(outside)),
        ("auto memory switched off for the run", AUTO_MEMORY_OFF_ENV in isolation.get("env", {}) and isolation["env"][AUTO_MEMORY_OFF_ENV] == "1", ""),
        ("no auto memory path in the init event", not facts["auto_memory_path"], str(facts["auto_memory_path"])),
        ("mod marker in the main transcript" if loaded else "no mod marker in the main transcript",
         plugin["mod_marker_present"] if loaded else not plugin["mod_marker_present"], MOD_MARKER),
        ("permission mode recorded", bool(facts["permission_mode"]), str(facts["permission_mode"])),
        ("command line without bypass flags", not problems, ", ".join(problems)),
    ]


def codex_answered(result_dir: Path, stream: list[dict[str, Any]]) -> bool:
    """Whether the Codex turn completed: the stream says so, or the main rollout holds `task_complete`."""
    if codex_host.stream_state(stream)["completed"]:
        return True
    rollouts, _ = codex_host.label_rollouts(collect.load_rollouts(result_dir / "codex", {}))
    return any(codex_host.payload_of(event).get("type") == "task_complete" for event in (rollouts[0]["events"] if rollouts else []))


def check_codex_run(result_dir: Path) -> list[tuple[str, bool, str]]:
    run = read_json(result_dir / "run.json", {})
    expected = str((run.get("plugin") or {}).get("path", ""))
    setup = read_json(result_dir / codex_host.SETUP_RECORD, {}) or {}
    steps = setup.get("steps") if isinstance(setup.get("steps"), list) else []
    installed = bool(steps) and all(step.get("returncode") == 0 for step in steps) and any(
        expected and expected in (step.get("argv") or []) for step in steps)
    loaded = bool(expected)
    env = read_json(result_dir / "env.json", {}) or {}
    checks = (read_json(result_dir / "metrics.json", {}) or {}).get("plugin") or {}
    argv = (read_json(result_dir / "command.json", {}) or {}).get("argv", [])
    stream = transcript.read_jsonl(result_dir / "stream.jsonl")
    return [
        ("turn completed", codex_answered(result_dir, stream), str(run.get("status"))),
        ("plugin installed from the exported directory" if loaded else "no plugin installed", installed if loaded else not steps, expected),
        ("plugin hooks trusted" if loaded else "no plugin hooks", ("hook_trust" in setup and "hook_trust_error" not in setup) if loaded else "hook_trust" not in setup, ""),
        ("CODEX_HOME isolated", env.get("codex_home_isolated") is True, ""),
        ("session model as requested", checks.get("model_as_requested") is True, ""),
        ("command line pins the model", "-m" in argv and "exec" in argv, ""),
    ]


def run_files(base: Path) -> list[Path]:
    """Every run.json of a campaign, on both hosts."""
    return sorted([*base.glob("results/*/*/rep*/run.json"), *base.glob(f"results/*/*/{HOST_CODEX}/rep*/run.json")])


def pilot_check(run_root: Path, campaign: str, run_ids: frozenset[str], out: TextIO) -> int:
    """Validate every selected run of either host; a call that validated no run fails."""
    failures, checked = 0, 0
    for run_json in run_files(campaign_dir(run_root, campaign)):
        run = read_json(run_json, {})
        if run_ids and run.get("run_id") not in run_ids:
            continue
        checked += 1
        out.write(f"{run.get('run_id')}\n")
        codex = run.get("host", HOST_CLAUDE) == HOST_CODEX
        for name, passed, detail in (check_codex_run if codex else check_run)(run_json.parent):
            failures += 0 if passed else 1
            out.write(f"  {'PASS' if passed else 'FAIL'} {name}{': ' + detail if detail and not passed else ''}\n")
    if not checked:
        out.write("FAIL no run was checked: the campaign holds no run, or no run matches --run-ids\n")
    return 1 if failures or not checked else 0
