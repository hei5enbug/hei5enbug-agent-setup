"""Constants, paths, and the injectable harness configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
E2E_ROOT = HARNESS_DIR.parent
REPO_ROOT = E2E_ROOT.parents[1]
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
VARIANTS_ROOT = E2E_ROOT / "variants"
DEFAULT_RUN_ROOT = Path.home() / ".local/state/hei5enbug-agent-setup/harness-eval/runs"

AGENT_MODEL = "claude-opus-5-5"
AGENT_EFFORT = "high"
PLUGIN_NAME = "hei5enbug-agent-setup"
INSTALLED_PLUGIN_KEY = "hei5enbug-agent-setup@hei5enbug"
INLINE_PLUGIN_SOURCE = "hei5enbug-agent-setup@inline"
MOD_MARKER = "hei5enbug-agent-setup mod: role pinning active"
APPROVER_SERVER = "eval_approver"
APPROVER_TOOL = "mcp__eval_approver__approve"
REMOVED_ENV_PREFIX = "ORCA_"

DEFAULT_PARALLEL = 3
SIGINT_GRACE_SECONDS = 20.0
SIGTERM_GRACE_SECONDS = 10.0
EXIT_USAGE_LIMIT = 75
EXIT_FAILURE = 1

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETE = "complete"
STATUS_INFRA_FAILED = "infra_failed"
STATUS_USAGE_LIMITED = "usage_limited"
STATUS_TIMED_OUT = "timed_out"
FINISHED_STATUSES = frozenset({STATUS_COMPLETE, STATUS_TIMED_OUT})
RETRIED_STATUSES = frozenset({STATUS_INFRA_FAILED, STATUS_USAGE_LIMITED, STATUS_RUNNING, STATUS_PENDING})

USAGE_LIMIT_PATTERN = re.compile(r"usage limit|limit reached|hit your limit|rate limit|out of extra usage|quota", re.I)
FORBIDDEN_ARGS = frozenset({"--dangerously-skip-permissions", "--bare", "--permission-mode", "bypassPermissions"})
RESERVED_ARGS = frozenset({
    "--model", "--effort", "--settings", "--plugin-dir", "--mcp-config", "--permission-prompt-tool", "--max-budget-usd",
    "--output-format", "-p", "--print", "--permission-prompts", "--strict-mcp-config", "--",
})

RUBRIC_MODEL = "gpt-6-astra"
RUBRIC_EFFORT = "xhigh"
RUBRIC_FALLBACK_MODEL = "claude-opus-5-5"
RUBRIC_FALLBACK_EFFORT = "high"
RUBRIC_RETRY_EXITS = frozenset({3, 4})


@dataclass(frozen=True)
class HarnessConfig:
    """Paths and process settings for one harness invocation; tests override them."""

    run_root: Path = DEFAULT_RUN_ROOT
    tasks_root: Path = TASKS_ROOT
    fixtures_root: Path = FIXTURES_ROOT
    variants_root: Path = VARIANTS_ROOT
    repo_root: Path = REPO_ROOT
    claude_bin: str = "claude"
    sigint_grace: float = SIGINT_GRACE_SECONDS
    sigterm_grace: float = SIGTERM_GRACE_SECONDS
    extra_env: dict[str, str] = field(default_factory=dict)
