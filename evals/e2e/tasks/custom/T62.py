"""Custom checks for T62: the changelog line follows the named skill, and the skill was loaded by the worker."""

from __future__ import annotations

import re

SKILL = "changelog-entry"
LINE = re.compile(r"^- (added|changed|fixed): (?P<summary>[^\n]{1,60}) \[entry-v2\]$")
AGENT_TOOLS = ("Agent", "Task", "spawn_agent")


def changelog_entry(ctx):
    path = ctx.repo / "CHANGELOG.md"
    if not path.is_file():
        return False, "CHANGELOG.md is missing", {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if "## Unreleased" not in lines:
        return False, "the Unreleased heading is gone", {}
    start = lines.index("## Unreleased") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    entries = [line for line in lines[start:end] if line.strip()]
    released = "\n".join(lines[end:])
    if len(entries) != 1:
        return False, f"expected one entry under Unreleased, found {len(entries)}", {"entries": entries}
    match = LINE.match(entries[0])
    ok = bool(match) and not match.group("summary").endswith(".") and "* Memo search ignores case." in released
    return ok, f"entry: {entries[0]!r}", {"entry": entries[0]}


def loads_skill(call) -> bool:
    if call["name"] == "Skill":
        return str(call["input"].get("skill", "")).rsplit(":", 1)[-1] == SKILL
    if call["name"] == "Bash":
        return f"{SKILL}/SKILL.md" in str(call["input"].get("command", ""))
    return False


def skill_loaded(ctx):
    calls = ctx.view.get("tool_calls", [])
    delegated = any(item.get("class") == "implementation" for item in ctx.view.get("delegations", []))
    loaders = sorted({call["source"] for call in calls if loads_skill(call)})
    wanted = [source for source in loaders if (source != "main") == delegated]
    where = "a worker" if delegated else "the main session"
    return bool(wanted), f"{SKILL} loaded by {loaders or 'nobody'}; expected {where}", {"loaders": loaders, "delegated": delegated}


def worker_result_lists_skill(ctx):
    results = [call["result_text"] for call in ctx.view.get("tool_calls", []) if call["source"] == "main"
               and (call["name"] in AGENT_TOOLS or "role_runner.py" in str(call["input"].get("command", "")))]
    return any(SKILL in text for text in results), f"{len(results)} worker results read", {"results": len(results)}
