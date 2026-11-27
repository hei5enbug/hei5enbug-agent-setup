from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_hook_trust  # noqa: E402
from plugin_toggles import service_tier_setting  # noqa: E402
from role_runner_agents import agent_run, chosen_effort, default_host, runner_for  # noqa: E402
from role_runner_child import child_environment, codex_mcp_off, guard_switch_off, kill_group, run_child  # noqa: E402
from role_runner_command import claude_command, claude_tools, codex_command, sandbox_for  # noqa: E402
from role_runner_config import (  # noqa: E402
    AGENT_TARGET, CAPABILITIES, CODEX_HOOKS_MESSAGE, DEFAULT_REVIEW_MODEL, EXIT_EVIDENCE, EXIT_OK,
    EXIT_CAP, EXIT_RUN, EXIT_USAGE, GUARD_SWITCH_MESSAGE, GUARD_UNKNOWN_MESSAGE, HOST_NAMES, MCP_NETWORK_RULE, PREFLIGHT_PROMPT,
    REGISTRY, REVIEW_MODEL_ENV, REVIEW_MODELS, ROLE_DEFINITIONS,
    ROLE_ENTRY, ROLE_MODEL, ROLE_SENTENCES, ROLES, WRITING_CAPABILITIES, Run, RunnerError, UsageError, build_parser,
)
from role_runner_budget import Gate  # noqa: E402
from role_runner_evidence import (  # noqa: E402
    claude_init, claude_result, codex_home, json_lines, require_heartbeat, thread_id_from, turns_before, verify_claude, verify_codex,
)
from role_runner_hooks import exchange_hooks, guard_ready, heal_hooks, hooks_for_cwd, is_guard_hook  # noqa: E402
from role_runner_prompt import capability_sentence, compose, compose_capability_prompt, compose_prompt  # noqa: E402
from role_runner_scratch import scratch_folder  # noqa: E402
from role_runner_validate import validate  # noqa: E402


def app_server_hooks(marker: str, mcp_off: list[str], cwd: str, timeout: int) -> object:
    """Ask a Codex app-server for the folder's hooks, keeping stdin open until it answers, and return the result."""
    command = ["codex", "app-server", *mcp_off]
    try:
        child = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", cwd=cwd, env=child_environment(marker), start_new_session=True,
        )
    except OSError as error:
        raise RunnerError(EXIT_RUN, f"Cannot start {command[0]} app-server: {error}") from error
    expired = threading.Event()

    def expire() -> None:
        expired.set()
        kill_group(child.pid)

    timer = threading.Timer(timeout, expire)
    timer.start()
    method, reply = "initialize", None
    try:
        method, reply = exchange_hooks(child, cwd)
    except OSError:
        pass
    finally:
        timer.cancel()
        returncode = child.poll()
        kill_group(child.pid)
        child.stdout.close()
        try:
            child.stdin.close()
        except OSError:
            pass
        child.wait()
    if expired.is_set():
        raise RunnerError(EXIT_RUN, f"codex app-server exceeded the {timeout} second timeout")
    if reply is None:
        raise RunnerError(EXIT_RUN, f"codex app-server ended before answering {method} (exit {returncode})")
    if "error" in reply:
        raise RunnerError(EXIT_RUN, f"codex app-server rejected {method}: {str(reply['error'])[:500]}")
    return reply.get("result")


def guard_states(listed: list) -> list[dict]:
    """Return the state of each guard PreToolUse hook in a hooks/list result."""
    return [
        {
            "key": hook.get("key"), "enabled": hook.get("enabled"), "trust": hook.get("trustStatus"),
            "async": hook.get("async"), "matcher": hook.get("matcher"),
        }
        for hook in listed if is_guard_hook(hook)
    ]


def hooks_message(found: list[dict]) -> str:
    """The untrusted-hooks message with the state of each guard hook the app-server listed."""
    states = "; ".join(
        f"trust={hook['trust']}, enabled={hook['enabled']}, async={hook['async']}, matcher={hook['matcher']}" for hook in found
    )
    return f"{CODEX_HOOKS_MESSAGE} (guard hooks listed: {states or 'none'})"


