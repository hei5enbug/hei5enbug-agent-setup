from __future__ import annotations

import argparse
import subprocess
import sys

from opponent_state import (
    RunnerError,
    StatePaths,
    active_detached_job,
    helper_path,
    read_integer,
    read_required,
    state_lock,
)


def detached_helper_args(paths: StatePaths) -> list[str]:
    return [
        "--pid-file",
        str(paths.worker_pid),
        "--exit-file",
        str(paths.worker_exit),
        "--result-file",
        str(paths.worker_result),
        "--progress-log",
        str(paths.worker_log),
        "--uncertain-file",
        str(paths.uncertain),
    ]


def collect_job(paths: StatePaths, collect: bool) -> int:
    command = [
        sys.executable,
        str(helper_path("detached_job.py")),
        "wait",
        *detached_helper_args(paths),
    ]
    if collect:
        command.append("--collect")
    return subprocess.run(command, check=False).returncode


def show_status(args: argparse.Namespace, paths: StatePaths) -> int:
    if paths.marker.exists():
        opponent = read_required(paths.opponent, "상대")
        maximum = read_integer(paths.maximum, "교환 한도")
        count = read_integer(paths.count, "교환 수")
        model = paths.model.read_text(encoding="utf-8").strip() if paths.model.exists() else "없음"
        effort = read_required(paths.effort, "사고 강도")
        state = "불확실" if paths.uncertain.exists() else "정상"
        print(
            f"opponent={opponent} model={model} effort={effort} "
            f"exchanges={count}/{maximum} state={state}"
        )
    elif not paths.worker_pid.exists():
        raise RunnerError("tiki-taka 상태 폴더가 아닙니다.")

    command = [
        sys.executable,
        str(helper_path("detached_job.py")),
        "status",
        "--pid-file",
        str(paths.worker_pid),
        "--exit-file",
        str(paths.worker_exit),
        "--progress-file",
        str(paths.progress),
    ]
    return subprocess.run(command, check=False).returncode


def finish_state(paths: StatePaths) -> int:
    if active_detached_job(paths):
        raise RunnerError("분리 실행이 진행 중이어서 상태를 정리하지 않았습니다.")
    if not paths.marker.exists():
        raise RunnerError("tiki-taka 상태 폴더가 아닙니다.")

    with state_lock(paths):
        unexpected = [
            entry.name
            for entry in paths.root.iterdir()
            if entry.name not in paths.known_names()
        ]
        if unexpected:
            raise RunnerError("알 수 없는 파일이 있어 상태 폴더를 지우지 않았습니다.")
        skipped: list[str] = []
        for entry in list(paths.root.iterdir()):
            if entry == paths.lock:
                continue
            # Only plain files that this runner wrote are removed. A directory
            # or symbolic link with a known name is not ours to delete.
            if entry.is_symlink() or not entry.is_file():
                skipped.append(entry.name)
                continue
            entry.unlink(missing_ok=True)
        if skipped:
            raise RunnerError(
                "일반 파일이 아닌 항목이 있어 상태 폴더를 지우지 않았습니다: "
                + ", ".join(sorted(skipped))
            )
    paths.root.rmdir()
    print("토론 상태를 정리했습니다.")
    return 0
