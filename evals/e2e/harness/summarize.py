"""Campaign summary tables: per-task and overall statistics, status counts, and variant comparison."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import FINISHED_STATUSES
from .matrix import campaign_dir, read_json

MISSING = "-"


def nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    """Nearest-rank percentile: the value at rank ceil(p/100 * n) of the sorted sample."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(math.ceil(percentile / 100 * len(ordered)), 1)
    return ordered[min(rank, len(ordered)) - 1]


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def claude_cost(metrics: dict[str, Any] | None) -> float | None:
    """One run's Claude USD: the stream total plus the separate role runner processes, else the list cost alone.

    The list cost already holds the runner and subagent tokens; the stream total holds the subagents but not the runners."""
    cost = (metrics or {}).get("cost") or {}
    total = number(cost.get("claude_total_cost_usd"))
    if total is not None:
        return total + (number(cost.get("claude_runner_list_cost_usd")) or 0.0)
    return number(cost.get("claude_list_cost_usd"))


def run_spend(metrics: dict[str, Any] | None) -> tuple[float, float]:
    """(Claude USD, Codex estimated USD) one run's metrics report; 0 stands in for a missing figure."""
    codex = number(((metrics or {}).get("cost") or {}).get("codex_list_cost_usd_estimate"))
    return (claude_cost(metrics) or 0.0, codex or 0.0)


def attempts_spend(run_json: Path, rep: Any) -> tuple[float, float]:
    """Spend of the archived earlier attempts of one run: results/<task>/<variant>/attempts/rep<k>/<n>/metrics.json."""
    folder = run_json.parent.parent / "attempts" / f"rep{rep}"
    spent = [run_spend(read_json(item / "metrics.json", None)) for item in sorted(folder.glob("*")) if item.is_dir()]
    return sum(item[0] for item in spent), sum(item[1] for item in spent)


def load_results(run_root: Path, campaign: str) -> list[dict[str, Any]]:
    """Every run's metrics (with its status), from results/<task>/<variant>/rep<k>/metrics.json or run.json.

    Each row also carries `spend_claude` and `spend_codex`: the final attempt plus every archived attempt."""
    rows: list[dict[str, Any]] = []
    for run_json in sorted(campaign_dir(run_root, campaign).glob("results/*/*/rep*/run.json")):
        run = read_json(run_json, {})
        metrics = read_json(run_json.with_name("metrics.json"), None)
        final, archived = run_spend(metrics), attempts_spend(run_json, run.get("rep"))
        rows.append({**(metrics or {}), "run_id": run.get("run_id"), "task": run.get("task"), "variant": run.get("variant"),
                     "rep": run.get("rep"), "status": run.get("status"), "has_metrics": metrics is not None,
                     "spend_claude": final[0] + archived[0], "spend_codex": final[1] + archived[1]})
    return rows


def graded(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("status") in FINISHED_STATUSES and row.get("has_metrics") and not row.get("grade_error")]


def fmt(value: float | None, digits: int = 2) -> str:
    return MISSING if value is None else f"{value:.{digits}f}"


def pct(values: Sequence[float], percentile: float, digits: int = 2) -> str:
    value = nearest_rank(values, percentile)
    return MISSING if value is None else f"{value:.{digits}f}"


def band(values: Sequence[float], digits: int) -> str:
    return f"{pct(values, 50, digits)} / {pct(values, 95, digits)} (n={len(values)})"


def present(rows: list[dict[str, Any]], getter: Callable[[dict[str, Any]], Any]) -> list[float]:
    values = [getter(row) for row in rows]
    return [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]


def total_calls(row: dict[str, Any]) -> int:
    return sum(((row.get("tool_calls_by_tool") or {}).get("total") or {}).values())


def runner_total(row: dict[str, Any]) -> int:
    return sum(sum(counts.values()) for counts in (row.get("role_runner_calls") or {}).values())


def spend_cells(rows: list[dict[str, Any]], successes: int) -> list[str]:
    claude = sum(float(r.get("spend_claude") or 0.0) for r in rows)
    codex = sum(float(r.get("spend_codex") or 0.0) for r in rows)
    per_success = (claude + codex) / successes if successes else None
    return [fmt(claude, 3), fmt(codex, 3), fmt(per_success, 3)]


def stats_row(rows: list[dict[str, Any]], spend_rows: list[dict[str, Any]] | None = None) -> list[str]:
    """Statistics of the graded final attempts; spend covers `spend_rows` (default `rows`) with archived attempts."""
    n = len(rows)
    claude = present(rows, claude_cost)
    codex = present(rows, lambda r: (r.get("cost") or {}).get("codex_list_cost_usd_estimate"))
    wall = present(rows, lambda r: r.get("wall_seconds"))
    turns = present(rows, lambda r: r.get("num_turns"))
    calls = [float(total_calls(r)) for r in rows]
    success = sum(1 for r in rows if r.get("success"))
    handoff = sum((r.get("handoff") or {}).get("missing", 0) for r in rows)
    return [
        str(n), f"{success}/{n}" if n else MISSING, fmt(mean(present(rows, lambda r: r.get("correctness")))),
        fmt(mean(present(rows, lambda r: r.get("test_pass_rate")))),
        band(claude, 3), band(codex, 3), band(wall, 0),
        f"{pct(turns, 50, 0)} (n={len(turns)})", f"{pct(calls, 50, 0)} (n={len(calls)})",
        fmt(mean([float(sum((r.get("subagent_launches_by_type") or {}).values())) for r in rows])),
        fmt(mean([float(runner_total(r)) for r in rows])), fmt(mean(present(rows, lambda r: r.get("approval_prompts")))),
        fmt(mean([float((r.get("retries") or {}).get("total", 0)) for r in rows])), str(handoff),
        *spend_cells(rows if spend_rows is None else spend_rows, success),
    ]


