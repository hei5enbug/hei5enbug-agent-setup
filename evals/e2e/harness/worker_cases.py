"""The worker-model case set: its criteria, the recorded results of Claude Sonnet and Claude Opus, and the rule that
decides which criteria count as hard work.

A case is a task file with `"worker_case": true` and a `"worker_criteria"` list. The results file holds one pass or fail
per model and case, the model and effort read from the run's host records, each model's total cost over all attempts, and
its cost per solved case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import records
from .matrix import read_json

CASES_DIR = Path(__file__).resolve().parent.parent / "worker-cases"
RESULTS_PATH = CASES_DIR / "results.json"
TASKS_DIR = Path(__file__).resolve().parent.parent / "tasks"
ISSUE = 87
CRITERIA = ("components", "public-contract", "security", "concurrency", "hook-guard")
CRITERION_PHRASES = {
    "components": "several components",
    "public-contract": "a public contract",
    "security": "security",
    "concurrency": "concurrency",
    "hook-guard": "a hook or guard change",
}
MODELS = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
EFFORT = "high"
MAX_CASES = 10
CASE_KEYS = ("passed", "model", "effort", "cost_usd")
TOTAL_KEYS = ("cost_usd", "solved", "cost_per_solved_task")
PENDING = {"issue": ISSUE, "measured": False, "models": {}, "cases": {}, "totals": {}}


class WorkerCaseError(ValueError):
    pass


def load_cases(tasks_dir: Path = TASKS_DIR) -> dict[str, list[str]]:
    """Each worker case's id and its criteria, from the task files."""
    found: dict[str, list[str]] = {}
    for path in sorted(tasks_dir.glob("T*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        if task.get("worker_case"):
            found[str(task["id"])] = [str(item) for item in task.get("worker_criteria", [])]
    return found


def case_problems(cases: Mapping[str, Sequence[str]]) -> list[str]:
    problems = []
    if not cases or len(cases) > MAX_CASES:
        problems.append(f"the set needs 1 to {MAX_CASES} cases, found {len(cases)}")
    for task, criteria in cases.items():
        unknown = sorted(set(criteria) - set(CRITERIA))
        if not criteria or unknown:
            problems.append(f"{task}: criteria must be a non-empty subset of {', '.join(CRITERIA)}; unknown {unknown}")
    for criterion in CRITERIA:
        if not any(criterion in criteria for criteria in cases.values()):
            problems.append(f"no case carries the criterion {criterion}")
    return problems


def passes(results: Mapping[str, Any], task: str, model: str) -> bool:
    entry = (results.get("cases") or {}).get(task, {}).get(model)
    return bool(isinstance(entry, Mapping) and entry.get("passed") is True)


def hard_criteria(results: Mapping[str, Any], cases: Mapping[str, Sequence[str]]) -> list[str]:
    """The criteria on which Opus passes strictly more of the cases that carry it than Sonnet does."""
    if not results.get("measured"):
        return []
    hard = []
    for criterion in CRITERIA:
        carried = [task for task, criteria in cases.items() if criterion in criteria]
        if sum(passes(results, task, "opus") for task in carried) > sum(passes(results, task, "sonnet") for task in carried):
            hard.append(criterion)
    return hard


def number_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0)


def results_problems(results: Any, cases: Mapping[str, Sequence[str]]) -> list[str]:
    """Problems of a results file; a file that records no measurement yet is valid only in its pending form."""
    if not isinstance(results, Mapping) or results.get("issue") != ISSUE or not isinstance(results.get("measured"), bool):
        return ["the file needs issue 87 and a boolean measured"]
    if not results["measured"]:
        return [] if dict(results) == PENDING else ["an unmeasured file holds nothing but the pending form"]
    problems = []
    models = results.get("models")
    if models != {name: {"model": model, "effort": EFFORT} for name, model in MODELS.items()}:
        problems.append("models must name both pinned models at high")
    recorded = results.get("cases")
    if not isinstance(recorded, Mapping) or set(recorded) != set(cases):
        return problems + ["cases must hold exactly the worker case ids"]
    for task in cases:
        for name, model in MODELS.items():
            entry = recorded[task].get(name) if isinstance(recorded[task], Mapping) else None
            if not isinstance(entry, Mapping) or set(entry) != set(CASE_KEYS) or not isinstance(entry["passed"], bool):
                problems.append(f"{task} {name}: needs {', '.join(CASE_KEYS)} with a boolean passed")
            elif (entry["model"], entry["effort"]) != (model, EFFORT) or not number_or_none(entry["cost_usd"]):
                problems.append(f"{task} {name}: model, effort, or cost does not match the host records' pins")
    totals = results.get("totals")
    if not isinstance(totals, Mapping) or set(totals) != set(MODELS):
        return problems + ["totals must hold one entry per model"]
    for name in MODELS:
        entry = totals[name]
        if not isinstance(entry, Mapping) or set(entry) != set(TOTAL_KEYS):
            problems.append(f"totals {name}: needs {', '.join(TOTAL_KEYS)}")
            continue
        solved = sum(passes(results, task, name) for task in cases)
        costs = [recorded[task][name]["cost_usd"] for task in cases if isinstance(recorded[task].get(name), Mapping)]
        total = None if any(cost is None for cost in costs) else round(sum(costs), 6)
        per_task = round(total / solved, 6) if solved and total is not None else None
        if (entry["solved"], entry["cost_usd"], entry["cost_per_solved_task"]) != (solved, total, per_task):
            problems.append(f"totals {name}: solved, cost, or cost per solved task disagrees with the cases")
    for text in records.strings(results):
        if records.LOCAL_PATH.search(text):
            problems.append("the file holds a local path")
            break
    return problems


def check_results(results: Any, cases: Mapping[str, Sequence[str]]) -> None:
    problems = results_problems(results, cases)
    if problems:
        raise WorkerCaseError("; ".join(problems))


def build_results(runs: Sequence[Mapping[str, Any]], variants: Mapping[str, str], cases: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """The results of one campaign: `variants` maps `sonnet` and `opus` to a variant name. Every case needs one finished,
    graded Claude Code run per model whose host records show the pinned model and effort and no role but the main session."""
    chosen: dict[tuple[str, str], Mapping[str, Any]] = {}
    for run in runs:
        if run["host"] != "claude" or run["case"] not in cases:
            continue
        for name, variant in variants.items():
            if run["variant"] == variant:
                if (run["case"], name) in chosen:
                    raise WorkerCaseError(f"{run['case']} has more than one run of {variant}; each model runs once per case")
                chosen[(run["case"], name)] = run
    recorded: dict[str, dict[str, Any]] = {}
    for task in cases:
        recorded[task] = {}
        for name, model in MODELS.items():
            run = chosen.get((task, name))
            entry = run.get("entry") if run else None
            if not entry:
                raise WorkerCaseError(f"{task} has no finished, graded run of {variants[name]}")
            roles = entry["models"]
            if set(roles) != {records.MAIN_ROLE}:
                raise WorkerCaseError(f"{task} {variants[name]} started other roles: {sorted(set(roles) - {records.MAIN_ROLE})}")
            main = roles[records.MAIN_ROLE]
            if (main["model"], main["effort"]) != (model, EFFORT):
                raise WorkerCaseError(f"{task} {variants[name]} ran {main['model']} at {main['effort']}, not {model} at {EFFORT}")
            recorded[task][name] = {"passed": bool(run["summary"]["passed"]), "model": model, "effort": EFFORT,
                                    "cost_usd": run["summary"]["cost_usd"]}
    totals = {}
    for name in MODELS:
        costs = [recorded[task][name]["cost_usd"] for task in cases]
        total = None if any(cost is None for cost in costs) else round(sum(costs), 6)
        solved = sum(recorded[task][name]["passed"] for task in cases)
        totals[name] = {"cost_usd": total, "solved": solved,
                        "cost_per_solved_task": round(total / solved, 6) if solved and total is not None else None}
    results = {"issue": ISSUE, "measured": True,
               "models": {name: {"model": model, "effort": EFFORT} for name, model in MODELS.items()},
               "cases": recorded, "totals": totals}
    check_results(results, cases)
    return results


def write_results(results: Mapping[str, Any], path: Path = RESULTS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return path


def read_results(path: Path = RESULTS_PATH) -> Any:
    return read_json(path, None)
