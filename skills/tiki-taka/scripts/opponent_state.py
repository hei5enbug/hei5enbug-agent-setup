from __future__ import annotations

import argparse
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
OPPONENTS = json.loads((PLUGIN_ROOT / "config" / "model-registry.json").read_text(encoding="utf-8"))["opponents"]
CODEX_MODEL = OPPONENTS["codex"]["model"]
CLAUDE_MODEL = OPPONENTS["claude"]["model"]
DEFAULT_EFFORT = OPPONENTS["effort"]
FAST_EFFORT = OPPONENTS["fast_effort"]
DEEP_EFFORT = DEFAULT_EFFORT
STATE_VERSION = "tiki-taka-state-v4"
DEFAULT_MAX_EXCHANGES = 2
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_HEARTBEAT_SECONDS = 60
SYNTHETIC_MODEL = "<synthetic>"


class RunnerError(RuntimeError):
    pass


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def read_required(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise RunnerError(f"저장된 {label} 정보를 읽을 수 없습니다: {error}") from error


def read_integer(path: Path, label: str) -> int:
    value = read_required(path, label)
    try:
        number = int(value)
    except ValueError as error:
        raise RunnerError(f"저장된 {label} 값이 올바르지 않습니다.") from error
    if number < 0:
        raise RunnerError(f"저장된 {label} 값이 올바르지 않습니다.")
    return number


def canonical_directory(value: str, label: str) -> Path:
    try:
        path = Path(value).resolve(strict=True)
    except OSError as error:
        raise RunnerError(f"{label}를 확인할 수 없습니다: {value}") from error
    if not path.is_dir():
        raise RunnerError(f"{label}는 폴더여야 합니다: {value}")
    return path


class StatePaths:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.marker = root / ".tiki-taka-state"
        self.opponent = root / "opponent"
        self.repo = root / "repo"
        self.maximum = root / "max-exchanges"
        self.count = root / "exchange-count"
        self.session = root / "session-id"
        self.model = root / "active-model"
        self.effort = root / "active-effort"
        self.uncertain = root / "uncertain"
        self.progress = root / "progress.json"
        self.lock = root / ".lock"
        self.worker_pid = root / "worker-pid"
        self.worker_exit = root / "worker-exit"
        self.worker_result = root / "worker-result.txt"
        self.worker_log = root / "worker-progress.log"

    def known_names(self) -> set[str]:
        return {
            path.name
            for path in (
                self.marker,
                self.opponent,
                self.repo,
                self.maximum,
                self.count,
                self.session,
                self.model,
                self.effort,
                self.uncertain,
                self.progress,
                self.lock,
                self.worker_pid,
                self.worker_exit,
                self.worker_result,
                self.worker_log,
            )
        }

    def job_paths(self) -> tuple[Path, ...]:
        return (
            self.worker_pid,
            self.worker_exit,
            self.worker_result,
            self.worker_log,
        )


def prepare_state_root(value: str, create: bool) -> StatePaths:
    candidate = Path(value)
    if candidate.is_symlink():
        raise RunnerError("상태 폴더에는 심볼릭 링크를 사용할 수 없습니다.")
    if not candidate.exists():
        if not create:
            raise RunnerError(f"상태 폴더가 없습니다: {candidate}")
        candidate.mkdir(mode=0o700, parents=True)
    if not candidate.is_dir():
        raise RunnerError("상태 경로는 폴더여야 합니다.")
    candidate.chmod(0o700)
    return StatePaths(candidate.resolve(strict=True))


LOCK_WAIT_SECONDS = 10.0


@contextmanager
def state_lock(paths: StatePaths, wait_seconds: float = 0.0) -> Iterator[None]:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            paths.lock.mkdir()
            break
        except FileExistsError as error:
            if time.monotonic() >= deadline:
                raise RunnerError("같은 상태 폴더를 다른 호출이 사용 중입니다.") from error
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            paths.lock.rmdir()
        except FileNotFoundError:
            pass


def validate_limit(value: int) -> int:
    if not 1 <= value <= 5:
        raise RunnerError("교환 한도는 1부터 5까지여야 합니다.")
    return value


def initialize_or_load_state(
    paths: StatePaths,
    args: argparse.Namespace,
) -> tuple[Path, int, int, str]:
    requested_maximum = args.max_exchanges
    requested_effort = FAST_EFFORT if args.fast else DEFAULT_EFFORT

    if paths.marker.exists():
        if read_required(paths.marker, "상태 형식") != STATE_VERSION:
            raise RunnerError("알 수 없는 상태 폴더 형식입니다.")
        stored_opponent = read_required(paths.opponent, "상대")
        if stored_opponent != args.opponent:
            raise RunnerError("처음 지정한 상대와 현재 상대가 다릅니다.")

        stored_repo = canonical_directory(read_required(paths.repo, "작업 폴더"), "작업 폴더")
        requested_repo = canonical_directory(args.repo, "작업 폴더")
        if stored_repo != requested_repo:
            raise RunnerError("처음 지정한 작업 폴더와 현재 경로가 다릅니다.")

        maximum = validate_limit(read_integer(paths.maximum, "교환 한도"))
        if requested_maximum is not None and requested_maximum != maximum:
            raise RunnerError("처음 지정한 교환 한도와 현재 값이 다릅니다.")

        effort = read_required(paths.effort, "사고 강도")
        if effort not in (DEFAULT_EFFORT, FAST_EFFORT):
            raise RunnerError("저장된 사고 강도가 올바르지 않습니다.")
        if args.fast and effort != FAST_EFFORT:
            raise RunnerError("처음 지정한 사고 강도와 현재 값이 다릅니다.")
        if args.deep and effort != DEEP_EFFORT:
            raise RunnerError("처음 지정한 사고 강도와 현재 값이 다릅니다.")
        count = read_integer(paths.count, "교환 수")
        return stored_repo, maximum, count, effort

    allowed_before_initialization = {
        paths.lock.name,
        paths.worker_pid.name,
        paths.worker_exit.name,
        paths.worker_result.name,
        paths.worker_log.name,
    }
    unexpected = [
        entry.name
        for entry in paths.root.iterdir()
        if entry.name not in allowed_before_initialization
    ]
    if unexpected:
        raise RunnerError("새 상태 폴더는 비어 있어야 합니다.")

    repo = canonical_directory(args.repo, "작업 폴더")
    maximum = validate_limit(requested_maximum or DEFAULT_MAX_EXCHANGES)
    count = 0
    effort = requested_effort
    atomic_write_text(paths.opponent, args.opponent + "\n")
    atomic_write_text(paths.repo, str(repo) + "\n")
    atomic_write_text(paths.maximum, f"{maximum}\n")
    atomic_write_text(paths.count, "0\n")
    atomic_write_text(paths.effort, effort + "\n")
    atomic_write_text(paths.marker, STATE_VERSION + "\n")
    return repo, maximum, count, effort


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_optional_integer(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, UnicodeError, ValueError):
        return None


def active_detached_job(paths: StatePaths) -> bool:
    if paths.worker_exit.exists():
        return False
    pid = read_optional_integer(paths.worker_pid)
    return pid is not None and process_exists(pid)


def ensure_no_pending_job(paths: StatePaths) -> None:
    if active_detached_job(paths):
        raise RunnerError("분리 실행이 진행 중입니다. --wait로 다시 연결하세요.")
    if any(path.exists() for path in paths.job_paths()):
        raise RunnerError("수집하지 않은 분리 실행 결과가 있습니다. --wait를 실행하세요.")


def helper_path(name: str) -> Path:
    return Path(__file__).resolve().with_name(name)
