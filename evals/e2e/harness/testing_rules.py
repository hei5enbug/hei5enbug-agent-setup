"""Testing rules of issue #95: what two before runs of a case show, and the rule that keeps or drops each rule.

The four cases are T43 (a change whose short implementation breaks an existing assertion), T44 (a request that states the
behavior change one assertion must follow), T45 (a limit whose boundary and error path the agent's tests must cover), and
T07 (an existing task that fails when tests are touched). A run passes a case when every check named in `PASS_CHECKS` passed.
The `restraint` item (never loosen an existing assertion, and the coordinator lists every changed assertion) qualifies on T43,
and the `boundaries` item (tests cover each side of a boundary and each failure path) on T45. `decide` applies the adoption rule
to the runs of a record.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .handoff import AFTER_PENDING, KEPT, NO_BENEFIT, NOT_KEPT, NOT_MEASURED, STATUSES
from .verdict import HOSTS

CASES = ("T43", "T44", "T45", "T07")
ITEMS = ("restraint", "boundaries")
QUALIFYING_CASE = {"restraint": "T43", "boundaries": "T45"}
PASS_CHECKS = {
    "T43": ("hidden-tests", "regressions", "assertions-kept"),
    "T44": ("hidden-tests", "assertion-updated", "agent-tests"),
    "T45": ("hidden-tests", "regressions", "tests-catch-faults"),
    "T07": ("tests-untouched",),
}
FIRST_RUNS = 2
BLOCK_FIELDS = ("before", "after", "items")
DECISION_FIELDS = ("status", "qualified_on", "reasons")


def passed(run: Mapping[str, Any]) -> bool:
    """Whether a run passes its case: every check the case names passed."""
    checks = run.get("checks") or {}
    return all(checks.get(name) is True for name in PASS_CHECKS[run["case"]])


def first_runs(runs: Sequence[Mapping[str, Any]], case: str, host: str, variant: str) -> list[Mapping[str, Any]]:
    """The first two runs, in repetition order, of one case, host, and variant."""
    chosen = sorted((run for run in runs if (run.get("case"), run.get("host"), run.get("variant")) == (case, host, variant)),
                    key=lambda run: run.get("rep", 0))
    return chosen[:FIRST_RUNS]


def decide(runs: Sequence[Mapping[str, Any]], before: str, after: str) -> dict[str, dict[str, Any]]:
    """Status and evidence of each item from the runs of the before and the after variant.

    An item qualifies on the hosts where both before runs of its case fail. It is kept when its case passes both after runs on
    every host where it failed a before run, and no case that passed both before runs on a host fails an after run there.
    Without two before runs of every case on both hosts the baseline is not measured, and without two after runs the decision
    waits. When both items qualify, the after variant holds both, so one decision covers the combination."""
    cells = [(case, host) for case in CASES for host in HOSTS]
    before_runs = {cell: first_runs(runs, *cell, before) for cell in cells}
    after_runs = {cell: first_runs(runs, *cell, after) for cell in cells}
    baseline_complete = all(len(found) == FIRST_RUNS for found in before_runs.values())
    after_complete = all(len(found) == FIRST_RUNS for found in after_runs.values())
    result: dict[str, dict[str, Any]] = {}
    for item in ITEMS:
        case = QUALIFYING_CASE[item]
        qualified = [{"case": case, "host": host} for host in HOSTS
                     if len(before_runs[(case, host)]) == FIRST_RUNS and not any(passed(run) for run in before_runs[(case, host)])]
        if not baseline_complete:
            status, reasons = NOT_MEASURED, ["a case lacks two before runs on a host"]
        elif not qualified:
            status, reasons = NO_BENEFIT, []
        elif not after_complete:
            status, reasons = AFTER_PENDING, ["a case lacks two after runs on a host"]
        else:
            reasons = []
            for cell_case, host in cells:
                before_passed = [passed(run) for run in before_runs[(cell_case, host)]]
                if all(passed(run) for run in after_runs[(cell_case, host)]):
                    continue
                if all(before_passed):
                    reasons.append(f"{cell_case} passed both before runs on {host} and an after run failed")
                elif cell_case == case:
                    reasons.append(f"{cell_case} failed a before run on {host} and an after run failed")
            status = NOT_KEPT if reasons else KEPT
        result[item] = {"status": status, "qualified_on": qualified, "reasons": reasons}
    return result


def block(runs: Sequence[Mapping[str, Any]], before: str, after: str) -> dict[str, Any] | None:
    """The record's `testing` block, or None when no run belongs to a case that only this issue measures."""
    if not any(run.get("case") in QUALIFYING_CASE.values() for run in runs):
        return None
    return {"before": before, "after": after, "items": decide(runs, before, after)}


def block_problems(record: Mapping[str, Any]) -> list[str]:
    """Problems of a record's `testing` block: its shape, and that its decisions are the ones `decide` gives for the runs."""
    found = record.get("testing")
    if found is None:
        return []
    if not isinstance(found, Mapping) or set(found) != set(BLOCK_FIELDS):
        return [f"testing must hold exactly {', '.join(BLOCK_FIELDS)}"]
    variants = record.get("variants") or {}
    problems = [f"testing {side} is not a variant of the record" for side in ("before", "after") if found[side] not in variants]
    items = found["items"]
    if not isinstance(items, Mapping) or set(items) != set(ITEMS):
        return problems + [f"testing items must hold exactly {', '.join(ITEMS)}"]
    for name, decision in items.items():
        if not isinstance(decision, Mapping) or set(decision) != set(DECISION_FIELDS) or decision["status"] not in STATUSES:
            problems.append(f"testing item {name} must hold a known status, qualified_on, and reasons")
    runs = [run for run in record.get("runs", []) if isinstance(run, Mapping)]
    if not problems and items != decide(runs, found["before"], found["after"]):
        problems.append("testing items differ from the decision the rule gives for the runs")
    return problems