HEADER = [
    "n", "success", "correctness mean", "test pass mean", "Claude cost USD p50/p95", "Codex est. USD p50/p95",
    "wall s p50/p95", "turns p50", "tool calls p50", "subagents mean", "role_runner mean", "approvals mean",
    "retries mean", "handoff misses", "spend incl. attempts Claude USD", "spend incl. attempts Codex est. USD",
    "cost per success USD",
]


def table(first: str, rows: list[list[str]]) -> list[str]:
    head = [first, *HEADER]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key))].append(row)
    return dict(sorted(groups.items()))


def variant_section(variant: str, rows: list[dict[str, Any]]) -> list[str]:
    done, all_by_task = graded(rows), group_by(rows, "task")
    per_task = [[task, *stats_row(items, all_by_task.get(task, items))] for task, items in group_by(done, "task").items()]
    lines = [f"### Variant {variant}", ""]
    lines += table("task", per_task) if per_task else ["No graded runs."]
    lines += ["", "Overall", ""] + table("variant", [[variant, *stats_row(done, rows)]])
    notes = ("Statistics describe the final attempt of each graded run; a run whose grading failed is not graded. "
             "Spend adds every run of the task or variant, including archived earlier attempts, runs that did not "
             "finish, and runs whose grading failed; cost per success is that spend, "
             "Claude plus Codex estimate, divided by the successes.")
    return lines + ["", notes, ""]


def status_counts(rows: list[dict[str, Any]]) -> str:
    counts = Counter(row.get("status") for row in rows)
    return ", ".join(f"{name}={counts.get(name, 0)}" for name in ("complete", "timed_out", "infra_failed", "usage_limited"))


def success_by_rep(rows: list[dict[str, Any]]) -> dict[int, bool]:
    return {int(r["rep"]): bool(r.get("success")) for r in graded(rows) if r.get("rep") is not None}


def compare(rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]], names: tuple[str, str]) -> list[str]:
    a_name, b_name = names
    lines = [f"### Comparison {a_name} vs {b_name}", "",
             f"| task | pairs | {a_name} pass / {b_name} fail | {a_name} fail / {b_name} pass | majority flip | "
             f"cost p50 delta | wall p50 delta | turns p50 delta | tool calls p50 delta |", "|---|---|---|---|---|---|---|---|---|"]
    a_tasks, b_tasks = group_by(rows_a, "task"), group_by(rows_b, "task")
    for task in sorted(set(a_tasks) | set(b_tasks)):
        a_rows, b_rows = graded(a_tasks.get(task, [])), graded(b_tasks.get(task, []))
        a_success, b_success = success_by_rep(a_rows), success_by_rep(b_rows)
        shared = sorted(set(a_success) & set(b_success))
        a_only = sum(1 for k in shared if a_success[k] and not b_success[k])
        b_only = sum(1 for k in shared if b_success[k] and not a_success[k])
        flip = _majority(a_success) != _majority(b_success) if a_success and b_success else None
        lines.append("| " + " | ".join([
            task, str(len(shared)), str(a_only), str(b_only), MISSING if flip is None else ("yes" if flip else "no"),
            delta(a_rows, b_rows, claude_cost, 3),
            delta(a_rows, b_rows, lambda r: r.get("wall_seconds"), 0),
            delta(a_rows, b_rows, lambda r: r.get("num_turns"), 0), delta(a_rows, b_rows, total_calls, 0),
        ]) + " |")
    return lines + ["", "Majority: a variant passes a task when more than half of its graded reps succeed. Deltas are "
                    f"{b_name} minus {a_name} on nearest-rank p50.", ""]


def _majority(success: dict[int, bool]) -> bool:
    return sum(success.values()) * 2 > len(success)


def delta(a_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]], getter: Callable[[dict[str, Any]], Any], digits: int) -> str:
    a_value, b_value = nearest_rank(present(a_rows, getter), 50), nearest_rank(present(b_rows, getter), 50)
    if a_value is None or b_value is None:
        return MISSING
    return f"{b_value - a_value:+.{digits}f}"


def summarize(run_root: Path, campaign: str, compare_pair: tuple[str, str] | None = None) -> str:
    rows = load_results(run_root, campaign)
    lines = [f"## Campaign {campaign}", "", f"Runs: {len(rows)} ({status_counts(rows)}). "
             "n is the number of graded runs behind every statistic; percentiles use the nearest-rank method.", ""]
    variants = group_by(rows, "variant")
    for name, items in variants.items():
        lines += variant_section(name, items)
    if compare_pair:
        lines += compare(variants.get(compare_pair[0], []), variants.get(compare_pair[1], []), compare_pair)
    return "\n".join(lines).rstrip() + "\n"
