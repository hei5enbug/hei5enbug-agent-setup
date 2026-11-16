"""The record of the Fable-versus-Opus comparison, and the efficiency rule it applies to each role.

Four candidates run every case once. The reviewer role counts only the review cases and the opponent role only the
debate cases. A role keeps the candidates that passed every one of its cases; when none did, the role has no winner
and keeps its baseline pin. Among the kept candidates, one that is slower than the fastest by more than 1.5 times and
by more than 60 seconds on any case is dropped, measured against the fastest of the kept candidates on that case. Of the
rest, the lowest cost per passing case wins; costs within 10 percent or within $0.05 of the lowest tie, and the lowest
summed wall time over the role's cases decides the tie. Candidates tied on that too leave the role undecided, and a role where every kept candidate is dropped has no winner.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

OPUS = "claude-opus-5-5"
FABLE = "claude-fable-5-2"
CANDIDATES = (
    (OPUS, "high"), (OPUS, "xhigh"), (FABLE, "high"), (FABLE, "xhigh"),
)
ROLES = ("reviewer", "opponent")
PENDING = "pending"
RECORDED = "recorded"
WINNER = "winner"
TIE = "tie"
NONE = "none"
TOLERANCE = 1e-6
SLOW_RATIO = 1.5
SLOW_SECONDS = 60.0
TIE_RATIO = 0.10
TIE_USD = 0.05
RESULT_KEYS = {
    "case", "model", "effort", "passed", "host_model", "host_effort", "cost_usd", "wall_seconds", "attempts",
}


def candidate_label(model: str, effort: str) -> str:
    return f"{model}/{effort}"


def role_cases(roles_by_case: Mapping[str, str], role: str) -> list[str]:
    return sorted(case for case, owner in roles_by_case.items() if owner == role)


def candidate_stats(results: Sequence[Mapping[str, Any]], cases: Sequence[str]) -> list[dict[str, Any]]:
    """Return each candidate's passes, total cost, and total wall time over the given cases, in candidate order."""
    stats = []
    for model, effort in CANDIDATES:
        own = [
            item for item in results
            if item["model"] == model and item["effort"] == effort and item["case"] in cases
        ]
        stats.append({
            "model": model, "effort": effort,
            "passes": sum(1 for item in own if item["passed"]),
            "cost_usd": round(sum(item["cost_usd"] for item in own), 6),
            "wall_seconds": round(sum(item["wall_seconds"] for item in own), 3),
        })
    return stats


def wall_of(results: Sequence[Mapping[str, Any]], candidate: tuple[str, str], case: str) -> float:
    return next(
        item["wall_seconds"] for item in results
        if (item["model"], item["effort"]) == candidate and item["case"] == case
    )


def too_slow(wall: float, fastest: float) -> bool:
    """True when a wall time is above 1.5 times the fastest and more than 60 seconds above it."""
    return wall > SLOW_RATIO * fastest and wall - fastest > SLOW_SECONDS


def cost_tied(cost: float, cheapest: float) -> bool:
    """True when a cost per passing case is within 10 percent or within $0.05 of the lowest."""
    gap = cost - cheapest
    return gap <= TIE_RATIO * cheapest + TOLERANCE or gap <= TIE_USD + TOLERANCE


def decide(results: Sequence[Mapping[str, Any]], cases: Sequence[str]) -> dict[str, Any]:
    """Return the role's decision: a winner, a tie that decides nothing, or none when no candidate passed every case."""
    stats = candidate_stats(results, cases)
    kept = [item for item in stats if item["passes"] == len(cases)]
    if not kept:
        return {"status": NONE, "winner": None}
    labels = [(item["model"], item["effort"]) for item in kept]
    for case in cases:
        fastest = min(wall_of(results, label, case) for label in labels)
        kept = [
            item for item in kept
            if not too_slow(wall_of(results, (item["model"], item["effort"]), case), fastest)
        ]
    if not kept:
        return {"status": NONE, "winner": None}
    cheapest = min(item["cost_usd"] for item in kept) / len(cases)
    close = [item for item in kept if cost_tied(item["cost_usd"] / len(cases), cheapest)]
    quickest = min(item["wall_seconds"] for item in close)
    winners = [item for item in close if item["wall_seconds"] - quickest <= TOLERANCE]
    if len(winners) != 1:
        return {"status": TIE, "winner": None}
    return {"status": WINNER, "winner": {"model": winners[0]["model"], "effort": winners[0]["effort"]}}


def role_block(results: Sequence[Mapping[str, Any]], cases: Sequence[str]) -> dict[str, Any]:
    return {"cases": list(cases), "candidates": candidate_stats(results, cases), "decision": decide(results, cases)}


