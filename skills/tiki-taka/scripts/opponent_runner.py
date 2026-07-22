#!/usr/bin/env python3
"""tiki-taka 반대쪽 세션과 분리 실행 상태를 관리한다."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


CODEX_MODEL = "gpt-5.6-sol"
CLAUDE_MODEL = "claude-fable-5"
CLAUDE_FALLBACK = "claude-opus-4-8"
DEFAULT_EFFORT = "xhigh"
FAST_EFFORT = "high"
DEEP_EFFORT = DEFAULT_EFFORT
STATE_VERSION = "tiki-taka-state-v3"
DEFAULT_MAX_EXCHANGES = 2
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_HEARTBEAT_SECONDS = 60
QUOTA_PATTERN = re.compile(
    r"reached your .*limit|limit[.].*/model to switch", re.IGNORECASE
)


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
        self.host = root / "host"
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
                self.host,
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


@contextmanager
def state_lock(paths: StatePaths) -> Iterator[None]:
    try:
        paths.lock.mkdir()
    except FileExistsError as error:
        raise RunnerError("같은 상태 폴더를 다른 호출이 사용 중입니다.") from error
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
        stored_host = read_required(paths.host, "호스트")
        if stored_host != args.host:
            raise RunnerError("처음 지정한 호스트와 현재 호스트가 다릅니다.")

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
    atomic_write_text(paths.host, args.host + "\n")
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


def supervisor_command(
    provider: str,
    repo: Path,
    prompt: Path,
    output: Path,
    events: Path,
    log: Path,
    paths: StatePaths,
    exchange: int,
    maximum: int,
    model: str,
    args: argparse.Namespace,
    participant_command: list[str],
) -> list[str]:
    return [
        sys.executable,
        str(helper_path("stream_agent.py")),
        "--provider",
        provider,
        "--repo",
        str(repo),
        "--prompt-file",
        str(prompt),
        "--output-file",
        str(output),
        "--events-file",
        str(events),
        "--log-file",
        str(log),
        "--progress-file",
        str(paths.progress),
        "--uncertain-file",
        str(paths.uncertain),
        "--exchange",
        str(exchange),
        "--max-exchanges",
        str(maximum),
        "--model",
        model,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--heartbeat-seconds",
        str(args.heartbeat_seconds),
        "--",
        *participant_command,
    ]


def extract_codex_session(events: Path) -> str:
    with events.open(encoding="utf-8") as source:
        for line in source:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "thread.started":
                continue
            session_id = str(event.get("thread_id", ""))
            try:
                uuid.UUID(session_id)
            except ValueError:
                continue
            return session_id
    raise RunnerError("Codex 대화 식별자를 읽지 못했습니다.")


def extract_claude_model(events: Path, fallback: str) -> str:
    try:
        with events.open(encoding="utf-8") as source:
            for line in source:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                model = event.get("model")
                if model is None and isinstance(event.get("message"), dict):
                    model = event["message"].get("model")
                if model in (CLAUDE_MODEL, CLAUDE_FALLBACK):
                    return str(model)
    except OSError:
        pass
    return fallback


def claude_result_is_error(events: Path) -> bool:
    try:
        with events.open(encoding="utf-8") as source:
            for line in source:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(event, dict)
                    and event.get("type") == "result"
                    and event.get("is_error") is True
                ):
                    return True
    except OSError:
        return False
    return False


def quota_message_found(output: Path, log: Path) -> bool:
    for path in (output, log):
        try:
            if QUOTA_PATTERN.search(path.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def show_failure_log(log: Path) -> None:
    try:
        data = log.read_bytes()[-4096:]
    except OSError:
        return
    if data:
        print(data.decode("utf-8", errors="replace"), file=sys.stderr, end="")


def run_supervised(command: list[str], log: Path) -> None:
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        show_failure_log(log)
        raise RunnerError(f"반대쪽 에이전트 호출이 실패했습니다({result.returncode}).")


def codex_participant_command(
    repo: Path,
    output: Path,
    effort: str,
    session_id: str,
) -> list[str]:
    if not session_id:
        return [
            "codex",
            "exec",
            "-m",
            CODEX_MODEL,
            "-c",
            f"model_reasoning_effort={effort}",
            "-s",
            "read-only",
            "-C",
            str(repo),
            "--json",
            "-o",
            str(output),
            "-",
        ]
    return [
        "codex",
        "exec",
        "resume",
        "-m",
        CODEX_MODEL,
        "-c",
        f"model_reasoning_effort={effort}",
        "-c",
        'sandbox_mode="read-only"',
        "--json",
        "-o",
        str(output),
        session_id,
        "-",
    ]


def claude_participant_command(
    effort: str,
    session_id: str,
    active_model: str,
    first_call: bool,
) -> list[str]:
    command = ["claude", "-p"]
    if first_call:
        command.extend(
            [
                "--session-id",
                session_id,
                "--model",
                CLAUDE_MODEL,
                "--fallback-model",
                CLAUDE_FALLBACK,
            ]
        )
    else:
        command.extend(["--resume", session_id, "--model", active_model])
        if active_model == CLAUDE_MODEL:
            command.extend(["--fallback-model", CLAUDE_FALLBACK])
    command.extend(
        [
            "--effort",
            effort,
            "--permission-mode",
            "plan",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
    )
    return command


def invoke_opponent(
    args: argparse.Namespace,
    paths: StatePaths,
    repo: Path,
    maximum: int,
    count: int,
    effort: str,
    prompt_text: str,
) -> str:
    if count >= maximum:
        raise RunnerError(f"최대 {maximum}교환에 도달했습니다.")
    if paths.uncertain.exists():
        raise RunnerError("응답 수신 여부가 불확실합니다. 새 복구 상태를 사용하세요.")

    call_dir = Path(tempfile.mkdtemp(prefix=".call.", dir=paths.root))
    prompt = call_dir / "prompt.txt"
    output = call_dir / "output.txt"
    events = call_dir / "events.jsonl"
    log = call_dir / "participant.log"
    prompt.write_text(prompt_text, encoding="utf-8")
    prompt.chmod(0o600)
    session_id = paths.session.read_text(encoding="utf-8").strip() if paths.session.exists() else ""

    try:
        if args.host == "claude":
            participant = codex_participant_command(repo, output, effort, session_id)
            command = supervisor_command(
                "codex",
                repo,
                prompt,
                output,
                events,
                log,
                paths,
                count + 1,
                maximum,
                CODEX_MODEL,
                args,
                participant,
            )
            run_supervised(command, log)
            if not session_id:
                try:
                    session_id = extract_codex_session(events)
                except RunnerError:
                    atomic_write_text(
                        paths.uncertain,
                        "Codex 대화 식별자를 확인할 수 없습니다.\n",
                    )
                    raise
            active_model = CODEX_MODEL
        else:
            first_call = not session_id
            if first_call:
                session_id = str(uuid.uuid4())
                active_model = CLAUDE_MODEL
            else:
                active_model = read_required(paths.model, "상대 모델")
                if active_model not in (CLAUDE_MODEL, CLAUDE_FALLBACK):
                    raise RunnerError("저장된 Claude 모델이 허용된 값과 다릅니다.")

            participant = claude_participant_command(
                effort,
                session_id,
                active_model,
                first_call,
            )
            command = supervisor_command(
                "claude",
                repo,
                prompt,
                output,
                events,
                log,
                paths,
                count + 1,
                maximum,
                active_model,
                args,
                participant,
            )
            run_supervised(command, log)
            active_model = extract_claude_model(events, active_model)

            result_is_error = claude_result_is_error(events)
            quota_error = quota_message_found(output, log)
            if active_model == CLAUDE_MODEL and quota_error:
                print(
                    "[tiki-taka] Claude 기본 모델 한도 감지 · 대체 모델로 한 번 재개",
                    file=sys.stderr,
                    flush=True,
                )
                prompt.write_text(
                    "앞선 요청은 모델 한도 안내 때문에 처리되지 않았습니다.\n"
                    "같은 세션의 바로 앞 사용자 요청에 답하세요. 요청을 되풀이하지 마세요.\n",
                    encoding="utf-8",
                )
                output.unlink(missing_ok=True)
                events.unlink(missing_ok=True)
                log.unlink(missing_ok=True)
                participant = claude_participant_command(
                    effort,
                    session_id,
                    CLAUDE_FALLBACK,
                    False,
                )
                command = supervisor_command(
                    "claude",
                    repo,
                    prompt,
                    output,
                    events,
                    log,
                    paths,
                    count + 1,
                    maximum,
                    CLAUDE_FALLBACK,
                    args,
                    participant,
                )
                run_supervised(command, log)
                active_model = CLAUDE_FALLBACK
                result_is_error = claude_result_is_error(events)

            if result_is_error:
                atomic_write_text(
                    paths.uncertain,
                    "Claude가 오류 결과를 반환했습니다.\n",
                )
                raise RunnerError("Claude가 오류 결과를 반환했습니다.")

        try:
            response = output.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            atomic_write_text(paths.uncertain, "반대쪽 응답을 읽을 수 없습니다.\n")
            raise RunnerError(f"반대쪽 응답을 읽을 수 없습니다: {error}") from error
        if not response.strip():
            atomic_write_text(paths.uncertain, "반대쪽 응답이 비어 있습니다.\n")
            raise RunnerError("반대쪽 에이전트가 빈 응답을 반환했습니다.")

        atomic_write_text(paths.session, session_id + "\n")
        atomic_write_text(paths.model, active_model + "\n")
        atomic_write_text(paths.count, f"{count + 1}\n")
        return response
    finally:
        shutil.rmtree(call_dir, ignore_errors=True)


def normal_run(args: argparse.Namespace, paths: StatePaths, prompt_text: str) -> int:
    if not args.worker:
        ensure_no_pending_job(paths)
    with state_lock(paths):
        repo, maximum, count, effort = initialize_or_load_state(paths, args)
        response = invoke_opponent(
            args,
            paths,
            repo,
            maximum,
            count,
            effort,
            prompt_text,
        )
    print(response, end="" if response.endswith("\n") else "\n")
    return 0


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


def worker_runner_command(args: argparse.Namespace, paths: StatePaths) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--host",
        args.host,
        "--state-dir",
        str(paths.root),
        "--repo",
        args.repo,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--heartbeat-seconds",
        str(args.heartbeat_seconds),
    ]
    if args.max_exchanges is not None:
        command.extend(["--max-exchanges", str(args.max_exchanges)])
    if args.fast:
        command.append("--fast")
    if args.deep:
        command.append("--deep")
    return command


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


def launch_detached(
    args: argparse.Namespace,
    paths: StatePaths,
    prompt_text: str,
    wait_after_launch: bool,
) -> int:
    ensure_no_pending_job(paths)
    file_descriptor, prompt_name = tempfile.mkstemp(prefix="tiki-taka-prompt.")
    prompt_path = Path(prompt_name)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as target:
            target.write(prompt_text)
        command = [
            sys.executable,
            str(helper_path("detached_job.py")),
            "launch",
            *detached_helper_args(paths),
            "--prompt-file",
            str(prompt_path),
            "--",
            *worker_runner_command(args, paths),
        ]
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            return result.returncode
        if wait_after_launch:
            return collect_job(paths, collect=True)
        print(f"state_dir={paths.root}")
        return 0
    finally:
        if not paths.worker_pid.exists():
            prompt_path.unlink(missing_ok=True)


def show_status(args: argparse.Namespace, paths: StatePaths) -> int:
    if paths.marker.exists():
        host = read_required(paths.host, "호스트")
        maximum = read_integer(paths.maximum, "교환 한도")
        count = read_integer(paths.count, "교환 수")
        model = paths.model.read_text(encoding="utf-8").strip() if paths.model.exists() else "없음"
        effort = read_required(paths.effort, "사고 강도")
        state = "불확실" if paths.uncertain.exists() else "정상"
        print(
            f"host={host} model={model} effort={effort} "
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
        for entry in list(paths.root.iterdir()):
            if entry == paths.lock:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink(missing_ok=True)
    paths.root.rmdir()
    print("토론 상태를 정리했습니다.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run-opponent.sh",
        description="tiki-taka 반대쪽 전용 세션 실행기",
    )
    parser.add_argument(
        "--host",
        choices=("claude", "codex"),
        required=True,
        help="현재 스킬을 실행 중인 호스트",
    )
    parser.add_argument("--state-dir", help="이번 토론의 고유한 상태 폴더")
    parser.add_argument("--repo", default=os.getcwd(), help="검토할 작업 폴더")
    parser.add_argument("--max-exchanges", type=int, help="최대 교환 수, 기본값 2")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="반대쪽 호출의 최대 실행 시간, 기본값 900초",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=int,
        default=DEFAULT_HEARTBEAT_SECONDS,
        help="진행 상태 출력 간격, 기본값 60초",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="명시적으로 사고 강도를 high로 낮춤",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="이전 호출과의 호환을 위한 xhigh 명시",
    )
    parser.add_argument("--show-config", action="store_true", help="상대 모델 설정 표시")
    parser.add_argument("--status", action="store_true", help="현재 실행 상태 표시")
    parser.add_argument("--watch", action="store_true", help="진행 상태만 계속 표시")
    parser.add_argument("--wait", action="store_true", help="분리 작업에 다시 연결하고 결과 수집")
    parser.add_argument("--finish", action="store_true", help="이번 토론의 로컬 상태 정리")
    parser.add_argument("--detach", action="store_true", help="상대 작업만 분리 실행")
    parser.add_argument(
        "--durable",
        action="store_true",
        help="상대 작업을 분리 실행하고 완료까지 기다림",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return parser


def validate_args(args: argparse.Namespace) -> None:
    modes = (
        args.show_config,
        args.status,
        args.watch,
        args.wait,
        args.finish,
        args.detach,
        args.durable,
    )
    if sum(bool(mode) for mode in modes) > 1:
        raise RunnerError("실행 모드 옵션은 하나만 선택해야 합니다.")
    if args.max_exchanges is not None:
        validate_limit(args.max_exchanges)
    if args.timeout_seconds < 1:
        raise RunnerError("실행 시간 제한은 1초 이상이어야 합니다.")
    if args.heartbeat_seconds < 10:
        raise RunnerError("진행 출력 간격은 10초 이상이어야 합니다.")
    if args.fast and args.deep:
        raise RunnerError("--fast와 --deep은 함께 사용할 수 없습니다.")
    if not args.show_config and not args.state_dir:
        raise RunnerError("--state-dir가 필요합니다.")


def main() -> int:
    args = build_parser().parse_args()
    try:
        validate_args(args)
        effort = FAST_EFFORT if args.fast else DEFAULT_EFFORT
        if args.show_config:
            if args.host == "claude":
                print(f"opponent=codex model={CODEX_MODEL} effort={effort}")
            else:
                print(
                    f"opponent=claude model={CLAUDE_MODEL} "
                    f"fallback={CLAUDE_FALLBACK} effort={effort}"
                )
            return 0

        create = args.detach or args.durable or args.worker or not (
            args.status or args.watch or args.wait or args.finish
        )
        paths = prepare_state_root(args.state_dir, create=create)

        if args.status:
            return show_status(args, paths)
        if args.watch:
            return collect_job(paths, collect=False)
        if args.wait:
            return collect_job(paths, collect=True)
        if args.finish:
            return finish_state(paths)

        prompt_text = sys.stdin.read()
        if not prompt_text.strip():
            raise RunnerError("표준 입력으로 프롬프트를 전달해야 합니다.")
        if args.detach or args.durable:
            return launch_detached(
                args,
                paths,
                prompt_text,
                wait_after_launch=args.durable,
            )
        return normal_run(args, paths, prompt_text)
    except RunnerError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("오류: 현재 호출이 중단되었습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
