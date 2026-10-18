from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_guard  # noqa: E402
import session_context  # noqa: E402


ROLES = ("scout", "researcher", "reviewer", "worker")
ASSIGNED_ROLE_ENV = "HEI5ENBUG_ASSIGNED_ROLE"
REVIEW_MODEL_ENV = "HEI5ENBUG_REVIEW_MODEL"
PARENT_SESSION_ENV = "HEI5ENBUG_PARENT_SESSION"
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "model-registry.json"
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
ROLE_EFFORT = REGISTRY["runner"]["effort"]
DEFAULT_TIMEOUT = 2700
DEFAULT_REVIEW_MODEL = REGISTRY["runner"]["default_review_model"]
ROLE_MODEL = REGISTRY["runner"]["role_model"]
REVIEW_MODELS = tuple(REGISTRY["runner"]["review_models"])
CAPABILITIES = REGISTRY["capabilities"]
HOSTS = ("claude", "codex")
WRITING_CAPABILITIES = ("implementation", "design", "language")
ROOT = Path(__file__).resolve().parents[1]
AGENT_TARGET = "agent"
ROLE_DEFINITIONS = {"researcher": "scout"}
WEB_TOOLS = ("WebSearch", "WebFetch")
MCP_TOOL_RULE = "mcp__*"
READ_SHELL_RULES = (
    "Bash(git diff:*)", "Bash(git show:*)", "Bash(git grep:*)", "Bash(git log:*)", "Bash(git cat-file:*)",
    "Bash(git ls-tree:*)", "Bash(git ls-files:*)", "Bash(git rev-parse:*)", "Bash(git merge-base:*)",
    "Bash(rg:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
)
SYNTHETIC_MODEL = "<synthetic>"
PREFLIGHT_PROMPT = "Run the shell command `true` exactly once, then reply with OK only."
MCP_SERVER_NAME = re.compile(r"[A-Za-z0-9_-]+")
CODEX_HOOKS_MESSAGE = "The approval guard hooks did not run in Codex; trust them in /hooks"
CLAUDE_HOOKS_MESSAGE = "The approval guard hooks did not run in Claude Code"
NO_NETWORK_RULE = "use no network"
MCP_NETWORK_RULE = "use MCP tools and network only for the external work the assignment names"
CODEX_NETWORK_ON = "sandbox_workspace_write.network_access=true"


def worker_sentence(network: str) -> str:
    return (
        'You are an assigned worker under the "Assigned workers" rules: start no agents, make no commit or push, '
        f"{network}, edit only the allowed paths, and end with the changed paths, check results, and blockers."
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
    "worker": worker_sentence(NO_NETWORK_RULE),
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


@dataclass(frozen=True)
class Run:
    """A validated call: the role or capability, the registry entry it resolves to, and the call options."""

    target: str
    role: str | None
    capability: str | None
    fallback: bool
    runner: str
    model: str
    effort: str
    writing: bool
    add_dirs: tuple[str, ...]
    resume: str | None
    instructions: Path | None
    agent: str | None = None
    body: str | None = None
    web_tools: tuple[str, ...] = ()
    mcp: bool = False


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="role_runner.py", add_help=False)
    parser.add_argument("role")
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--model")
    parser.add_argument("--add-dir", action="append", default=[], dest="add_dirs")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--host", choices=HOSTS)
    parser.add_argument("--fallback", action="store_true")
    parser.add_argument("--instructions")
    parser.add_argument("--resume")
    parser.add_argument("--name")
    parser.add_argument("--mcp", action="store_true")
    return parser


def without_frontmatter(text: str, label: str) -> str:
    if text.startswith("---"):
        lines = text.splitlines()
        closing = next((index for index in range(1, len(lines)) if lines[index].rstrip() == "---"), None)
        if closing is None:
            raise ValueError(f"{label} has an unterminated frontmatter block")
        text = "\n".join(lines[closing + 1 :])
    return text.strip()


def role_body(role: str, root: Path) -> str:
    name = ROLE_DEFINITIONS.get(role, role)
    text = (root / "agents" / f"{name}.md").read_text(encoding="utf-8")
    return without_frontmatter(text, f"agents/{name}.md")


