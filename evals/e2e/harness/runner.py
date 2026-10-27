"""One run end to end: materialize, execute, collect, view, grade, metrics."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from typing import Any

from . import codex_calls, collect, command, environment, metrics, rubric, transcript, usage
from .config import FINISHED_STATUSES, STATUS_COMPLETE, STATUS_INFRA_FAILED, STATUS_TIMED_OUT, STATUS_USAGE_LIMITED, HarnessConfig
from .matrix import RunSpec, prior_attempts, read_json, write_json
from .process import ProcessResult, run_agent


def load_graders() -> Any:
    from . import graders

    return graders


def decide_status(facts: dict[str, Any], limit_reason: str | None, timed_out: bool) -> str:
    if limit_reason:
        return STATUS_USAGE_LIMITED
    if timed_out:
        return STATUS_TIMED_OUT
    return STATUS_COMPLETE if facts["has_result"] else STATUS_INFRA_FAILED


def write_run_files(
    spec: RunSpec, task: dict[str, Any], variant: dict[str, Any], prompt: str, cfg: HarnessConfig, plugin: dict[str, Any],
) -> list[str]:
    spec.result_dir.mkdir(parents=True, exist_ok=True)
    (spec.result_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(spec.result_dir / "settings.json", command.run_settings(variant))
    write_json(spec.result_dir / "mcp.json", command.mcp_config(spec.result_dir / "approvals.jsonl", spec.work_dir, spec.repo))
    argv = command.build_command(cfg, task, variant, prompt, plugin["path"], spec.result_dir)
    write_json(spec.result_dir / "command.json", {"argv": argv, "cwd": str(spec.repo)})
    return argv


def grade_run(
    spec: RunSpec, task: dict[str, Any], run: dict[str, Any], cfg: HarnessConfig, graders: Any, view: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    grade_dir = spec.result_dir / "grade"
    grade_dir.mkdir(parents=True, exist_ok=True)
    grade = graders.grade_run(task, spec.repo, run["base_commit"], view, cfg.tasks_root, grade_dir / "work")
    write_json(grade_dir / "grade.json", grade)
    if not task.get("rubric"):
        return grade, None
    prompt = (spec.result_dir / "prompt.txt").read_text(encoding="utf-8")
    artifact = rubric.artifact_text(task["rubric"], spec.repo, view["final_answer"])
    work = rubric.opaque_dir(spec.base_dir, spec.run_id)
    result = {**rubric.grade(task, artifact, prompt, work, repo_root=cfg.repo_root), "rubric_dir": str(work)}
    write_json(grade_dir / "rubric.json", result)
    return grade, result


def analyze(spec: RunSpec, task: dict[str, Any], run: dict[str, Any], cfg: HarnessConfig, graders: Any = None) -> dict[str, Any]:
    """Build view, grade, and metrics for a run from the files in its result dir."""
    directory = spec.result_dir
    events = transcript.read_jsonl(directory / "stream.jsonl")
    facts = metrics.stream_facts(events)
    subagents = collect.load_subagents(directory / "transcripts" / "subagents")
    main_events = transcript.read_jsonl(directory / "transcripts" / "main.jsonl")
    approvals = transcript.read_jsonl(directory / "approvals.jsonl")
    base_view = transcript.build_view(events, subagents, approvals, collect.load_assignments(directory / "assignments"))
    rollouts = collect.load_rollouts(directory / "codex", collect.rollout_roles(base_view["tool_calls"]))
    view = {**base_view, "tool_calls": [*base_view["tool_calls"], *codex_calls.codex_tool_calls(rollouts)]}
    runners = collect.load_runner_transcripts(directory / "transcripts" / "runner")
    write_json(directory / "view.json", view)
    grade, rubric_result, failure = None, None, None
    if run["status"] in FINISHED_STATUSES:
        try:
            grade, rubric_result = grade_run(spec, task, run, cfg, graders or load_graders(), view)
        except Exception as error:  # noqa: BLE001 - usage and cost are still written; the error is raised after metrics.json
            failure = error
    by_source, usage_source = usage.claude_requests_by_source(main_events, subagents, events, runners)
    result = metrics.build_metrics(
        run=run, task=task, view=view, facts=facts, claude_report=usage.claude_token_report(by_source),
        codex_report=usage.codex_token_report(rollouts), grade=grade, rubric=rubric_result,
        checks=metrics.plugin_checks(facts, run["plugin"]["path"], main_events, subagents), usage_source=usage_source,
    )
    if failure is not None:
        result = {**result, "grade_error": f"{type(failure).__name__}: {failure}"}
    write_json(directory / "metrics.json", result)
    if failure is not None:
        raise failure
    return result


def collect_records(spec: RunSpec, session_id: str | None, proc: ProcessResult) -> dict[str, Any]:
    claude = collect.collect_claude(environment.claude_config_dir(), session_id or "", spec.result_dir / "transcripts")
    codex = collect.collect_codex(environment.codex_home(), spec.work_dir, proc.started_at, proc.ended_at, spec.result_dir / "codex")
    return {"claude": claude, "codex": codex}


def finish_run(spec: RunSpec, task: dict[str, Any], run: dict[str, Any], proc: ProcessResult, cfg: HarnessConfig) -> dict[str, Any]:
    events = transcript.read_jsonl(spec.result_dir / "stream.jsonl")
    facts = metrics.stream_facts(events)
    records = collect_records(spec, facts["session_id"], proc)
    subagents = collect.load_subagents(spec.result_dir / "transcripts" / "subagents")
    calls = transcript.build_view(events, subagents)["tool_calls"]
    collect.collect_assignments(calls, spec.result_dir / "assignments", spec.repo)
    records = {**records, "runner": collect.collect_runner_transcripts(calls, spec.result_dir / "transcripts" / "runner")}
    limit = transcript.usage_limit_reason(events)
    finished = {
        **run, "status": decide_status(facts, limit, proc.timed_out), "returncode": proc.returncode,
        "timed_out": proc.timed_out, "wall_seconds": proc.wall_seconds, "started_at": proc.started_at.isoformat(),
        "ended_at": proc.ended_at.isoformat(), "session_id": facts["session_id"], "usage_limit": limit,
        "error": proc.error, "collected": records, "orphans_killed": proc.orphans_killed,
        "leftover_killed": proc.leftover_killed,
    }
    write_json(spec.result_dir / "run.json", finished)
    try:
        analyze(spec, task, finished, cfg)
    except Exception as error:  # noqa: BLE001 - keep the agent outcome; `regrade` repairs a grading failure later
        finished = {**finished, "grade_error": f"{type(error).__name__}: {error}"}
        write_json(spec.result_dir / "run.json", finished)
    return finished


def execute_run(
    spec: RunSpec, task: dict[str, Any], variant: dict[str, Any], plugin: dict[str, Any], cfg: HarnessConfig,
    base_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Run one agent session and return the final run record (also written as run.json)."""
    shutil.rmtree(spec.work_dir, ignore_errors=True)
    prompt = command.read_prompt(cfg.tasks_root, task)
    argv = write_run_files(spec, task, variant, prompt, cfg, plugin)
    env, removed = environment.child_environment(os.environ, {**cfg.extra_env, **variant["env"]})
    write_json(spec.result_dir / "env.json", environment.run_snapshot(base_snapshot, plugin, removed))
    run: dict[str, Any] = {
        "run_id": spec.run_id, "task": spec.task, "variant": spec.variant, "rep": spec.rep, "plugin": plugin,
        "attempts": prior_attempts(spec) + 1, "base_commit": None,
    }
    try:
        run["base_commit"] = load_graders().materialize_fixture(task, cfg.fixtures_root, cfg.tasks_root, spec.repo)
    except Exception as error:  # noqa: BLE001 - any failure to build the work repo is an infrastructure failure
        failed = {**run, "status": STATUS_INFRA_FAILED, "error": f"materialize failed: {error}"}
        write_json(spec.result_dir / "run.json", failed)
        return failed
    proc = run_agent(
        argv, spec.repo, env, spec.result_dir / "stream.jsonl", spec.result_dir / "stderr.txt",
        float(task["limits"]["wall_seconds"]), cfg.sigint_grace, cfg.sigterm_grace,
    )
    return finish_run(spec, task, run, proc, cfg)