def build_record(issue: int, roles_by_case: Mapping[str, str], results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a recorded comparison from one result per candidate and case, with every role's block computed."""
    ordered = [dict(item) for item in sorted(results, key=lambda item: (item["case"], item["model"], item["effort"]))]
    return {
        "version": 1,
        "issue": issue,
        "status": RECORDED,
        "candidates": [{"model": model, "effort": effort} for model, effort in CANDIDATES],
        "cases": dict(sorted(roles_by_case.items())),
        "results": ordered,
        "roles": {role: role_block(ordered, role_cases(roles_by_case, role)) for role in ROLES},
    }


def pending_record(issue: int, roles_by_case: Mapping[str, str]) -> dict[str, Any]:
    return {
        "version": 1,
        "issue": issue,
        "status": PENDING,
        "candidates": [{"model": model, "effort": effort} for model, effort in CANDIDATES],
        "cases": dict(sorted(roles_by_case.items())),
        "results": [],
        "roles": {},
    }


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def result_problems(item: Any, cases: Sequence[str]) -> list[str]:
    if not isinstance(item, dict) or set(item) != RESULT_KEYS:
        return [f"a result must hold exactly the keys {sorted(RESULT_KEYS)}"]
    label = f"{item['case']}/{candidate_label(str(item['model']), str(item['effort']))}"
    problems = []
    if item["case"] not in cases or (item["model"], item["effort"]) not in CANDIDATES:
        problems.append(f"{label}: unknown case or candidate")
    if not isinstance(item["passed"], bool):
        problems.append(f"{label}: passed must be true or false")
    if item["host_model"] != item["model"]:
        problems.append(f"{label}: the host record shows model {item['host_model']!r}")
    if item["host_effort"] != item["effort"]:
        problems.append(f"{label}: the host record shows effort {item['host_effort']!r}")
    for key in ("cost_usd", "wall_seconds"):
        if not _number(item[key]):
            problems.append(f"{label}: {key} must be a number of 0 or more")
    if isinstance(item["attempts"], bool) or not isinstance(item["attempts"], int) or item["attempts"] < 1:
        problems.append(f"{label}: attempts must be a whole number of 1 or more")
    return problems


def _blocks_match(given: Any, wanted: Mapping[str, Any]) -> bool:
    if not isinstance(given, dict) or set(given) != set(wanted):
        return False
    for role, block in wanted.items():
        have = given[role]
        if not isinstance(have, dict) or have.get("cases") != block["cases"] or have.get("decision") != block["decision"]:
            return False
        stats = have.get("candidates")
        if not isinstance(stats, list) or len(stats) != len(block["candidates"]):
            return False
        for got, want in zip(stats, block["candidates"]):
            keys = ("model", "effort", "passes")
            if any(got.get(key) != want[key] for key in keys):
                return False
            for key in ("cost_usd", "wall_seconds"):
                if not _number(got.get(key)) or abs(got[key] - want[key]) > TOLERANCE:
                    return False
    return True


def record_problems(record: Any, roles_by_case: Mapping[str, str]) -> list[str]:
    """Return every way the record breaks its format: header, one result per candidate and case, and the computed roles."""
    if not isinstance(record, dict):
        return ["the record is not an object"]
    problems = []
    header = {
        "version": 1, "candidates": [{"model": model, "effort": effort} for model, effort in CANDIDATES],
        "cases": dict(sorted(roles_by_case.items())),
    }
    for key, value in header.items():
        if record.get(key) != value:
            problems.append(f"{key} must be {value!r}, found {record.get(key)!r}")
    status, results = record.get("status"), record.get("results")
    if status not in (PENDING, RECORDED) or not isinstance(results, list):
        return problems + ["status must be pending or recorded, and results a list"]
    if status == PENDING:
        if results or record.get("roles") != {}:
            problems.append("a pending record holds no results and no roles")
        return problems
    for item in results:
        problems += result_problems(item, list(roles_by_case))
    if problems:
        return problems
    pairs = sorted((item["case"], item["model"], item["effort"]) for item in results)
    if pairs != sorted((case, model, effort) for case in roles_by_case for model, effort in CANDIDATES):
        return ["a recorded comparison holds exactly one result per case and candidate"]
    wanted = {role: role_block(results, role_cases(roles_by_case, role)) for role in ROLES}
    if not _blocks_match(record.get("roles"), wanted):
        problems.append("roles do not match the rule applied to the results")
    return problems


def decisions(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return each role's decision from a recorded comparison, and an empty mapping while it is pending."""
    if record.get("status") != RECORDED:
        return {}
    return {role: block["decision"] for role, block in record["roles"].items()}
