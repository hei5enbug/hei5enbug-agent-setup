"""Run matrix ordering, campaign state, and resume handling."""

from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import FINISHED_STATUSES, HOST_CLAUDE, HOST_CODEX, STATUS_PENDING


@dataclass(frozen=True)
class RunSpec:
    task: str
    variant: str
    rep: int
    run_id: str
    result_dir: Path
    work_dir: Path
    host: str = HOST_CLAUDE

    @property
    def repo(self) -> Path:
        return self.work_dir / "repo"

    @property
    def base_dir(self) -> Path:
        """The campaign folder this run belongs to."""
        return self.work_dir.parent.parent


def run_id_for(task: str, variant: str, rep: int, host: str = HOST_CLAUDE) -> str:
    """`<task>-<variant>-r<rep>` for Claude Code, `<task>-<variant>-codex-r<rep>` for another host."""
    return f"{task}-{variant}-{host}-r{rep}" if host != HOST_CLAUDE else f"{task}-{variant}-r{rep}"


def parse_run_id(run_id: str) -> tuple[str, str, int, str]:
    """(task, variant, rep, host) of a run id."""
    head, _, rep = run_id.rpartition("-r")
    task, _, variant = head.partition("-")
    if variant.endswith(f"-{HOST_CODEX}"):
        return task, variant[: -len(HOST_CODEX) - 1], int(rep), HOST_CODEX
    return task, variant, int(rep), HOST_CLAUDE


def campaign_dir(run_root: Path, campaign: str) -> Path:
    return run_root / campaign


def make_spec(run_root: Path, campaign: str, task: str, variant: str, rep: int, host: str = HOST_CLAUDE) -> RunSpec:
    """Claude Code runs keep `results/<task>/<variant>/rep<k>`; another host's runs go below `<variant>/<host>/`."""
    base = campaign_dir(run_root, campaign)
    run_id = run_id_for(task, variant, rep, host)
    folder = base / "results" / task / variant / (host if host != HOST_CLAUDE else "") / f"rep{rep}"
    return RunSpec(task, variant, rep, run_id, folder, base / "work" / run_id, host)


def plan_matrix(tasks: list[str], variants: list[str], reps: int) -> list[tuple[int, str, str]]:
    """Reps outer, tasks middle, variants inner; the variant start rotates per (rep, task) so pairs alternate ABAB/BABA."""
    order: list[tuple[int, str, str]] = []
    for rep in range(1, reps + 1):
        for task_index, task in enumerate(tasks):
            shift = ((rep - 1) * len(tasks) + task_index) % len(variants)
            rotated = variants[shift:] + variants[:shift]
            order.extend((rep, task, variant) for variant in rotated)
    return order


def plan_runs(tasks: list[str], variants: list[str], hosts: list[str], reps: int) -> list[tuple[int, str, str, str]]:
    """Like `plan_matrix`, with each variant paired with each host; the (variant, host) start rotates per (rep, task)."""
    combos = [(variant, host) for variant in variants for host in hosts]
    order: list[tuple[int, str, str, str]] = []
    for rep in range(1, reps + 1):
        for task_index, task in enumerate(tasks):
            shift = ((rep - 1) * len(tasks) + task_index) % len(combos)
            order.extend((rep, task, variant, host) for variant, host in combos[shift:] + combos[:shift])
    return order


WORK_ARCHIVE_NAME = "work"


def attempts_dir(spec: RunSpec) -> Path:
    return spec.result_dir.parent / "attempts" / f"rep{spec.rep}"


def prior_attempts(spec: RunSpec) -> int:
    directory = attempts_dir(spec)
    return sum(1 for item in directory.iterdir() if item.is_dir()) if directory.is_dir() else 0


def move_aside(spec: RunSpec) -> Path | None:
    """Move an existing result dir and its work dir into attempts/rep<k>/<n>/ (as `work/`) and return that folder."""
    if not spec.result_dir.exists():
        return None
    target = attempts_dir(spec) / str(prior_attempts(spec) + 1)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(spec.result_dir), str(target))
    if spec.work_dir.exists():
        shutil.move(str(spec.work_dir), str(target / WORK_ARCHIVE_NAME))
    return target


def runs_to_start(
    specs: Iterable[RunSpec], state: dict[str, str], only_rerun: frozenset[str] = frozenset(),
) -> tuple[list[RunSpec], list[RunSpec]]:
    """Split planned runs into those to start and those skipped as complete."""
    start: list[RunSpec] = []
    skipped: list[RunSpec] = []
    for spec in specs:
        finished = state.get(spec.run_id, STATUS_PENDING) in FINISHED_STATUSES
        if finished and spec.run_id not in only_rerun:
            skipped.append(spec)
        else:
            start.append(spec)
    return start, skipped


class CampaignState:
    """run_id -> status, persisted atomically after each change."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                loaded = {}
            self._data = {str(k): str(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._data)

    def set(self, run_id: str, status: str) -> None:
        with self._lock:
            self._data = {**self._data, run_id: status}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temp, self.path)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
