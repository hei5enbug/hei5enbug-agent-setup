from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_hook_trust  # noqa: E402
from role_runner_agents import agent_run, chosen_effort, default_host, runner_for  # noqa: E402
from role_runner_child import child_environment, codex_mcp_off, kill_group, run_child  # noqa: E402
from role_runner_command import claude_command, claude_tools, codex_command, sandbox_for  # noqa: E402
from role_runner_config import (  # noqa: E402
    AGENT_TARGET, CAPABILITIES, CLAUDE_HOOKS_MESSAGE, CODEX_HOOKS_MESSAGE, DEFAULT_REVIEW_MODEL, EXIT_EVIDENCE, EXIT_OK,
    EXIT_RUN, EXIT_USAGE, MCP_NETWORK_RULE, PREFLIGHT_PROMPT, REGISTRY, REVIEW_MODEL_ENV, REVIEW_MODELS, ROLE_DEFINITIONS,
    ROLE_ENTRY, ROLE_MODEL, ROLE_SENTENCES, ROLES, WRITING_CAPABILITIES, Run, RunnerError, UsageError, build_parser,
)
from role_runner_evidence import (  # noqa: E402
    claude_result, codex_home, json_lines, require_heartbeat, thread_id_from, verify_claude, verify_codex,
)
from role_runner_hooks import exchange_hooks, guard_ready, heal_hooks, hooks_for_cwd, is_guard_hook  # noqa: E402
from role_runner_prompt import capability_sentence, compose, compose_capability_prompt, compose_prompt  # noqa: E402
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


def require_hooks_ready(marker: str, mcp_off: list[str], cwd: str, timeout: int) -> None:
    """Require a ready guard PreToolUse hook for the folder, so no assignment runs unguarded."""
    listed = hooks_for_cwd(app_server_hooks(marker, mcp_off, cwd, timeout), cwd)
    if guard_ready(listed):
        return
    listed, reason = heal_hooks(marker, mcp_off, cwd, timeout, listed)
    if guard_ready(listed):
        return
    found = [
        {
            "key": hook.get("key"), "enabled": hook.get("enabled"), "trust": hook.get("trustStatus"),
            "async": hook.get("async"), "matcher": hook.get("matcher"),
        }
        for hook in listed if is_guard_hook(hook)
    ]
    evidence = {"hooks": found, **({"auto_trust": reason} if reason else {})}
    raise RunnerError(EXIT_EVIDENCE, CODEX_HOOKS_MESSAGE, evidence)


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
    require_heartbeat("codex", run.resume, CODEX_HOOKS_MESSAGE)
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


def execute_codex(args: argparse.Namespace, run: Run, prompt: str, cwd: str) -> dict:
    """A writing run preflights a fresh thread and resumes it; a read-only run checks hooks/list, then runs once."""
    mcp_off = [] if run.mcp else codex_mcp_off(run.target, cwd, args.timeout)
    sandbox = sandbox_for(run)
    if run.writing:
        run = preflight_healing(run, cwd, mcp_off, args.timeout)
    else:
        require_hooks_ready(run.target, mcp_off, cwd, args.timeout)
        if run.resume is not None:
            require_heartbeat("codex", run.resume, CODEX_HOOKS_MESSAGE)
    stdout = run_child(run.target, codex_command(run, cwd, args.result, mcp_off), prompt, cwd, args.timeout)
    evidence = verify_codex(stdout, run.model, run.effort, sandbox)
    if not run.writing and evidence["tool_calls"]:
        require_heartbeat("codex", evidence["session"], CODEX_HOOKS_MESSAGE)
    result_path = Path(args.result)
    if not result_path.is_file() or not result_path.read_text(encoding="utf-8").strip():
        raise RunnerError(EXIT_EVIDENCE, f"Codex wrote no answer at {result_path}")
    return evidence


def execute(args: argparse.Namespace, run: Run, root: Path, cwd: str) -> dict:
    """Run the target, verify its evidence, and return the verified evidence."""
    result_path = Path(args.result)
    try:
        prompt = compose(run, args, root)
    except (OSError, ValueError) as error:
        raise RunnerError(EXIT_RUN, f"Cannot compose the prompt: {error}") from error
    discard(result_path)
    if run.runner == "claude":
        stdout = run_child(run.target, claude_command(run), prompt, cwd, args.timeout)
        result = claude_result(stdout)
        if result.get("is_error"):
            raise RunnerError(EXIT_RUN, f"Claude reported an error: {str(result.get('result'))[:2000]}")
        evidence = verify_claude(result, run.model, run.effort)
        require_heartbeat("claude", evidence["session"], CLAUDE_HOOKS_MESSAGE)
        text = result.get("result")
        if not isinstance(text, str) or not text.strip():
            raise RunnerError(EXIT_EVIDENCE, "Claude returned no answer")
        result_path.write_text(text, encoding="utf-8")
        return evidence
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
            effort=chosen_effort(args.effort, ROLE_ENTRY, model), writing=target == "worker", add_dirs=tuple(args.add_dirs),
            resume=args.resume, instructions=None,
        )
    host = args.host or default_host()
    primary = capability_model(target, host)
    entry = capability_fallback(target, host, primary) if args.fallback else CAPABILITIES[target][host]["primary"]
    if entry["via"] != "runner":
        raise UsageError(
            f"The {host} {'fallback' if args.fallback else 'primary'} entry of {target} has via {entry['via']!r}; "
            "the runner runs only via 'runner'. Use the agent route or the main session."
        )
    model = entry["model"] if args.fallback else primary
    if args.fallback and runner_for(model) == runner_for(primary):
        raise UsageError(f"The fallback {model} of {target} must be the other model family from its primary {primary}")
    return Run(
        target=target, role=None, capability=target, fallback=args.fallback, runner=runner_for(model), model=model,
        effort=chosen_effort(args.effort, entry, model), writing=target in WRITING_CAPABILITIES,
        add_dirs=tuple(args.add_dirs), resume=args.resume, instructions=Path(args.instructions), mcp=args.mcp,
    )


def plan(args: argparse.Namespace) -> Run:
    validate(args)
    run = resolve(args)
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
    if len(pairs) == 1:
        outcomes = [run_pair(args, run, root, cwd, *pairs[0])]
    else:
        with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
            outcomes = list(pool.map(lambda pair: run_pair(args, run, root, cwd, *pair), pairs))
    for _, line, error in outcomes:
        if error is not None:
            print(f"role_runner: {error}", file=sys.stderr)
        print(line)
    return max(code for code, _, _ in outcomes)


if __name__ == "__main__":
    sys.exit(main())
