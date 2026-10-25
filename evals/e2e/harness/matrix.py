"""Run matrix ordering, campaign state, and resume handling."""

from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import FINISHED_STATUSES, STATUS_PENDING


@dataclass(frozen=True)
class RunSpec:
    task: str
    variant: str
    rep: int
    run_id: str
    result_dir: Path
    work_dir: Path

    @property
    def repo(self) -> Path:
        return self.work_dir / "repo"

    @property
    def base_dir(self) -> Path:
        """The campaign folder this run belongs to."""
        return self.work_dir.parent.parent


def run_id_for(task: str, variant: str, rep: int) -> str:
    return f"{task}-{variant}-r{rep}"


def campaign_dir(run_root: Path, campaign: str) -> Path:
    return run_root / campaign


def make_spec(run_root: Path, campaign: str, task: str, variant: str, rep: int) -> RunSpec:
    base = campaign_dir(run_root, campaign)
    run_id = run_id_for(task, variant, rep)
    return RunSpec(task, variant, rep, run_id, base / "results" / task / variant / f"rep{rep}", base / "work" / run_id)


def plan_matrix(tasks: list[str], variants: list[str], reps: int) -> list[tuple[int, str, str]]:
    """Reps outer, tasks middle, variants inner; the variant start rotates per (rep, task) so pairs alternate ABAB/BABA."""
    order: list[tuple[int, str, str]] = []
    for rep in range(1, reps + 1):
        for task_index, task in enumerate(tasks):
            shift = ((rep - 1) * len(tasks) + task_index) % len(variants)
            rotated = variants[shift:] + variants[:shift]
            order.extend((rep, task, variant) for variant in rotated)
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
