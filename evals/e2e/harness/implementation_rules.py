"""Implementation rules of issue #93: what the before runs of eight seeded tasks show, and the rule that keeps or drops each rule.

Each rule (a) to (h) has one seeded task, T34 to T41, and a run passes its task when every check named in `PASS_CHECKS`
passed. A rule qualifies on a host when both of the first two before runs of its task fail there, so a rule whose task passes
a before run on both hosts adds nothing and reads `no demonstrated benefit at baseline`. The after variant holds exactly the
qualifying rules. A qualifying rule is kept when its task passes both after runs on every host where it failed and no task that
passed both before runs on a host fails an after run there. A qualifying rule whose own task still fails is reworded once, and
the reworded variant is judged the same way; the rule is left out when it fails again. `decide` applies this to a record's runs.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .handoff import AFTER_PENDING, KEPT, NO_BENEFIT, NOT_KEPT, NOT_MEASURED
from .verdict import HOSTS

RULES = ("a", "b", "c", "d", "e", "f", "g", "h")
TASK_OF = {"a": "T34", "b": "T35", "c": "T36", "d": "T37", "e": "T38", "f": "T39", "g": "T40", "h": "T41"}
CASES = tuple(TASK_OF.values())
CONDITIONAL_RULES = ("f", "g", "h")
PASS_CHECKS = {
    "T34": ("hidden-tests", "manifest-unchanged", "no-extra-files", "no-extra-setting-keys"),
    "T35": ("hidden-tests",),
    "T36": ("hidden-tests",),
    "T37": ("hidden-tests",),
    "T38": ("hidden-tests", "report-names-function"),
    "T39": ("hidden-tests", "test-fails-on-base", "agent-tests"),
    "T40": ("hidden-import", "hidden-concurrent"),
    "T41": ("hidden-tests", "engine-check-after-edit"),
}
FIRST_RUNS = 2
REWORD = "qualified; task still fails: reword once"
REWORD_PENDING = "reworded; runs not measured"
STATUSES = (NO_BENEFIT, NOT_MEASURED, AFTER_PENDING, REWORD, REWORD_PENDING, KEPT, NOT_KEPT)
BLOCK_FIELDS = ("before", "after", "reworded", "qualifying", "rules")
DECISION_FIELDS = ("task", "status", "qualified_on", "reasons")


def passed(run: Mapping[str, Any]) -> bool:
    """Whether a run passes its task: every check the task names passed."""
    checks = run.get("checks") or {}
    return all(checks.get(name) is True for name in PASS_CHECKS[run["case"]])


def first_runs(runs: Sequence[Mapping[str, Any]], case: str, host: str, variant: str, count: int = FIRST_RUNS) -> list[Mapping[str, Any]]:
    """The first `count` runs, in repetition order, of one task, host, and variant."""
    chosen = sorted((run for run in runs if (run.get("case"), run.get("host"), run.get("variant")) == (case, host, variant)),
                    key=lambda run: run.get("rep", 0))
    return chosen[:count]


def complete(runs: Sequence[Mapping[str, Any]], variant: str, doubled: Sequence[str]) -> bool:
    """Whether a variant holds two runs of each task in `doubled` and one run of every other task, on both hosts."""
    return all(len(first_runs(runs, case, host, variant, FIRST_RUNS if case in doubled else 1)) == (FIRST_RUNS if case in doubled else 1)
               for case in CASES for host in HOSTS)


def own_failures(rule: str, hosts: Sequence[str], runs: Sequence[Mapping[str, Any]], variant: str) -> list[str]:
    case = TASK_OF[rule]
    return [f"{case} failed an after run on {host}" for host in hosts
            if not all(passed(run) for run in first_runs(runs, case, host, variant))]


def regressions(runs: Sequence[Mapping[str, Any]], before: str, variant: str) -> list[str]:
    """Tasks that passed both before runs on a host and fail a run of `variant` there."""
    found = []
    for case in CASES:
        for host in HOSTS:
            earlier = first_runs(runs, case, host, before)
            if len(earlier) == FIRST_RUNS and all(passed(run) for run in earlier) \
                    and not all(passed(run) for run in first_runs(runs, case, host, variant)):
                found.append(f"{case} passed both before runs on {host} and a run of {variant} failed")
    return found


def decide(runs: Sequence[Mapping[str, Any]], before: str, after: str, reworded: str | None = None) -> dict[str, dict[str, Any]]:
    """Status and evidence of each rule from the runs of the before, the after, and the reworded variant.

    Without two before runs of every task on both hosts the baseline is not measured, and without the after runs the decision
    waits. A regression, a task that passed both before runs and fails an after run, leaves every qualifying rule out, because
    the after variant holds them all. A qualifying rule whose own task fails stays open for one rewording, and the reworded
    variant is judged the same way for those rules alone."""
    baseline = all(len(first_runs(runs, case, host, before)) == FIRST_RUNS for case in CASES for host in HOSTS)
    qualified = {rule: [{"case": TASK_OF[rule], "host": host} for host in HOSTS
                        if len(first_runs(runs, TASK_OF[rule], host, before)) == FIRST_RUNS
                        and not any(passed(run) for run in first_runs(runs, TASK_OF[rule], host, before))] for rule in RULES}
    qualifying = [rule for rule in RULES if qualified[rule]]
    result: dict[str, dict[str, Any]] = {}

    def settle(rule: str, status: str, reasons: Sequence[str] = ()) -> None:
        result[rule] = {"task": TASK_OF[rule], "status": status, "qualified_on": qualified[rule], "reasons": list(reasons)}

    if not baseline:
        for rule in RULES:
            settle(rule, NOT_MEASURED, ["a task lacks two before runs on a host"])
        return result
    if not qualifying:
        for rule in RULES:
            settle(rule, NO_BENEFIT)
        return result
    if not complete(runs, after, [TASK_OF[rule] for rule in qualifying]):
        for rule in RULES:
            settle(rule, AFTER_PENDING if rule in qualifying else NO_BENEFIT,
                   ["a task lacks its after runs on a host"] if rule in qualifying else [])
        return result
    broken = regressions(runs, before, after)
    open_rules = []
    for rule in RULES:
        if rule not in qualifying:
            settle(rule, NO_BENEFIT)
            continue
        own = own_failures(rule, [item["host"] for item in qualified[rule]], runs, after)
        if broken:
            settle(rule, NOT_KEPT, [*own, *broken])
        elif own:
            open_rules.append(rule)
            settle(rule, REWORD, own)
        else:
            settle(rule, KEPT)
    if not open_rules or reworded is None:
        return result
    if not complete(runs, reworded, [TASK_OF[rule] for rule in open_rules]):
        for rule in open_rules:
            settle(rule, REWORD_PENDING, ["a task lacks its reworded runs on a host"])
        return result
    broken = regressions(runs, before, reworded)
    for rule in open_rules:
        own = own_failures(rule, [item["host"] for item in qualified[rule]], runs, reworded)
        settle(rule, NOT_KEPT if own or broken else KEPT, [f"{reason} after the rewording" for reason in own] + broken)
    return result


def kept_rules(decisions: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The rules a decision keeps, in the canonical order."""
    return [rule for rule in RULES if (decisions.get(rule) or {}).get("status") == KEPT]


