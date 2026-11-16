"""Check that the repository's pins for the two roles match the comparison record.

While the record is pending, every pin site holds the baseline pin. Once it is recorded and a role has a winner, every
site of that role names the winner's model and effort, and no site still names the other Claude model of the
comparison. A role the record leaves tied keeps its baseline until the owner decides.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from mr_record import FABLE, OPUS, TIE, WINNER, decisions

CLAUDE_ID = re.compile(r"claude-(?:opus|fable)-[\d-]+")
BASELINE = {
    "opponent": {"models": {FABLE}, "claude_effort": "xhigh"},
    "reviewer": {"models": {OPUS, FABLE}, "independent_review": [OPUS, FABLE]},
}
FAST_EFFORT = "high"
SITES = {
    "opponent": (
        ("skills/tiki-taka/SKILL.md", r"Fix a Claude opponent to"),
        ("docs/ko/skills/tiki-taka/SKILL.ko.md", r"Claude 상대는"),
    ),
    "reviewer": (
        ("instructions/independent-model-validation.md", r"^\| GPT \|"),
        ("instructions/independent-model-validation.md", r"^The coordinating session picks one reviewer"),
        ("docs/ko/instructions/independent-model-validation.ko.md", r"^\| GPT \|"),
        ("docs/ko/instructions/independent-model-validation.ko.md", r"^조율 세션이 범위와 위험에 따라"),
        ("docs/instructions-and-delegation.md", r"a GPT-authored result goes to"),
        ("docs/ko/docs/instructions-and-delegation.ko.md", r"GPT가 작성한 결과는"),
        ("AGENTS.md", r"^\s*\| GPT-authored"),
        ("docs/ko/AGENTS.ko.md", r"^\s*\| GPT 작성"),
    ),
}
EFFORT_LINES = {
    "opponent": SITES["opponent"],
    "reviewer": (
        ("instructions/independent-model-validation.md", r"^\| GPT \|"),
        ("AGENTS.md", r"^\s*\| GPT-authored"),
    ),
}


def block_around(text: str, anchor: str) -> tuple[str, str] | None:
    """Return the anchor's line and its run of consecutive non-blank lines, or None when no line matches."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.search(anchor, line):
            first, last = index, index
            while first > 0 and lines[first - 1].strip():
                first -= 1
            while last + 1 < len(lines) and lines[last + 1].strip():
                last += 1
            return line, "\n".join(lines[first:last + 1])
    return None


def word(effort: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(effort)}(?![A-Za-z0-9])")


def expected_models(role: str, decision: Mapping[str, Any] | None) -> set[str]:
    if decision and decision["status"] != TIE:
        return {decision["winner"]["model"]}
    return set(BASELINE[role]["models"])


def site_problems(role: str, read: Callable[[str], str], decision: Mapping[str, Any] | None) -> list[str]:
    """Return each pin site whose Claude model ids differ from the expected set: the baseline's, or the winner alone."""
    problems = []
    wanted = expected_models(role, decision)
    for path, anchor in SITES[role]:
        located = block_around(read(path), anchor)
        if located is None:
            problems.append(f"{path}: no line matches {anchor!r}; update the anchor with the pin text")
            continue
        found = set(CLAUDE_ID.findall(located[1]))
        if found != wanted:
            problems.append(f"{path}: the pin site names {sorted(found)}, expected {sorted(wanted)}")
    return problems


def effort_problems(role: str, read: Callable[[str], str], decision: Mapping[str, Any] | None) -> list[str]:
    if not decision or decision["status"] == TIE:
        return []
    keep, drop = decision["winner"]["effort"], {"high", "xhigh"} - {decision["winner"]["effort"]}
    problems = []
    for path, anchor in EFFORT_LINES[role]:
        located = block_around(read(path), anchor)
        if located is None:
            continue
        if not word(keep).search(located[0]) or any(word(other).search(located[0]) for other in drop):
            problems.append(f"{path}: the pin line must name effort {keep} and not {sorted(drop)}")
    return problems


def registry_problems(registry: Mapping[str, Any], decisions: Mapping[str, Any]) -> list[str]:
    problems = []
    opponents = registry["opponents"]
    claude = opponents["claude"]
    opponent = decisions.get("opponent")
    if opponent and opponent["status"] == WINNER:
        want_model, want_effort = opponent["winner"]["model"], opponent["winner"]["effort"]
    else:
        want_model, want_effort = FABLE, BASELINE["opponent"]["claude_effort"]
    if claude["model"] != want_model:
        problems.append(f"registry opponents.claude.model is {claude['model']!r}, expected {want_model!r}")
    if claude.get("effort", opponents["effort"]) != want_effort:
        problems.append(f"registry opponents effort for Claude is not {want_effort!r}")
    if opponents["fast_effort"] != FAST_EFFORT:
        problems.append("registry opponents.fast_effort changed")
    reviewer = decisions.get("reviewer")
    want_list = (
        [reviewer["winner"]["model"]] if reviewer and reviewer["status"] == WINNER
        else BASELINE["reviewer"]["independent_review"]
    )
    if registry["runner"]["independent_review"]["gpt"] != want_list:
        problems.append(f"registry runner.independent_review.gpt is not {want_list!r}")
    return problems



def pin_problems(
    record: Mapping[str, Any], registry: Mapping[str, Any], read: Callable[[str], str]
) -> list[str]:
    """Return every place where the repository's pins disagree with the record: baseline while pending or tied, else the winner."""
    by_role = decisions(record)
    problems = registry_problems(registry, by_role)
    for role in SITES:
        problems += site_problems(role, read, by_role.get(role))
        problems += effort_problems(role, read, by_role.get(role))
    return problems
