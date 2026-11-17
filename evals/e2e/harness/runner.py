"""One run end to end: materialize, execute, collect, view, grade, metrics."""

from __future__ import annotations

import os
import shutil
import threading
from datetime import datetime
from typing import Any

from . import caps, codex_calls, codex_host, collect, command, converse, environment, metrics, rubric, transcript, usage
from .config import (
    APPROVAL_GUARD_OFF_ENV, CLAUDE_INSTRUCTION_ENV, FINISHED_STATUSES, HOST_CODEX, INSTRUCTION_ISOLATION, STATUS_COMPLETE,
    STATUS_INFRA_FAILED, STATUS_INTERRUPTED, STATUS_TIMED_OUT, STATUS_USAGE_LIMITED, HarnessConfig,
)
from .matrix import RunSpec, prior_attempts, read_json, write_json
from .process import GradingInterrupted, ProcessResult, run_agent

AGENT_TMP_NAME = "tmp"
ABORTED_REASON_PREFIX = "aborted"


def load_graders() -> Any:
    from . import graders

    return graders


def decide_status(facts: dict[str, Any], limit_reason: str | None, timed_out: bool, interrupted: bool = False) -> str:
    if interrupted:
        return STATUS_INTERRUPTED
    if limit_reason:
        return STATUS_USAGE_LIMITED
    if metrics.extra_plugins(facts):
        return STATUS_INFRA_FAILED
    if timed_out:
        return STATUS_TIMED_OUT
    if str(facts.get("terminal_reason") or "").startswith(ABORTED_REASON_PREFIX):
        return STATUS_INTERRUPTED
    return STATUS_COMPLETE if facts["has_result"] else STATUS_INFRA_FAILED


def contamination_error(facts: dict[str, Any]) -> str | None:
    names = metrics.extra_plugins(facts)
    return f"contaminated run: plugins other than the variant were loaded: {', '.join(names)}" if names else None


