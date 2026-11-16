"""Grade one candidate answer against a case's fixed list of real problems, deterministically.

An answer ends with one fenced json block of findings. A case passes when every planted problem is named by a finding
that cites its location and whose text names the problem and its effect, and no finding falls outside the case's
list of real problems.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
LOCATION = re.compile(r"^\s*`?(?P<file>[^\s:`]+):(?P<start>\d+)(?:\s*-\s*(?P<end>\d+))?`?\s*$")
FIELDS = ("location", "problem", "effect")


class FindingsError(ValueError):
    """The answer has no usable findings block."""


def parse_findings(text: str) -> list[dict[str, str]]:
    """Return the findings of the last json block of the answer, or raise FindingsError."""
    blocks = FENCE.findall(text)
    if not blocks:
        raise FindingsError("the answer has no fenced json block")
    try:
        data = json.loads(blocks[-1])
    except json.JSONDecodeError as error:
        raise FindingsError(f"the last json block is not valid JSON: {error}") from error
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(findings, list):
        raise FindingsError("the json block has no findings list")
    for finding in findings:
        if not isinstance(finding, dict) or any(not isinstance(finding.get(name), str) for name in FIELDS):
            raise FindingsError(f"a finding lacks a text {', '.join(FIELDS)}")
    return [{name: finding[name] for name in FIELDS} for finding in findings]


def parse_location(value: str) -> tuple[str, int, int] | None:
    """Return (file, first line, last line) of a `path:line` or `path:first-last` location, or None."""
    found = LOCATION.match(value)
    if found is None:
        return None
    start = int(found["start"])
    end = int(found["end"]) if found["end"] else start
    return found["file"].removeprefix("./"), start, max(start, end)


def at_location(finding: Mapping[str, str], problem: Mapping[str, Any]) -> bool:
    parsed = parse_location(finding["location"])
    if parsed is None:
        return False
    name, start, end = parsed
    return any(
        (name == place["file"] or name.endswith("/" + place["file"])) and start <= place["end"] and end >= place["start"]
        for place in problem["locations"]
    )


def names(text: str, patterns: Sequence[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def finding_matches(finding: Mapping[str, str], problem: Mapping[str, Any]) -> bool:
    """A finding names a listed problem when it cites one of its locations, and its text names the problem and an effect."""
    text = f"{finding['problem']} {finding['effect']}"
    return (
        at_location(finding, problem)
        and bool(finding["effect"].strip())
        and names(text, problem["problem_any"])
        and names(text, problem["effect_any"])
    )


def grade(case: Mapping[str, Any], answer: str) -> dict[str, Any]:
    """Return pass, the problems found and missed, and the findings outside the list, for one answer."""
    try:
        findings = parse_findings(answer)
    except FindingsError as error:
        return {"pass": False, "error": str(error), "findings": 0, "found": [], "missed": planted(case), "outside": []}
    found = {
        problem["id"] for problem in case["problems"]
        if any(finding_matches(finding, problem) for finding in findings)
    }
    outside = [
        {"index": index, "location": finding["location"]}
        for index, finding in enumerate(findings)
        if not any(finding_matches(finding, problem) for problem in case["problems"])
    ]
    missed = [item for item in planted(case) if item not in found]
    return {
        "pass": not missed and not outside, "error": None, "findings": len(findings),
        "found": sorted(found), "missed": missed, "outside": outside,
    }


def planted(case: Mapping[str, Any]) -> list[str]:
    return [problem["id"] for problem in case["problems"] if problem["planted"]]
