"""The record of the requirements agreement measurement: every run of the before variant and of each drafter step, the verdicts of
the host comparison, and the step each host registers.

Cases A to G are tasks T46 to T52. A step's runs are read from its variant in one campaign: a run that is unfinished, has no
verdict from its checks, or ended on a harness or infrastructure error is not counted, so it never enters a case's run list.
The comparison of the host rule takes, on each host, the before run, the first run of the registered step for cases A to D, and
the first run with step 1 for cases E to G.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from . import records
from .agreement_candidate import STEP1, STEPS
from .agreement_decision import ABCD, CASES, EFG, agreement_problems, decide
from .command import ConfigError
from .config import HOSTS
from .verdict import compare

CASE_TASKS = dict(zip(CASES, ("T46", "T47", "T48", "T49", "T50", "T51", "T52")))
TASK_CASES = {task: case for case, task in CASE_TASKS.items()}
DRAFTER_ROLES = ("spec-drafter", "runner:reviewer", "role_runner:reviewer", "codex_child:")


def counted_runs(runs: Sequence[Mapping[str, Any]], variant: str, task: str, host: str) -> list[bool]:
    """Pass or fail of each counted run of the variant on the task and host, in repetition order."""
    chosen = sorted((run for run in runs if (run["case"], run["variant"], run["host"]) == (task, variant, host)
                     and run["summary"].get("measured", True) and isinstance(run["summary"].get("passed"), bool)),
                    key=lambda run: run["summary"]["rep"])
    return [bool(run["summary"]["passed"]) for run in chosen]


def steps_section(runs: Sequence[Mapping[str, Any]], variants: Mapping[str, str]) -> dict[str, dict[str, dict[str, list[bool]]]]:
    """Per step, host, and case letter, the counted run results. Step 1 holds cases A to G, every later step A to D; a case with
    no counted run is left out."""
    section: dict[str, dict[str, dict[str, list[bool]]]] = {}
    for step, variant in variants.items():
        cases = CASES if step == STEP1 else ABCD
        per_host = {host: {case: counted_runs(runs, variant, CASE_TASKS[case], host) for case in cases} for host in HOSTS}
        section[step] = {host: {case: results for case, results in held.items() if results} for host, held in per_host.items()}
    return section


def drafter_models(runs: Sequence[Mapping[str, Any]], variants: Mapping[str, str]) -> dict[str, dict[str, dict[str, str]]]:
    """The drafter's model and effort per agent step and host, read from the `models` of its runs' host records; an effort no
    record states reads "not measured". A step with no drafter role in any run is left out."""
    found: dict[str, dict[str, dict[str, str]]] = {}
    for step, variant in variants.items():
        if step == STEP1:
            continue
        for run in runs:
            entry = run.get("entry") or {}
            if run["variant"] != variant:
                continue
            role = next((name for name in entry.get("models", {}) if any(mark in name for mark in DRAFTER_ROLES)), None)
            if role:
                found.setdefault(step, {}).setdefault(run["host"], dict(entry["models"][role]))
    return found


def build_section(runs: Sequence[Mapping[str, Any]], variants: Mapping[str, str]) -> dict[str, Any]:
    steps = steps_section(runs, variants)
    decided = decide(steps)
    return {"case_tasks": dict(CASE_TASKS), "steps": steps, "drafters": drafter_models(runs, variants),
            "registered": decided["registered"], "state": decided["state"]}


def host_cases(runs: Sequence[Mapping[str, Any]], before: str, variants: Mapping[str, str], registered: Mapping[str, str | None],
               expected: Sequence[str], planned: set[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """The cases of the host comparison: on each host the before runs against the registered step for cases A to D and against
    step 1 for E to G. A host with no registered step falls back to step 1 for every case, so its verdict stays measurable."""
    cases = []
    for task in expected:
        case = TASK_CASES.get(task)
        merged: dict[str, Any] = {"id": task, "before": {}, "after": {}, "baseline_hosts": []}
        for host in HOSTS:
            step = STEP1 if case in EFG or not registered.get(host) else registered[host]
            built = records.build_cases(runs, before, variants[step], [task], planned)[0]
            merged["before"][host], merged["after"][host] = built["before"][host], built["after"][host]
            if host in built["baseline_hosts"]:
                merged["baseline_hosts"].append(host)
        cases.append(merged)
    return cases


def record_agreement(
    run_root: Path, campaign: str, issue: int, before: str, variants: Mapping[str, str], tasks: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build the record: every run of `before` and of each step's variant, the host comparison, and the agreement section.

    `variants` maps a drafter step to its variant name and must hold `step1`. Returns the record, the comparison, and the section."""
    unknown = [step for step in variants if step not in STEPS]
    if unknown or STEP1 not in variants or before in variants.values():
        raise ConfigError("--steps takes step names from " + ", ".join(STEPS) + ", must include step1, and must not name the before variant")
    runs = records.campaign_runs(run_root, campaign, (before, *variants.values()), tasks)
    expected = records.expected_tasks(run_root, campaign, tasks, runs)
    if not expected or not any(run["entry"] for run in runs):
        raise ConfigError(f"campaign {campaign} holds no finished graded run of {before} or of a step")
    section = build_section(runs, variants)
    problems = agreement_problems(section)
    if problems:
        raise ConfigError("; ".join(problems))
    compared = compare(host_cases(runs, before, variants, section["registered"], expected, records.planned_runs(run_root, campaign)))
    names = (before, *variants.values())
    revisions = {name: records.variant_revision(run_root, campaign, name, runs) for name in names}
    entries = records.verdict_entries(compared, [])
    record = records.build_record(issue, expected, revisions, [run["entry"] for run in runs if run["entry"]], entries,
                                  {"agreement": section})
    return {"record": record, "compared": compared, "section": section}


def report_lines(result: Mapping[str, Any]) -> list[str]:
    """One line per host with its registered step, the adoption state, and the host comparison."""
    section = result["section"]
    lines = [f"{host}: registered {section['registered'][host] or 'nothing'}" for host in HOSTS]
    lines.append(f"agreement: {section['state']}")
    return [*lines, *records.report_lines({"compared": result["compared"], "claims": []})]
