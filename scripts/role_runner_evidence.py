from __future__ import annotations

import json
import os
from pathlib import Path

from role_runner_config import EXIT_EVIDENCE, SYNTHETIC_MODEL, VALIDATION_PACKAGE_HOSTS, RunnerError


def state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state").expanduser()


def require_heartbeat(host: str, session_id: str, message: str) -> None:
    """Require a Codex PreToolUse heartbeat, or a Claude prompt or legacy heartbeat."""
    plain = state_home() / "hei5enbug-agent-setup" / "heartbeats" / f"{host}-{session_id}"
    event_name = "PreToolUse" if host == "codex" else "UserPromptSubmit"
    heartbeat = plain.with_name(plain.name + "." + event_name)
    present = heartbeat.is_file() or (host == "claude" and plain.is_file())
    if "/" in session_id or not present:
        raise RunnerError(EXIT_EVIDENCE, message, {"heartbeat": heartbeat.as_posix(), "session": session_id})


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def thread_id_from(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
    return None


def json_lines(path: Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            yield entry


def count_tool_calls(rollout: Path) -> int:
    """Count the rollout entries that record a tool call, not counting web searches."""
    count = 0
    for entry in json_lines(rollout):
        payload = entry.get("payload")
        kind = payload.get("type") if isinstance(payload, dict) else None
        if isinstance(kind, str) and kind.endswith("_call") and kind != "web_search_call":
            count += 1
    return count


def find_rollout(thread_id: str) -> Path | None:
    """Return the newest rollout file of a Codex thread, or None when the thread has none yet."""
    sessions = codex_home() / "sessions"
    rollouts = sorted(sessions.glob(f"**/rollout-*{thread_id}.jsonl")) if sessions.is_dir() else []
    return rollouts[-1] if rollouts else None


def turn_contexts(rollout: Path) -> list[dict]:
    """Return the payload of every turn_context entry of a rollout, in order."""
    turns = []
    for entry in json_lines(rollout):
        if entry.get("type") == "turn_context":
            payload = entry.get("payload")
            turns.append(payload if isinstance(payload, dict) else {})
    return turns


def turns_before(thread_id: str) -> int:
    """Count the turns a thread already holds, so a resumed run is checked only on the turns it adds."""
    rollout = find_rollout(thread_id)
    return len(turn_contexts(rollout)) if rollout is not None else 0


def writable_paths(profile: object) -> list[str] | None:
    """Return what a turn_context permission_profile lets the run write, or None when the profile records no write limit.

    A write entry for a path is its resolved path; one for a special location is `special:<kind>`; a deny entry is skipped."""
    if not isinstance(profile, dict) or profile.get("type") != "managed":
        return None
    system = profile.get("file_system")
    if not isinstance(system, dict) or system.get("type") != "restricted" or not isinstance(system.get("entries"), list):
        return None
    entries = system["entries"]
    writable = []
    for entry in entries:
        target = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(target, dict):
            return None
        if entry.get("access") != "write":
            continue
        if target.get("type") == "path" and isinstance(target.get("path"), str):
            writable.append(Path(target["path"]).resolve().as_posix())
        elif target.get("type") == "special" and isinstance(target.get("value"), dict):
            writable.append(f"special:{target['value'].get('kind')}")
        else:
            return None
    return writable


def require_scratch_only(turn: dict, scratch: Path, rollout: Path, turns: int) -> None:
    """Require a turn's permission_profile to allow writes to the run's scratch folder and nothing else."""
    writable = writable_paths(turn.get("permission_profile"))
    if writable != [scratch.as_posix()]:
        raise RunnerError(
            EXIT_EVIDENCE,
            f"turn_context allows writes to {writable!r}, expected only the scratch folder {scratch.as_posix()!r}",
            {"rollout": rollout.as_posix(), "turns": turns},
        )


def require_sandbox(turn: dict, sandbox: str, rollout: Path, turns: int) -> None:
    policy = turn.get("sandbox_policy")
    sandbox_type = policy.get("type") if isinstance(policy, dict) else None
    if sandbox_type != sandbox:
        raise RunnerError(
            EXIT_EVIDENCE,
            f"turn_context names sandbox {sandbox_type!r}, expected {sandbox!r}",
            {"rollout": rollout.as_posix(), "turns": turns},
        )


def verify_codex(
    stdout: str, model: str, effort: str, sandbox: str, scratch: Path | None = None, since_turn: int = 0,
) -> dict:
    """Verify a Codex run's model, effort, and write limit. A run with a scratch folder must have been able to write that
    folder only, checked on the turns after since_turn; any other run must name the given sandbox type on every turn."""
    thread_id = thread_id_from(stdout)
    if thread_id is None:
        raise RunnerError(EXIT_EVIDENCE, "No thread.started event with a thread_id in the Codex output")
    rollout = find_rollout(thread_id)
    if rollout is None:
        raise RunnerError(EXIT_EVIDENCE, f"No rollout file for thread {thread_id} under {codex_home() / 'sessions'}")
    turns = turn_contexts(rollout)
    if not turns:
        raise RunnerError(EXIT_EVIDENCE, f"No turn_context entry in {rollout}", {"rollout": rollout.as_posix()})
    for turn in turns:
        if turn.get("model") != model or turn.get("effort") != effort:
            raise RunnerError(
                EXIT_EVIDENCE,
                f"turn_context names {turn.get('model')!r} with {turn.get('effort')!r}, expected {model!r} with {effort!r}",
                {"rollout": rollout.as_posix(), "turns": len(turns)},
            )
    if scratch is not None and len(turns) <= since_turn:
        raise RunnerError(EXIT_EVIDENCE, f"The resumed run added no turn_context entry to {rollout}", {"rollout": rollout.as_posix()})
    for turn in turns[since_turn:] if scratch is not None else turns:
        if scratch is not None:
            require_scratch_only(turn, scratch, rollout, len(turns))
        else:
            require_sandbox(turn, sandbox, rollout, len(turns))
    return {"rollout": rollout.as_posix(), "turns": len(turns), "session": thread_id, "tool_calls": count_tool_calls(rollout)}


def claude_result(stdout: str) -> dict:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RunnerError(EXIT_EVIDENCE, "The Claude output is not JSON") from error
    if isinstance(parsed, list):
        parsed = next((item for item in parsed if isinstance(item, dict) and item.get("type") == "result"), None)
    if not isinstance(parsed, dict):
        raise RunnerError(EXIT_EVIDENCE, "The Claude output has no result object")
    return parsed


def claude_init(stdout: str) -> dict | None:
    """Return the system init event of a verbose Claude JSON output, or None when the output has none."""
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    events = parsed if isinstance(parsed, list) else []
    return next(
        (item for item in events if isinstance(item, dict) and item.get("type") == "system" and item.get("subtype") == "init"),
        None,
    )


def sandbox_settings_in(command: list[str]) -> dict | None:
    """Return the JSON a command passes after --settings, or None when it passes none or it is not a JSON object."""
    if "--settings" not in command or command.index("--settings") + 1 >= len(command):
        return None
    try:
        settings = json.loads(command[command.index("--settings") + 1])
    except json.JSONDecodeError:
        return None
    return settings if isinstance(settings, dict) else None


def confinement_problem(settings: dict | None, scratch: Path, validation: bool) -> str | None:
    """Return why a --settings object does not confine a Claude shell's writes to the scratch folder, or None when it does."""
    sandbox = settings.get("sandbox") if isinstance(settings, dict) else None
    if not isinstance(sandbox, dict):
        return "the command carries no sandbox settings"
    wanted = {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False, "excludedCommands": []}
    for key, value in wanted.items():
        if sandbox.get(key) != value:
            return f"sandbox {key} is {sandbox.get(key)!r}, expected {value!r}"
    filesystem = sandbox.get("filesystem")
    if not isinstance(filesystem, dict) or filesystem.get("allowWrite") != [scratch.as_posix()]:
        return f"sandbox allowWrite is not exactly the scratch folder {scratch.as_posix()!r}"
    if set(filesystem) - {"allowWrite"}:
        return "sandbox filesystem holds keys other than allowWrite"
    network = sandbox.get("network")
    domains = network.get("allowedDomains") if isinstance(network, dict) else None
    if not isinstance(domains, list) or not set(domains) <= (set(VALIDATION_PACKAGE_HOSTS) if validation else set()):
        return f"sandbox network allows {domains!r}, more than this run may reach"
    if network.get("strictAllowlist") is not True:
        return "sandbox network is not a strict allowlist"
    return None


def verify_sandbox(command: list[str], init: dict | None, scratch: Path, validation: bool) -> None:
    """Require the command's sandbox settings, which start the sandbox or end the run at startup, to confine writes to the
    scratch folder, and the host's init event to name the scratch folder as the working directory; anything else exits 4."""
    problem = confinement_problem(sandbox_settings_in(command), scratch, validation)
    if problem is not None:
        raise RunnerError(EXIT_EVIDENCE, f"The Claude run was not confined to its scratch folder: {problem}")
    if init is None:
        raise RunnerError(EXIT_EVIDENCE, "The Claude output has no system init event, so the run is not shown to have started")
    cwd = init.get("cwd")
    if not isinstance(cwd, str) or Path(cwd).resolve() != scratch:
        raise RunnerError(EXIT_EVIDENCE, f"The init event names the working directory {cwd!r}, expected {scratch.as_posix()!r}")


def is_synthetic(entry: dict) -> bool:
    message = entry.get("message")
    return isinstance(message, dict) and message.get("model") == SYNTHETIC_MODEL


def verify_claude(
    result: dict, model: str, effort: str, command: list[str] | None = None, init: dict | None = None,
    scratch: Path | None = None, validation: bool = False, session: str | None = None,
) -> dict:
    """Verify a Claude run's model and effort; a read-only run, which has a scratch folder, must also show the sandbox
    that confines its writes to that folder and the session id it was given."""
    if scratch is not None:
        verify_sandbox(command or [], init, scratch, validation)
        if result.get("session_id") != session:
            raise RunnerError(EXIT_EVIDENCE, f"The result names session {result.get('session_id')!r}, expected {session!r}")
    usage = result.get("modelUsage")
    if not isinstance(usage, dict) or set(usage) != {model}:
        found = sorted(usage) if isinstance(usage, dict) else usage
        raise RunnerError(EXIT_EVIDENCE, f"modelUsage names {found!r}, expected only {model!r}")
    session_id = result.get("session_id")
    if not isinstance(session_id, str) or not session_id or "/" in session_id:
        raise RunnerError(EXIT_EVIDENCE, "The Claude result has no usable session_id")
    projects = claude_home() / "projects"
    transcripts = sorted(projects.glob(f"*/{session_id}.jsonl")) if projects.is_dir() else []
    if not transcripts:
        raise RunnerError(EXIT_EVIDENCE, f"No transcript for session {session_id} under {projects}")
    transcript = transcripts[-1]
    assistants = [entry for entry in json_lines(transcript) if entry.get("type") == "assistant"]
    if not assistants:
        raise RunnerError(EXIT_EVIDENCE, f"No assistant entry in {transcript}", {"transcript": transcript.as_posix()})
    assistants = [entry for entry in assistants if not is_synthetic(entry)]
    if not assistants:
        raise RunnerError(
            EXIT_EVIDENCE, f"No assistant entry from a real model in {transcript}", {"transcript": transcript.as_posix()},
        )
    for entry in assistants:
        message = entry.get("message")
        entry_model = message.get("model") if isinstance(message, dict) else None
        if entry_model != model or entry.get("effort") != effort:
            raise RunnerError(
                EXIT_EVIDENCE,
                f"assistant entry names {entry_model!r} with {entry.get('effort')!r}, expected {model!r} with {effort!r}",
                {"transcript": transcript.as_posix(), "entries": len(assistants)},
            )
    return {"transcript": transcript.as_posix(), "entries": len(assistants), "session": session_id}
