#!/usr/bin/env python3
"""분리한 tiki-taka 실행을 시작하고 다시 연결한다."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def command_tail(values: list[str]) -> list[str]:
    command = list(values)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("실행할 작업 명령이 없습니다.")
    return command


def launch(args: argparse.Namespace) -> int:
    command = command_tail(args.command)
    worker_command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "worker",
        "--prompt-file",
        args.prompt_file,
        "--result-file",
        args.result_file,
        "--progress-log",
        args.progress_log,
        "--exit-file",
        args.exit_file,
        "--uncertain-file",
        args.uncertain_file,
        "--",
        *command,
    ]
    with open(os.devnull, "rb") as empty_input, open(
        os.devnull, "wb"
    ) as ignored_output:
        process = subprocess.Popen(
            worker_command,
            stdin=empty_input,
            stdout=ignored_output,
            stderr=ignored_output,
            start_new_session=True,
        )
    atomic_write_text(Path(args.pid_file), f"{process.pid}\n")
    print(
        f"[tiki-taka] 분리 실행 시작 · 작업 {process.pid}",
        file=sys.stderr,
        flush=True,
    )
    return 0


def worker(args: argparse.Namespace) -> int:
    command = command_tail(args.command)
    prompt_path = Path(args.prompt_file)
    exit_path = Path(args.exit_file)
    uncertain_path = Path(args.uncertain_file)
    process: subprocess.Popen[bytes] | None = None
    signal_received: int | None = None

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal signal_received
        signal_received = signum
        if process is not None:
            terminate_group(process)

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handle_signal)

    return_code = 1
    try:
        with (
            prompt_path.open("rb") as prompt,
            Path(args.result_file).open("wb") as result,
            Path(args.progress_log).open("wb") as progress,
        ):
            process = subprocess.Popen(
                command,
                stdin=prompt,
                stdout=result,
                stderr=progress,
                start_new_session=True,
            )
            try:
                prompt_path.unlink()
            except FileNotFoundError:
                pass
            return_code = process.wait()
        if signal_received is not None:
            atomic_write_text(
                uncertain_path,
                "분리 실행 중 작업 감시 프로세스가 중단되었습니다.\n",
            )
            return_code = 128 + signal_received
    except OSError as error:
        atomic_write_text(
            uncertain_path,
            f"분리 실행 작업을 시작하거나 마칠 수 없습니다: {error}\n",
        )
        return_code = 1
    finally:
        try:
            prompt_path.unlink()
        except FileNotFoundError:
            pass
        atomic_write_text(exit_path, f"{return_code}\n")
    return return_code


def read_new_bytes(path: Path, offset: int) -> tuple[int, str]:
    try:
        with path.open("rb") as source:
            source.seek(offset)
            value = source.read()
            return source.tell(), value.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return offset, ""


def read_exit_code(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    try:
        return int(value)
    except ValueError:
        return 1


def read_pid(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def wait_for_job(args: argparse.Namespace) -> int:
    progress_path = Path(args.progress_log)
    exit_path = Path(args.exit_file)
    pid_path = Path(args.pid_file)
    uncertain_path = Path(args.uncertain_file)
    result_path = Path(args.result_file)
    offset = 0

    while True:
        offset, output = read_new_bytes(progress_path, offset)
        if output:
            print(output, end="", file=sys.stderr, flush=True)

        return_code = read_exit_code(exit_path)
        if return_code is not None:
            break

        pid = read_pid(pid_path)
        if pid is not None and not process_exists(pid):
            atomic_write_text(
                uncertain_path,
                "분리 실행 작업이 완료 상태를 남기지 않고 종료되었습니다.\n",
            )
            print(
                "오류: 분리 실행 작업의 완료 상태를 확인할 수 없습니다.",
                file=sys.stderr,
            )
            return_code = 1
            break
        time.sleep(args.poll_seconds)

    offset, output = read_new_bytes(progress_path, offset)
    if output:
        print(output, end="", file=sys.stderr, flush=True)

    if args.collect:
        if return_code == 0:
            try:
                response = result_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                print(f"오류: 최종 응답을 읽을 수 없습니다: {error}", file=sys.stderr)
                return_code = 1
            else:
                if response:
                    print(response, end="")
                else:
                    print("오류: 분리 실행의 최종 응답이 비어 있습니다.", file=sys.stderr)
                    return_code = 1

        for path in (result_path, progress_path, exit_path, pid_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    return return_code


def summarize_usage(usage: object) -> str:
    if not isinstance(usage, dict):
        return ""
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    cached_tokens = usage.get("cached_input_tokens")
    if cached_tokens is None:
        cached_tokens = usage.get("cache_read_input_tokens")
    parts = []
    if isinstance(input_tokens, int):
        parts.append(f"입력 {input_tokens}")
    if isinstance(cached_tokens, int):
        parts.append(f"캐시 {cached_tokens}")
    if isinstance(output_tokens, int):
        parts.append(f"출력 {output_tokens}")
    return ", ".join(parts)


def show_status(args: argparse.Namespace) -> int:
    progress_path = Path(args.progress_file)
    exit_path = Path(args.exit_file)
    pid = read_pid(Path(args.pid_file))
    return_code = read_exit_code(exit_path)

    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        progress = {}

    if return_code is not None:
        job_state = "완료" if return_code == 0 else f"실패({return_code})"
    elif pid is not None and process_exists(pid):
        job_state = "실행 중"
    elif pid is not None:
        job_state = "확인 필요"
    else:
        job_state = "대기"

    phase_names = {
        "starting": "시작 중",
        "analyzing": "분석 중",
        "inspecting": "저장소 확인 중",
        "organizing": "쟁점 정리 중",
        "answering": "답변 정리 중",
        "completed": "완료",
        "failed": "실패",
        "timed_out": "시간 초과",
        "interrupted": "중단 처리 중",
    }
    raw_phase = progress.get("phase", "없음")
    phase = phase_names.get(raw_phase, raw_phase)
    exchange = progress.get("exchange", 0)
    maximum = progress.get("max_exchanges", 0)
    elapsed = progress.get("elapsed_seconds", 0)
    model = progress.get("model", "없음")
    print(
        f"작업={job_state} 교환={exchange}/{maximum} 단계={phase} "
        f"경과={elapsed}초 모델={model}"
    )
    usage = summarize_usage(progress.get("usage"))
    if usage:
        print(f"토큰={usage}")
    return 0


def add_job_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pid-file", required=True)
    parser.add_argument("--exit-file", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--progress-log", required=True)
    parser.add_argument("--uncertain-file", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="분리한 tiki-taka 작업을 관리합니다.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    launch_parser = subparsers.add_parser("launch")
    add_job_paths(launch_parser)
    launch_parser.add_argument("--prompt-file", required=True)
    launch_parser.add_argument("command", nargs=argparse.REMAINDER)

    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--prompt-file", required=True)
    worker_parser.add_argument("--result-file", required=True)
    worker_parser.add_argument("--progress-log", required=True)
    worker_parser.add_argument("--exit-file", required=True)
    worker_parser.add_argument("--uncertain-file", required=True)
    worker_parser.add_argument("command", nargs=argparse.REMAINDER)

    wait_parser = subparsers.add_parser("wait")
    add_job_paths(wait_parser)
    wait_parser.add_argument("--poll-seconds", type=float, default=0.5)
    wait_parser.add_argument("--collect", action="store_true")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--pid-file", required=True)
    status_parser.add_argument("--exit-file", required=True)
    status_parser.add_argument("--progress-file", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.mode == "launch":
            return launch(args)
        if args.mode == "worker":
            return worker(args)
        if args.mode == "wait":
            if args.poll_seconds < 0.1:
                print("오류: 확인 간격은 0.1초 이상이어야 합니다.", file=sys.stderr)
                return 2
            return wait_for_job(args)
        return show_status(args)
    except (OSError, ValueError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
