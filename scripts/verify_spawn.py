from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import role_runner  # noqa: E402


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_EVIDENCE = 4
SANDBOXES = ("read-only", "workspace-write")


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="verify_spawn.py", add_help=False)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--agent-path", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--sandbox", choices=SANDBOXES)
    return parser


def report(verified: bool, rollout: Path | None, turns: int, error: str | None) -> dict:
    return {"verified": verified, "rollout": rollout.as_posix() if rollout else None, "turns": turns, "error": error}


def dig(value: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def first_entry(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            entry = json.loads(handle.readline())
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


def spawned_by(path: Path, parent: str, agent_path: str) -> bool:
    entry = first_entry(path)
    if entry is None or entry.get("type") != "session_meta":
        return False
    spawn = dig(entry, "payload", "source", "subagent", "thread_spawn")
    return dig(spawn, "parent_thread_id") == parent and dig(spawn, "agent_path") == agent_path


def rollouts_for(parent: str, agent_path: str) -> list[Path]:
    sessions = role_runner.codex_home() / "sessions"
    if not sessions.is_dir():
        return []
    return sorted(path for path in sessions.glob("**/rollout-*.jsonl") if spawned_by(path, parent, agent_path))


def turn_contexts(rollout: Path) -> list[dict]:
    return [
        entry["payload"] if isinstance(entry.get("payload"), dict) else {}
        for entry in role_runner.json_lines(rollout)
        if entry.get("type") == "turn_context"
    ]


def verify(parent: str, agent_path: str, model: str, effort: str, sandbox: str | None = None) -> dict:
    rollouts = rollouts_for(parent, agent_path)
    if not rollouts:
        return report(False, None, 0, f"No rollout for agent path {agent_path} under parent {parent}")
    rollout = rollouts[-1]
    turns = turn_contexts(rollout)
    if not turns:
        return report(False, rollout, 0, f"No turn_context entry in {rollout}")
    for turn in turns:
        if turn.get("model") != model or turn.get("effort") != effort:
            return report(
                False, rollout, len(turns),
                f"turn_context names {turn.get('model')!r} with {turn.get('effort')!r}, expected {model!r} with {effort!r}",
            )
        if sandbox is not None:
            policy = turn.get("sandbox_policy")
            sandbox_type = policy.get("type") if isinstance(policy, dict) else None
            if sandbox_type != sandbox:
                return report(False, rollout, len(turns), f"turn_context names sandbox {sandbox_type!r}, expected {sandbox!r}")
    return report(True, rollout, len(turns), None)


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if not (args.parent and args.agent_path and args.model and args.effort):
            raise UsageError("--parent, --agent-path, --model, and --effort must not be empty")
    except UsageError as error:
        print(json.dumps(report(False, None, 0, str(error)), ensure_ascii=False))
        return EXIT_USAGE
    result = verify(args.parent, args.agent_path, args.model, args.effort, args.sandbox)
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_OK if result["verified"] else EXIT_EVIDENCE


if __name__ == "__main__":
    raise SystemExit(main())
