"""Verdicts of a harness change measured on both hosts, as pure functions over run summaries.

A run summary is a dict: `passed` (every required check passed), `wall_seconds`, and `cost_usd` (list price of the
whole run). A case holds `before` and `after`, each a dict from host to the list of that host's run summaries in
repetition order; a case whose before side has no run on a host decides quality only.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Mapping, Sequence

HOSTS = ("claude", "codex")
MEASURES = ("wall_seconds", "cost_usd")
FIRST_RUNS = 1
FULL_RUNS = 5
INVESTIGATE_ABOVE = 2.0
TOLERANCE = 1e-9

PASS = "pass"
FAIL = "fail"
REPEAT = "repeat"
NOT_MEASURED = "not measured"
INVESTIGATE = "investigate"
BASELINE = "baseline"

CONTINUE_TO_FIVE = "continue to five"
SECOND_PAIR = "second pair"
REJECT = "reject"
ACCEPT = "accept"


def number(value: Any) -> float | None:
    """A usable measurement: a positive number that is not a boolean."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def runs_of(side: Mapping[str, Sequence[Mapping[str, Any]]] | None, host: str) -> list[Mapping[str, Any]]:
    return list((side or {}).get(host) or [])


def by_rep(runs: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    """Runs keyed by repetition number: a run's own `rep`, else its position in the list counted from 1."""
    keyed: dict[int, Mapping[str, Any]] = {}
    for index, run in enumerate(runs, start=1):
        rep = run.get("rep")
        keyed[rep if isinstance(rep, int) and not isinstance(rep, bool) else index] = run
    return keyed


def is_measured(run: Mapping[str, Any]) -> bool:
    return run.get("measured", True) is not False


def side_reps(side: Mapping[str, Sequence[Mapping[str, Any]]] | None) -> dict[str, dict[int, Mapping[str, Any]]]:
    return {host: by_rep(runs_of(side, host)) for host in HOSTS}


def host_gap(side: Mapping[str, Sequence[Mapping[str, Any]]] | None, measure: str, rep: int) -> float | None:
    """Larger host value divided by the smaller for one repetition number, or None when either host lacks that repetition
    or its value."""
    values = []
    for host, keyed in side_reps(side).items():
        values.append(number(keyed[rep].get(measure)) if rep in keyed else None)
    if None in values:
        return None
    return max(values) / min(values)


def gaps(side: Mapping[str, Sequence[Mapping[str, Any]]] | None, measure: str, reps: Sequence[int]) -> list[float | None]:
    return [host_gap(side, measure, rep) for rep in reps]


def quality_verdict(case: Mapping[str, Any]) -> dict[str, Any]:
    """Every after run passes on both hosts, and a case that passed before fails on neither host. A run that was not
    measured, such as an unfinished or ungraded one, leaves the quality not measured unless another run already fails."""
    before, after = case.get("before"), case.get("after")
    for host in HOSTS:
        after_runs = runs_of(after, host)
        if not after_runs:
            return {"verdict": NOT_MEASURED, "reason": f"no after run on {host}"}
    for host in HOSTS:
        before_runs = [run for run in runs_of(before, host) if is_measured(run)]
        failed = [run for run in runs_of(after, host) if is_measured(run) and not run.get("passed")]
        if failed and before_runs and all(run.get("passed") for run in before_runs):
            return {"verdict": FAIL, "reason": f"passed before and fails after on {host}"}
    for host in HOSTS:
        if any(is_measured(run) and not run.get("passed") for run in runs_of(after, host)):
            return {"verdict": FAIL, "reason": f"a required check fails after on {host}"}
    for host in HOSTS:
        if any(not is_measured(run) for run in runs_of(after, host)):
            return {"verdict": NOT_MEASURED, "reason": f"an after run on {host} is not measured"}
    return {"verdict": PASS, "reason": "every required check passes after on both hosts"}


def result(measure: str, verdict: str, step: str, **extra: Any) -> dict[str, Any]:
    return {"measure": measure, "verdict": verdict, "step": step, "line": extra.pop("line", None), **extra}


def missing_repetition(sides: Mapping[str, Mapping[str, Mapping[int, Any]]], reps: Sequence[int]) -> str | None:
    """The first (side, host, repetition) that lacks a run among `reps`, or None when every pair is complete."""
    for rep in reps:
        for name, hosts in sides.items():
            for host in HOSTS:
                if rep not in hosts[host]:
                    return f"repetition {rep} has no {name} run on {host}"
    return None


def measure_verdict(case: Mapping[str, Any], measure: str) -> dict[str, Any]:
    """One measure of one case. Its own first pair decides it: a gap that did not grow passes whatever later repetitions
    another measure needed; a gap that grew asks for four more runs per variant and host, and five complete pairs
    decide it by the median rule. A missing run or value is not measured, never a pass."""
    before, after = case.get("before"), case.get("after")
    case_id = case.get("id", "case")
    after_runs = side_reps(after)
    if any(not after_runs[host] for host in HOSTS):
        return result(measure, NOT_MEASURED, "no after run on a host")
    if any(number(run.get(measure)) is None for keyed in after_runs.values() for run in keyed.values()):
        return result(measure, NOT_MEASURED, "an after value is missing")
    before_runs = side_reps(before)
    if any(not before_runs[host] for host in HOSTS):
        return result(measure, BASELINE, "no before run on a host")
    sides = {"before": before_runs, "after": after_runs}
    absent = missing_repetition(sides, [1])
    if absent:
        return result(measure, NOT_MEASURED, absent)
    first_before = host_gap(before, measure, 1)
    if first_before is None:
        return result(measure, NOT_MEASURED, "a before value is missing")
    if first_before > INVESTIGATE_ABOVE:
        line = f"investigate: {case_id} {measure} host gap before is {first_before:.2f}"
        return result(measure, INVESTIGATE, "first before gap above 2", line=line, gap_before=[first_before])
    gap_after = host_gap(after, measure, 1)
    if gap_after is None:
        return result(measure, NOT_MEASURED, "an after value is missing")
    if gap_after <= first_before + TOLERANCE:
        return result(measure, PASS, "first run", gap_before=[first_before], gap_after=[gap_after])
    reps = sorted({rep for hosts in sides.values() for keyed in hosts.values() for rep in keyed})
    absent = missing_repetition(sides, reps)
    if absent:
        return result(measure, NOT_MEASURED, absent)
    if len(reps) < FULL_RUNS:
        return result(measure, REPEAT, "gap grew on the first run; run four more per variant and host",
                      gap_before=[first_before], gap_after=[gap_after])
    reps = reps[:FULL_RUNS]
    gap_before, gap_after = gaps(before, measure, reps), gaps(after, measure, reps)
    if None in gap_before or None in gap_after:
        return result(measure, NOT_MEASURED, "a value is missing among five runs")
    verdict = PASS if median(gap_after) <= max(gap_before) + TOLERANCE else FAIL
    return result(measure, verdict, "five runs", gap_before=gap_before, gap_after=gap_after,
                  median_after=median(gap_after), max_before=max(gap_before))


def case_verdict(case: Mapping[str, Any]) -> dict[str, Any]:
    """Quality and the time and cost gaps of one case; a quality failure fails it whatever the gaps are."""
    quality = quality_verdict(case)
    measures = [measure_verdict(case, measure) for measure in MEASURES]
    states = [item["verdict"] for item in measures]
    if quality["verdict"] == FAIL or FAIL in states:
        overall = FAIL
    elif quality["verdict"] == NOT_MEASURED:
        overall = NOT_MEASURED
    elif REPEAT in states:
        overall = REPEAT
    elif NOT_MEASURED in states:
        overall = NOT_MEASURED
    else:
        overall = PASS
    return {"case": case.get("id"), "verdict": overall, "quality": quality, "measures": measures,
            "lines": [item["line"] for item in measures if item["line"]]}


def overall_verdict(states: Sequence[str]) -> str:
    for state in (FAIL, REJECT, REPEAT, NOT_MEASURED, SECOND_PAIR, CONTINUE_TO_FIVE):
        if state in states:
            return state
    return PASS


def compare(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One verdict per case; the change is adoptable only when every case passes."""
    results = [case_verdict(case) for case in cases]
    return {"verdict": overall_verdict([item["verdict"] for item in results]), "cases": results,
            "lines": [line for item in results for line in item["lines"]]}


def combine_claim(case_state: str, claim_state: str | None) -> str:
    """A case verdict with its improvement claim: a quality failure stays a failure, a rejected claim rejects the case, and a
    claim that is not accepted yet leaves the case at the claim's state instead of a pass."""
    if claim_state is None or case_state == FAIL:
        return case_state
    if claim_state == REJECT:
        return REJECT
    if case_state != PASS:
        return case_state
    return PASS if claim_state == ACCEPT else claim_state


def with_claims(compared: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The comparison with each claimed case's verdict and the overall verdict decided together with its claim."""
    by_case = {claim["case"]: claim["verdict"] for claim in claims}
    cases = [{**item, "verdict": combine_claim(item["verdict"], by_case.get(item["case"]))} for item in compared["cases"]]
    return {**compared, "cases": cases, "verdict": overall_verdict([item["verdict"] for item in cases])}


def pair_is_lower(before: Mapping[str, Any], after: Mapping[str, Any], claimed: Sequence[str]) -> bool | None:
    """True when the after run passes and is lower on every claimed measure; None when a value is missing."""
    values = [(number(after.get(measure)), number(before.get(measure))) for measure in claimed]
    if any(low is None or high is None for low, high in values):
        return None
    return bool(after.get("passed")) and all(low < high for low, high in values)


def paired_runs(before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]]) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]] | None:
    """The before and after run of each repetition number in order; None when a repetition lacks one of the two."""
    keyed_before, keyed_after = by_rep(before), by_rep(after)
    reps = sorted({*keyed_before, *keyed_after})
    if any(rep not in keyed_before or rep not in keyed_after for rep in reps):
        return None
    return [(keyed_before[rep], keyed_after[rep]) for rep in reps]


