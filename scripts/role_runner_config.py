from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROLES = ("scout", "researcher", "reviewer", "worker")
ASSIGNED_ROLE_ENV = "HEI5ENBUG_ASSIGNED_ROLE"
REVIEW_MODEL_ENV = "HEI5ENBUG_REVIEW_MODEL"
PARENT_SESSION_ENV = "HEI5ENBUG_PARENT_SESSION"
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "model-registry.json"
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
ROLE_EFFORT = REGISTRY["runner"]["effort"]
ROLE_ENTRY = {"effort": ROLE_EFFORT, "max_effort": REGISTRY["runner"].get("max_effort")}
CODEX_SKILLS_OFF = ("-c", "skills.max_context_tokens=1")
CLAUDE_SKILLS_OFF = "--disable-slash-commands"
DEFAULT_TIMEOUT = 2700
SERVICE_TIERS = ("fast",)
DEFAULT_REVIEW_MODEL = REGISTRY["runner"]["default_review_model"]
ROLE_MODEL = REGISTRY["runner"]["role_model"]
REVIEW_MODELS = tuple(REGISTRY["runner"]["review_models"])
REVIEWER_MODELS = tuple(dict.fromkeys((*REVIEW_MODELS, REGISTRY["pins"]["gpt-sol"])))
WORKER_MODELS = tuple(REGISTRY["runner"]["worker_models"])
WORKER_AGENTS = frozenset(
    name for table in (REGISTRY["claude_agents"], REGISTRY["codex_agents"]) for name, entry in table.items()
    if entry.get("role") == "worker" or name == "worker"
)
CAPABILITIES = REGISTRY["capabilities"]
HOSTS = ("claude", "codex")
WRITING_CAPABILITIES = ("implementation", "design", "language")
ROOT = Path(__file__).resolve().parents[1]
AGENT_TARGET = "agent"
ROLE_DEFINITIONS = {"researcher": "scout"}
WEB_TOOLS = ("WebSearch", "WebFetch")
MCP_TOOL_RULE = "mcp__*"
READ_SHELL_RULES = (
    "Bash(git -C:*)", "Bash(git diff:*)", "Bash(git show:*)", "Bash(git grep:*)", "Bash(git log:*)", "Bash(git cat-file:*)",
    "Bash(git ls-tree:*)", "Bash(git ls-files:*)", "Bash(git rev-parse:*)", "Bash(git merge-base:*)",
    "Bash(rg:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
)
SYNTHETIC_MODEL = "<synthetic>"
PREFLIGHT_PROMPT = "Run the shell command `true` exactly once, then reply with OK only."
GUARD_COMMAND = re.compile(r'sh "[^"]*/scripts/hook_python\.sh" approval_guard\.py')
SHELL_TOOL = "Bash"
MCP_SERVER_NAME = re.compile(r"[A-Za-z0-9_-]+")
HOST_NAMES = {"codex": "Codex", "claude": "Claude Code"}
CODEX_HOOKS_MESSAGE = "The approval guard hooks are not trusted or not enabled in Codex; trust and enable them in /hooks"
GUARD_SWITCH_MESSAGE = "The approval guard is switched off in the environment of the {host} child by {variable}={value}"
GUARD_UNKNOWN_MESSAGE = "The approval guard wrote no heartbeat in {host} and its cause is unknown; looked for {heartbeat}"
NO_NETWORK_RULE = "use no network"
MCP_NETWORK_RULE = "use MCP tools and network only for the external work the assignment names"
CODEX_NETWORK_ON = "sandbox_workspace_write.network_access=true"
SCRATCH_PREFIX = "role-runner-scratch-"
SCRATCH_PROFILE = "role-runner-scratch"
SKIP_GIT_REPO_CHECK = "--skip-git-repo-check"
SCRATCH_VARIABLES = {
    "TMPDIR": "tmp",
    "TMPPREFIX": "tmp/zsh",
    "UV_CACHE_DIR": "cache/uv",
    "XDG_CACHE_HOME": "cache/xdg",
    "PYTHONPYCACHEPREFIX": "pycache",
    "npm_config_cache": "cache/npm",
    "PIP_CACHE_DIR": "cache/pip",
}
VALIDATION_PACKAGE_HOSTS = ("pypi.org", "files.pythonhosted.org", "registry.npmjs.org")
VALIDATION_ROLE = "reviewer"
REVIEWER_BAN = re.compile(
    r"Never modify files, branches, or worktrees\.\s+Never run\s+build, test, install, or network commands\."
)
VALIDATION_RULE = (
    "Validation mode: run the project's tests, scripts, and calculations to check the claims under review. "
    "The only path you may write is the folder the TMPDIR environment variable names, which is your scratch folder; "
    "every cache and temporary folder already points into it. Reuse the project's existing environment read-only when "
    "one exists, and install a dependency a check needs into the scratch folder only when the environment is missing or "
    "does not fit the check. Use the network only for those installs. Edit no file outside the scratch folder, "
    "make no commit or push, and change no external state. Report each command you ran with its result."
)
CLAUDE_SCRATCH_RULE = (
    "Your working directory is your scratch folder, the only path your shell can write. The repository is at {repository}: "
    "read it by absolute path, and run git as `git -C {repository} <subcommand>`."
)
CLAUDE_VALIDATION_COPY = (
    " To run a check that needs the repository, copy what it needs into the scratch folder first, for example "
    "`mkdir repo && git -C {repository} archive HEAD | tar -x -C repo`, and run it there."
)
VALIDATION_SENTENCE = (
    'You are an assigned reviewer under the "Assigned workers" rules: start no agents, make no commit or push, '
    "change no external state, and return findings only under the role's output contract."
)


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
EXIT_CAP = 5


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
    user_requested: bool = False
    validation: bool = False
    service_tier: str | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="role_runner.py", add_help=False)
    parser.add_argument("role")
    parser.add_argument("--assignment", required=True, action="append")
    parser.add_argument("--result", required=True, action="append")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--add-dir", action="append", default=[], dest="add_dirs")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--host", choices=HOSTS)
    parser.add_argument("--fallback", action="store_true")
    parser.add_argument("--instructions")
    parser.add_argument("--resume")
    parser.add_argument("--name")
    parser.add_argument("--mcp", action="store_true")
    parser.add_argument("--user-requested", action="store_true", dest="user_requested")
    parser.add_argument("--validation", action="store_true")
    parser.add_argument("--service-tier", choices=SERVICE_TIERS, dest="service_tier")
    return parser
