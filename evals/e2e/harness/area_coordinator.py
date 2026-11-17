"""The decision on the area coordinator layer, read from the record `records/99.json`.

Case L (T57) compares two layers (the before variant) with three layers (the after variant) on wall time by the improvement
claim; case M (T58) must pass on the three-layer variant. The decision is `adopt` when the claim is accepted on both hosts
and case M passes, `reject` when the claim is rejected or case M fails, and `undecided` while a run or value is missing or
a pair is still to run. Run summaries come from the record's runs: a run passes when every required check of its task
passes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from . import verdict
from .records import LAYOUTS

CASE_L, CASE_M = "T57", "T58"
TWO, THREE = LAYOUTS["two"], LAYOUTS["three"]
CLAIMED = ("wall_seconds",)
ADOPT, REJECT, UNDECIDED = "adopt", "reject", "undecided"
TASKS_ROOT = Path(__file__).resolve().parent.parent / "tasks"
RECORD_ISSUE = 99


def required_checks(case: str, tasks_root: Path = TASKS_ROOT) -> set[str]:
    task = json.loads((tasks_root / f"{case}.json").read_text(encoding="utf-8"))
    return {check["id"] for check in task["checks"] if check["required"]}


def layout_variants(record: Mapping[str, Any]) -> dict[str, str]:
    """The variant that ran each layout, read from the record's variants; a missing layout is an error."""
    found = {entry.get("layout"): name for name, entry in record["variants"].items() if isinstance(entry, Mapping)}
    missing = [layout for layout in (TWO, THREE) if layout not in found]
    if missing:
        raise ValueError(f"the record names no variant for {', '.join(missing)}")
    return found


def summary(run: Mapping[str, Any], required: set[str]) -> dict[str, Any]:
    checks = run["checks"]
    return {"rep": run.get("rep"), "passed": all(checks.get(name, False) for name in required),
            "wall_seconds": run["wall_seconds"], "cost_usd": run["cost_usd"]}


def build_case(record: Mapping[str, Any], case: str, tasks_root: Path = TASKS_ROOT) -> dict[str, Any]:
    """A verdict case from the record's runs: the two-layer variant is the before side and the three-layer one the after side."""
    variants = layout_variants(record)
    required = required_checks(case, tasks_root)
    built: dict[str, Any] = {"id": case, "before": {}, "after": {}}
    for side, layout in (("before", TWO), ("after", THREE)):
        for host in verdict.HOSTS:
            runs = [run for run in record["runs"] if (run["case"], run["variant"], run["host"]) == (case, variants[layout], host)]
            built[side][host] = [summary(run, required) for run in sorted(runs, key=lambda run: run.get("rep") or 0)]
    return built


def decide(record: Mapping[str, Any], tasks_root: Path = TASKS_ROOT) -> dict[str, Any]:
    """Apply the adoption rule to a record: the claim on case L, case M's quality, and the host comparison of both cases."""
    case_l, case_m = build_case(record, CASE_L, tasks_root), build_case(record, CASE_M, tasks_root)
    claim = verdict.claim_verdict(case_l, CLAIMED)
    quality = verdict.quality_verdict(case_m)
    comparison = verdict.compare([case_l, case_m])
    if claim["verdict"] == verdict.REJECT or quality["verdict"] == verdict.FAIL:
        outcome = REJECT
    elif claim["verdict"] == verdict.ACCEPT and quality["verdict"] == verdict.PASS:
        outcome = ADOPT
    else:
        outcome = UNDECIDED
    return {"decision": outcome, "claim": claim, "case_m": quality, "host_comparison": comparison["verdict"]}


def record_decision(records_dir: Path, tasks_root: Path = TASKS_ROOT) -> str | None:
    """The decision of the committed record of this issue, or None when no record exists."""
    path = records_dir / f"{RECORD_ISSUE}.json"
    if not path.is_file():
        return None
    return decide(json.loads(path.read_text(encoding="utf-8")), tasks_root)["decision"]

