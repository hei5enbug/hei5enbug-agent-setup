"""Campaign scheduling: matrix expansion, parallel execution, resume, and the usage-limit stop."""

from __future__ import annotations

import shlex
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, TextIO

from . import command, environment, plugin_export
from .config import EXIT_USAGE_LIMIT, STATUS_RUNNING, STATUS_USAGE_LIMITED, HarnessConfig
from .matrix import CampaignState, RunSpec, campaign_dir, make_spec, move_aside, plan_matrix, read_json, runs_to_start, write_json
from .runner import execute_run, regrade_run

RunFunction = Callable[..., dict[str, Any]]


def discover_tasks(cfg: HarnessConfig) -> list[str]:
    return sorted(path.stem for path in cfg.tasks_root.glob("T*.json"))


def load_plan(cfg: HarnessConfig, task_ids: list[str], variant_names: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    tasks = {task_id: command.load_task(cfg.tasks_root, task_id) for task_id in task_ids}
    variants = {name: command.load_variant(cfg.variants_root, name) for name in variant_names}
    return tasks, variants


def build_specs(cfg: HarnessConfig, campaign: str, task_ids: list[str], variant_names: list[str], reps: int) -> list[RunSpec]:
    return [make_spec(cfg.run_root, campaign, task, variant, rep) for rep, task, variant in plan_matrix(task_ids, variant_names, reps)]


def print_plan(out: TextIO, cfg: HarnessConfig, specs: list[RunSpec], tasks: dict[str, dict], variants: dict[str, dict]) -> None:
    plugin_paths = {}
    for name, variant in variants.items():
        sha = plugin_export.resolve_ref(cfg.repo_root, variant["ref"])
        plugin_paths[name] = str(plugin_export.export_dir(cfg.run_root, sha))
    out.write(f"planned runs: {len(specs)}\n")
    for index, spec in enumerate(specs, start=1):
        task, variant = tasks[spec.task], variants[spec.variant]
        prompt = command.read_prompt(cfg.tasks_root, task)
        argv = command.build_command(cfg, task, variant, prompt, plugin_paths[spec.variant], spec.result_dir)
        out.write(f"\n[{index}] {spec.run_id} wall={task['limits']['wall_seconds']}s cwd={spec.repo}\n{shlex.join(argv)}\n")


def run_campaign(
    cfg: HarnessConfig, campaign: str, task_ids: list[str], variant_names: list[str], reps: int, parallel: int,
    only_rerun: frozenset[str], out: TextIO, run_function: RunFunction = execute_run,
) -> int:
    """Execute the matrix; returns 75 when a usage limit stopped it, else 0."""
    tasks, variants = load_plan(cfg, task_ids, variant_names)
    specs = build_specs(cfg, campaign, task_ids, variant_names, reps)
    base = campaign_dir(cfg.run_root, campaign)
    write_campaign_file(cfg, base, campaign, task_ids, variant_names, reps)
    state = CampaignState(base / "state.json")
    todo, skipped = runs_to_start(specs, state.snapshot(), only_rerun)
    out.write(f"{len(todo)} to run, {len(skipped)} already complete\n")
    plugins = {name: plugin_export.export_plugin(cfg.repo_root, cfg.run_root, variant["ref"]) for name, variant in variants.items()}
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


def write_campaign_file(cfg: HarnessConfig, base: Any, campaign: str, tasks: list[str], variants: list[str], reps: int) -> None:
    path = base / "campaign.json"
    existing = read_json(path, {})
    created = existing.get("created") or datetime.now(timezone.utc).isoformat()
    head = environment.run_command(["git", "rev-parse", "HEAD"], cfg.repo_root)
    write_json(path, {
        "campaign": campaign, "tasks": tasks, "variants": variants, "reps": reps, "created": created,
        "order": [f"{task}-{variant}-r{rep}" for rep, task, variant in plan_matrix(tasks, variants, reps)],
        "harness_git_sha": head,
    })


def regrade_campaign(cfg: HarnessConfig, campaign: str, run_ids: frozenset[str], out: TextIO, graders: Any = None) -> int:
    """Re-grade finished runs of a campaign from their saved work repos."""
    base = campaign_dir(cfg.run_root, campaign)
    state = CampaignState(base / "state.json").snapshot()
    done = 0
    for run_id in sorted(state):
        task_id, variant, rep = parse_run_id(run_id)
        if run_ids and run_id not in run_ids:
            continue
        spec = make_spec(cfg.run_root, campaign, task_id, variant, rep)
        task = command.load_task(cfg.tasks_root, task_id)
        result = regrade_run(spec, task, cfg, graders)
        out.write(f"{run_id}: {'regraded' if result else 'skipped'}\n")
        done += 1 if result else 0
    return 0 if done else 1


def parse_run_id(run_id: str) -> tuple[str, str, int]:
    head, _, rep = run_id.rpartition("-r")
    task, _, variant = head.partition("-")
    return task, variant, int(rep)
