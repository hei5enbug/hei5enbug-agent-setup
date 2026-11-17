"""Per-request caps on delegated runs and retries, and the parallel limit computed from the machine's free resources.

One count per user request lives in the session state store under the session that received the prompt. The Claude Code
`Agent` hook, the Codex agent guard, and the role runner all admit a launch through `admit`, so a launch through any of
them adds to the same count. A child the role runner starts inherits that session through `HEI5ENBUG_PARENT_SESSION`.
The runs that are running on this machine, of every session, sit in one file under the same lock. Every reading comes
from the operating system without starting a process.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import tomllib
from collections import namedtuple
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_state_store as store  # noqa: E402
import hook_runtime  # noqa: E402
import machine_load  # noqa: E402
import plugin_toggles  # noqa: E402

RUN_CAP_KEY = "request_run_cap"
RETRY_CAP_KEY = "request_retry_cap"
DEFAULT_RUN_CAP = 20
DEFAULT_RETRY_CAP = 3
HOSTS = ("claude", "codex")
PARENT_SESSION_ENV = "HEI5ENBUG_PARENT_SESSION"
AGENT_TOOLS = frozenset({"Agent", "Task", "spawn_agent"})
HIDDEN_AGENTS = re.compile(r"^(general-purpose|explore|plan|claude)$", re.IGNORECASE)
CLAUDE_HOST_LIMIT_ENV = "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"
CLAUDE_HOST_LIMIT_DEFAULT = 20
UNREADABLE_CEILING = 6
PARALLEL_CEILING = 6
CEILING_ENV = "HEI5ENBUG_PARALLEL_CEILING_FOR_TESTS"
MEMORY_MB_ENV = "HEI5ENBUG_AVAILABLE_MEMORY_MB_FOR_TESTS"
GIB = 1024
RUNNER_POLL_SECONDS = 2.0

Machine = namedtuple("Machine", "cpus available_mb load memory_fraction")
Verdict = namedtuple("Verdict", "allowed reason message", defaults=(True, None, ""))


def parallel_limit(machine: Machine, host_limit: int | None = None, ceiling: int | None = None) -> int:
    """The lowest of CPUs minus one, whole GiB of available memory, and the host's own limit, and at least one.

    A known load or memory shortage gives one. A CPU count or memory reading that is unavailable leaves its term out and
    caps the result at six. `ceiling` caps the result further.
    """
    cpus, available_mb, load, fraction = machine
    if (load is not None and cpus and load >= machine_load.LOAD_FACTOR * cpus) or (
        fraction is not None and fraction < machine_load.MEMORY_FRACTION
    ):
        return 1
    terms = []
    if cpus:
        terms.append(cpus - 1)
    if available_mb is not None:
        terms.append(available_mb // GIB)
    if host_limit is not None:
        terms.append(host_limit)
    limit = min(terms) if terms else UNREADABLE_CEILING
    if not cpus or available_mb is None:
        limit = min(limit, UNREADABLE_CEILING)
    if ceiling:
        limit = min(limit, ceiling)
    return max(1, limit)


def parallel_ceiling() -> int | None:
    """The cap on the computed limit: six until the measured case that lifts it passes, `off` or 0 in the test variable."""
    text = os.environ.get(CEILING_ENV, "").strip().lower()
    if text in ("0", "off"):
        return None
    return int(text) if text.isdigit() else PARALLEL_CEILING


def read_machine() -> Machine:
    override = machine_load.override_counters()
    memory = os.environ.get(MEMORY_MB_ENV)
    available = int(memory) if memory is not None and memory.isdigit() else None
    if override is not None:
        return Machine(override.cpu_count, available, override.load_average, override.memory_available_fraction)
    if memory is None:
        available = machine_load.read_available_mb()
    return Machine(
        machine_load.read_cpu_count(), available, machine_load.read_load_average(), machine_load.read_memory_fraction(),
    )


def codex_host_limit(environ=os.environ) -> int | None:
    path = Path(environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"
    try:
        agents = tomllib.loads(path.read_text(encoding="utf-8")).get("agents")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(agents, dict):
        return None
    for key in ("max_concurrent_threads_per_session", "max_threads"):
        value = agents.get(key)
        if type(value) is int and value > 0:
            return value
    return None


def host_limit(host: str, environ=os.environ) -> int | None:
    """The host's own concurrent-agent limit: Claude Code's variable or its default of 20, Codex's configured one."""
    if host == "codex":
        return codex_host_limit(environ)
    text = environ.get(CLAUDE_HOST_LIMIT_ENV, "").strip()
    return int(text) if re.fullmatch(r"[0-9]+", text) and int(text) > 0 else CLAUDE_HOST_LIMIT_DEFAULT


def option_number(key: str, default: int) -> int:
    """A cap option: its value from the environment of either host or the saved Claude options, else the default."""
    text = ""
    for host in HOSTS:
        text = os.environ.get(plugin_toggles.variable_name(key, host), "").strip()
        if text:
            break
    if not text:
        saved, _ = plugin_toggles.saved_options((key,))
        text = str(saved.get(key, "")).strip()
    return int(text) if re.fullmatch(r"[0-9]+", text) else default


