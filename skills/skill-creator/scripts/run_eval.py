#!/usr/bin/env python3
"""Run vendor-neutral trigger evaluations for a skill description.

Each query is sent to a configured model runner with a stable routing prompt.
This measures description quality independently of any host's private skill
discovery implementation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.model_runner import RunnerError, resolve_runner_command, run_model
from scripts.utils import parse_skill_md


def build_routing_prompt(query: str, skill_name: str, skill_description: str) -> str:
    """Build the same skill-selection task for every model runner."""
    return f"""Act as the skill router for an AI agent.

Decide whether the agent should load the optional skill below before answering
the user's request. Use only the skill name, description, and request. Load the
skill when its specialized instructions or workflow would materially help;
do not load it for superficial keyword overlap or a simple task the agent can
complete without the specialized workflow.

<skill_name>{skill_name}</skill_name>
<skill_description>{skill_description}</skill_description>
<user_request>{query}</user_request>

Return exactly one tag and no explanation:
<trigger>true</trigger>
or
<trigger>false</trigger>
"""


def parse_trigger_response(response: str) -> bool:
    """Parse a strict trigger decision, with JSON and bare-boolean fallbacks."""
    match = re.search(
        r"<trigger>\s*(true|false)\s*</trigger>", response, re.IGNORECASE
    )
    if match:
        return match.group(1).lower() == "true"

    stripped = response.strip()
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RunnerError(
            "Runner returned an invalid trigger decision; expected "
            "<trigger>true|false</trigger>"
        ) from exc

    if isinstance(parsed, dict) and isinstance(parsed.get("triggered"), bool):
        return parsed["triggered"]
    raise RunnerError(
        "Runner returned an invalid trigger decision; expected "
        "<trigger>true|false</trigger>"
    )


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    runner_command: str,
    model: str | None = None,
) -> bool:
    """Run one portable routing simulation and return its decision."""
    prompt = build_routing_prompt(query, skill_name, skill_description)
    response = run_model(prompt, runner_command, model=model, timeout=timeout)
    return parse_trigger_response(response)


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    num_workers: int,
    timeout: int,
    runner_command: str,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
) -> dict:
    """Run the full eval set and return results."""
    query_triggers: dict[int, list[bool | None]] = {
        index: [] for index in range(len(eval_set))
    }

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_index = {}
        for index, item in enumerate(eval_set):
            for _ in range(runs_per_query):
                future = executor.submit(
                    run_single_query,
                    item["query"],
                    skill_name,
                    description,
                    timeout,
                    runner_command,
                    model,
                )
                future_to_index[future] = index

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                query_triggers[index].append(future.result())
            except Exception as exc:
                print(f"Warning: query failed: {exc}", file=sys.stderr)
                query_triggers[index].append(None)

    results = []
    for index, item in enumerate(eval_set):
        triggers = query_triggers[index]
        successful = [value for value in triggers if value is not None]
        errors = len(triggers) - len(successful)
        trigger_rate = sum(successful) / len(successful) if successful else 0.0
        should_trigger = item["should_trigger"]
        did_pass = errors == 0 and (
            trigger_rate >= trigger_threshold
            if should_trigger
            else trigger_rate < trigger_threshold
        )
        results.append(
            {
                "query": item["query"],
                "should_trigger": should_trigger,
                "trigger_rate": trigger_rate,
                "triggers": sum(successful),
                "runs": len(triggers),
                "errors": errors,
                "pass": did_pass,
            }
        )

    passed = sum(1 for result in results if result["pass"])
    return {
        "skill_name": skill_name,
        "description": description,
        "evaluation_mode": "portable-routing-simulation",
        "results": results,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "runner_errors": sum(result["errors"] for result in results),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run portable trigger evaluation for a skill description"
    )
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument("--description", default=None, help="Override description to test")
    parser.add_argument("--num-workers", type=int, default=10, help="Number of parallel workers")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout per query in seconds")
    parser.add_argument("--runs-per-query", type=int, default=3, help="Number of runs per query")
    parser.add_argument("--trigger-threshold", type=float, default=0.5, help="Trigger rate threshold")
    parser.add_argument("--model", default=None, help="Optional model ID passed through {model}")
    parser.add_argument(
        "--runner-command",
        default=None,
        help=(
            "Command that reads a prompt from stdin and writes the model response "
            "to stdout; defaults to SKILL_CREATOR_RUNNER_COMMAND"
        ),
    )
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    args = parser.parse_args()

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)
    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    try:
        runner_command = resolve_runner_command(args.runner_command)
    except RunnerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    name, original_description, _ = parse_skill_md(skill_path)
    description = args.description or original_description

    if args.verbose:
        print(f"Evaluating: {description}", file=sys.stderr)

    output = run_eval(
        eval_set=eval_set,
        skill_name=name,
        description=description,
        num_workers=args.num_workers,
        timeout=args.timeout,
        runner_command=runner_command,
        runs_per_query=args.runs_per_query,
        trigger_threshold=args.trigger_threshold,
        model=args.model,
    )

    if args.verbose:
        summary = output["summary"]
        print(f"Results: {summary['passed']}/{summary['total']} passed", file=sys.stderr)
        for result in output["results"]:
            status = "PASS" if result["pass"] else "FAIL"
            rate = f"{result['triggers']}/{result['runs']}"
            error_note = f" errors={result['errors']}" if result["errors"] else ""
            print(
                f"  [{status}] rate={rate}{error_note} expected={result['should_trigger']}: "
                f"{result['query'][:70]}",
                file=sys.stderr,
            )

    print(json.dumps(output, indent=2))
    if output["summary"]["runner_errors"]:
        sys.exit(3)


if __name__ == "__main__":
    main()
