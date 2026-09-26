#!/usr/bin/env python3
"""
Aggregate individual run results into benchmark summary statistics.

Reads grading.json files from run directories and produces:
- run_summary with mean, stddev, min, max for each metric
- delta between with_skill and without_skill configurations

Usage:
    python aggregate_benchmark.py <benchmark_dir>

Example:
    python aggregate_benchmark.py benchmarks/2026-01-15T10-30-00/

The script supports two directory layouts:

    Workspace layout (from skill-builder iterations):
    <benchmark_dir>/
    └── eval-N/
        ├── with_skill/
        │   ├── run-1/grading.json
        │   └── run-2/grading.json
        └── without_skill/
            ├── run-1/grading.json
            └── run-2/grading.json

    Legacy layout (with runs/ subdirectory):
    <benchmark_dir>/
    └── runs/
        └── eval-N/
            ├── with_skill/
            │   └── run-1/grading.json
            └── without_skill/
                └── run-1/grading.json
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path


def calculate_stats(values: list[float]) -> dict:
    """Calculate mean, stddev, min, max for a list of values."""
    if not values:
        return {"mean": None, "stddev": None, "min": None, "max": None}

    n = len(values)
    mean = sum(values) / n

    if n > 1:
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0

    return {
        "mean": round(mean, 4),
        "stddev": round(stddev, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4)
    }


INCOMPLETE_KEY = "_incomplete"


def is_finite_non_negative_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def is_non_negative_integer(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def validate_grading(grading: object) -> str | None:
    """Return a schema error for a grading result, or None when it is usable."""
    if not isinstance(grading, dict):
        return "root must be a JSON object"
    summary = grading.get("summary")
    if not isinstance(summary, dict):
        return "summary must be a JSON object"
    counts = {}
    for field in ("passed", "failed", "total"):
        value = summary.get(field)
        if not is_non_negative_integer(value):
            return f"summary.{field} must be a non-negative integer"
        counts[field] = value
    if counts["total"] < 1:
        return "summary.total must be at least 1"
    if counts["passed"] + counts["failed"] != counts["total"]:
        return "summary.passed + summary.failed must equal summary.total"

    pass_rate = summary.get("pass_rate")
    if (
        isinstance(pass_rate, bool)
        or not isinstance(pass_rate, (int, float))
        or not math.isfinite(pass_rate)
        or not 0 <= pass_rate <= 1
    ):
        return "summary.pass_rate must be a finite number from 0 through 1"
    expected_rate = counts["passed"] / counts["total"]
    if not math.isclose(pass_rate, expected_rate, abs_tol=0.011):
        return "summary.pass_rate does not match summary counts"

    expectations = grading.get("expectations")
    if not isinstance(expectations, list) or len(expectations) != counts["total"]:
        return "expectations must contain one entry per summary item"
    passed_expectations = 0
    for index, expectation in enumerate(expectations):
        if not isinstance(expectation, dict):
            return f"expectations[{index}] must be a JSON object"
        if not isinstance(expectation.get("text"), str):
            return f"expectations[{index}].text must be a string"
        if not isinstance(expectation.get("passed"), bool):
            return f"expectations[{index}].passed must be a boolean"
        if not isinstance(expectation.get("evidence"), str):
            return f"expectations[{index}].evidence must be a string"
        passed_expectations += int(expectation["passed"])
    if passed_expectations != counts["passed"]:
        return "expectation verdicts do not match summary.passed"

    timing = grading.get("timing", {})
    if not isinstance(timing, dict):
        return "timing must be a JSON object"
    duration = timing.get("total_duration_seconds")
    if duration is not None and not is_finite_non_negative_number(duration):
        return "timing.total_duration_seconds must be a finite non-negative number"

    metrics = grading.get("execution_metrics", {})
    if not isinstance(metrics, dict):
        return "execution_metrics must be a JSON object"
    for field in ("total_tool_calls", "output_chars", "errors_encountered"):
        value = metrics.get(field)
        if value is not None and not is_non_negative_integer(value):
            return f"execution_metrics.{field} must be a non-negative integer"

    notes = grading.get("user_notes_summary", {})
    if not isinstance(notes, dict):
        return "user_notes_summary must be a JSON object"
    for field in ("uncertainties", "needs_review", "workarounds"):
        value = notes.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return f"user_notes_summary.{field} must be an array of strings"
    return None


def load_run_results(benchmark_dir: Path) -> dict:
    """
    Load all run results from a benchmark directory.

    Returns dict keyed by config name (e.g. "with_skill"/"without_skill",
    or "new_skill"/"old_skill"), each containing a list of run results.

    Runs whose grading.json is missing or unreadable are not silently
    skipped: they are collected under the reserved key ``INCOMPLETE_KEY`` so
    that aggregation can exclude them from averages and comparisons.
    """
    # Support both layouts: eval dirs directly under benchmark_dir, or under runs/
    runs_dir = benchmark_dir / "runs"
    if runs_dir.exists():
        search_dir = runs_dir
    elif any(path.is_dir() for path in benchmark_dir.iterdir()):
        search_dir = benchmark_dir
    else:
        print(f"No eval directories found in {benchmark_dir} or {benchmark_dir / 'runs'}")
        return {}

    results: dict[str, list] = {}
    incomplete: list[dict] = []

    eval_dirs = sorted(
        path
        for path in search_dir.iterdir()
        if path.is_dir()
        and (path.name.startswith("eval-") or (path / "eval_metadata.json").exists())
    )
    if not eval_dirs:
        print(f"No eval directories found in {search_dir}")
        return {}

    for eval_idx, eval_dir in enumerate(eval_dirs):
        metadata_path = eval_dir / "eval_metadata.json"
        eval_name = eval_dir.name
        if metadata_path.exists():
            try:
                with open(metadata_path) as mf:
                    metadata = json.load(mf)
                if not isinstance(metadata, dict):
                    raise ValueError("root must be a JSON object")
                candidate_id = metadata.get("eval_id", eval_idx)
                candidate_name = metadata.get("eval_name", eval_name)
                if isinstance(candidate_id, bool) or not isinstance(candidate_id, int):
                    raise ValueError("eval_id must be an integer")
                if not isinstance(candidate_name, str):
                    raise ValueError("eval_name must be a string")
                eval_id = candidate_id
                eval_name = candidate_name
            except (json.JSONDecodeError, OSError, UnicodeError, ValueError) as error:
                print(f"Warning: Invalid eval metadata in {metadata_path}: {error}")
                eval_id = eval_idx
        else:
            try:
                eval_id = int(eval_dir.name.split("-")[1])
            except ValueError:
                eval_id = eval_idx

        # Discover config directories dynamically rather than hardcoding names
        def config_order(path: Path) -> tuple[int, str]:
            priority = {
                "with_skill": 0,
                "new_skill": 0,
                "old_skill": 1,
                "without_skill": 1,
            }
            return priority.get(path.name, 2), path.name

        for config_dir in sorted(eval_dir.iterdir(), key=config_order):
            if not config_dir.is_dir():
                continue
            run_dirs = sorted(config_dir.glob("run-*"))
            if not run_dirs and (config_dir / "grading.json").exists():
                run_dirs = [config_dir]
            if not run_dirs:
                continue
            config = config_dir.name
            if config not in results:
                results[config] = []

            for direct_index, run_dir in enumerate(run_dirs, start=1):
                if run_dir == config_dir:
                    run_number = direct_index
                else:
                    try:
                        run_number = int(run_dir.name.split("-")[1])
                    except (IndexError, ValueError):
                        run_number = direct_index
                grading_file = run_dir / "grading.json"

                if not grading_file.exists():
                    print(f"Warning: grading.json not found in {run_dir}")
                    incomplete.append({
                        "eval_id": eval_id,
                        "eval_name": eval_name,
                        "configuration": config,
                        "run_number": run_number,
                        "reason": "grading.json not found",
                    })
                    continue

                try:
                    with open(grading_file) as f:
                        grading = json.load(f)
                except (json.JSONDecodeError, OSError, UnicodeError) as e:
                    print(f"Warning: Invalid JSON in {grading_file}: {e}")
                    incomplete.append({
                        "eval_id": eval_id,
                        "eval_name": eval_name,
                        "configuration": config,
                        "run_number": run_number,
                        "reason": f"grading.json unreadable: {e}",
                    })
                    continue

                grading_problem = validate_grading(grading)
                if grading_problem is not None:
                    print(f"Warning: Invalid grading schema in {grading_file}: {grading_problem}")
                    incomplete.append({
                        "eval_id": eval_id,
                        "eval_name": eval_name,
                        "configuration": config,
                        "run_number": run_number,
                        "reason": f"grading.json invalid: {grading_problem}",
                    })
                    continue

                # Extract metrics
                result = {
                    "eval_id": eval_id,
                    "eval_name": eval_name,
                    "run_number": run_number,
                    "pass_rate": grading["summary"]["pass_rate"],
                    "passed": grading["summary"]["passed"],
                    "failed": grading["summary"]["failed"],
                    "total": grading["summary"]["total"],
                }

                # Timing: grading.json first, then sibling timing.json.
                # Tokens come only from timing.json's total_tokens; when it is
                # absent the value stays null. Character counts are a different
                # unit and are kept in their own field.
                timing = grading.get("timing", {})
                result["time_seconds"] = timing.get("total_duration_seconds")
                result["tokens"] = None
                timing_file = run_dir / "timing.json"
                if timing_file.exists():
                    try:
                        with open(timing_file) as tf:
                            timing_data = json.load(tf)
                    except (json.JSONDecodeError, OSError, UnicodeError):
                        timing_data = {}
                    if not isinstance(timing_data, dict):
                        timing_data = {}
                    if result["time_seconds"] is None:
                        duration = timing_data.get("total_duration_seconds")
                        if is_finite_non_negative_number(duration):
                            result["time_seconds"] = duration
                    tokens = timing_data.get("total_tokens")
                    if is_non_negative_integer(tokens):
                        result["tokens"] = tokens

                # Extract metrics if available
                metrics = grading.get("execution_metrics", {})
                result["tool_calls"] = metrics.get("total_tool_calls")
                result["output_chars"] = metrics.get("output_chars")
                result["errors"] = metrics.get("errors_encountered", 0)

                # Extract expectations — viewer requires fields: text, passed, evidence
                result["expectations"] = grading["expectations"]

                # Extract notes from user_notes_summary
                notes_summary = grading.get("user_notes_summary", {})
                notes = []
                notes.extend(notes_summary.get("uncertainties", []))
                notes.extend(notes_summary.get("needs_review", []))
                notes.extend(notes_summary.get("workarounds", []))
                result["notes"] = notes

                results[config].append(result)

    if incomplete:
        results[INCOMPLETE_KEY] = incomplete
    return results


def aggregate_results(results: dict) -> dict:
    """
    Aggregate run results into summary statistics.

    Returns run_summary with stats for each configuration and delta.
    Incomplete runs are never averaged. A configuration without any complete
    run reports null statistics instead of zeros. Deltas compare only the
    eval_ids that both configurations completed; when there is no shared
    eval_id the delta is null.
    """
    run_summary = {}
    configs = [key for key in results.keys() if key != INCOMPLETE_KEY]

    for config in configs:
        runs = results.get(config, [])

        pass_rates = [r["pass_rate"] for r in runs]
        times = [r["time_seconds"] for r in runs if r["time_seconds"] is not None]
        tokens = [r["tokens"] for r in runs if r.get("tokens") is not None]

        run_summary[config] = {
            "pass_rate": calculate_stats(pass_rates),
            "time_seconds": calculate_stats(times),
            "tokens": calculate_stats(tokens)
        }

    # Delta between the first two configs over the eval_ids they share
    delta_values = {"pass_rate": None, "time_seconds": None, "tokens": None}
    if len(configs) >= 2:
        primary_runs = results.get(configs[0], [])
        baseline_runs = results.get(configs[1], [])
        shared = {r["eval_id"] for r in primary_runs} & {r["eval_id"] for r in baseline_runs}

        def mean_of(runs: list, metric: str, metric_ids: set) -> float | None:
            values = [r[metric] for r in runs if r["eval_id"] in metric_ids and r.get(metric) is not None]
            return sum(values) / len(values) if values else None

        def delta(metric: str, precision: int) -> str | None:
            metric_ids = (
                {r["eval_id"] for r in primary_runs if r.get(metric) is not None}
                & {r["eval_id"] for r in baseline_runs if r.get(metric) is not None}
            )
            primary_value = mean_of(primary_runs, metric, metric_ids)
            baseline_value = mean_of(baseline_runs, metric, metric_ids)
            if primary_value is None or baseline_value is None:
                return None
            return f"{primary_value - baseline_value:+.{precision}f}"

        if shared:
            delta_values = {
                "pass_rate": delta("pass_rate", 2),
                "time_seconds": delta("time_seconds", 1),
                "tokens": delta("tokens", 0),
            }
        delta_values["shared_eval_ids"] = sorted(shared)

    run_summary["delta"] = delta_values

    return run_summary


def generate_benchmark(
    benchmark_dir: Path,
    skill_name: str = "",
    skill_path: str = "",
    executor_model: str | None = None,
    analyzer_model: str | None = None,
) -> dict:
    """
    Generate complete benchmark.json from run results.
    """
    results = load_run_results(benchmark_dir)
    incomplete = results.get(INCOMPLETE_KEY, [])
    complete = {key: value for key, value in results.items() if key != INCOMPLETE_KEY}
    run_summary = aggregate_results(complete)

    # Build runs array for benchmark.json
    runs = []
    for config in complete:
        for result in complete[config]:
            runs.append({
                "eval_id": result["eval_id"],
                "eval_name": result["eval_name"],
                "configuration": config,
                "run_number": result["run_number"],
                "result": {
                    "pass_rate": result["pass_rate"],
                    "passed": result["passed"],
                    "failed": result["failed"],
                    "total": result["total"],
                    "time_seconds": result["time_seconds"],
                    "tokens": result.get("tokens"),
                    "output_chars": result.get("output_chars"),
                    "tool_calls": result.get("tool_calls"),
                    "errors": result.get("errors", 0)
                },
                "expectations": result["expectations"],
                "notes": result["notes"]
            })

    # Determine eval IDs from results
    eval_ids = sorted(set(
        r["eval_id"]
        for config in complete.values()
        for r in config
    ))

    benchmark = {
        "metadata": {
            "skill_name": skill_name or "<skill-name>",
            "skill_path": skill_path or "<path/to/skill>",
            "executor_model": executor_model,
            "analyzer_model": analyzer_model,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "evals_run": eval_ids,
            "runs_per_configuration": max(
                (len(config_runs) for config_runs in complete.values()),
                default=0,
            ) // max(len(eval_ids), 1)
        },
        "runs": runs,
        "incomplete": incomplete,
        "run_summary": run_summary,
        "notes": []  # To be filled by analyzer
    }

    return benchmark


def generate_markdown(benchmark: dict) -> str:
    """Generate human-readable benchmark.md from benchmark data."""
    metadata = benchmark["metadata"]
    run_summary = benchmark["run_summary"]

    # Determine config names (excluding "delta")
    configs = [k for k in run_summary if k != "delta"]
    config_a = configs[0] if len(configs) >= 1 else "config_a"
    config_b = configs[1] if len(configs) >= 2 else "config_b"
    label_a = config_a.replace("_", " ").title()
    label_b = config_b.replace("_", " ").title()

    lines = [
        f"# Skill Benchmark: {metadata['skill_name']}",
        "",
        f"**Model**: {metadata.get('executor_model') or 'N/A'}",
        f"**Date**: {metadata['timestamp']}",
        f"**Evals**: {', '.join(map(str, metadata['evals_run']))} ({metadata['runs_per_configuration']} runs each per configuration)",
        "",
        "## Summary",
        "",
        f"| Metric | {label_a} | {label_b} | Delta |",
        "|--------|------------|---------------|-------|",
    ]

    a_summary = run_summary.get(config_a, {})
    b_summary = run_summary.get(config_b, {})
    delta = run_summary.get("delta", {})

    def format_stat(stats: dict, scale: float = 1.0, decimals: int = 1) -> str:
        mean = stats.get("mean")
        stddev = stats.get("stddev")
        if mean is None or stddev is None:
            return "N/A"
        return f"{mean * scale:.{decimals}f} ± {stddev * scale:.{decimals}f}"

    def add_suffix(value: str, suffix: str) -> str:
        return value if value == "N/A" else value + suffix

    # Format pass rate
    a_pr = a_summary.get("pass_rate", {})
    b_pr = b_summary.get("pass_rate", {})
    lines.append(f"| Pass Rate | {add_suffix(format_stat(a_pr, 100, 0), '%')} | {add_suffix(format_stat(b_pr, 100, 0), '%')} | {delta.get('pass_rate') or '—'} |")

    # Format time
    a_time = a_summary.get("time_seconds", {})
    b_time = b_summary.get("time_seconds", {})
    lines.append(f"| Time | {add_suffix(format_stat(a_time), 's')} | {add_suffix(format_stat(b_time), 's')} | {delta.get('time_seconds') or '—'} |")

    # Format tokens
    a_tokens = a_summary.get("tokens", {})
    b_tokens = b_summary.get("tokens", {})
    lines.append(f"| Tokens | {format_stat(a_tokens, 1, 0)} | {format_stat(b_tokens, 1, 0)} | {delta.get('tokens') or '—'} |")

    incomplete = benchmark.get("incomplete") or []
    if incomplete:
        lines.extend(["", "## Incomplete Runs", ""])
        lines.append("These runs have no usable grading.json and are excluded from every average and delta.")
        lines.append("")
        for item in incomplete:
            lines.append(
                f"- eval {item['eval_id']} / {item['configuration']} / run {item['run_number']}: {item['reason']}"
            )

    # Notes section
    if benchmark.get("notes"):
        lines.extend([
            "",
            "## Notes",
            ""
        ])
        for note in benchmark["notes"]:
            lines.append(f"- {note}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate benchmark run results into summary statistics"
    )
    parser.add_argument(
        "benchmark_dir",
        type=Path,
        help="Path to the benchmark directory"
    )
    parser.add_argument(
        "--skill-name",
        default="",
        help="Name of the skill being benchmarked"
    )
    parser.add_argument(
        "--skill-path",
        default="",
        help="Path to the skill being benchmarked"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output path for benchmark.json (default: <benchmark_dir>/benchmark.json)"
    )
    parser.add_argument("--executor-model", default=None, help="Executor model identifier")
    parser.add_argument("--analyzer-model", default=None, help="Analyzer model identifier")

    args = parser.parse_args()

    if not args.benchmark_dir.exists():
        print(f"Directory not found: {args.benchmark_dir}")
        sys.exit(1)

    # Generate benchmark
    benchmark = generate_benchmark(
        args.benchmark_dir,
        args.skill_name,
        args.skill_path,
        args.executor_model,
        args.analyzer_model,
    )

    # Determine output paths
    output_json = args.output or (args.benchmark_dir / "benchmark.json")
    output_md = output_json.with_suffix(".md")

    # Write benchmark.json
    with open(output_json, "w") as f:
        json.dump(benchmark, f, indent=2)
    print(f"Generated: {output_json}")

    # Write benchmark.md
    markdown = generate_markdown(benchmark)
    with open(output_md, "w") as f:
        f.write(markdown)
    print(f"Generated: {output_md}")

    # Print summary
    run_summary = benchmark["run_summary"]
    configs = [k for k in run_summary if k != "delta"]
    delta = run_summary.get("delta", {})

    print(f"\nSummary:")
    for config in configs:
        pr = run_summary[config]["pass_rate"]["mean"]
        label = config.replace("_", " ").title()
        print(f"  {label}: {'N/A' if pr is None else f'{pr*100:.1f}%'} pass rate")
    if benchmark.get("incomplete"):
        print(f"  Incomplete runs: {len(benchmark['incomplete'])} (excluded)")
    print(f"  Delta:         {delta.get('pass_rate') or '—'}")


if __name__ == "__main__":
    main()
