"""Adoption of the candidate loop shapes of issue 102, decided from the runs of a record.

A candidate is adopted when, against the baseline on both hosts, the writing rule holds on the writing tasks, the improvement claim on the list
cost is accepted on the claim tasks, and the host comparison passes on them. Candidates adopted alone are then run together, and a combined
revision that fails drops the candidate adopted last. A run of a record is a dict with `case`, `variant`, `host`, `rep`, `passed`, `checks`,
`wall_seconds`, and `cost_usd`; a combined variant is named by its candidates joined with `+`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .verdict import ACCEPT, FAIL, HOSTS, NOT_MEASURED, PASS, REJECT, claim_verdict, compare, with_claims

BASELINE = "baseline"
CANDIDATES = ("a", "b", "c")
WRITING_TASKS = tuple(f"T{number}" for number in range(13, 21))
CLAIM_TASKS = ("T13", "T15", "T20")
CLAIMED = ("cost_usd",)
CLEAN_CHECK = "text-review-clean"
ADOPTED, REJECTED, DROPPED, UNDECIDED = "adopted", "rejected", "dropped", "undecided"
DECISIONS = frozenset({ADOPTED, REJECTED, DROPPED, UNDECIDED})
WRITING_RULE = "writing_rule"


def summary(run: Mapping[str, Any]) -> dict[str, Any]:
    passed = run.get("passed")
    return {"rep": run.get("rep", 1), "passed": bool(passed), "measured": isinstance(passed, bool),
            "wall_seconds": run.get("wall_seconds"), "cost_usd": run.get("cost_usd")}


def case_of(runs: Sequence[Mapping[str, Any]], before: str, after: str, task: str) -> dict[str, Any]:
    case: dict[str, Any] = {"id": task, "before": {}, "after": {}}
    for side, variant in (("before", before), ("after", after)):
        for host in HOSTS:
            chosen = sorted((run for run in runs if (run["case"], run["variant"], run["host"]) == (task, variant, host)),
                            key=lambda run: run.get("rep", 1))
            case[side][host] = [summary(run) for run in chosen]
    return case


def first_clean(runs: Sequence[Mapping[str, Any]], variant: str, task: str, host: str) -> bool | None:
    """The `text-review-clean` result of the first run of a variant on a task and host; None when there is none."""
    chosen = sorted((run for run in runs if (run["case"], run["variant"], run["host"]) == (task, variant, host)), key=lambda run: run.get("rep", 1))
    value = (chosen[0].get("checks") or {}).get(CLEAN_CHECK) if chosen else None
    return value if isinstance(value, bool) else None


def writing_rule(runs: Sequence[Mapping[str, Any]], baseline: str, variant: str) -> tuple[str, str, list[dict[str, str]]]:
    """No writing task whose `text-review-clean` passes on the baseline fails on the variant, and the number of passing tasks does not
    fall, on each host. Returns the verdict (`pass`, `fail`, or `not measured`), its step, and the entry of each task."""
    entries, lost, pending = [], [], []
    passing = {host: [0, 0] for host in HOSTS}
    for task in WRITING_TASKS:
        task_lost, task_pending = [], []
        for host in HOSTS:
            old, new = first_clean(runs, baseline, task, host), first_clean(runs, variant, task, host)
            if old is None or new is None:
                task_pending.append(f"{task} on {host} has no {CLEAN_CHECK} result for the {'baseline' if old is None else variant}")
                continue
            passing[host][0] += old
            passing[host][1] += new
            if old and not new:
                task_lost.append(f"{task} {CLEAN_CHECK} passes on the baseline and fails on {variant} on {host}")
        lost += task_lost
        pending += task_pending
        state, step = (FAIL, task_lost[0]) if task_lost else (NOT_MEASURED, task_pending[0]) if task_pending else (PASS, f"{CLEAN_CHECK} holds on both hosts")
        entries.append({"case": task, "variant": variant, "measure": WRITING_RULE, "verdict": state, "step": step})
    if lost:
        return FAIL, lost[0], entries
    if pending:
        return NOT_MEASURED, pending[0], entries
    fallen = [host for host, (old, new) in passing.items() if new < old]
    if fallen:
        return FAIL, f"{variant} passes fewer writing tasks than the baseline on {fallen[0]}", entries
    return PASS, "no writing task lost and the number of passing tasks did not fall on either host", entries


def rejection_step(item: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]) -> str:
    """Why a case rejects its variant: its claim steps by host, else its quality reason, else the measure that failed."""
    claim = next((claim for claim in claims if claim["case"] == item["case"] and claim["verdict"] == REJECT), None)
    if claim:
        return f"{item['case']} claim on {','.join(claim['claimed'])}: " + ", ".join(f"{host}: {data['step']}" for host, data in claim["hosts"].items())
    if item["quality"]["verdict"] == FAIL:
        return f"{item['case']} quality: {item['quality']['reason']}"
    failed = next(m for m in item["measures"] if m["verdict"] == FAIL)
    return f"{item['case']} {failed['measure']}: {failed['step']}"


def evaluate(runs: Sequence[Mapping[str, Any]], baseline: str, variant: str) -> dict[str, Any]:
    """The verdict of one revision against the baseline: `adopted`, `rejected`, or `undecided`, with the step that decided it and the
    entries of its case verdicts."""
    rule_state, rule_step, entries = writing_rule(runs, baseline, variant)
    cases = [case_of(runs, baseline, variant, task) for task in CLAIM_TASKS]
    claims = [claim_verdict(case, CLAIMED) for case in cases]
    compared = with_claims(compare(cases), claims)
    for item in compared["cases"]:
        entries.append({"case": item["case"], "variant": variant, "measure": "quality", "verdict": item["quality"]["verdict"], "step": item["quality"]["reason"]})
        entries += [{"case": item["case"], "variant": variant, "measure": m["measure"], "verdict": m["verdict"], "step": m["step"]} for m in item["measures"]]
        entries.append({"case": item["case"], "variant": variant, "verdict": item["verdict"], "step": "quality, both measures, and the claim of the case"})
    for claim in claims:
        steps = ", ".join(f"{host}: {data['step']}" for host, data in claim["hosts"].items())
        entries.append({"case": claim["case"], "variant": variant, "measure": "claim", "verdict": claim["verdict"], "step": f"{','.join(claim['claimed'])}; {steps}"})
    rejecting = [item for item in compared["cases"] if item["verdict"] in (FAIL, REJECT)]
    if rule_state == FAIL or rejecting:
        step = rule_step if rule_state == FAIL else rejection_step(rejecting[0], claims)
        return {"verdict": REJECTED, "step": step, "entries": entries}
    if rule_state == PASS and compared["verdict"] == PASS and all(claim["verdict"] == ACCEPT for claim in claims):
        return {"verdict": ADOPTED, "step": "writing rule, improvement claim, and host comparison hold", "entries": entries}
    waiting = rule_step if rule_state != PASS else next((f"{item['case']}: {item['verdict']}" for item in compared["cases"] if item["verdict"] != PASS), compared["verdict"])
    return {"verdict": UNDECIDED, "step": waiting, "entries": entries}


def decide(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Decide every candidate that has runs, then the combined revisions of the candidates adopted alone, dropping the last adopted one
    of a combination that does not hold. Returns `decisions` (`candidate`, `verdict`, `step`) and the case entries of every revision."""
    variants = {run["variant"] for run in runs}
    single = {name: evaluate(runs, BASELINE, name) for name in CANDIDATES if name in variants}
    entries = [entry for result in single.values() for entry in result["entries"]]
    decisions = {name: {"verdict": result["verdict"], "step": result["step"]} for name, result in single.items()}
    adopted = [name for name in CANDIDATES if decisions.get(name, {}).get("verdict") == ADOPTED]
    current = list(adopted)
    while len(current) >= 2:
        key = "+".join(current)
        if key not in variants:
            for name in current:
                decisions[name] = {"verdict": UNDECIDED, "step": f"run the revision that holds {key} against the baseline"}
            break
        combined = evaluate(runs, BASELINE, key)
        entries += combined["entries"]
        decisions[key] = {"verdict": combined["verdict"], "step": combined["step"]}
        if combined["verdict"] == ADOPTED:
            break
        if combined["verdict"] == UNDECIDED:
            for name in current:
                decisions[name] = {"verdict": UNDECIDED, "step": f"waiting for the combined revision {key}: {combined['step']}"}
            break
        last = current.pop()
        decisions[last] = {"verdict": DROPPED, "step": f"adopted alone, dropped because the combined revision {key} failed: {combined['step']}"}
    return {"decisions": [{"candidate": name, **value} for name, value in decisions.items()], "entries": entries}


def adopted_candidates(decisions: Sequence[Mapping[str, Any]]) -> list[str]:
    """The candidates the record adopts: those adopted alone that no failing combination dropped, and not the combined entries."""
    return [item["candidate"] for item in decisions if item["candidate"] in CANDIDATES and item["verdict"] == ADOPTED]


def decision_problems(record: Mapping[str, Any]) -> list[str]:
    """Problems of a record's `decisions`: a verdict outside the known ones, or decisions that differ from those its own runs give."""
    decisions = record.get("decisions")
    if decisions is None:
        return []
    if not isinstance(decisions, list) or not decisions:
        return ["decisions is not a non-empty list"]
    problems = []
    for index, item in enumerate(decisions):
        if not (isinstance(item, Mapping) and set(item) == {"candidate", "verdict", "step"}):
            problems.append(f"decisions[{index}] needs candidate, verdict, and step")
        elif item["verdict"] not in DECISIONS or not (isinstance(item["step"], str) and item["step"].strip()):
            problems.append(f"decisions[{index}] has an unknown verdict or an empty step")
    if not problems:
        recomputed = decide(record.get("runs") or [])["decisions"]
        if recomputed != decisions:
            problems.append("decisions differ from the ones the runs of the record give")
    return problems
