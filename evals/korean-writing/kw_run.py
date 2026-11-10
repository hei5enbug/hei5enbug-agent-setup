#!/usr/bin/env python3
"""Korean writing evaluation: writers, blind graders, seeded checks, and the decision rule.

  python3 evals/korean-writing/kw_run.py run --out <folder>
  python3 evals/korean-writing/kw_run.py seeded --out <folder>
  python3 evals/korean-writing/kw_run.py aggregate --out <folder>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kw_aggregate import format_report, summarize  # noqa: E402
from kw_jobs import prepare, run_campaign, spec_map  # noqa: E402
from kw_prompts import DEFAULT_SEED, load_cases  # noqa: E402
from kw_seeded import run_seeded  # noqa: E402

DEFAULT_WRITERS = ["codex:gpt-6.1-sol", "claude:claude-opus-5-5", "codex:gpt-6.1-terra", "claude:claude-fable-5-2"]
DEFAULT_GRADERS = ["codex:gpt-6-astra", "claude:claude-opus-5-5"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("run", "seeded", "aggregate"))
    parser.add_argument("--out", required=True, type=Path, help="output folder; an existing one is resumed")
    parser.add_argument("--writer", action="append", metavar="HOST:MODEL",
                        help="writer as codex:<model id> or claude:<model id>; repeat; default: the four candidates")
    parser.add_argument("--grader", action="append", metavar="HOST:MODEL",
                        help="grader, same form; repeat; default: codex:gpt-6-astra and claude:claude-opus-5-5")
    parser.add_argument("--tasks", help="comma-separated task ids; default: all")
    parser.add_argument("--runs", type=int, default=5, help="runs per task and writer (default 5)")
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--max-hours", type=float, default=3.0)
    parser.add_argument("--timeout", type=int, default=900, help="seconds per model call")
    parser.add_argument("--seed", default=DEFAULT_SEED, help="seed of the blind shuffle")
    return parser


def logger(out: Path):
    handle = (out / "run.log").open("a", encoding="utf-8")

    def log(message: str) -> None:
        line = time.strftime("%H:%M:%S ") + message
        print(line, flush=True)
        handle.write(line + "\n")
        handle.flush()
    return log


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = args.out.resolve()
    if args.command == "aggregate":
        summary = summarize(out)
        print(format_report(summary))
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    writers = args.writer or DEFAULT_WRITERS
    graders = args.grader or DEFAULT_GRADERS
    specs = spec_map(writers + graders)
    prepare(out)
    log = logger(out)
    if args.command == "seeded":
        records = run_seeded(out, specs, [spec.partition(":")[2] for spec in graders], args.parallel, args.timeout, log)
        return 0 if all(record["passed"] for record in records) else 1
    task_ids = args.tasks.split(",") if args.tasks else list(load_cases())
    summary = run_campaign(out, specs, [spec.partition(":")[2] for spec in writers],
                           [spec.partition(":")[2] for spec in graders], task_ids, args.runs,
                           args.parallel, args.max_hours, args.timeout, args.seed, log)
    log("DONE " + json.dumps(summary, ensure_ascii=False))
    print(format_report(summarize(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
