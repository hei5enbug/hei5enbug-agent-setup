from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_context  # noqa: E402


ROLES = ("scout", "researcher", "reviewer", "worker")
ASSIGNED_ROLE_ENV = "HEI5ENBUG_ASSIGNED_ROLE"
EFFORT = "xhigh"
DEFAULT_TIMEOUT = 2700
DEFAULT_REVIEW_MODEL = "gpt-6-astra"
ROLE_MODEL = "gpt-5.6-luna"
REVIEW_MODELS = (
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "gpt-6-astra",
    "gpt-5.6-luna",
    "gpt-6.1-sol",
)
ROLE_SENTENCES = {
    "scout": (
        "You are Codex acting as a read-only scout for this session: start no agents, make no commit or push, "
        "use no network, make no edits, and return the result the assignment defines."
    ),
    "researcher": (
        "You are Codex acting as a read-only public researcher for this session: start no agents, make no commit "
        "or push, use only the web search tool and no shell network, make no edits, and return the result the "
        "assignment defines."
    ),
    "reviewer": (
        'You are an assigned reviewer under the "Assigned workers" rules: start no agents, make no commit or push, '
        "use no network, make no edits, and return findings only under the role's output contract."
    ),
    "worker": (
        'You are an assigned worker under the "Assigned workers" rules: start no agents, make no commit or push, '
        "use no network, edit only the allowed paths, and end with the changed paths, check results, and blockers."
    ),
}
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_RUN = 3
EXIT_EVIDENCE = 4


class RunnerError(Exception):
    def __init__(self, code: int, message: str, evidence: dict | None = None):
        super().__init__(message)
        self.code = code
        self.evidence = evidence or {"error": message}


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="role_runner.py", add_help=False)
    parser.add_argument("role", choices=ROLES)
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--model")
    parser.add_argument("--add-dir", action="append", default=[], dest="add_dirs")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    return parser


def role_body(role: str, root: Path) -> str:
    text = (root / "agents" / f"{role}.md").read_text(encoding="utf-8")
    if text.startswith("---"):
        lines = text.splitlines()
        closing = next((index for index in range(1, len(lines)) if lines[index].rstrip() == "---"), None)
        if closing is None:
            raise ValueError(f"agents/{role}.md has an unterminated frontmatter block")
        text = "\n".join(lines[closing + 1 :])
    return text.strip()


def compose_prompt(role: str, assignment_text: str, root: Path) -> str:
    """Build the full prompt: role sentence, role definition body, worker rules for a worker, then the assignment."""
    if role not in ROLES:
        raise ValueError(f"Unsupported role: {role}")
    parts = [ROLE_SENTENCES[role], role_body(role, root)]
    if role == "worker":
        parts.append(session_context.assigned_workers_section(root))
    parts.append("## Assignment\n\n" + assignment_text.strip())
    return "\n\n".join(parts) + "\n"


def codex_command(role: str, model: str, cwd: str, result: str, add_dirs: list[str]) -> list[str]:
    command = ["codex"]
    if role == "researcher":
        command.append("--search")
    sandbox = "workspace-write" if role == "worker" else "read-only"
    command += [
        "exec", "-m", model, "-c", f'model_reasoning_effort="{EFFORT}"', "-s", sandbox, "-C", cwd,
    ]
    for directory in add_dirs:
        command += ["--add-dir", directory]
    command += ["--json", "-o", result, "-"]
    return command


def claude_command(model: str) -> list[str]:
    return [
        "claude", "-p", "--model", model, "--effort", EFFORT, "--output-format", "json",
        "--tools", "Read", "Grep", "Glob", "--strict-mcp-config", "--permission-mode", "dontAsk",
        "--allowedTools", "Read", "Grep", "Glob",
    ]


def run_child(role: str, command: list[str], prompt: str, cwd: str, timeout: int) -> str:
    environment = dict(os.environ)
    environment[ASSIGNED_ROLE_ENV] = role
    try:
        child = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", cwd=cwd, env=environment, start_new_session=True,
        )
    except OSError as error:
        raise RunnerError(EXIT_RUN, f"Cannot start {command[0]}: {error}") from error
    try:
        stdout, stderr = child.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.communicate()
        raise RunnerError(EXIT_RUN, f"{command[0]} exceeded the {timeout} second timeout") from None
    if child.returncode != 0:
        tail = (stderr or "").strip()[-2000:]
        raise RunnerError(EXIT_RUN, f"{command[0]} exited with {child.returncode}: {tail}")
    return stdout


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


