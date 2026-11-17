"""Handoff fields of the assignment: what one run shows about a seeded item, and the rule that decides a field.

A task file lists seeded items under `constraints`. Each item has an `id`, the `field` that would carry it
(`constraints` or `behavior`), the `keywords` that are its marker strings, the delegation classes it `applies_to`, and the
`check_ids` that fail when it is ignored. A task's `handoff.pass_checks` are the checks that decide whether a run of the case
passed. `run_handoff` turns one graded run into facts, and `decide` applies the adoption rule to a record's runs.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .verdict import HOSTS

FIELDS = ("constraints", "behavior")
CASES = ("T02", "T05", "T42")
FIRST_RUNS = 2

NO_BENEFIT = "no demonstrated benefit at baseline"
NOT_MEASURED = "not measured"
AFTER_PENDING = "qualified; after runs not measured"
KEPT = "kept"
NOT_KEPT = "not kept"

STATUSES = (NO_BENEFIT, NOT_MEASURED, AFTER_PENDING, KEPT, NOT_KEPT)
BLOCK_FIELDS = ("before", "after", "fields")
DECISION_FIELDS = ("status", "qualified_on", "reasons")
ITEM_FIELDS = ("id", "field", "failed_checks", "delegations", "markers_present", "markers_missing")
ENTRY_FIELDS = ("passed", "items")


def has_items(task: Mapping[str, Any]) -> bool:
    return any(item.get("field") for item in task.get("constraints", []))


def run_handoff(task: Mapping[str, Any], delegations: Sequence[Mapping[str, Any]],
                checks: Mapping[str, bool]) -> dict[str, Any] | None:
    """Facts of one graded run per seeded item: the mapped checks that failed, how many delegation prompts of the item's
    classes the run holds, and which marker strings those prompts contain and which they lack. None for a task with no
    seeded item."""
    if not has_items(task):
        return None
    items = []
    for constraint in task["constraints"]:
        if not constraint.get("field"):
            continue
        prompts = [str(item.get("prompt", "")).lower() for item in delegations
                   if item.get("class") in constraint.get("applies_to", [])]
        markers = list(dict.fromkeys(constraint.get("keywords", [])))
        present = [marker for marker in markers if any(marker.lower() in prompt for prompt in prompts)]
        items.append({
            "id": constraint["id"], "field": constraint["field"],
            "failed_checks": [check for check in constraint.get("check_ids", []) if checks.get(check) is False],
            "delegations": len(prompts), "markers_present": present,
            "markers_missing": [marker for marker in markers if marker not in present],
        })
    pass_checks = (task.get("handoff") or {}).get("pass_checks", [])
    return {"passed": bool(pass_checks) and all(checks.get(check) is True for check in pass_checks), "items": items}


def entry_problems(position: str, entry: Any) -> list[str]:
    """Problems of one run's handoff entry; an empty list means it has the shape `run_handoff` writes."""
    if not isinstance(entry, Mapping):
        return [f"{position} is not an object"]
    problems = [f"{position} lacks {field}" for field in ENTRY_FIELDS if field not in entry]
    problems += [f"{position} has unknown field {field}" for field in entry if field not in ENTRY_FIELDS]
    if "passed" in entry and not isinstance(entry["passed"], bool):
        problems.append(f"{position} passed is not true or false")
    items = entry.get("items")
    if "items" in entry and not (isinstance(items, list) and items):
        problems.append(f"{position} items is not a non-empty list")
        return problems
    for index, item in enumerate(items or []):
        where = f"{position}.items[{index}]"
        if not isinstance(item, Mapping):
            problems.append(f"{where} is not an object")
            continue
        problems += [f"{where} lacks {field}" for field in ITEM_FIELDS if field not in item]
        problems += [f"{where} has unknown field {field}" for field in item if field not in ITEM_FIELDS]
        if item.get("field") not in FIELDS:
            problems.append(f"{where} field is not one of {', '.join(FIELDS)}")
        if not (isinstance(item.get("delegations"), int) and not isinstance(item.get("delegations"), bool)
                and item["delegations"] >= 0):
            problems.append(f"{where} delegations is not a count")
        for key in ("failed_checks", "markers_present", "markers_missing"):
            if key in item and not (isinstance(item[key], list) and all(isinstance(value, str) for value in item[key])):
                problems.append(f"{where} {key} is not a list of names")
    return problems


