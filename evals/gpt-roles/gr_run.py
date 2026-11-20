"""Run one case with one candidate model through the role runner, the text review script, or the tiki-taka opponent script, and
write one result file. Starting a run is the only step that costs model calls."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import gr_cases
import gr_core
import gr_text_cases
import gr_worker_cases

OPPONENT_COPY_PATHS = ("skills/tiki-taka/run-opponent.sh", "skills/tiki-taka/scripts", "config/model-registry.json")
RUNNER_TIMEOUT = 1500


class CaseError(RuntimeError):
    """The run could not be graded: no verified status, no rollout, or an unpriced model. The case is rerun, not failed."""


def runner_path(plugin: Path) -> Path:
    return plugin / "scripts" / "role_runner.py"


def runner_argv(plugin: Path, role: str, model: str, effort: str, assignment: Path, result: Path, extra: tuple[str, ...] = (), user_requested: bool = False) -> list[str]:
    argv = [sys.executable, str(runner_path(plugin)), role, "--model", model, "--effort", effort, "--assignment", str(assignment),
            "--result", str(result), "--timeout", str(RUNNER_TIMEOUT), *extra]
    return [*argv, "--user-requested"] if user_requested else argv


def finish(case: gr_cases.Case, model: str, rep: int, failures: list[str], cost: float, wall: float, rollout: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"role": case.role, "case": case.id, "model": model, "effort": case.effort, "rep": rep, "passed": not failures,
            "failures": failures, "cost_usd": cost, "wall_seconds": wall, "rollout": rollout, **(extra or {})}


def run_and_verify(argv: list[str], cwd: Path, model: str, effort: str) -> tuple[dict[str, Any], float]:
    done, wall = gr_core.run_timed(argv, cwd)
    try:
        return gr_core.verified_status(done.stdout, model, effort), wall
    except ValueError as error:
        raise CaseError(f"{error}; stderr: {done.stderr.strip()[-300:]}") from error


def rollout_of(status: dict[str, Any]) -> Path:
    value = (status.get("evidence") or {}).get("rollout")
    if not isinstance(value, str) or not Path(value).is_file():
        raise CaseError(f"the status line names no readable rollout: {json.dumps(status.get('evidence'))[:200]}")
    return Path(value)


def run_reviewer_case(case: gr_cases.Case, model: str, work: Path, plugin: Path, rep: int) -> dict[str, Any]:
    if case.kind == "scratch-validation":
        demo = gr_cases.load_demo()
        repo = work / "repo"
        demo.seed(repo, False)
        before = work / "before.txt"
        before.write_text(demo.snapshot(repo), encoding="utf-8")
        assignment, result = work / "assignment.md", work / "result.md"
        assignment.write_text(gr_cases.REVIEW_ASSIGNMENT, encoding="utf-8")
        status, wall = run_and_verify(runner_argv(plugin, "reviewer", model, case.effort, assignment, result, ("--validation",)), repo, model, case.effort)
        rollout = rollout_of(status)
        failures = demo.check("validation", repo, rollout, result, before)
        return finish(case, model, rep, failures, gr_core.rollout_cost(rollout, model), wall, rollout.as_posix())
    paths = gr_cases.mr_cases.seed(case.id, work)
    result = work / "answer.md"
    status, wall = run_and_verify(runner_argv(plugin, "reviewer", model, case.effort, Path(paths["prompt"]), result), Path(paths["repo"]), model, case.effort)
    rollout = rollout_of(status)
    failures, grade = gr_cases.mr_failures(case.id, result.read_text(encoding="utf-8"))
    return finish(case, model, rep, failures, gr_core.rollout_cost(rollout, model), wall, rollout.as_posix(), {"grade": grade})


def run_scout_case(case: gr_cases.Case, model: str, work: Path, plugin: Path, rep: int) -> dict[str, Any]:
    repo, assignment, result = work / "repo", work / "assignment.md", work / "result.md"
    if case.kind == "scratch-scout":
        demo = gr_cases.load_demo()
        demo.seed(repo, False)
        text = ("Total quantity * unit_cents over every row of data/orders.csv with a Python command written as a heredoc "
                "(python3 - <<'EOF' ... EOF) and report the total. Run no test and install nothing. Change no file.\n")
    else:
        gr_cases.seed_scout_demo(repo)
        text = gr_cases.SCOUT_ASSIGNMENTS[case.id]
    assignment.write_text(text, encoding="utf-8")
    before = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--ignored"], capture_output=True, text=True).stdout
    status, wall = run_and_verify(runner_argv(plugin, "scout", model, case.effort, assignment, result, user_requested=True), repo, model, case.effort)
    rollout, answer = rollout_of(status), result.read_text(encoding="utf-8")
    if case.kind == "scratch-scout":
        failures = demo.scout_failures(demo.tool_records(rollout), answer.replace(",", ""))
    else:
        failures = gr_cases.scout_failures(case.id, answer)
    after = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--ignored"], capture_output=True, text=True).stdout
    if before != after:
        failures.append("git status --porcelain --ignored changed")
    return finish(case, model, rep, failures, gr_core.rollout_cost(rollout, model), wall, rollout.as_posix())


def run_researcher_case(case: gr_cases.Case, model: str, work: Path, plugin: Path, rep: int) -> dict[str, Any]:
    repo = work / "repo"
    repo.mkdir(parents=True)
    assignment, result = work / "assignment.md", work / "result.md"
    assignment.write_text(gr_cases.researcher_assignment(case.id), encoding="utf-8")
    status, wall = run_and_verify(runner_argv(plugin, "researcher", model, case.effort, assignment, result, user_requested=True), repo, model, case.effort)
    rollout = rollout_of(status)
    failures = gr_cases.researcher_failures(result.read_text(encoding="utf-8"), rollout.read_text(encoding="utf-8", errors="replace"), case.id)
    return finish(case, model, rep, failures, gr_core.rollout_cost(rollout, model), wall, rollout.as_posix())


def run_worker_case(case: gr_cases.Case, model: str, work: Path, plugin: Path, rep: int) -> dict[str, Any]:
    repo, assignment, result = work / "repo", work / "assignment.md", work / "result.md"
    repo.mkdir(parents=True)
    base = gr_worker_cases.seed(case.id, repo)
    assignment.write_text(gr_cases.worker_assignment(case.id), encoding="utf-8")
    status, wall = run_and_verify(runner_argv(plugin, "worker", model, case.effort, assignment, result, user_requested=True), repo, model, case.effort)
    rollout = rollout_of(status)
    failures = gr_worker_cases.failures(case.id, repo, base)
    return finish(case, model, rep, failures, gr_core.rollout_cost(rollout, model), wall, rollout.as_posix())


def run_text_review_case(case: gr_cases.Case, model: str, work: Path, plugin: Path, rep: int) -> dict[str, Any]:
    """text_review.py prints no rollout path, so the review's own rollout is found by its temporary folder name and start time."""
    paths = gr_text_cases.seed(case.id, work)
    argv = gr_text_cases.command(case.id, paths, plugin / "scripts" / "text_review.py", model)
    started = time.time()
    done, wall = gr_core.run_timed(argv, work)
    if done.returncode not in (0, 1):
        raise CaseError(f"text_review.py exited {done.returncode}: {(done.stderr or done.stdout).strip()[-300:]}")
    output = gr_text_cases.parse_output(done.stdout)
    rollouts = gr_core.rollouts_since(started, "text-review-", model)
    if len(rollouts) != 1:
        raise CaseError(f"expected one review rollout since the start, found {len(rollouts)}: {done.stdout[-200:]}")
    return finish(case, model, rep, gr_text_cases.failures(case.id, output), gr_core.rollout_cost(rollouts[0], model), wall, rollouts[0].as_posix(), {"findings": output.get("findings")})


