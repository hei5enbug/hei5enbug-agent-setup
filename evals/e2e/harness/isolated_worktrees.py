"""The decision on one worktree per parallel worker, read from the record `records/98.json`.

Case S (T55) compares workers in sequence (the before variant) with one worktree per worker run in parallel (the after
variant) on wall time by the improvement claim, so cost may not rise: the median cost after is not above the highest cost
before. Cases D (T56, two changes to one database file) and T05 (two independent changes) must pass on the isolated
variant. The decision is `adopt` when the claim is accepted on both hosts and D and T05 pass, `reject` when the claim is
rejected or D or T05 fails, and `undecided` while a run or value is missing or a pair is still to run. A run passes when
every required check of its task passes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from . import verdict
from .area_coordinator import ADOPT, REJECT, UNDECIDED, TASKS_ROOT, required_checks, summary
from .records import WORKSPACES

CASE_S, CASE_D, CASE_T05 = "T55", "T56", "T05"
SEQUENTIAL, ISOLATED = WORKSPACES["sequential"], WORKSPACES["isolated"]
CLAIMED = ("wall_seconds",)
RECORD_ISSUE = 98
RULE_MARKER = "one worktree per worker"


def workspace_variants(record: Mapping[str, Any]) -> dict[str, str]:
    """The variant that ran each workspace layout, read from the record's variants; a missing layout is an error."""
    found = {entry.get("workspace"): name for name, entry in record["variants"].items() if isinstance(entry, Mapping)}
    missing = [layout for layout in (SEQUENTIAL, ISOLATED) if layout not in found]
    if missing:
        raise ValueError(f"the record names no variant for {', '.join(missing)}")
    return found


def build_case(record: Mapping[str, Any], case: str, tasks_root: Path = TASKS_ROOT) -> dict[str, Any]:
    """A verdict case from the record's runs: the sequential variant is the before side and the isolated one the after side."""
    variants = workspace_variants(record)
    required = required_checks(case, tasks_root)
    built: dict[str, Any] = {"id": case, "before": {}, "after": {}}
    for side, layout in (("before", SEQUENTIAL), ("after", ISOLATED)):
        for host in verdict.HOSTS:
            runs = [run for run in record["runs"] if (run["case"], run["variant"], run["host"]) == (case, variants[layout], host)]
            built[side][host] = [summary(run, required) for run in sorted(runs, key=lambda run: run.get("rep") or 0)]
    return built


def decide(record: Mapping[str, Any], tasks_root: Path = TASKS_ROOT) -> dict[str, Any]:
    """Apply the adoption rule to a record: the claim on case S, the quality of D and T05, and the host comparison of the three."""
    case_s, case_d, case_t05 = (build_case(record, case, tasks_root) for case in (CASE_S, CASE_D, CASE_T05))
    claim = verdict.claim_verdict(case_s, CLAIMED)
    quality = {case["id"]: verdict.quality_verdict(case)["verdict"] for case in (case_d, case_t05)}
    comparison = verdict.compare([case_s, case_d, case_t05])
    if claim["verdict"] == verdict.REJECT or verdict.FAIL in quality.values():
        outcome = REJECT
    elif claim["verdict"] == verdict.ACCEPT and set(quality.values()) == {verdict.PASS}:
        outcome = ADOPT
    else:
        outcome = UNDECIDED
    return {"decision": outcome, "claim": claim, "quality": quality, "host_comparison": comparison["verdict"]}


def record_decision(records_dir: Path, tasks_root: Path = TASKS_ROOT) -> str | None:
    """The decision of the committed record of this issue, or None when no record exists."""
    path = records_dir / f"{RECORD_ISSUE}.json"
    if not path.is_file():
        return None
    return decide(json.loads(path.read_text(encoding="utf-8")), tasks_root)["decision"]
