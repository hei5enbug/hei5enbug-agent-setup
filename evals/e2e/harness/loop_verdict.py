"""Adopt or reject the loop-shape candidates of the independent text review from the runs of a record.

A candidate is judged against the baseline in three steps. The writing rule: on each host, no task of T13 to T20 whose
`text-review-clean` check passed on the baseline fails on the candidate, and the number of passing tasks does not fall.
The improvement claim: on T13, T15, and T20 the list cost of the whole run is the claimed measure, accepted on both hosts.
The host comparison: the gaps between the hosts on those three tasks hold. Two or more adopted candidates are then run
together against the baseline in the same three steps; a combined revision that is rejected drops the candidate adopted
last. A run is a record run: `case`, `variant`, `host`, `rep`, `checks`, `passed`, `wall_seconds`, and `cost_usd`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import verdict

WRITING_CASES = tuple(f"T{number}" for number in range(13, 21))
CLAIM_CASES = ("T13", "T15", "T20")
CLAIMED = ("cost_usd",)
CLEAN_CHECK = "text-review-clean"
COMBINED = "combined"
ADOPT, REJECT, UNDECIDED = "adopt", "reject", "undecided"
WRITING_RULE, CLAIM_STEP, HOST_STEP = "writing rule", "improvement claim", "host comparison"
UNDECIDED_STATES = (verdict.NOT_MEASURED, verdict.REPEAT, verdict.CONTINUE_TO_FIVE, verdict.SECOND_PAIR)


def summary(run: Mapping[str, Any]) -> dict[str, Any]:
    """The fields the verdict functions read from one record run."""
    checks = run.get("checks") or {}
    passed = run.get("passed")
    return {"rep": run.get("rep"), "passed": all(checks.values()) if passed is None else bool(passed),
            "wall_seconds": run.get("wall_seconds"), "cost_usd": run.get("cost_usd"), "clean": checks.get(CLEAN_CHECK)}


def side_of(runs: Sequence[Mapping[str, Any]], variant: str, case: str) -> dict[str, list[dict[str, Any]]]:
    """The summaries of one variant on one case by host, in repetition order."""
    found: dict[str, list[dict[str, Any]]] = {}
    for host in verdict.HOSTS:
        chosen = [run for run in runs if (run.get("variant"), run.get("case"), run.get("host")) == (variant, case, host)]
        found[host] = [summary(run) for run in sorted(chosen, key=lambda run: run.get("rep") or 1)]
    return found


def case_of(runs: Sequence[Mapping[str, Any]], baseline: str, candidate: str, case: str) -> dict[str, Any]:
    return {"id": case, "before": side_of(runs, baseline, case), "after": side_of(runs, candidate, case)}


def writing_rule(runs: Sequence[Mapping[str, Any]], baseline: str, candidate: str) -> tuple[str, str]:
    """The first run of every writing task on each host: a lost `text-review-clean` or a fall in passing tasks fails; a
    missing run or check result is not measured."""
    lost, falls, missing = [], [], []
    for host in verdict.HOSTS:
        passing = {"before": 0, "after": 0}
        for case in WRITING_CASES:
            pair = {side: (side_of(runs, name, case)[host] or [None])[0] for side, name in (("before", baseline), ("after", candidate))}
            if None in pair.values() or pair["before"]["clean"] is None or pair["after"]["clean"] is None:
                missing.append(f"{case} on {host}")
                continue
            if pair["before"]["clean"] and not pair["after"]["clean"]:
                lost.append(f"{case} on {host}")
            for side, run in pair.items():
                passing[side] += bool(run["passed"])
        if passing["after"] < passing["before"]:
            falls.append(f"{host}: {passing['after']} of {passing['before']}")
    if lost:
        return verdict.FAIL, f"text-review-clean passed on the baseline and fails on the candidate: {', '.join(lost)}"
    if falls:
        return verdict.FAIL, f"passing tasks fell ({'; '.join(falls)})"
    if missing:
        return verdict.NOT_MEASURED, f"no run or check result for {', '.join(missing)}"
    return verdict.PASS, "no task lost and no fall in passing tasks"


def worst(states: Sequence[str], order: Sequence[str], default: str) -> str:
    return next((state for state in order if state in states), default)


def cost_claim(runs: Sequence[Mapping[str, Any]], baseline: str, candidate: str) -> tuple[str, str]:
    """The improvement claim on cost for T13, T15, and T20; accepted only when every task holds on both hosts."""
    results = [verdict.claim_verdict(case_of(runs, baseline, candidate, case), CLAIMED) for case in CLAIM_CASES]
    state = worst([item["verdict"] for item in results],
                  (verdict.REJECT, verdict.NOT_MEASURED, verdict.SECOND_PAIR, verdict.CONTINUE_TO_FIVE), verdict.ACCEPT)
    pick = next((item for item in results if item["verdict"] == state), results[0])
    steps = "; ".join(f"{host}: {data['step']}" for host, data in pick["hosts"].items())
    return state, f"{pick['case']} {steps}" if state != verdict.ACCEPT else "accepted on both hosts for T13, T15, and T20"


def host_comparison(runs: Sequence[Mapping[str, Any]], baseline: str, candidate: str) -> tuple[str, str]:
    """The host comparison of #92 on T13, T15, and T20: the gaps after must not be wider than the gaps before."""
    results = [verdict.case_verdict(case_of(runs, baseline, candidate, case)) for case in CLAIM_CASES]
    state = worst([item["verdict"] for item in results], (verdict.FAIL, verdict.REPEAT, verdict.NOT_MEASURED), verdict.PASS)
    pick = next((item for item in results if item["verdict"] == state), results[0])
    return state, f"{pick['case']} {state}" if state != verdict.PASS else "the host gaps hold on T13, T15, and T20"