def verify_codex(stdout: str, model: str) -> dict:
    thread_id = thread_id_from(stdout)
    if thread_id is None:
        raise RunnerError(EXIT_EVIDENCE, "No thread.started event with a thread_id in the Codex output")
    sessions = codex_home() / "sessions"
    rollouts = sorted(sessions.glob(f"**/rollout-*{thread_id}.jsonl")) if sessions.is_dir() else []
    if not rollouts:
        raise RunnerError(EXIT_EVIDENCE, f"No rollout file for thread {thread_id} under {sessions}")
    rollout = rollouts[-1]
    turns = []
    for entry in json_lines(rollout):
        if entry.get("type") == "turn_context":
            payload = entry.get("payload")
            turns.append(payload if isinstance(payload, dict) else {})
    if not turns:
        raise RunnerError(EXIT_EVIDENCE, f"No turn_context entry in {rollout}", {"rollout": rollout.as_posix()})
    for turn in turns:
        if turn.get("model") != model or turn.get("effort") != EFFORT:
            raise RunnerError(
                EXIT_EVIDENCE,
                f"turn_context names {turn.get('model')!r} with {turn.get('effort')!r}, expected {model!r} with {EFFORT!r}",
                {"rollout": rollout.as_posix(), "turns": len(turns)},
            )
    return {"rollout": rollout.as_posix(), "turns": len(turns)}


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


def verify_claude(result: dict, model: str) -> dict:
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
    for entry in assistants:
        message = entry.get("message")
        entry_model = message.get("model") if isinstance(message, dict) else None
        if entry_model != model or entry.get("effort") != EFFORT:
            raise RunnerError(
                EXIT_EVIDENCE,
                f"assistant entry names {entry_model!r} with {entry.get('effort')!r}, expected {model!r} with {EFFORT!r}",
                {"transcript": transcript.as_posix(), "entries": len(assistants)},
            )
    return {"transcript": transcript.as_posix(), "entries": len(assistants)}


def discard(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def execute(args: argparse.Namespace, root: Path, cwd: str) -> tuple[str, str, dict]:
    """Run the role, verify its evidence, and return the runner, model, and evidence."""
    role = args.role
    result_path = Path(args.result)
    try:
        assignment = Path(args.assignment).read_text(encoding="utf-8")
        prompt = compose_prompt(role, assignment, root)
    except (OSError, ValueError) as error:
        raise RunnerError(EXIT_RUN, f"Cannot compose the prompt: {error}") from error
    model = args.model or (DEFAULT_REVIEW_MODEL if role == "reviewer" else ROLE_MODEL)
    discard(result_path)
    if model.startswith("claude-"):
        stdout = run_child(role, claude_command(model), prompt, cwd, args.timeout)
        result = claude_result(stdout)
        if result.get("is_error"):
            raise RunnerError(EXIT_RUN, f"Claude reported an error: {str(result.get('result'))[:2000]}")
        evidence = verify_claude(result, model)
        text = result.get("result")
        if not isinstance(text, str) or not text.strip():
            raise RunnerError(EXIT_EVIDENCE, "Claude returned no answer")
        result_path.write_text(text, encoding="utf-8")
        return "claude", model, evidence
    command = codex_command(role, model, cwd, args.result, args.add_dirs)
    try:
        stdout = run_child(role, command, prompt, cwd, args.timeout)
        evidence = verify_codex(stdout, model)
        if not result_path.is_file() or not result_path.read_text(encoding="utf-8").strip():
            raise RunnerError(EXIT_EVIDENCE, f"Codex wrote no answer at {result_path}")
    except RunnerError:
        discard(result_path)
        raise
    return "codex", model, evidence


def status(role, runner, model, verified: bool, evidence: dict, code: int) -> str:
    return json.dumps(
        {
            "role": role, "runner": runner, "model": model, "effort": EFFORT, "verified": verified,
            "evidence": evidence, "exit": code,
        },
        ensure_ascii=False,
    )


def validate(args: argparse.Namespace) -> None:
    if args.model is not None and args.role != "reviewer":
        raise UsageError("--model is allowed only for the reviewer role")
    if args.add_dirs and args.role != "worker":
        raise UsageError("--add-dir is allowed only for the worker role")
    if args.model is not None and args.model not in REVIEW_MODELS:
        raise UsageError(f"--model must be one of: {', '.join(REVIEW_MODELS)}")
    if args.timeout <= 0:
        raise UsageError("--timeout must be a positive number of seconds")
    if not Path(args.assignment).is_file():
        raise UsageError(f"Assignment file not found: {args.assignment}")
    result = Path(args.result)
    if result.resolve() == Path(args.assignment).resolve():
        raise UsageError("--assignment and --result must name different files")
    if result.is_dir() or not result.parent.is_dir():
        raise UsageError(f"Result must name a file in an existing directory: {args.result}")


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        args = build_parser().parse_args(argv)
        validate(args)
    except UsageError as error:
        print(f"role_runner: {error}", file=sys.stderr)
        print(status(None, None, None, False, {"error": str(error)}, EXIT_USAGE))
        return EXIT_USAGE
    role = args.role
    model = args.model or (DEFAULT_REVIEW_MODEL if role == "reviewer" else ROLE_MODEL)
    runner = "claude" if model.startswith("claude-") else "codex"
    try:
        runner, model, evidence = execute(args, root, os.getcwd())
    except RunnerError as error:
        print(f"role_runner: {error}", file=sys.stderr)
        print(status(role, runner, model, False, error.evidence, error.code))
        return error.code
    print(status(role, runner, model, True, evidence, EXIT_OK))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