def explain_heartbeat(host: str, marker: str, listing: Callable[[], list] | None = None) -> Callable[[str], tuple[str, dict]]:
    """Return the function that names why a required heartbeat is missing, from what the runner sees: the approval guard
    switch in the environment the child got, then the guard hooks that listing returns, else an unknown cause."""

    def explain(heartbeat: str) -> tuple[str, dict]:
        name = HOST_NAMES[host]
        off = guard_switch_off(host, child_environment(marker))
        if off is not None:
            return GUARD_SWITCH_MESSAGE.format(host=name, variable=off[0], value=off[1]), {"cause": "switch", "switch": off[0]}
        extra: dict = {}
        if listing is not None:
            try:
                listed = listing()
            except RunnerError as error:
                extra = {"hooks_error": str(error)}
            else:
                if not guard_ready(listed):
                    found = guard_states(listed)
                    return hooks_message(found), {"cause": "untrusted", "hooks": found}
        return GUARD_UNKNOWN_MESSAGE.format(host=name, heartbeat=heartbeat), {"cause": "unknown", **extra}

    return explain


def require_hooks_ready(marker: str, mcp_off: list[str], cwd: str, timeout: int) -> list:
    """Require a ready guard PreToolUse hook for the folder, so no assignment runs unguarded; return the hooks it listed."""
    listed = hooks_for_cwd(app_server_hooks(marker, mcp_off, cwd, timeout), cwd)
    if guard_ready(listed):
        return listed
    listed, reason = heal_hooks(marker, mcp_off, cwd, timeout, listed)
    if guard_ready(listed):
        return listed
    found = guard_states(listed)
    evidence = {"cause": "untrusted", "hooks": found, **({"auto_trust": reason} if reason else {})}
    raise RunnerError(EXIT_EVIDENCE, hooks_message(found), evidence)