def decide(runs: Sequence[Mapping[str, Any]], baseline: str, candidate: str) -> dict[str, str]:
    """Adopt, reject, or leave undecided one candidate, with the step that decided it. A reject names the first failing
    step; a candidate with no failing step and any unfinished one stays undecided; all three holding adopts it."""
    steps = [(WRITING_RULE, *writing_rule(runs, baseline, candidate)), (CLAIM_STEP, *cost_claim(runs, baseline, candidate)),
             (HOST_STEP, *host_comparison(runs, baseline, candidate))]
    for name, state, reason in steps:
        if state in (verdict.FAIL, verdict.REJECT):
            return {"verdict": REJECT, "step": f"{name}: {reason}"}
    for name, state, reason in steps:
        if state in UNDECIDED_STATES:
            return {"verdict": UNDECIDED, "step": f"{name}: {state}; {reason}"}
    return {"verdict": ADOPT, "step": "the writing rule, the improvement claim, and the host comparison hold"}


def entry(name: str, variant: str, outcome: Mapping[str, str], **extra: Any) -> dict[str, Any]:
    return {"candidate": name, "variant": variant, **outcome, **extra}


def decide_all(runs: Sequence[Mapping[str, Any]], baseline: str, candidates: Mapping[str, str],
               combined: str | None = None) -> list[dict[str, Any]]:
    """One entry per candidate in the order given, then the combined revision when two or more are adopted. A rejected
    combined revision drops the candidate adopted last."""
    entries = [entry(name, variant, decide(runs, baseline, variant)) for name, variant in candidates.items()]
    adopted = [item["candidate"] for item in entries if item["verdict"] == ADOPT]
    if len(adopted) < 2:
        return entries
    if combined is None:
        return [*entries, entry(COMBINED, baseline, {
            "verdict": UNDECIDED, "step": f"{', '.join(adopted)} are adopted; run the revision that holds them all"})]
    outcome = decide(runs, baseline, combined)
    extra = {"dropped": [adopted[-1]]} if outcome["verdict"] == REJECT else {}
    return [*entries, entry(COMBINED, combined, outcome, **extra)]


def final_adopted(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """The candidates the entries adopt: each adopted one when it is alone or the combined revision is adopted, less the one a
    rejected combined revision dropped; nothing while two or more adopted ones await their combined revision."""
    names = [item["candidate"] for item in entries if item["candidate"] != COMBINED and item["verdict"] == ADOPT]
    combined = next((item for item in entries if item["candidate"] == COMBINED), None)
    if combined is None:
        return names if len(names) < 2 else []
    remaining = [name for name in names if name not in combined.get("dropped", [])]
    if combined["verdict"] == ADOPT or (combined["verdict"] == REJECT and len(remaining) < 2):
        return remaining
    return []