def opponent_plugin(plugin: Path, model: str, dest: Path) -> Path:
    for relative in OPPONENT_COPY_PATHS:
        source, target = plugin / relative, dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, target)
    path = dest / "config" / "model-registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    registry["opponents"]["codex"]["model"] = model
    path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return dest


def codex_rollout(session: str) -> Path:
    found = sorted((Path.home() / ".codex" / "sessions").glob(f"**/rollout-*{session}.jsonl"))
    if not found:
        raise CaseError(f"no Codex rollout for session {session}")
    return found[-1]


def run_opponent_case(case: gr_cases.Case, model: str, work: Path, plugin: Path, rep: int) -> dict[str, Any]:
    paths = gr_cases.mr_cases.seed(case.id, work)
    copy = opponent_plugin(plugin, model, work / "opponent-plugin")
    state = Path(tempfile.mkdtemp(prefix="gr-opponent-"))
    script = copy / "skills" / "tiki-taka" / "run-opponent.sh"
    argv = ["bash", str(script), "--opponent", "codex", "--state-dir", str(state), "--repo", paths["repo"], "--max-exchanges", "1"]
    try:
        done, wall = gr_core.run_timed(argv, Path(paths["repo"]), stdin=Path(paths["prompt"]).read_text(encoding="utf-8"))
        session_file = state / "session-id"
        if done.returncode != 0 or not session_file.is_file():
            raise CaseError(f"run-opponent.sh exited {done.returncode}: {done.stderr.strip()[-300:]}")
        rollout = codex_rollout(session_file.read_text(encoding="utf-8").strip())
        failures, grade = gr_cases.mr_failures(case.id, done.stdout)
        return finish(case, model, rep, failures, gr_core.rollout_cost(rollout, model), wall, rollout.as_posix(), {"grade": grade})
    finally:
        gr_core.run_timed(["bash", str(script), "--opponent", "codex", "--state-dir", str(state), "--finish"], work)
        shutil.rmtree(state, ignore_errors=True)


