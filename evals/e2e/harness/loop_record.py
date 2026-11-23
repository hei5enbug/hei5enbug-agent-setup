"""Write the record of the loop-shape candidates: the baseline and every candidate on both hosts, with the loop measures."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from . import loop_verdict, records, verdict
from .command import ConfigError


def variant_names(baseline: str, candidates: Mapping[str, str], combined: str | None) -> list[str]:
    """The variant names of a loop record; they must differ, and no candidate may be named like the combined revision."""
    names = [baseline, *candidates.values(), *([combined] if combined else [])]
    if len(set(names)) != len(names) or loop_verdict.COMBINED in candidates:
        raise ConfigError("the baseline, the candidates, and the combined variant need different names, and no candidate is named "
                          + loop_verdict.COMBINED)
    return names


def verdict_lines(cases: Sequence[Mapping[str, Any]], name: str, outcome: Mapping[str, Any],
                  claims: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The verdicts of one candidate: quality of every writing task, then the gaps and the claim of T13, T15, and T20."""
    claimed = [case for case in cases if case["id"] in loop_verdict.CLAIM_CASES]
    quality = [{"case": case["id"], "measure": "quality", "verdict": verdict.quality_verdict(case)["verdict"],
                "step": f"{name}: {verdict.quality_verdict(case)['reason']}"} for case in cases if case not in claimed]
    detail = records.verdict_entries(verdict.with_claims(verdict.compare(claimed), claims), claims) if claimed else []
    return quality + [{**item, "step": f"{name}: {item['step']}"} for item in detail]


def record_loop(
    run_root: Path, campaign: str, issue: int, baseline: str, candidates: Mapping[str, str], combined: str | None = None,
    tasks: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Judge each candidate against the baseline on both hosts and build the record. Returns the record and the lines to print."""
    names = variant_names(baseline, candidates, combined)
    runs = records.campaign_runs(run_root, campaign, names, tasks)
    entries = [run["entry"] for run in runs if run["entry"]]
    if not entries:
        raise ConfigError(f"campaign {campaign} holds no finished graded run of the baseline or a candidate")
    decided = loop_verdict.decide_all(entries, baseline, candidates, combined)
    cases = sorted({run["case"] for run in runs})
    claims_of = {}
    verdicts: list[dict[str, str]] = []
    for item in (item for item in decided if item["variant"] != baseline):
        built = records.build_cases(runs, baseline, item["variant"], cases, records.planned_runs(run_root, campaign))
        built = [case for case in built if case["id"] in loop_verdict.WRITING_CASES]
        claims = [verdict.claim_verdict(case, loop_verdict.CLAIMED) for case in built if case["id"] in loop_verdict.CLAIM_CASES]
        claims_of[item["candidate"]] = claims
        verdicts += verdict_lines(built, item["candidate"], item, claims)
    revisions = {name: records.variant_revision(run_root, campaign, name, runs) for name in names}
    record = records.build_record(issue, cases, revisions, entries, verdicts, decided)
    lines = [f"{item['candidate']}: {item['verdict']} ({item['step']})" for item in decided]
    return {"record": record, "lines": [*lines, f"adopted: {', '.join(loop_verdict.final_adopted(decided)) or 'none'}"]}
