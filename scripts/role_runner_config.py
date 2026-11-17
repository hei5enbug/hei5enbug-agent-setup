from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from delegation_depth import COORDINATOR_ROLE

ROLES = ("scout", "researcher", "reviewer", "worker")
RUNNER_ROLES = (*ROLES, COORDINATOR_ROLE)
ASSIGNED_ROLE_ENV = "HEI5ENBUG_ASSIGNED_ROLE"
REVIEW_MODEL_ENV = "HEI5ENBUG_REVIEW_MODEL"
PARENT_SESSION_ENV = "HEI5ENBUG_PARENT_SESSION"
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "model-registry.json"
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
ROLE_EFFORT = REGISTRY["runner"]["effort"]
ROLE_ENTRY = {"effort": ROLE_EFFORT, "max_effort": REGISTRY["runner"].get("max_effort")}
MAX_BATCH = 6
SERVICE_TIERS = ("fast",)
CODEX_SKILLS_OFF = ("-c", "skills.max_context_tokens=1")
CLAUDE_SKILLS_OFF = "--disable-slash-commands"
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
GUARD_COMMAND = re.compile(r'sh "[^"]*/scripts/hook_python\.sh" approval_guard\.py')
SHELL_TOOL = "Bash"
MCP_SERVER_NAME = re.compile(r"[A-Za-z0-9_-]+")
CODEX_HOOKS_MESSAGE = "The approval guard hooks did not run in Codex; trust them in /hooks"
CLAUDE_HOOKS_MESSAGE = "The approval guard hooks did not run in Claude Code"
NO_NETWORK_RULE = "use no network"
MCP_NETWORK_RULE = "use MCP tools and network only for the external work the assignment names"
CODEX_NETWORK_ON = "sandbox_workspace_write.network_access=true"
SCRATCH_PREFIX = "role-runner-scratch-"
SCRATCH_PROFILE = "role-runner-scratch"
CLAUDE_INSTALL_DOMAINS = ("pypi.org", "files.pythonhosted.org", "registry.npmjs.org")
SCRATCH_ENVIRONMENT = {
    "TMPDIR": "tmp", "UV_CACHE_DIR": "uv-cache", "XDG_CACHE_HOME": "cache", "PYTHONPYCACHEPREFIX": "pycache",
    "npm_config_cache": "npm-cache", "PIP_CACHE_DIR": "pip-cache",
}


def worker_sentence(network: str) -> str:
    return (
        'You are an assigned worker under the "Assigned workers" rules: start no agents, make no commit or push, '
        f"{network}, edit only the allowed paths, and end with the changed paths, check results, and blockers."
    )


COORDINATOR_PIN_KEYS = {"claude": "claude-opus", "codex": "gpt-sol"}
COORDINATOR_EFFORT = "high"
COORDINATOR_SENTENCE = (
    "You are an area coordinator under the main session, the middle layer of three: start implementation workers only "
    "and no coordinator, make no push, use no network, edit only your worktree, and end with your branch, the check "
    "evidence, and the open items."
)
COORDINATOR_BODY = (
    "Split your area into tasks with clear ownership and assign each task to an implementation worker under the "
    "plugin's delegation rules. Your workers start nothing. Review each worker's returned changes, run the area's "
    "checks yourself, and commit the accepted result on the branch of your worktree. Report a missing decision to "
    "the main session instead of settling it, and never edit a path outside your area. Return the branch, the check "
    "evidence as each command with its result, and the open items."
)


def coordinator_entry(host: str) -> dict:
    """The model and effort of the area coordinator on a host: its registered entry, else the capped main model of the host."""
    registered = (REGISTRY["runner"].get("area_coordinator") or {}).get(host)
    if registered:
        return registered
    return {"model": REGISTRY["pins"][COORDINATOR_PIN_KEYS[host]], "effort": COORDINATOR_EFFORT}


def coordinator_worker_models() -> frozenset[str]:
    """The Claude models of the implementation workers a Claude coordinator starts as subagents."""
    return frozenset(entry["model"] for entry in REGISTRY["claude_agents"].values() if entry.get("role") == "worker")


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
NO_RUN_RULE = re.compile(r"Never run\s+build, test, install, or network commands\.")
VALIDATION_SENTENCE = (
    'You are an assigned reviewer under the "Assigned workers" rules: start no agents, make no commit or push, '
    "edit no file outside the scratch folder, change no external state, and return findings only under the role's "
    "output contract."
)


def validation_rule(scratch: str) -> str:
    return (
        f"The scratch folder `{scratch}` is the only path you can write; `TMPDIR` and the tool caches already point "
        "into it. You may run the project's tests, scripts, and calculations, and when the assignment lists check "
        "commands, rerun them. Reuse the project's existing environment read-only when one exists; install the "
        "dependencies a check needs into the scratch folder only when it is missing or does not fit the check. Use "
        "the network only for those installs. When a command fails writing elsewhere, rerun it with its temporary or "
        "cache folder set inside the scratch folder. Never edit a file outside the scratch folder, commit, push, or change "
        "external state."
    )
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_RUN = 3
EXIT_EVIDENCE = 4
EXIT_CAPPED = 5


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
    scratch: str | None = None
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