def block(runs: Sequence[Mapping[str, Any]], before: str, after: str, reworded: str | None = None) -> dict[str, Any] | None:
    """The record's `implementation` block, or None when no run belongs to one of the eight tasks."""
    if not any(run.get("case") in CASES for run in runs):
        return None
    decisions = decide(runs, before, after, reworded)
    return {"before": before, "after": after, "reworded": reworded,
            "qualifying": [rule for rule in RULES if decisions[rule]["qualified_on"]], "rules": decisions}


def block_problems(record: Mapping[str, Any]) -> list[str]:
    """Problems of a record's `implementation` block: its shape, and that its decisions are the ones `decide` gives for the runs."""
    found = record.get("implementation")
    if found is None:
        return []
    if not isinstance(found, Mapping) or set(found) != set(BLOCK_FIELDS):
        return [f"implementation must hold exactly {', '.join(BLOCK_FIELDS)}"]
    variants = record.get("variants") or {}
    problems = [f"implementation {side} is not a variant of the record" for side in ("before", "after", "reworded")
                if found[side] is not None and found[side] not in variants]
    rules = found["rules"]
    if not isinstance(rules, Mapping) or set(rules) != set(RULES):
        return problems + [f"implementation rules must hold exactly {', '.join(RULES)}"]
    for name, decision in rules.items():
        if not isinstance(decision, Mapping) or set(decision) != set(DECISION_FIELDS) or decision["status"] not in STATUSES:
            problems.append(f"implementation rule {name} must hold a task, a known status, qualified_on, and reasons")
    runs = [run for run in record.get("runs", []) if isinstance(run, Mapping)]
    if not problems and found != block(runs, found["before"], found["after"], found["reworded"]):
        problems.append("implementation rules differ from the decision the rule gives for the runs")
    return problems
