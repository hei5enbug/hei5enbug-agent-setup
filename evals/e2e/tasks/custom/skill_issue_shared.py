"""Shared checks of the skill-issue-creator tasks: the stub gh log, the issues it kept, and the issue body contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = "demo-org/demo-plugin"
FIRST_CREATED = 200
WRITE_COMMAND = re.compile(
    r"^gh (?:issue (?:create|edit|comment)\b|api\b.*(?:-X|--method)[ =]?(?:PATCH|POST|PUT|DELETE)\b)")
CREATE_COMMAND = re.compile(r"^gh issue create\b")
SEARCH_COMMAND = re.compile(r"^gh issue list\b")
IDENTIFIERS = ("ABC-123", "report-empty-sections", "PR 45", "2026-03-02")
CONDITION = "Under the condition that"
ITEM = re.compile(r"^\s*(?:\d+\.|[-*])\s+(.*)$")
SKILL = "skill-issue-creator"


def work_of(ctx) -> Path:
    return Path(ctx.origin).parent


def gh_calls(ctx) -> list[str]:
    path = work_of(ctx) / "gh.log"
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("gh ")]


def written(ctx) -> list[str]:
    return [line for line in gh_calls(ctx) if WRITE_COMMAND.match(line)]


def tracker_issues(ctx) -> list[dict]:
    path = work_of(ctx) / "gh-state" / f"{REPO.replace('/', '_')}.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("issues", [])


def created_issues(ctx) -> list[dict]:
    return [issue for issue in tracker_issues(ctx) if issue["number"] >= FIRST_CREATED]


def skill_invoked(ctx):
    calls = [call for call in ctx.view.get("tool_calls", []) if call.get("name") == "Skill"
             and str((call.get("input") or {}).get("skill", "")).endswith(SKILL)]
    return bool(calls), f"{len(calls)} call(s) of the {SKILL} skill", {}


SECTION_GROUPS = (("Summary",), ("Observations",), ("Gap in current rules", "Why no existing skill covers it"),
                  ("Proposal",), ("Acceptance criteria",), ("Evidence",))
HEADING = re.compile(r"^##\s+(.+?)\s*#*\s*$", re.MULTILINE)


def sections_in_order(body: str) -> bool:
    """The six section headings in order; the checkout may hold no check_filed.py, so the rule is read here."""
    headings = [match.group(1) for match in HEADING.finditer(body)]
    positions = [min((headings.index(name) for name in group if name in headings), default=-1) for group in SECTION_GROUPS]
    return -1 not in positions and positions == sorted(positions)


def section_text(body: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def target_is_public(ctx) -> bool:
    """The identifier rule binds a public tracker only; a private one asks for the case's real identifiers in the Proposal."""
    path = work_of(ctx) / "repo" / "issue-target.json"
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("public", True))
    except (OSError, ValueError):
        return True


def body_problems(ctx, body: str) -> list[str]:
    problems = []
    if not sections_in_order(body):
        problems.append("the six headings are not in order")
    proposal = section_text(body, "Proposal")
    items = [match.group(1) for line in proposal.splitlines() if (match := ITEM.match(line))]
    if not items:
        problems.append("the Proposal has no numbered item")
    problems += [f"a Proposal item does not start with '{CONDITION}'" for item in items if not item.startswith(CONDITION)]
    leaked = sorted({name for name in IDENTIFIERS for heading in ("Proposal", "Acceptance criteria")
                     if name.lower() in section_text(body, heading).lower()}) if target_is_public(ctx) else []
    problems += [f"Observations identifier {name} appears in Proposal or Acceptance criteria" for name in leaked]
    return problems