def qualifies(entry: Mapping[str, Any] | None, field: str) -> bool:
    """One run qualifies a field when, for one of its seeded items, a mapped check failed, the run delegated, and no
    delegation prompt holds a marker string of that item."""
    return any(item["field"] == field and item["failed_checks"] and item["delegations"] > 0 and not item["markers_present"]
               for item in (entry or {}).get("items", []))


def first_runs(runs: Sequence[Mapping[str, Any]], case: str, host: str, variant: str) -> list[Mapping[str, Any]]:
    """The first two runs, in repetition order, of one case, host, and variant that carry handoff facts."""
    chosen = sorted((run for run in runs if (run["case"], run["host"], run["variant"]) == (case, host, variant)
                     and run.get("handoff")), key=lambda run: run.get("rep", 0))
    return chosen[:FIRST_RUNS]


def decide(runs: Sequence[Mapping[str, Any]], cases: Sequence[str], before: str, after: str) -> dict[str, dict[str, Any]]:
    """Status and evidence of each field from the runs of the before and the after variant.

    A field qualifies when, on at least one host, both before runs of a case qualify it. It is kept when every case that
    qualified it passes both after runs on every host where that case failed a before run, and no case that passed both
    before runs on a host fails an after run there. Without two before runs for every case and host the baseline is not
    measured, and without two after runs the decision waits."""
    cells = [(case, host) for case in cases for host in HOSTS]
    before_runs = {cell: first_runs(runs, *cell, before) for cell in cells}
    after_runs = {cell: first_runs(runs, *cell, after) for cell in cells}
    baseline_complete = all(len(found) == FIRST_RUNS for found in before_runs.values())
    after_complete = all(len(found) == FIRST_RUNS for found in after_runs.values())
    result: dict[str, dict[str, Any]] = {}
    for field in FIELDS:
        qualified = [{"case": case, "host": host} for case, host in cells
                     if len(before_runs[(case, host)]) == FIRST_RUNS
                     and all(qualifies(run["handoff"], field) for run in before_runs[(case, host)])]
        if not baseline_complete:
            status, reasons = NOT_MEASURED, ["a case lacks two before runs on a host"]
        elif not qualified:
            status, reasons = NO_BENEFIT, []
        elif not after_complete:
            status, reasons = AFTER_PENDING, ["a case lacks two after runs on a host"]
        else:
            qualified_cases = {item["case"] for item in qualified}
            reasons = []
            for case, host in cells:
                before_passed = [run["handoff"]["passed"] for run in before_runs[(case, host)]]
                if all(run["handoff"]["passed"] for run in after_runs[(case, host)]):
                    continue
                if all(before_passed):
                    reasons.append(f"{case} passed both before runs on {host} and an after run failed")
                elif case in qualified_cases:
                    reasons.append(f"{case} qualified the field, failed a before run on {host}, and an after run failed")
            status = NOT_KEPT if reasons else KEPT
        result[field] = {"status": status, "qualified_on": qualified, "reasons": reasons}
    return result


def block(runs: Sequence[Mapping[str, Any]], before: str, after: str) -> dict[str, Any] | None:
    """The record's `handoff` block, or None when no run carries handoff facts."""
    if not any(run.get("handoff") for run in runs):
        return None
    return {"before": before, "after": after, "fields": decide(runs, CASES, before, after)}


def block_problems(record: Mapping[str, Any]) -> list[str]:
    """Problems of a record's `handoff` block: its shape, and that its decisions are the ones `decide` gives for the runs."""
    found = record.get("handoff")
    if found is None:
        return []
    if not isinstance(found, Mapping) or set(found) != set(BLOCK_FIELDS):
        return [f"handoff must hold exactly {', '.join(BLOCK_FIELDS)}"]
    variants = record.get("variants") or {}
    problems = [f"handoff {side} is not a variant of the record" for side in ("before", "after") if found[side] not in variants]
    fields = found["fields"]
    if not isinstance(fields, Mapping) or set(fields) != set(FIELDS):
        return problems + [f"handoff fields must hold exactly {', '.join(FIELDS)}"]
    for name, decision in fields.items():
        if not isinstance(decision, Mapping) or set(decision) != set(DECISION_FIELDS) or decision["status"] not in STATUSES:
            problems.append(f"handoff field {name} must hold a known status, qualified_on, and reasons")
    runs = [run for run in record.get("runs", []) if isinstance(run, Mapping)]
    if not problems and fields != decide(runs, CASES, found["before"], found["after"]):
        problems.append("handoff fields differ from the decision the rule gives for the runs")
    return problems
