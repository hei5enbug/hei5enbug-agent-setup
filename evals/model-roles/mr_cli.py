#!/usr/bin/env python3
"""Seed, grade, and record the Fable-versus-Opus comparison cases. Starting a candidate run is the only paid step."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import mr_cases  # noqa: E402
import mr_evidence  # noqa: E402
import mr_grading  # noqa: E402
import mr_pins  # noqa: E402
import mr_record  # noqa: E402

REPO_ROOT = HERE.parents[1]
RECORD_PATH = HERE / "record.json"
ISSUE = 84
OPPONENT_COPY_PATHS = ("skills/tiki-taka/run-opponent.sh", "skills/tiki-taka/scripts", "config/model-registry.json")


def parse_candidate(value: str) -> tuple[str, str]:
    model, _, effort = value.partition("/")
    if (model, effort) not in mr_record.CANDIDATES:
        raise argparse.ArgumentTypeError(f"{value!r} is not one of {[mr_record.candidate_label(*c) for c in mr_record.CANDIDATES]}")
    return model, effort


def run_source(args: argparse.Namespace) -> dict[str, str]:
    if args.status_line:
        return mr_evidence.status_session(Path(args.status_line).read_text(encoding="utf-8"))
    return mr_evidence.state_session(Path(args.state_dir))


def result_entry(
    case_id: str, candidate: tuple[str, str], grade: dict[str, Any], evidence: dict[str, Any],
    attempts: int, earlier_cost: float, earlier_wall: float,
) -> dict[str, Any]:
    model, effort = candidate
    return {
        "case": case_id, "model": model, "effort": effort, "passed": bool(grade["pass"]),
        "host_model": evidence["host_model"], "host_effort": evidence["host_effort"],
        "cost_usd": round(evidence["cost_usd"] + earlier_cost, 6),
        "wall_seconds": round(evidence["wall_seconds"] + earlier_wall, 3), "attempts": attempts,
    }


def command_seed(args: argparse.Namespace) -> int:
    print(json.dumps(mr_cases.seed(args.case, Path(args.out))))
    return 0


def command_grade(args: argparse.Namespace) -> int:
    grade = mr_grading.grade(mr_cases.load_cases()[args.case], Path(args.answer).read_text(encoding="utf-8"))
    print(json.dumps(grade))
    return 0 if grade["pass"] else 1


def command_evidence(args: argparse.Namespace) -> int:
    print(json.dumps(mr_evidence.run_evidence(run_source(args)["session"])))
    return 0


def command_result(args: argparse.Namespace) -> int:
    source = run_source(args)
    model, effort = args.candidate
    if (source["model"], source["effort"]) != (model, effort):
        raise mr_evidence.EvidenceError(f"the run record shows {source['model']}/{source['effort']}, not {model}/{effort}")
    grade = mr_grading.grade(mr_cases.load_cases()[args.case], Path(args.answer).read_text(encoding="utf-8"))
    entry = result_entry(
        args.case, args.candidate, grade, mr_evidence.run_evidence(source["session"]),
        args.attempts, args.earlier_cost, args.earlier_wall,
    )
    Path(args.out).write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entry": entry, "grade": grade}))
    return 0


def command_build(args: argparse.Namespace) -> int:
    roles = mr_cases.roles_by_case(mr_cases.load_cases())
    results = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.results]
    record = mr_record.build_record(ISSUE, roles, results)
    problems = mr_record.record_problems(record, roles)
    for problem in problems:
        print(f"problem: {problem}")
    if not problems:
        Path(args.out).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return 1 if problems else 0


def command_check(args: argparse.Namespace) -> int:
    roles = mr_cases.roles_by_case(mr_cases.load_cases())
    record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    registry = json.loads((REPO_ROOT / "config" / "model-registry.json").read_text(encoding="utf-8"))
    problems = mr_record.record_problems(record, roles)
    problems += mr_pins.pin_problems(record, registry, lambda name: (REPO_ROOT / name).read_text(encoding="utf-8"))
    for problem in problems:
        print(f"problem: {problem}")
    print(f"status: {record['status']}")
    for role, decision in mr_record.decisions(record).items():
        print(f"{role}: {decision['status']} {decision['winner'] or ''}")
    return 1 if problems else 0


def command_opponent_plugin(args: argparse.Namespace) -> int:
    out = Path(args.out)
    for relative in OPPONENT_COPY_PATHS:
        source, target = REPO_ROOT / relative, out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, target)
    registry_path = out / "config" / "model-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["opponents"]["claude"]["model"] = args.model
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    print(out.resolve())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed", help="create <out>/repo and <out>/prompt.md for a case")
    seed.add_argument("case", choices=sorted(mr_cases.load_cases()))
    seed.add_argument("--out", required=True)
    grade = commands.add_parser("grade", help="grade an answer file; exit 1 when the case fails")
    grade.add_argument("case", choices=sorted(mr_cases.load_cases()))
    grade.add_argument("--answer", required=True)
    for name, helptext in (("evidence", "print a run's host-verified model, effort, cost, and wall time"),
                           ("result", "grade an answer and write its record entry")):
        sub = commands.add_parser(name, help=helptext)
        source = sub.add_mutually_exclusive_group(required=True)
        source.add_argument("--status-line", help="file holding the role runner status line (reviewer cases)")
        source.add_argument("--state-dir", help="the opponent state folder, read before --finish (debate cases)")
        if name == "result":
            sub.add_argument("case", choices=sorted(mr_cases.load_cases()))
            sub.add_argument("--candidate", required=True, type=parse_candidate, help="model/effort")
            sub.add_argument("--answer", required=True)
            sub.add_argument("--out", required=True)
            sub.add_argument("--attempts", type=int, default=1)
            sub.add_argument("--earlier-cost", type=float, default=0.0, help="cost of earlier attempts")
            sub.add_argument("--earlier-wall", type=float, default=0.0, help="wall seconds of earlier attempts")
    build = commands.add_parser("build", help="write record.json from the 20 result files")
    build.add_argument("--results", nargs="+", required=True)
    build.add_argument("--out", default=str(RECORD_PATH))
    commands.add_parser("check", help="validate record.json and the repository's pins against it")
    plugin = commands.add_parser("opponent-plugin", help="copy the opponent runner with another Claude opponent model")
    plugin.add_argument("--model", required=True, choices=sorted({model for model, _ in mr_record.CANDIDATES}))
    plugin.add_argument("--out", required=True)
    return parser


COMMANDS = {
    "seed": command_seed, "grade": command_grade, "evidence": command_evidence, "result": command_result,
    "build": command_build, "check": command_check, "opponent-plugin": command_opponent_plugin,
}


def main() -> int:
    args = build_parser().parse_args()
    try:
        return COMMANDS[args.command](args)
    except (mr_evidence.EvidenceError, OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