def network_rule(mcp: bool) -> str:
    """Return the network rule a prompt states: no network, or MCP and network for the external work only."""
    return MCP_NETWORK_RULE if mcp else NO_NETWORK_RULE


def shell_sentence(limited: bool) -> list[str]:
    """Name the read-only shell commands a Claude run without --mcp may use; its permission rules match the command prefix."""
    if not limited:
        return []
    commands = ", ".join(f"`{rule[len('Bash('):-len(':*)')]}`" for rule in READ_SHELL_RULES)
    return [
        f"The shell runs only these read-only commands from the working directory: {commands}. "
        "Do not prefix them with `git -C` or `cd`; use file tools for other reads."
    ]


def capability_sentence(capability: str, mcp: bool = False) -> str:
    return (
        f"You are an assigned worker for the {capability} capability: start no agents, make no commit or push, "
        f"{network_rule(mcp)}, and follow the instructions and assignment below."
    )


def compose_prompt(role: str, assignment_text: str, root: Path) -> str:
    """Build the full prompt: role sentence, role definition body, worker rules for a worker, then the assignment."""
    if role not in ROLES:
        raise ValueError(f"Unsupported role: {role}")
    parts = [ROLE_SENTENCES[role], role_body(role, root)]
    if role == "worker":
        parts.append(session_context.assigned_workers_section(root))
    parts.append("## Assignment\n\n" + assignment_text.strip())
    return "\n\n".join(parts) + "\n"


def compose_capability_prompt(
    capability: str, instructions: str, assignment_text: str, root: Path, mcp: bool = False, limited_shell: bool = False,
) -> str:
    """Build a capability prompt: capability sentence, instructions body, worker rules, then the assignment."""
    parts = [
        capability_sentence(capability, mcp),
        *shell_sentence(limited_shell),
        instructions,
        session_context.assigned_workers_section(root),
        "## Assignment\n\n" + assignment_text.strip(),
    ]
    return "\n\n".join(parts) + "\n"


def compose_agent_prompt(body: str, assignment_text: str, root: Path, mcp: bool = False, limited_shell: bool = False) -> str:
    """Build an agent prompt: the assigned-worker sentence, the agent instructions, worker rules, then the assignment."""
    parts = [
        worker_sentence(network_rule(mcp)),
        *shell_sentence(limited_shell),
        body,
        session_context.assigned_workers_section(root),
        "## Assignment\n\n" + assignment_text.strip(),
    ]
    return "\n\n".join(parts) + "\n"


def compose(run: Run, args: argparse.Namespace, root: Path) -> str:
    assignment_text = Path(args.assignment).read_text(encoding="utf-8")
    limited_shell = run.runner == "claude" and not run.mcp
    if run.agent is not None:
        return compose_agent_prompt(run.body, assignment_text, root, run.mcp, limited_shell)
    if run.capability is None:
        return compose_prompt(run.role, assignment_text, root)
    instructions = run.instructions.read_text(encoding="utf-8")
    body = without_frontmatter(instructions, run.instructions.as_posix())
    return compose_capability_prompt(run.capability, body, assignment_text, root, run.mcp, limited_shell)


def sandbox_for(run: Run) -> str:
    return "workspace-write" if run.writing else "read-only"


def scoped_codex_config(run: Run, mcp_off: list[str]) -> list[str]:
    """A run without --mcp turns every listed MCP server off, and a writing run with --mcp also allows network."""
    if not run.mcp:
        return mcp_off
    return ["-c", CODEX_NETWORK_ON] if run.writing else []


def codex_command(run: Run, cwd: str, result: str, mcp_off: list[str]) -> list[str]:
    command = ["codex"]
    if run.role == "researcher" or run.web_tools:
        command.append("--search")
    sandbox = sandbox_for(run)
    scoped = scoped_codex_config(run, mcp_off)
    if run.resume is not None:
        command += [
            "exec", "resume", run.resume, "-m", run.model,
            "-c", f'model_reasoning_effort="{run.effort}"', "-c", f'sandbox_mode="{sandbox}"', *scoped,
        ]
        if run.writing and run.add_dirs:
            roots = [str(Path(directory).resolve()) for directory in run.add_dirs]
            command += ["-c", f"sandbox_workspace_write.writable_roots={json.dumps(roots)}"]
        command += ["--json", "-o", result, "-"]
        return command
    command += [
        "exec", "-m", run.model, "-c", f'model_reasoning_effort="{run.effort}"', "-s", sandbox, "-C", cwd, *scoped,
    ]
    for directory in run.add_dirs:
        command += ["--add-dir", directory]
    command += ["--json", "-o", result, "-"]
    return command