def write_run_files(
    spec: RunSpec, task: dict[str, Any], variant: dict[str, Any], prompt: str, cfg: HarnessConfig, plugin: dict[str, Any],
) -> list[str]:
    spec.result_dir.mkdir(parents=True, exist_ok=True)
    (spec.result_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(spec.result_dir / "settings.json", command.run_settings(
        variant, environment.profile_plugin_ids(environment.claude_config_dir()), command.ancestor_excludes(spec.repo)))
    sheet = command.task_sheet(cfg.tasks_root, task)
    write_json(spec.result_dir / "mcp.json", command.mcp_config(
        spec.result_dir / "approvals.jsonl", spec.work_dir, spec.repo, sheet, spec.result_dir / converse.LOG_NAME,
        spec.result_dir / "stream.jsonl"))
    argv = command.build_command(cfg, task, variant, prompt, plugin["path"], spec.result_dir)
    write_json(spec.result_dir / "command.json", {"argv": argv, "cwd": str(spec.repo)})
    return argv


def write_codex_run_files(
    spec: RunSpec, variant: dict[str, Any], prompt: str, cfg: HarnessConfig, plugin: dict[str, Any],
) -> list[str]:
    spec.result_dir.mkdir(parents=True, exist_ok=True)
    (spec.result_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    argv = codex_host.build_codex_command(cfg, variant, prompt, spec.repo)
    write_json(spec.result_dir / "command.json", {
        "argv": argv, "cwd": str(spec.repo), "env": codex_host.host_env(spec.result_dir),
        "setup": codex_host.setup_commands(cfg, plugin["path"]), "approval_handling": codex_host.APPROVAL_HANDLING,
    })
    return argv


def grade_run(
    spec: RunSpec, task: dict[str, Any], run: dict[str, Any], cfg: HarnessConfig, graders: Any, view: dict[str, Any],
    interrupt: threading.Event | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Grade a run; a set `interrupt` ends the grading processes and raises GradingInterrupted."""
    if interrupt is not None and interrupt.is_set():
        raise GradingInterrupted("harness interrupted before grading")
    grade_dir = spec.result_dir / "grade"
    grade_dir.mkdir(parents=True, exist_ok=True)
    extra = {} if interrupt is None else {"interrupt": interrupt}
    grade = graders.grade_run(task, spec.repo, run["base_commit"], view, cfg.tasks_root, grade_dir / "work", **extra)
    write_json(grade_dir / "grade.json", grade)
    if not task.get("rubric"):
        return grade, None
    prompt = (spec.result_dir / "prompt.txt").read_text(encoding="utf-8")
    artifact = rubric.artifact_text(task["rubric"], spec.repo, view["final_answer"])
    work = rubric.opaque_dir(spec.base_dir, spec.run_id)
    result = {**rubric.grade(task, artifact, prompt, work, repo_root=cfg.repo_root, interrupt=interrupt), "rubric_dir": str(work)}
    write_json(grade_dir / "rubric.json", result)
    return grade, result


def claude_records(spec: RunSpec, run: dict[str, Any]) -> dict[str, Any]:
    """Everything `analyze` needs from a Claude Code run's saved records."""
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
    by_source, usage_source = usage.claude_requests_by_source(main_events, subagents, events, runners)
    return {
        "view": view, "facts": facts, "claude_report": usage.claude_token_report(by_source),
        "codex_report": usage.codex_token_report(rollouts), "usage_source": usage_source,
        "checks": metrics.plugin_checks(facts, run["plugin"]["path"], main_events, subagents),
        "violations": caps.scan_run(stream_events=events, by_source=by_source, tool_calls=view["tool_calls"], rollouts=rollouts,
                                    exception=run.get("cap_exception")),
        "extra": {},
    }


def analyze(
    spec: RunSpec, task: dict[str, Any], run: dict[str, Any], cfg: HarnessConfig, graders: Any = None,
    interrupt: threading.Event | None = None,
) -> dict[str, Any]:
    """Build view, grade, and metrics for a run from the files in its result dir."""
    directory = spec.result_dir
    if spec.host == HOST_CODEX:
        records = codex_host.load_records(spec, run, str(run.get("expected_model") or ""))
        records = {**records, "extra": codex_host.host_metrics(records)}
    else:
        records = claude_records(spec, run)
    main_events = records["rollouts"][0]["events"] if spec.host == HOST_CODEX and records["rollouts"] else (
        transcript.read_jsonl(directory / "stream.jsonl"))
    view = converse.attach(records["view"], directory, spec.host, main_events, scripted=command.task_sheet(cfg.tasks_root, task) is not None,
                           repo=spec.repo)
    write_json(directory / "view.json", view)
    grade, rubric_result, failure = None, None, None
    if run["status"] in FINISHED_STATUSES:
        try:
            grade, rubric_result = grade_run(spec, task, run, cfg, graders or load_graders(), view, interrupt)
        except Exception as error:  # noqa: BLE001 - usage and cost are still written; the error is raised after metrics.json
            failure = error
    result = metrics.build_metrics(
        run=run, task=task, view=view, facts=records["facts"], claude_report=records["claude_report"],
        codex_report=records["codex_report"], grade=grade, rubric=rubric_result, checks=records["checks"],
        usage_source=records["usage_source"],
    )
    result = {**result, "host": spec.host, **records["extra"]}
    if records["violations"]:
        result = {**result, "success": False, "cap_violation": records["violations"]}
    if failure is not None:
        result = {**result, "grade_error": f"{type(failure).__name__}: {failure}"}
    write_json(directory / "metrics.json", result)
    if spec.host == HOST_CODEX:
        codex_host.write_env(spec, records)
    if failure is not None:
        raise failure
    return result


def collect_records(spec: RunSpec, session_id: str | None, proc: ProcessResult) -> dict[str, Any]:
    claude = collect.collect_claude(environment.claude_config_dir(), session_id or "", spec.result_dir / "transcripts")
    codex = collect.collect_codex(environment.codex_home(), spec.work_dir, proc.started_at, proc.ended_at, spec.result_dir / "codex")
    return {"claude": claude, "codex": codex}


def finish_run(
    spec: RunSpec, task: dict[str, Any], run: dict[str, Any], proc: ProcessResult, cfg: HarnessConfig,
    interrupt: threading.Event | None = None,
) -> dict[str, Any]:
    events = transcript.read_jsonl(spec.result_dir / "stream.jsonl")
    facts = metrics.stream_facts(events)
    records = collect_records(spec, facts["session_id"], proc)
    subagents = collect.load_subagents(spec.result_dir / "transcripts" / "subagents")
    calls = transcript.build_view(events, subagents)["tool_calls"]
    collect.collect_assignments(calls, spec.result_dir / "assignments", spec.repo)
    records = {**records, "runner": collect.collect_runner_transcripts(calls, spec.result_dir / "transcripts" / "runner")}
    limit = transcript.usage_limit_reason(events)
    finished = {
        **run, "status": decide_status(facts, limit, proc.timed_out, proc.interrupted), "returncode": proc.returncode,
        "timed_out": proc.timed_out, "interrupted": proc.interrupted, "wall_seconds": proc.wall_seconds,
        "started_at": proc.started_at.isoformat(), "ended_at": proc.ended_at.isoformat(), "session_id": facts["session_id"], "usage_limit": limit,
        "error": proc.error or contamination_error(facts), "collected": records, "orphans_killed": proc.orphans_killed,
        "leftover_killed": proc.leftover_killed,
    }
    return record_and_analyze(spec, task, finished, cfg, interrupt)


def record_and_analyze(
    spec: RunSpec, task: dict[str, Any], finished: dict[str, Any], cfg: HarnessConfig, interrupt: threading.Event | None = None,
) -> dict[str, Any]:
    """Write run.json, analyze the run, and add what analysis found (a cap violation, a grading error) to run.json.

    A harness interrupt that stopped or prevented grading records the run as interrupted, so a resume runs it again."""
    write_json(spec.result_dir / "run.json", finished)
    try:
        result = analyze(spec, task, finished, cfg, interrupt=interrupt)
    except GradingInterrupted:
        finished = {**finished, "status": STATUS_INTERRUPTED, "interrupted": True}
        write_json(spec.result_dir / "run.json", finished)
        return finished
    except Exception as error:  # noqa: BLE001 - keep the agent outcome; `regrade` repairs a grading failure later
        finished = {**finished, "grade_error": f"{type(error).__name__}: {error}"}
        write_json(spec.result_dir / "run.json", finished)
        return finished
    if result.get("cap_violation"):
        finished = {**finished, "cap_violation": result["cap_violation"]}
        write_json(spec.result_dir / "run.json", finished)
    return finished


def finish_codex_run(
    spec: RunSpec, task: dict[str, Any], run: dict[str, Any], proc: ProcessResult, cfg: HarnessConfig,
    interrupt: threading.Event | None = None,
) -> dict[str, Any]:
    """Copy the rollouts the run's CODEX_HOME holds, set the status from the stream and rollouts, then analyze."""
    copied = codex_host.copy_rollouts(spec.result_dir)
    rollouts, calls = codex_host.label_rollouts(collect.load_rollouts(spec.result_dir / "codex", {}))
    main_calls = [call for call in calls if call["source"] == "main"]
    collect.collect_assignments(main_calls, spec.result_dir / "assignments", spec.repo)
    runner_names = collect.collect_runner_transcripts(main_calls, spec.result_dir / "transcripts" / "runner")
    state = codex_host.stream_state(transcript.read_jsonl(spec.result_dir / "stream.jsonl"))
    answered = state["completed"] or any(
        codex_host.payload_of(event).get("type") == "task_complete" for event in (rollouts[0]["events"] if rollouts else []))
    finished = {
        **run, "status": decide_status({"has_result": answered}, state["usage_limit"], proc.timed_out, proc.interrupted),
        "returncode": proc.returncode, "timed_out": proc.timed_out, "interrupted": proc.interrupted,
        "wall_seconds": proc.wall_seconds,
        "started_at": proc.started_at.isoformat(), "ended_at": proc.ended_at.isoformat(), "session_id": None,
        "usage_limit": state["usage_limit"], "error": proc.error, "collected": {"codex": copied, "runner": runner_names},
        "orphans_killed": proc.orphans_killed, "leftover_killed": proc.leftover_killed,
    }
    return record_and_analyze(spec, task, finished, cfg, interrupt)


def agent_overrides(spec: RunSpec, task: dict[str, Any], variant: dict[str, Any], cfg: HarnessConfig, agent_tmp: Path) -> dict[str, str]:
    """The variables the harness sets on the agent; a Claude Code run gets the instruction controls last, so no variant turns them off."""
    codex = spec.host == HOST_CODEX
    return {
        "TMPDIR": str(agent_tmp), **command.task_environment(task, spec.repo, spec.work_dir),
        **cfg.extra_env, **APPROVAL_GUARD_OFF_ENV, **variant["env"],
        **(codex_host.host_env(spec.result_dir) if codex else CLAUDE_INSTRUCTION_ENV),
    }


def execute_run(
    spec: RunSpec, task: dict[str, Any], variant: dict[str, Any], plugin: dict[str, Any], cfg: HarnessConfig,
    base_snapshot: dict[str, Any], interrupt: threading.Event | None = None,
) -> dict[str, Any]:
    """Run one agent session and return the final run record (also written as run.json)."""
    shutil.rmtree(spec.work_dir, ignore_errors=True)
    prompt = command.read_prompt(cfg.tasks_root, task)
    codex = spec.host == HOST_CODEX
    argv = write_codex_run_files(spec, variant, prompt, cfg, plugin) if codex else write_run_files(spec, task, variant, prompt, cfg, plugin)
    agent_tmp = spec.work_dir / AGENT_TMP_NAME
    agent_tmp.mkdir(parents=True, exist_ok=True)
    overrides = agent_overrides(spec, task, variant, cfg, agent_tmp)
    env, removed = environment.child_environment(os.environ, overrides)
    write_json(spec.result_dir / "env.json", environment.run_snapshot(base_snapshot, plugin, removed, None if codex else INSTRUCTION_ISOLATION))
    run: dict[str, Any] = {
        "run_id": spec.run_id, "task": spec.task, "variant": spec.variant, "rep": spec.rep, "plugin": plugin,
        "attempts": prior_attempts(spec) + 1, "base_commit": None, "host": spec.host,
        "expected_model": command.main_model(variant, spec.host), **({"cap_exception": variant["cap_exception"]} if variant.get("cap_exception") else {}),
    }
    try:
        run["base_commit"] = load_graders().materialize_fixture(task, cfg.fixtures_root, cfg.tasks_root, spec.repo)
    except Exception as error:  # noqa: BLE001 - any failure to build the work repo is an infrastructure failure
        failed = {**run, "status": STATUS_INFRA_FAILED, "error": f"materialize failed: {error}"}
        write_json(spec.result_dir / "run.json", failed)
        return failed
    if codex:
        try:
            run["setup"] = codex_host.prepare_home(cfg, spec.result_dir, plugin["path"], env, repo=spec.repo)
        except codex_host.CodexSetupError as error:
            failed = {**run, "status": STATUS_INFRA_FAILED, "error": f"codex setup failed: {error}"}
            write_json(spec.result_dir / "run.json", failed)
            return failed
    sheet = command.task_sheet(cfg.tasks_root, task)
    if sheet is None:
        proc = run_agent(
            argv, spec.repo, env, spec.result_dir / "stream.jsonl", spec.result_dir / "stderr.txt",
            float(task["limits"]["wall_seconds"]), cfg.sigint_grace, cfg.sigterm_grace, interrupt=interrupt,
        )
    else:
        proc = converse.run_turns(
            argv, host=spec.host, cwd=spec.repo, env=env, result_dir=spec.result_dir, sheet_path=sheet,
            wall_seconds=float(task["limits"]["wall_seconds"]), sigint_grace=cfg.sigint_grace, sigterm_grace=cfg.sigterm_grace,
            interrupt=interrupt,
        )
    if codex:
        return finish_codex_run(spec, task, run, proc, cfg, interrupt)
    return finish_run(spec, task, run, proc, cfg, interrupt)


def parse_moment(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def recollect(spec: RunSpec, run: dict[str, Any]) -> dict[str, Any]:
    """Copy the host records again (Claude, subagents, runner sessions, Codex rollouts); return the updated run record."""
    directory, previous = spec.result_dir, run.get("collected") or {}
    if spec.host == HOST_CODEX:
        copied = codex_host.copy_rollouts(directory)
        _, calls = codex_host.label_rollouts(collect.load_rollouts(directory / "codex", {}))
        main_calls = [call for call in calls if call["source"] == "main"]
        collect.collect_assignments(main_calls, directory / "assignments", spec.repo)
        names = collect.collect_runner_transcripts(main_calls, directory / "transcripts" / "runner")
        updated = {**run, "collected": {"codex": copied or previous.get("codex", []), "runner": names or previous.get("runner", [])}}
        write_json(directory / "run.json", updated)
        return updated
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
    result = analyze(spec, task, run, cfg, graders)
    updated = {key: value for key, value in run.items() if key not in ("grade_error", "cap_violation")}
    if result.get("cap_violation"):
        updated["cap_violation"] = result["cap_violation"]
    if updated != run:
        write_json(spec.result_dir / "run.json", updated)
    return updated