RUNNERS = {"mr-review": run_reviewer_case, "scratch-validation": run_reviewer_case, "scratch-scout": run_scout_case,
           "scout-demo": run_scout_case, "researcher": run_researcher_case, "worker": run_worker_case,
           "text-review": run_text_review_case, "opponent": run_opponent_case}


def dry_check(case_id: str, model: str, plugin: Path) -> dict[str, Any]:
    """Check a unit without a model call: the plugin copy lists the model, and the case seeds in a throwaway folder. Returns the
    command the run would start."""
    case = gr_cases.CASES[case_id]
    listed = json.loads((plugin / "config" / "model-registry.json").read_text(encoding="utf-8"))["runner"]["review_models"]
    if model not in listed and case.kind != "opponent":
        raise CaseError(f"the plugin copy's role runner does not list {model}")
    with tempfile.TemporaryDirectory(prefix="gr-dry-") as tmp:
        work = Path(tmp)
        if case.kind in ("mr-review", "opponent"):
            gr_cases.mr_cases.seed(case.id, work)
        elif case.kind == "scratch-validation" or (case.kind == "scratch-scout"):
            gr_cases.load_demo().seed(work / "repo", False)
        elif case.kind == "scout-demo":
            gr_cases.seed_scout_demo(work / "repo")
        elif case.kind == "worker":
            (work / "repo").mkdir()
            gr_worker_cases.seed(case.id, work / "repo")
        elif case.kind == "text-review":
            gr_text_cases.seed(case.id, work)
        role = {"mr-review": "reviewer", "scratch-validation": "reviewer"}.get(case.kind, case.role)
        command = (["bash", "run-opponent.sh", "--opponent", "codex"] if case.kind == "opponent"
                   else ["text_review.py", "review", "--model", model] if case.kind == "text-review"
                   else runner_argv(plugin, role, model, case.effort, Path("assignment.md"), Path("result.md"),
                                    ("--validation",) if case.kind == "scratch-validation" else (), role not in ("reviewer",)))
    return {"case": case_id, "model": model, "effort": case.effort, "command": " ".join(command)}


def execute(case_id: str, model: str, out: Path, rep: int, plugin: Path) -> dict[str, Any]:
    """Run one case on one model and write its result file; a run that cannot be graded raises CaseError and writes none."""
    case = gr_cases.CASES[case_id]
    work = out / "work" / f"{case.role}__{case.id}__{model}__r{rep}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    result = RUNNERS[case.kind](case, model, work, plugin, rep)
    gr_core.write_result(out, result)
    return result