def edit_rules(directories: tuple[str, ...]) -> list[str]:
    """Return one Edit rule per approved directory: Claude Code applies Edit rules to Write and reads `//` as the filesystem root."""
    return [f"Edit(/{Path(directory).resolve().as_posix()}/**)" for directory in directories]


def claude_rules(run: Run) -> list[str]:
    """Return an agent or capability run's Claude rules: reads, the read-only shell, listed web tools, approved edits, and --mcp."""
    rules = ["Read", "Grep", "Glob", *READ_SHELL_RULES, *run.web_tools]
    if run.writing:
        rules += edit_rules(run.add_dirs)
    if run.writing or run.mcp:
        rules += ["Bash"]
    if run.mcp:
        rules += [MCP_TOOL_RULE]
    return rules


def claude_tools(rules: list[str]) -> list[str]:
    """Return the built-in tools the rules name, in first-use order, plus Write after Edit, whose rules also grant Write."""
    names: list[str] = []
    for rule in rules:
        name = rule.split("(", 1)[0]
        if name != MCP_TOOL_RULE and name not in names:
            names.append(name)
    if "Edit" in names:
        names.append("Write")
    return names


def claude_command(run: Run) -> list[str]:
    if run.agent is not None or run.capability is not None:
        allowed = claude_rules(run)
        tools = claude_tools(allowed)
        mode = "dontAsk"
    else:
        allowed = ["Read", "Grep", "Glob", *(["Bash"] if run.writing else []), *(edit_rules(run.add_dirs) if run.writing else [])]
        tools = claude_tools(allowed)
        mode = "dontAsk"
    command = ["claude", "-p"]
    if run.resume is not None:
        command += ["--resume", run.resume]
    command += ["--model", run.model, "--effort", run.effort, "--output-format", "json", "--tools", *tools]
    if not run.mcp:
        command += ["--strict-mcp-config"]
    command += ["--permission-mode", mode, "--allowedTools", *allowed]
    for directory in run.add_dirs:
        command += ["--add-dir", directory]
    return command


def parent_session(environ) -> str | None:
    """Return the session the approval guard treats as the child's parent: the inherited value, else this session's own."""
    existing = environ.get(PARENT_SESSION_ENV)
    if existing:
        return existing
    claude_id = environ.get("CLAUDE_CODE_SESSION_ID")
    if environ.get("CLAUDECODE") and claude_id:
        return f"claude:{claude_id}"
    codex_id = environ.get("CODEX_SESSION_ID") or environ.get("CODEX_THREAD_ID")
    if codex_id:
        return f"codex:{codex_id}"
    return None


def child_environment(marker: str) -> dict:
    environment = dict(os.environ)
    environment[ASSIGNED_ROLE_ENV] = marker
    parent = parent_session(environment)
    if parent is not None:
        environment[PARENT_SESSION_ENV] = parent
    return environment


def run_child(marker: str, command: list[str], prompt: str, cwd: str, timeout: int) -> str:
    environment = child_environment(marker)
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


def codex_mcp_off(marker: str, cwd: str, timeout: int) -> list[str]:
    """List the configured Codex MCP servers with the child's environment and return one disabling override for each."""
    try:
        listing = run_child(marker, ["codex", "mcp", "list", "--json"], "", cwd, timeout)
        servers = json.loads(listing)
    except RunnerError as error:
        raise RunnerError(EXIT_RUN, f"Cannot list the Codex MCP servers to turn them off: {error}") from error
    except json.JSONDecodeError as error:
        raise RunnerError(EXIT_RUN, "The Codex MCP server list is not JSON, so the servers cannot be turned off") from error
    if not isinstance(servers, list):
        raise RunnerError(EXIT_RUN, "The Codex MCP server list is not a list, so the servers cannot be turned off")
    names = [server.get("name") if isinstance(server, dict) else None for server in servers]
    for name in names:
        if not isinstance(name, str) or not MCP_SERVER_NAME.fullmatch(name):
            raise RunnerError(EXIT_RUN, f"The Codex MCP server name {name!r} cannot be turned off safely")
    flags: list[str] = []
    for name in names:
        flags += ["-c", f"mcp_servers.{name}.enabled=false"]
    return flags


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