def claim_on_host(before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]],
                  claimed: Sequence[str]) -> tuple[str, str]:
    """The claim's verdict on one host and the step that decided it. Runs are paired by repetition number, and a
    repetition with only one side is not measured."""
    pairs = paired_runs(before, after)
    if pairs is None:
        return NOT_MEASURED, "a repetition lacks its before or after run"
    count = len(pairs)
    if count == 0:
        return NOT_MEASURED, "no paired run"
    if any(not is_measured(run) for pair in pairs for run in pair):
        return NOT_MEASURED, "a run is not measured"
    if count < FULL_RUNS:
        if any(not run.get("passed") for _, run in pairs[2:count]):
            return REJECT, "an after run failed a required check"
        lower = [pair_is_lower(old, new, claimed) for old, new in pairs[:2]]
        if None in lower:
            return NOT_MEASURED, "a value is missing"
        if count == 1:
            return (CONTINUE_TO_FIVE, "first pair is lower") if lower[0] else (SECOND_PAIR, "first pair is not lower")
        return (REJECT, "two pairs are not lower") if not any(lower) else (CONTINUE_TO_FIVE, "a pair is lower")
    before, after = [old for old, _ in pairs[:FULL_RUNS]], [new for _, new in pairs[:FULL_RUNS]]
    if any(not run.get("passed") for run in after):
        return REJECT, "an after run failed a required check"
    for measure in MEASURES:
        if any(number(run.get(measure)) is None for run in (*before, *after)):
            return NOT_MEASURED, f"{measure} is missing among five runs"
    for measure in MEASURES:
        median_after = median(run[measure] for run in after)
        if measure in claimed:
            if not median_after < min(run[measure] for run in before):
                return REJECT, f"median {measure} after is not below the lowest before"
        elif median_after > max(run[measure] for run in before):
            return REJECT, f"median {measure} after is above the highest before"
    return ACCEPT, "five runs"


def claim_verdict(case: Mapping[str, Any], claimed: Sequence[str]) -> dict[str, Any]:
    """Judge an improvement claim per host: accepted only when it holds on both hosts."""
    hosts = {}
    for host in HOSTS:
        verdict, step = claim_on_host(runs_of(case.get("before"), host), runs_of(case.get("after"), host), claimed)
        hosts[host] = {"verdict": verdict, "step": step}
    states = [item["verdict"] for item in hosts.values()]
    if REJECT in states:
        overall = REJECT
    elif NOT_MEASURED in states:
        overall = NOT_MEASURED
    elif SECOND_PAIR in states:
        overall = SECOND_PAIR
    elif CONTINUE_TO_FIVE in states:
        overall = CONTINUE_TO_FIVE
    else:
        overall = ACCEPT
    return {"case": case.get("id"), "claimed": list(claimed), "verdict": overall, "hosts": hosts}