def parse_moment(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def recollect(spec: RunSpec, run: dict[str, Any]) -> dict[str, Any]:
    """Copy the host records again (Claude, subagents, runner sessions, Codex rollouts); return the updated run record."""
    directory, previous = spec.result_dir, run.get("collected") or {}
    claude = collect.collect_claude(environment.claude_config_dir(), str(run.get("session_id") or ""), directory / "transcripts")
    events = transcript.read_jsonl(directory / "stream.jsonl")
    calls = transcript.build_view(events, collect.load_subagents(directory / "transcripts" / "subagents"))["tool_calls"]
    collect.collect_assignments(calls, directory / "assignments", spec.repo)
    runner_names = collect.collect_runner_transcripts(calls, directory / "transcripts" / "runner")
    start, end = parse_moment(run.get("started_at")), parse_moment(run.get("ended_at"))
    codex = collect.collect_codex(environment.codex_home(), spec.work_dir, start, end, directory / "codex") if start and end else []
    collected = {
        "claude": claude if claude["main"] else previous.get("claude", claude),
        "codex": codex or previous.get("codex", []),
        "runner": runner_names or previous.get("runner", []),
    }
    updated = {**run, "collected": collected}
    write_json(directory / "run.json", updated)
    return updated


def regrade_run(
    spec: RunSpec, task: dict[str, Any], cfg: HarnessConfig, graders: Any = None, recollect_records: bool = False,
) -> dict[str, Any] | None:
    """Re-run grading and metrics for a finished run from its saved results and work repo."""
    run = read_json(spec.result_dir / "run.json")
    if not isinstance(run, dict) or run.get("status") not in FINISHED_STATUSES or not spec.repo.is_dir():
        return None
    if recollect_records:
        run = recollect(spec, run)
    analyze(spec, task, run, cfg, graders)
    if "grade_error" in run:
        run = {key: value for key, value in run.items() if key != "grade_error"}
        write_json(spec.result_dir / "run.json", run)
    return run
