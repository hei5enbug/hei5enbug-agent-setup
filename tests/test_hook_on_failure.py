"""Guard hooks that exist to deny fail closed on Claude Code; every other hook stays non-blocking."""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_FILES = ("hooks.json", "claude-hooks.json")
SCRIPT = re.compile(r'hook_python\.sh" ([a-z_]+\.py)')
FAIL_CLOSED = {
    ("PreToolUse", "approval_guard.py"),
    ("PermissionRequest", "approval_guard.py"),
    ("PreToolUse", "datagrip_guard.py"),
    ("PreToolUse", "bash_pretool_checks.py"),
}


def handlers():
    for name in HOOK_FILES:
        hooks = json.loads((REPO_ROOT / "hooks" / name).read_text(encoding="utf-8"))["hooks"]
        for event, groups in hooks.items():
            for group in groups:
                for handler in group["hooks"]:
                    yield event, SCRIPT.search(handler["command"])[1], handler


def test_deny_guards_block_the_action_when_the_hook_fails():
    """A deny guard that cannot start, times out, or exits with an unexpected code must block the call (Claude Code 2.1.295 or later) instead of letting it run."""
    missing = [key for key in FAIL_CLOSED
               if not any((event, script) == key and handler.get("onFailure") == "block"
                          for event, script, handler in handlers())]
    assert missing == [], f"set \"onFailure\": \"block\" on these hook registrations in hooks/hooks.json: {missing}"


def test_only_the_deny_guards_fail_closed():
    """A reminder, status, language, session, or Stop hook must never block a call or a prompt because it failed."""
    blocking = [(event, script) for event, script, handler in handlers()
                if handler.get("onFailure") == "block" and (event, script) not in FAIL_CLOSED]
    assert blocking == [], f"these hooks must stay non-blocking; remove onFailure or extend FAIL_CLOSED on purpose: {blocking}"