def verify_codex(stdout: str, model: str, effort: str, sandbox: str) -> dict:
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
        if turn.get("model") != model or turn.get("effort") != effort:
            raise RunnerError(
                EXIT_EVIDENCE,
                f"turn_context names {turn.get('model')!r} with {turn.get('effort')!r}, expected {model!r} with {effort!r}",
                {"rollout": rollout.as_posix(), "turns": len(turns)},
            )
        policy = turn.get("sandbox_policy")
        sandbox_type = policy.get("type") if isinstance(policy, dict) else None
        if sandbox_type != sandbox:
            raise RunnerError(
                EXIT_EVIDENCE,
                f"turn_context names sandbox {sandbox_type!r}, expected {sandbox!r}",
                {"rollout": rollout.as_posix(), "turns": len(turns)},
            )
    return {"rollout": rollout.as_posix(), "turns": len(turns), "session": thread_id}


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


def is_synthetic(entry: dict) -> bool:
    message = entry.get("message")
    return isinstance(message, dict) and message.get("model") == SYNTHETIC_MODEL


def verify_claude(result: dict, model: str, effort: str) -> dict:
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


def discard(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def execute_codex(args: argparse.Namespace, run: Run, prompt: str, cwd: str) -> dict:
    """Preflight the approval guard hooks in a fresh thread, then send the assignment to it with exec resume."""
    mcp_off = [] if run.mcp else codex_mcp_off(run.target, cwd, args.timeout)
    sandbox = sandbox_for(run)
    if run.resume is None:
        with tempfile.TemporaryDirectory(prefix="role-runner-") as scratch:
            output = str(Path(scratch) / "preflight.txt")
            stdout = run_child(run.target, codex_command(run, cwd, output, mcp_off), PREFLIGHT_PROMPT, cwd, args.timeout)
        thread_id = thread_id_from(stdout)
        if thread_id is None:
            raise RunnerError(EXIT_EVIDENCE, "No thread.started event with a thread_id in the Codex preflight output")
        run = replace(run, resume=thread_id)
    require_heartbeat("codex", run.resume, CODEX_HOOKS_MESSAGE)
    stdout = run_child(run.target, codex_command(run, cwd, args.result, mcp_off), prompt, cwd, args.timeout)
    evidence = verify_codex(stdout, run.model, run.effort, sandbox)
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


def default_host() -> str:
    return "codex" if os.environ.get("CODEX_THREAD_ID") else "claude"


def runner_for(model: str) -> str:
    return "claude" if model.startswith("claude-") else "codex"


def accepts_add_dir(target: str) -> bool:
    return target in ("worker", AGENT_TARGET) or target in WRITING_CAPABILITIES


def definition_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise UsageError(f"Cannot read the agent definition {path}: {error}") from error


def definition_body(path: Path) -> str:
    try:
        return without_frontmatter(definition_text(path), path.as_posix())
    except ValueError as error:
        raise UsageError(str(error)) from error


def web_tools_in(path: Path | None) -> tuple[str, ...]:
    """Return the web tools a Claude agent definition lists in its frontmatter; a missing definition lists none."""
    if path is None or not path.is_file():
        return ()
    lines = definition_text(path).splitlines()
    if not lines or lines[0].rstrip() != "---":
        return ()
    closing = next((index for index in range(1, len(lines)) if lines[index].rstrip() == "---"), len(lines))
    for line in lines[1:closing]:
        key, _, value = line.partition(":")
        if key.strip() == "tools":
            listed = {item.strip() for item in value.split(",")}
            return tuple(tool for tool in WEB_TOOLS if tool in listed)
    return ()


def codex_instructions(name: str, paths: list[Path]) -> str | None:
    """Return the developer_instructions of the first role TOML in paths whose name is name."""
    for path in paths:
        try:
            settings = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
        text = settings.get("developer_instructions")
        if settings.get("name") == name and isinstance(text, str) and text.strip():
            return text.strip()
    return None


def codex_body(name: str, registry: bool) -> str:
    """Find a Codex role's instructions in the personal, then project, then (for a registry role) plugin role TOML files."""
    paths = [*sorted((codex_home() / "agents").glob("*.toml")), *sorted((Path.cwd() / ".codex" / "agents").glob("*.toml"))]
    if registry:
        paths.append(ROOT / "standalone-agents" / f"codex-{name}.toml")
    text = codex_instructions(name, paths)
    if text is None:
        raise UsageError(f"No developer_instructions for the Codex role {name} in a role TOML file")
    return text


def declared_claude_agent(name: str) -> tuple[dict, Path] | None:
    """Return the entry an installed Claude plugin declares for name, with the install path it came from."""
    if ":" not in name:
        return None
    try:
        installed = json.loads((claude_home() / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    plugins = installed.get("plugins") if isinstance(installed, dict) else None
    if not isinstance(plugins, dict):
        return None
    plugin = name.split(":", 1)[0]
    for key, installs in plugins.items():
        if key.split("@", 1)[0] != plugin or not isinstance(installs, list):
            continue
        for install in installs:
            install_path = install.get("installPath") if isinstance(install, dict) else None
            if not isinstance(install_path, str):
                continue
            agents, problem = agent_guard.read_declaration(Path(install_path) / ".claude-plugin" / "model-roles.json")
            if agents is not None and name in agents:
                if problem is not None:
                    raise UsageError(f"The model roles declared for {name} are invalid: {problem}")
                return agents[name], Path(install_path)
    return None


def declared_codex_role(name: str) -> dict | None:
    """Return the entry the newest cached Codex plugin declares for name."""
    for path in agent_guard.cached_roles_files(codex_home()):
        agents, problem = agent_guard.read_declaration(path)
        if agents is not None and name in agents:
            if problem is not None:
                raise UsageError(f"The model roles declared in {path} are invalid: {problem}")
            return agents[name]
    return None


def declared_agent(name: str, host: str) -> tuple[dict, Path | None, str]:
    """Return the declared entry, its Claude definition file (None for Codex), and its instructions."""
    if host == "claude":
        found = declared_claude_agent(name)
        if found is None:
            raise UsageError(f"Unknown agent {name} for host {host}: use a registry agent or a role an installed plugin declares")
        entry, install = found
        definition = install / "agents" / f"{name.split(':', 1)[1]}.md"
        return entry, definition, definition_body(definition)
    entry = declared_codex_role(name)
    if entry is None:
        raise UsageError(f"Unknown agent {name} for host {host}: use a registry agent or a role an installed plugin declares")
    return entry, None, codex_body(name, registry=False)


def agent_run(args: argparse.Namespace, host: str) -> Run:
    """Resolve an agent on its host: its declaration, instructions, access, and cross-family fallback."""
    name = args.name
    table = REGISTRY["claude_agents"] if host == "claude" else REGISTRY["codex_agents"]
    if name in table:
        entry = table[name]
        definition = ROOT / "agents" / f"{name.rsplit(':', 1)[-1]}.md"
        body = definition_body(definition) if host == "claude" else codex_body(name, registry=True)
    else:
        entry, definition, body = declared_agent(name, host)
    fallback = entry.get("fallback")
    problem = agent_guard.entry_problem(entry) if isinstance(fallback, dict) else "has no fallback"
    if problem is None:
        problem = agent_guard.entry_problem(fallback)
    if problem is not None:
        raise UsageError(f"{name}: {problem}")
    if runner_for(fallback["model"]) == runner_for(entry["model"]):
        raise UsageError(f"{name}: the fallback {fallback['model']} must be the other model family")
    access = entry.get("access", "read")
    if access not in ("read", "write"):
        raise UsageError(f"{name}: access must be read or write")
    if access == "write" and not args.add_dirs:
        raise UsageError(f"{name} writes, so it needs --add-dir for each directory it may write")
    return Run(
        target=AGENT_TARGET, role=None, capability=None, fallback=True, runner=runner_for(fallback["model"]),
        model=fallback["model"], effort=fallback["effort"], writing=access == "write", add_dirs=tuple(args.add_dirs),
        resume=args.resume, instructions=None, agent=name, body=body, web_tools=web_tools_in(definition), mcp=args.mcp,
    )


def validate(args: argparse.Namespace) -> None:
    target = args.role
    is_role = target in ROLES
    is_agent = target == AGENT_TARGET
    if not is_role and not is_agent and target not in CAPABILITIES:
        raise UsageError(
            f"Unknown target: {target}. Roles: {', '.join(ROLES)}. Capabilities: {', '.join(CAPABILITIES)}. Or agent."
        )
    if args.model is not None and target != "reviewer":
        raise UsageError("--model is allowed only for the reviewer role")
    if args.add_dirs and not accepts_add_dir(target):
        raise UsageError("--add-dir is allowed only for the worker role, writing capabilities, and agent mode")
    if args.model is not None and args.model not in REVIEW_MODELS:
        raise UsageError(f"--model must be one of: {', '.join(REVIEW_MODELS)}")
    if args.timeout <= 0:
        raise UsageError("--timeout must be a positive number of seconds")
    if is_role and args.fallback:
        raise UsageError("--fallback is allowed only for a capability or agent")
    if is_agent and not args.fallback:
        raise UsageError("agent mode needs --fallback: primaries run in-host as subagents")
    if args.name is not None and not is_agent:
        raise UsageError("--name is allowed only for agent mode")
    if is_agent and not args.name:
        raise UsageError("agent mode needs --name")
    if is_role and args.mcp:
        raise UsageError("--mcp is allowed only for a capability or agent")
    if is_role and args.instructions is not None:
        raise UsageError("--instructions is allowed only for a capability")
    if is_agent and args.instructions is not None:
        raise UsageError("--instructions is not allowed in agent mode: the agent's definition supplies it")
    if not is_role and not is_agent and args.instructions is None:
        raise UsageError("--instructions is required for a capability")
    if args.instructions is not None and not Path(args.instructions).is_file():
        raise UsageError(f"Instructions file not found: {args.instructions}")
    if args.resume is not None and not args.resume:
        raise UsageError("--resume must name a session id")
    if not Path(args.assignment).is_file():
        raise UsageError(f"Assignment file not found: {args.assignment}")
    result = Path(args.result)
    if result.resolve() == Path(args.assignment).resolve():
        raise UsageError("--assignment and --result must name different files")
    if result.is_dir() or not result.parent.is_dir():
        raise UsageError(f"Result must name a file in an existing directory: {args.result}")


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
            effort=ROLE_EFFORT, writing=target == "worker", add_dirs=tuple(args.add_dirs), resume=args.resume,
            instructions=None,
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
        effort=entry["effort"], writing=target in WRITING_CAPABILITIES, add_dirs=tuple(args.add_dirs),
        resume=args.resume, instructions=Path(args.instructions), mcp=args.mcp,
    )


def plan(args: argparse.Namespace) -> Run:
    validate(args)
    run = resolve(args)
    if run.writing and run.runner == "claude" and not run.add_dirs and run.agent is None:
        label = f"capability {run.capability}" if run.capability else f"role {run.role}"
        raise UsageError(f"The Claude path of the writing {label} needs --add-dir for each directory it may edit")
    return run


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        args = build_parser().parse_args(argv)
        run = plan(args)
    except UsageError as error:
        print(f"role_runner: {error}", file=sys.stderr)
        print(status(None, False, {"error": str(error)}, EXIT_USAGE))
        return EXIT_USAGE
    try:
        evidence = execute(args, run, root, os.getcwd())
    except RunnerError as error:
        print(f"role_runner: {error}", file=sys.stderr)
        print(status(run, False, error.evidence, error.code))
        return error.code
    print(status(run, True, evidence, EXIT_OK))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
