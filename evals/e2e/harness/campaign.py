"""Campaign scheduling: matrix expansion, parallel execution, resume, and the usage-limit stop."""

from __future__ import annotations

import secrets
import shlex
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, TextIO

from . import caps, codex_host, command, environment, inputs, plugin_export
from .config import EXIT_USAGE_LIMIT, HOST_CLAUDE, STATUS_RUNNING, STATUS_USAGE_LIMITED, HarnessConfig
from .matrix import (
    CampaignState, RunSpec, campaign_dir, make_spec, move_aside, parse_run_id, plan_runs, read_json, run_id_for, runs_to_start,
    write_json,
)
from .runner import execute_run, regrade_run

RunFunction = Callable[..., dict[str, Any]]


def discover_tasks(cfg: HarnessConfig) -> list[str]:
    return sorted(path.stem for path in cfg.tasks_root.glob("T*.json"))


def load_plan(cfg: HarnessConfig, task_ids: list[str], variant_names: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Load tasks and variants; a campaign whose roles could start a model outside the cap is rejected here, also by a dry run."""
    tasks = {task_id: command.load_task(cfg.tasks_root, task_id) for task_id in task_ids}
    variants = {name: command.load_variant(cfg.variants_root, name) for name in variant_names}
    caps.check_campaign(cfg, variants.values())
    return tasks, variants


def build_specs(
    cfg: HarnessConfig, campaign: str, task_ids: list[str], variant_names: list[str], reps: int, hosts: list[str] | None = None,
) -> list[RunSpec]:
    return [make_spec(cfg.run_root, campaign, task, variant, rep, host)
            for rep, task, variant, host in plan_runs(task_ids, variant_names, hosts or [HOST_CLAUDE], reps)]


def print_plan(out: TextIO, cfg: HarnessConfig, specs: list[RunSpec], tasks: dict[str, dict], variants: dict[str, dict]) -> None:
    plugin_paths = {}
    for name, variant in variants.items():
        sha = plugin_export.resolve_ref(cfg.repo_root, variant["ref"])
        plugin_paths[name] = str(plugin_export.export_dir(cfg.run_root, sha))
    out.write(f"planned runs: {len(specs)}\n")
    for index, spec in enumerate(specs, start=1):
        task, variant = tasks[spec.task], variants[spec.variant]
        prompt = command.read_prompt(cfg.tasks_root, task)
        header = f"\n[{index}] {spec.run_id} host={spec.host} wall={task['limits']['wall_seconds']}s cwd={spec.repo}\n"
        if spec.host == HOST_CLAUDE:
            argv = command.build_command(cfg, task, variant, prompt, plugin_paths[spec.variant], spec.result_dir)
            out.write(f"{header}{shlex.join(argv)}\n")
            continue
        argv = codex_host.build_codex_command(cfg, variant, prompt, spec.repo)
        env = " ".join(f"{name}={shlex.quote(value)}" for name, value in codex_host.host_env(spec.result_dir).items())
        setup = "".join(f"setup: {env} {shlex.join(step)}\n" for step in codex_host.setup_commands(cfg, plugin_paths[spec.variant]))
        out.write(f"{header}{setup}{env} {shlex.join(argv)} < /dev/null\n")


def run_campaign(
    cfg: HarnessConfig, campaign: str, task_ids: list[str], variant_names: list[str], reps: int, parallel: int,
    only_rerun: frozenset[str], out: TextIO, run_function: RunFunction = execute_run, allow_changed_inputs: bool = False,
    hosts: list[str] | None = None,
) -> int:
    """Execute the matrix; returns 75 when a usage limit stopped it, else 0. Changed inputs refuse a resume."""
    tasks, variants = load_plan(cfg, task_ids, variant_names)
    hosts = hosts or [HOST_CLAUDE]
    specs = build_specs(cfg, campaign, task_ids, variant_names, reps, hosts)
    base = campaign_dir(cfg.run_root, campaign)
    plugins = {name: plugin_export.export_plugin(cfg.repo_root, cfg.run_root, variant["ref"]) for name, variant in variants.items()}
    current = inputs.compute_inputs(cfg, task_ids, variant_names, plugins)
    changes = inputs.check_inputs(read_json(base / "campaign.json", {}).get("inputs"), current, allow_changed_inputs)
    write_campaign_file(cfg, base, campaign, task_ids, variant_names, reps, current, changes, hosts)
    state = CampaignState(base / "state.json")
    todo, skipped = runs_to_start(specs, state.snapshot(), only_rerun)
    out.write(f"{len(todo)} to run, {len(skipped)} already complete\n")
    snapshot = environment.capture_base(cfg.claude_bin, cfg.repo_root)
    stop = threading.Event()

    def job(spec: RunSpec) -> None:
        if stop.is_set():
            return
        move_aside(spec)
        state.set(spec.run_id, STATUS_RUNNING)
        try:
            run = run_function(spec, tasks[spec.task], variants[spec.variant], plugins[spec.variant], cfg, snapshot)
        except Exception as error:  # noqa: BLE001 - a crashed job must not take the rest of the matrix down
            out.write(f"{spec.run_id}: infra_failed ({error})\n")
            state.set(spec.run_id, "infra_failed")
            return
        state.set(spec.run_id, run["status"])
        out.write(f"{spec.run_id}: {run['status']}\n")
        if run["status"] == STATUS_USAGE_LIMITED:
            stop.set()

    with ThreadPoolExecutor(max_workers=max(parallel, 1)) as pool:
        list(pool.map(job, todo))
    if stop.is_set():
        out.write(f"usage limit reached; resume with the same command: run --campaign {campaign}\n")
        return EXIT_USAGE_LIMIT
    return 0


def write_campaign_file(
    cfg: HarnessConfig, base: Any, campaign: str, tasks: list[str], variants: list[str], reps: int,
    current_inputs: dict[str, Any], changes: list[str], hosts: list[str] | None = None,
) -> None:
    """Write campaign.json, keeping what an earlier run stored (creation time, rubric salt, input history)."""
    path = base / "campaign.json"
    existing = read_json(path, {})
    created = existing.get("created") or datetime.now(timezone.utc).isoformat()
    head = environment.run_command(["git", "rev-parse", "HEAD"], cfg.repo_root)
    history = list(existing.get("input_changes", []))
    if changes:
        history.append({"at": datetime.now(timezone.utc).isoformat(), "changed": changes,
                        "previous_fingerprint": (existing.get("inputs") or {}).get("fingerprint"),
                        "fingerprint": current_inputs["fingerprint"]})
    stored = existing.get("inputs") or {}
    merged_inputs = {
        "variant_shas": {**stored.get("variant_shas", {}), **current_inputs["variant_shas"]},
        "parts": {**stored.get("parts", {}), **current_inputs["parts"]},
        "fingerprint": current_inputs["fingerprint"],
    } if stored else current_inputs
    write_json(path, {
        **existing,
        "campaign": campaign, "tasks": tasks, "variants": variants, "reps": reps, "created": created,
        "hosts": hosts or [HOST_CLAUDE],
        "order": [run_id_for(task, variant, rep, host) for rep, task, variant, host in plan_runs(tasks, variants, hosts or [HOST_CLAUDE], reps)],
        "harness_git_sha": head, "inputs": merged_inputs, "input_changes": history,
        "rubric_salt": existing.get("rubric_salt") or secrets.token_hex(16),
    })


def regrade_campaign(
    cfg: HarnessConfig, campaign: str, run_ids: frozenset[str], out: TextIO, graders: Any = None, recollect: bool = False,
) -> int:
    """Re-grade finished runs of a campaign from their saved work repos, copying the host records again on request."""
    base = campaign_dir(cfg.run_root, campaign)
    state = CampaignState(base / "state.json").snapshot()
    done = 0
    for run_id in sorted(state):
        task_id, variant, rep, host = parse_run_id(run_id)
        if run_ids and run_id not in run_ids:
            continue
        spec = make_spec(cfg.run_root, campaign, task_id, variant, rep, host)
        task = command.load_task(cfg.tasks_root, task_id)
        result = regrade_run(spec, task, cfg, graders, recollect)
        out.write(f"{run_id}: {'regraded' if result else 'skipped'}\n")
        done += 1 if result else 0
    return 0 if done else 1