def discard(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def preflight_thread(run: Run, cwd: str, mcp_off: list[str], timeout: int) -> Run:
    """Preflight the guard hooks in a fresh thread unless resuming one, require its PreToolUse heartbeat, and return the run on it."""
    if run.resume is None:
        with tempfile.TemporaryDirectory(prefix="role-runner-") as scratch:
            output = str(Path(scratch) / "preflight.txt")
            stdout = run_child(run.target, codex_command(run, cwd, output, mcp_off), PREFLIGHT_PROMPT, cwd, timeout)
        thread_id = thread_id_from(stdout)
        if thread_id is None:
            raise RunnerError(EXIT_EVIDENCE, "No thread.started event with a thread_id in the Codex preflight output")
        run = replace(run, resume=thread_id)
    listing = lambda: hooks_for_cwd(app_server_hooks(run.target, mcp_off, cwd, timeout), cwd)  # noqa: E731
    require_heartbeat("codex", run.resume, explain_heartbeat("codex", run.target, listing))
    return run


def preflight_healing(run: Run, cwd: str, mcp_off: list[str], timeout: int) -> Run:
    """Preflight a fresh thread; when its guard hook did not run because a release left it untrusted, re-trust it from a
    verified official copy and preflight once more."""
    try:
        return preflight_thread(run, cwd, mcp_off, timeout)
    except RunnerError as error:
        if error.code != EXIT_EVIDENCE or run.resume is not None:
            raise
        listed = hooks_for_cwd(app_server_hooks(run.target, mcp_off, cwd, timeout), cwd)
        if guard_ready(listed) or not guard_ready(heal_hooks(run.target, mcp_off, cwd, timeout, listed)[0]):
            raise
    return preflight_thread(run, cwd, mcp_off, timeout)


def run_codex(args: argparse.Namespace, run: Run, prompt: str, cwd: str, mcp_off: list[str]) -> dict:
    """Run a Codex child and verify it: a writing run in its workspace-write sandbox, a read-only run in a scratch folder
    that holds its only writable path and is removed on every exit."""
    if run.writing:
        stdout = run_child(run.target, codex_command(run, cwd, args.result, mcp_off), prompt, cwd, args.timeout)
        return verify_codex(stdout, run.model, run.effort, sandbox_for(run))
    with scratch_folder(cwd, run.add_dirs) as scratch:
        since_turn = turns_before(run.resume) if run.resume is not None else 0
        command = codex_command(run, cwd, args.result, mcp_off, scratch)
        stdout = run_child(run.target, command, prompt, cwd, args.timeout, scratch)
        return verify_codex(stdout, run.model, run.effort, sandbox_for(run), scratch, since_turn)


def execute_codex(args: argparse.Namespace, run: Run, prompt: str, cwd: str) -> dict:
    """A writing run preflights a fresh thread and resumes it; a read-only run checks hooks/list, then runs once."""
    mcp_off = [] if run.mcp else codex_mcp_off(run.target, cwd, args.timeout)
    if run.writing:
        run = preflight_healing(run, cwd, mcp_off, args.timeout)
    else:
        ready = require_hooks_ready(run.target, mcp_off, cwd, args.timeout)
        explain = explain_heartbeat("codex", run.target, lambda: ready)
        if run.resume is not None:
            require_heartbeat("codex", run.resume, explain)
    evidence = run_codex(args, run, prompt, cwd, mcp_off)
    if not run.writing and evidence["tool_calls"]:
        require_heartbeat("codex", evidence["session"], explain)
    result_path = Path(args.result)
    if not result_path.is_file() or not result_path.read_text(encoding="utf-8").strip():
        raise RunnerError(EXIT_EVIDENCE, f"Codex wrote no answer at {result_path}")
    return evidence


def claude_outcome(
    run: Run, stdout: str, command: list[str] | None = None, init: dict | None = None, scratch: Path | None = None,
    session: str | None = None,
) -> tuple[dict, dict]:
    result = claude_result(stdout)
    if result.get("is_error"):
        raise RunnerError(EXIT_RUN, f"Claude reported an error: {str(result.get('result'))[:2000]}")
    return result, verify_claude(result, run.model, run.effort, command, init, scratch, run.validation, session)


def run_claude(args: argparse.Namespace, run: Run, prompt: str, cwd: str) -> tuple[dict, dict]:
    """Run a Claude child and return its result and verified evidence. A read-only run starts in a scratch folder under a
    sandbox that confines its writes to that folder, and the folder is removed on every exit."""
    if run.writing:
        return claude_outcome(run, run_child(run.target, claude_command(run), prompt, cwd, args.timeout))
    session = run.resume or str(uuid.uuid4())
    with scratch_folder(cwd, run.add_dirs, session) as scratch:
        command = claude_command(run, scratch, session)
        stdout = run_child(run.target, command, prompt, scratch.as_posix(), args.timeout, scratch)
        return claude_outcome(run, stdout, command, claude_init(stdout), scratch, session)


def execute_claude(args: argparse.Namespace, run: Run, prompt: str, cwd: str) -> dict:
    result, evidence = run_claude(args, run, prompt, cwd)
    require_heartbeat("claude", evidence["session"], explain_heartbeat("claude", run.target))
    text = result.get("result")
    if not isinstance(text, str) or not text.strip():
        raise RunnerError(EXIT_EVIDENCE, "Claude returned no answer")
    Path(args.result).write_text(text, encoding="utf-8")
    return evidence


def execute(args: argparse.Namespace, run: Run, root: Path, cwd: str) -> dict:
    """Run the target, verify its evidence, and return the verified evidence."""
    result_path = Path(args.result)
    try:
        prompt = compose(run, args, root, cwd)
    except (OSError, ValueError) as error:
        raise RunnerError(EXIT_RUN, f"Cannot compose the prompt: {error}") from error
    discard(result_path)
    if run.runner == "claude":
        return execute_claude(args, run, prompt, cwd)
    try:
        return execute_codex(args, run, prompt, cwd)
    except RunnerError:
        discard(result_path)
        raise


def status(run: Run | None, verified: bool, evidence: dict, code: int) -> str:
    return json.dumps(
        {
            "role": run.role if run else None,
            "capability": run.capability if run else None,
            "agent": run.agent if run else None,
            "fallback": run.fallback if run else False,
            "runner": run.runner if run else None,
            "model": run.model if run else None,
            "effort": run.effort if run else None,
            "verified": verified, "evidence": evidence, "exit": code,
            **({"user_requested": True} if run and run.user_requested else {}),
            **({"validation": True} if run and run.validation else {}),
            **({"service_tier": run.service_tier} if run and run.service_tier else {}),
        },
        ensure_ascii=False,
    )


def capability_model(target: str, host: str) -> str:
    """Return the model a capability's primary runs: its entry model, or the review_model setting when that names a listed model."""
    entry = CAPABILITIES[target][host]["primary"]
    if entry.get("setting") == "review_model" and os.environ.get(REVIEW_MODEL_ENV) in REVIEW_MODELS:
        return os.environ[REVIEW_MODEL_ENV]
    return entry["model"]


def capability_fallback(target: str, host: str, primary: str) -> dict:
    """Return a capability's fallback entry. A review on Claude whose primary resolves to Claude falls back cross-family to Astra."""
    if target == "review" and host == "claude" and runner_for(primary) == "claude":
        return REGISTRY["runner"]["review_cross_family_fallback"]
    return CAPABILITIES[target][host]["fallback"]


def resolve(args: argparse.Namespace) -> Run:
    target = args.role
    if target == AGENT_TARGET:
        return agent_run(args, args.host or default_host())
    if target in ROLES:
        model = args.model or (DEFAULT_REVIEW_MODEL if target == "reviewer" else ROLE_MODEL)
        return Run(
            target=target, role=target, capability=None, fallback=False, runner=runner_for(model), model=model,
            effort=chosen_effort(args.effort, ROLE_ENTRY, model, args.user_requested), writing=target == "worker", add_dirs=tuple(args.add_dirs),
            resume=args.resume, instructions=None,
        )
    host = args.host or default_host()
    primary = capability_model(target, host)
    entry = capability_fallback(target, host, primary) if args.fallback else CAPABILITIES[target][host]["primary"]
    if entry["via"] != "runner" and args.model is None and not args.user_requested:
        raise UsageError(
            f"The {host} {'fallback' if args.fallback else 'primary'} entry of {target} has via {entry['via']!r}; "
            "the runner runs only via 'runner'. Use the agent route or the main session."
        )
    model = args.model or (entry["model"] if args.fallback else primary)
    if args.fallback and args.model is None and runner_for(model) == runner_for(primary):
        raise UsageError(f"The fallback {model} of {target} must be the other model family from its primary {primary}")
    return Run(
        target=target, role=None, capability=target, fallback=args.fallback, runner=runner_for(model), model=model,
        effort=chosen_effort(args.effort, entry, model, args.user_requested), writing=target in WRITING_CAPABILITIES,
        add_dirs=tuple(args.add_dirs), resume=args.resume, instructions=Path(args.instructions), mcp=args.mcp,
    )


def is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def chosen_service_tier(args: argparse.Namespace, run: Run) -> str | None:
    """The service tier of a Codex run: the option when given, else the `codex_service_tier` setting; a Claude run has none."""
    if run.runner != "codex":
        return None
    if args.service_tier:
        return args.service_tier
    try:
        return service_tier_setting()
    except ValueError as error:
        raise UsageError(str(error)) from error


def plan(args: argparse.Namespace) -> Run:
    validate(args)
    run = replace(resolve(args), user_requested=args.user_requested, validation=args.validation)
    run = replace(run, service_tier=chosen_service_tier(args, run))
    if run.runner == "claude" and not run.writing and run.resume is not None and not is_uuid(run.resume):
        raise UsageError("--resume for a read-only Claude run must name the session id (a UUID) that a previous run reported")
    if run.writing and run.runner == "claude" and not run.add_dirs and run.agent is None:
        label = f"capability {run.capability}" if run.capability else f"role {run.role}"
        raise UsageError(f"The Claude path of the writing {label} needs --add-dir for each directory it may edit")
    if run.writing and len(args.assignment) > 1:
        raise UsageError("Several assignment and result pairs are allowed only for a read-only target")
    return run


def run_pair(args: argparse.Namespace, run: Run, root: Path, cwd: str, assignment: str, result: str) -> tuple[int, str, str | None]:
    """Run one assignment and result pair as a single run would, and return its exit code, status line, and error text."""
    pair = argparse.Namespace(**{**vars(args), "assignment": assignment, "result": result})
    try:
        evidence = execute(pair, run, root, cwd)
    except RunnerError as error:
        return error.code, status(run, False, error.evidence, error.code), str(error)
    except OSError as error:
        message = f"Cannot handle the result file: {error}"
        return EXIT_RUN, status(run, False, {"error": message}, EXIT_RUN), message
    return EXIT_OK, status(run, True, evidence, EXIT_OK), None


def run_gated(gate: Gate, args: argparse.Namespace, run: Run, root: Path, cwd: str, index: int, assignment: str, result: str):
    """Run one pair once the request budget admits it; a denied pair ends with the cap exit code and the denial."""
    run_id = f"runner-{os.getpid()}-{index}"
    reason = gate.acquire(run_id)
    if reason is not None:
        return EXIT_CAP, status(run, False, {"error": reason, "cap": True}, EXIT_CAP), reason
    outcome = (EXIT_RUN, "", None)
    try:
        outcome = run_pair(args, run, root, cwd, assignment, result)
        return outcome
    finally:
        gate.release(run_id, outcome[0] == EXIT_OK)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        args = build_parser().parse_args(argv)
        run = plan(args)
    except UsageError as error:
        print(f"role_runner: {error}", file=sys.stderr)
        print(status(None, False, {"error": str(error)}, EXIT_USAGE))
        return EXIT_USAGE
    cwd = os.getcwd()
    pairs = list(zip(args.assignment, args.result))
    gate = Gate(run)
    if len(pairs) == 1:
        outcomes = [run_gated(gate, args, run, root, cwd, 0, *pairs[0])]
    else:
        with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
            outcomes = list(pool.map(lambda item: run_gated(gate, args, run, root, cwd, item[0], *item[1]), enumerate(pairs)))
    for _, line, error in outcomes:
        if error is not None:
            print(f"role_runner: {error}", file=sys.stderr)
        print(line)
    return max(code for code, _, _ in outcomes)


if __name__ == "__main__":
    sys.exit(main())
