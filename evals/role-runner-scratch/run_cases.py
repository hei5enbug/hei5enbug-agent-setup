"""Drive the three model runs of the role runner scratch-folder issue: seed, snapshot, run, and check each case.

`--dry-run` prints every command and starts nothing: no folder is created and no model is called.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_RUNNER = HERE.parents[1] / "scripts" / "role_runner.py"
DEFAULT_WORKDIR = Path("/tmp/work")
REVIEW_ASSIGNMENT = (
    "Review pricing.py in the current repository for correctness against its docstring. "
    "Confirm any defect you report by running the repository's tests. Change no file.\n"
)
SCOUT_ASSIGNMENT = (
    "Total quantity * unit_cents over every row of data/orders.csv with a Python command written as a heredoc "
    "(python3 - <<'EOF' ... EOF) and report the total. Run no test and install nothing. Change no file.\n"
)
EVIDENCE_KEYS = ("rollout", "transcript")


@dataclass(frozen=True)
class Case:
    number: int
    kind: str
    model: str | None
    validation: bool
    with_env: bool
    assignment: str


CASES = {
    5: Case(5, "validation", "gpt-6.1-sol", True, False, REVIEW_ASSIGNMENT),
    6: Case(6, "validation", "claude-opus-5-5", True, True, REVIEW_ASSIGNMENT),
    7: Case(7, "scout", None, False, False, SCOUT_ASSIGNMENT),
}


def load_demo():
    spec = importlib.util.spec_from_file_location("role_runner_scratch_demo", HERE / "demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def role_of(case: Case) -> str:
    return "reviewer" if case.kind == "validation" else "scout"


def paths_for(case: Case, workdir: Path) -> dict[str, Path]:
    return {
        "repo": workdir / f"demo-{case.number}",
        "before": workdir / f"before-{case.number}.txt",
        "assignment": workdir / f"a{case.number}.md",
        "result": workdir / f"r{case.number}.md",
    }


def runner_argv(case: Case, paths: dict[str, Path], runner: Path, timeout: int | None) -> list[str]:
    role = role_of(case)
    argv = [sys.executable, str(runner), role]
    if case.model:
        argv += ["--model", case.model]
    if case.validation:
        argv.append("--validation")
    argv += ["--assignment", str(paths["assignment"]), "--result", str(paths["result"])]
    if timeout is not None:
        argv += ["--timeout", str(timeout)]
    return argv


def check_argv(case: Case, paths: dict[str, Path], records: str) -> list[str]:
    return [sys.executable, str(HERE / "demo.py"), "check", case.kind, str(paths["repo"]), "--records", records,
            "--result", str(paths["result"]), "--before", str(paths["before"])]


def plan_lines(case: Case, workdir: Path, runner: Path, timeout: int | None) -> list[str]:
    """The commands a case runs, in order, as text; the records path stays a placeholder until the runner reports it."""
    paths = paths_for(case, workdir)
    seed = [sys.executable, str(HERE / "demo.py"), "seed", str(paths["repo"]), *(["--with-env"] if case.with_env else [])]
    snapshot = [sys.executable, str(HERE / "demo.py"), "snapshot", str(paths["repo"]), str(paths["before"])]
    run = f"cd {shlex.quote(str(paths['repo']))} && " + shlex.join(runner_argv(case, paths, runner, timeout))
    return [
        f"case {case.number}: {role_of(case)} on {case.model or 'the default scout model'}",
        shlex.join(seed),
        shlex.join(snapshot),
        f"write the assignment to {paths['assignment']}",
        run,
        shlex.join(check_argv(case, paths, "<evidence path from the status line>")),
    ]


def evidence_path(stdout: str) -> str:
    """The rollout or transcript path in the verified status line the role runner printed, or raise ValueError."""
    for line in reversed(stdout.strip().splitlines()):
        try:
            status = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(status, dict) or "evidence" not in status:
            continue
        if status.get("verified") is not True:
            raise ValueError(f"the runner did not verify the run: {line}")
        evidence = status["evidence"] if isinstance(status["evidence"], dict) else {}
        for key in EVIDENCE_KEYS:
            if isinstance(evidence.get(key), str) and evidence[key]:
                return evidence[key]
        raise ValueError(f"the status line names no {' or '.join(EVIDENCE_KEYS)}: {line}")
    raise ValueError("the runner printed no status line")


def run_case(case: Case, workdir: Path, runner: Path, timeout: int | None) -> dict:
    demo = load_demo()
    paths = paths_for(case, workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    demo.seed(paths["repo"], case.with_env)
    paths["before"].write_text(demo.snapshot(paths["repo"]), encoding="utf-8")
    paths["assignment"].write_text(case.assignment, encoding="utf-8")
    done = subprocess.run(runner_argv(case, paths, runner, timeout), cwd=paths["repo"], capture_output=True, text=True)
    try:
        records = evidence_path(done.stdout)
    except ValueError as error:
        return {"case": case.number, "pass": False, "failures": [str(error)], "runner_exit": done.returncode}
    failures = demo.check(case.kind, paths["repo"], Path(records), paths["result"], paths["before"])
    return {"case": case.number, "pass": not failures, "failures": failures, "records": records, "runner_exit": done.returncode}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", type=int, choices=sorted(CASES), help="case numbers to run; default 5 6 7")
    parser.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--dry-run", action="store_true", help="print the commands and start nothing")
    args = parser.parse_args(argv)
    chosen = [CASES[number] for number in (args.cases or sorted(CASES))]
    if args.dry_run:
        for case in chosen:
            print("\n".join(plan_lines(case, args.workdir, args.runner, args.timeout)))
        return 0
    results = [run_case(case, args.workdir, args.runner, args.timeout) for case in chosen]
    for result in results:
        print(json.dumps(result))
    return 0 if all(result["pass"] for result in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