def request_owner(host: str, session, environ=os.environ) -> tuple[str, str] | None:
    """The host and session that received the user's prompt: the inherited one in a child, else this session."""
    linked_host, separator, linked = environ.get(PARENT_SESSION_ENV, "").partition(":")
    if separator and linked_host in HOSTS and store.session_key(linked):
        return linked_host, linked
    return (host, session) if store.session_key(session) else None


def environment_owner(environ=os.environ) -> tuple[str, str] | None:
    """The owner a process outside a hook finds from its environment, or None when it names no session."""
    if environ.get(PARENT_SESSION_ENV):
        return request_owner("claude", None, environ)
    if environ.get("CLAUDECODE") and environ.get("CLAUDE_CODE_SESSION_ID"):
        return request_owner("claude", environ["CLAUDE_CODE_SESSION_ID"], environ)
    codex = environ.get("CODEX_SESSION_ID") or environ.get("CODEX_THREAD_ID")
    return request_owner("codex", codex, environ) if codex else None


def runs_path() -> Path:
    return store.state_dir().parent / "runs" / "active.json"


def alive(pid) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_runs() -> list[dict]:
    """The runs recorded as running on this machine, without those whose process is gone."""
    try:
        data = json.loads(runs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return [
        entry for entry in entries or []
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("host"), str)
        and isinstance(entry.get("session"), str) and alive(entry.get("pid"))
    ]


def write_runs(entries: list[dict]) -> None:
    path = runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps({"entries": entries}, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def mutate(owner: tuple[str, str], change):
    """Run `change` on the owner's state under the store lock, which also covers the running-runs file."""
    host, session = owner
    directory = store.state_dir()
    path = directory / f"{host}-{session}.json"
    with store._locked(directory):
        data = store._read(path)
        result = change(data)
        store._cleanup(directory, path)
        store._write(path, data)
    return result


def record_launch(delegated: dict, key: str) -> None:
    """Count one launch of `key`; it is a retry when the last run of that key ended in an error."""
    delegated["runs"] += 1
    if key in delegated["failed"]:
        delegated["retries"] += 1
        delegated["failed"].remove(key)


def record_failure(delegated: dict, key: str) -> None:
    if key not in delegated["failed"]:
        delegated["failed"] = sorted({*delegated["failed"], key})


def cap_message(count: int, cap: int, what: str) -> str:
    return (
        f"Denied: this request reached its cap of {cap} {what} ({count} counted). Work that is already running may "
        "finish. Start no more agents or role runner runs, and report the request as stopped, with what is done and "
        "what remains, never as done."
    )


def limit_message(running: int, limit: int) -> str:
    return (
        f"Denied: {running} runs are running on this machine and its limit is {limit}, which follows its free CPU and "
        "memory. Start this run after one of this session's running runs ends; do not poll."
    )


def admit(
    owner: tuple[str, str] | None, key: str, pid: int, run_id: str, machine: Machine | None = None,
    limit_of_host: int | None = None, ceiling: int | None = None, now: float | None = None,
) -> Verdict:
    """Count one launch of `key` for the request and record it as running, or say why it is denied.

    A launch of a key whose last run ended in an error counts as a retry. A session with no running run of its own may
    always start one. `reason` is `cap` for a denial that holds until the next prompt and `limit` for one that holds
    until a run ends.
    """
    if owner is None:
        return Verdict()
    run_cap = option_number(RUN_CAP_KEY, DEFAULT_RUN_CAP)
    retry_cap = option_number(RETRY_CAP_KEY, DEFAULT_RETRY_CAP)
    limit = parallel_limit(machine or read_machine(), limit_of_host, ceiling)
    stamp = time.time() if now is None else now

    def change(data):
        delegated = data["delegated"]
        if run_cap and delegated["runs"] >= run_cap:
            return Verdict(False, "cap", cap_message(delegated["runs"], run_cap, "delegated runs"))
        if retry_cap and delegated["retries"] >= retry_cap:
            return Verdict(False, "cap", cap_message(delegated["retries"], retry_cap, "retries"))
        entries = read_runs()
        own = [entry for entry in entries if (entry.get("host"), entry.get("session")) == owner]
        if own and len(entries) >= limit:
            write_runs(entries)
            return Verdict(False, "limit", limit_message(len(entries), limit))
        record_launch(delegated, key)
        entries.append({"id": run_id, "key": key, "host": owner[0], "session": owner[1], "pid": pid, "time": stamp})
        write_runs(entries)
        return Verdict()

    return mutate(owner, change) or Verdict()


def claim(owner: tuple[str, str] | None, agent_id: str, key: str) -> None:
    """Give the owner's oldest running entry that has no agent id, preferably of this key, the id the host assigned."""
    if owner is None or not agent_id:
        return

    def change(data):
        entries = read_runs()
        pending = [entry for entry in entries if (entry["host"], entry["session"]) == owner and "agent_id" not in entry]
        chosen = next((entry for entry in pending if entry.get("key") == key), pending[0] if pending else None)
        if chosen is not None:
            chosen["agent_id"] = agent_id
        write_runs(entries)

    mutate(owner, change)


def finish(owner: tuple[str, str] | None, run_id: str, failed: bool = False) -> None:
    """Drop the run with this launch id or agent id, and remember its key when it ended in an error."""
    if owner is None or not run_id:
        return

    def change(data):
        entries = read_runs()
        ended = [entry for entry in entries if run_id in (entry["id"], entry.get("agent_id"))]
        if failed and ended:
            record_failure(data["delegated"], ended[0]["key"])
        write_runs([entry for entry in entries if entry not in ended])

    mutate(owner, change)


def reset(owner: tuple[str, str] | None) -> None:
    """Start a new request: the next user prompt zeroes the counts but leaves the running runs."""
    if owner is not None:
        mutate(owner, lambda data: data.update(delegated=store.fresh_delegated()))


def acquire(owner, key: str, run_id: str, sleep=time.sleep) -> str | None:
    """Admit a role runner run, waiting while only the parallel limit holds it; return the denial text for a capped request."""
    while True:
        verdict = admit(owner, key, os.getpid(), run_id, limit_of_host=host_limit(owner[0]) if owner else None,
                        ceiling=parallel_ceiling())
        if verdict.allowed:
            return None
        if verdict.reason == "cap":
            return verdict.message
        sleep(RUNNER_POLL_SECONDS)


def agent_key(tool_input: dict) -> str:
    value = tool_input.get("subagent_type") or tool_input.get("agent_type")
    return value if isinstance(value, str) and value else "general-purpose"


def hook_pid() -> int:
    text = os.environ.get("CLAUDE_PID", "")
    return int(text) if text.isdigit() else os.getppid()


def pre_spawn(event: dict, host: str) -> str | None:
    """The denial text for an agent launch the request's caps or the parallel limit refuse, else None."""
    if event.get("tool_name") not in AGENT_TOOLS or not isinstance(event.get("tool_input"), dict):
        return None
    key = agent_key(event["tool_input"])
    tool_use_id = event.get("tool_use_id")
    if HIDDEN_AGENTS.match(key) or not isinstance(tool_use_id, str):
        return None
    try:
        verdict = admit(
            request_owner(host, event.get("session_id")), key, hook_pid(), tool_use_id,
            limit_of_host=host_limit(host), ceiling=parallel_ceiling(),
        )
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return None if verdict.allowed else verdict.message


def handle(event: dict, host: str) -> dict | None:
    name = event.get("hook_event_name")
    owner = request_owner(host, event.get("session_id"))
    if name == "UserPromptSubmit":
        if not os.environ.get(PARENT_SESSION_ENV):
            reset(owner)
    elif name == "PreToolUse":
        reason = pre_spawn(event, host)
        if reason:
            return {"hookSpecificOutput": {
                "hookEventName": name, "permissionDecision": "deny", "permissionDecisionReason": reason,
            }}
    elif name == "PostToolUseFailure":
        if event.get("tool_name") in AGENT_TOOLS and isinstance(event.get("tool_use_id"), str):
            finish(owner, event["tool_use_id"], failed=True)
    elif name == "SubagentStart":
        claim(owner, str(event.get("agent_id") or ""), str(event.get("agent_type") or ""))
    elif name == "SubagentStop":
        finish(owner, str(event.get("agent_id") or ""))
    return None


def report() -> str:
    """The limit and the request's counts, for the session to read before it launches."""
    environ = os.environ
    owner = environment_owner(environ)
    host = owner[0] if owner else ("codex" if environ.get("CODEX_THREAD_ID") else "claude")
    limit = parallel_limit(read_machine(), host_limit(host, environ), parallel_ceiling())
    entries = read_runs()
    mine = [entry for entry in entries if owner and (entry["host"], entry["session"]) == owner]
    counts = store._read(store.state_dir() / f"{owner[0]}-{owner[1]}.json")["delegated"] if owner else None
    lines = [f"Parallel limit: {limit}. Running on this machine: {len(entries)}, in this session: {len(mine)}."]
    if counts is not None:
        run_cap, retry_cap = option_number(RUN_CAP_KEY, DEFAULT_RUN_CAP), option_number(RETRY_CAP_KEY, DEFAULT_RETRY_CAP)
        lines.append(
            f"This request: {counts['runs']} delegated runs (cap {run_cap or 'off'}), "
            f"{counts['retries']} retries (cap {retry_cap or 'off'})."
        )
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) > 1:
        if sys.argv[1] != "limit":
            print("usage: request_budget.py limit", file=sys.stderr)
            return 2
        print(report())
        return 0
    try:
        event = json.load(sys.stdin)
        output = handle(event, plugin_toggles.detect_host()) if isinstance(event, dict) else None
    except (OSError, ValueError, TypeError, KeyError):
        return 0
    if output:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main() if len(sys.argv) > 1 else hook_runtime.run("request_budget.py", main))
