#!/usr/bin/env python3
"""tiki-taka 반대쪽 세션과 분리 실행 상태를 관리한다."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from opponent_commands import (
    MCP_LIST_TIMEOUT_SECONDS,
    MCP_SERVER_NAME,
    claude_participant_command,
    codex_mcp_off,
    codex_participant_command,
    run_supervised,
    show_failure_log,
    supervisor_command,
)
from opponent_invoke import invoke_opponent, normal_run
from opponent_jobs import collect_job, detached_helper_args, finish_state, show_status
from opponent_state import (
    CLAUDE_MODEL,
    CODEX_MODEL,
    DEEP_EFFORT,
    DEFAULT_EFFORT,
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_MAX_EXCHANGES,
    DEFAULT_TIMEOUT_SECONDS,
    FAST_EFFORT,
    LOCK_WAIT_SECONDS,
    OPPONENTS,
    PLUGIN_ROOT,
    STATE_VERSION,
    SYNTHETIC_MODEL,
    RunnerError,
    StatePaths,
    active_detached_job,
    atomic_write_text,
    canonical_directory,
    ensure_no_pending_job,
    helper_path,
    initialize_or_load_state,
    prepare_state_root,
    process_exists,
    read_integer,
    read_optional_integer,
    read_required,
    state_lock,
    validate_limit,
)
from opponent_verify import (
    claude_home,
    claude_result_is_error,
    claude_transcript_problem,
    codex_rollout_problem,
    extract_claude_model,
    extract_codex_session,
)


def worker_runner_command(args: argparse.Namespace, paths: StatePaths) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--opponent",
        args.opponent,
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


def launch_detached(
    args: argparse.Namespace,
    paths: StatePaths,
    prompt_text: str,
    wait_after_launch: bool,
) -> int:
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
        # Checking for a pending job and writing the new pid file happen under
        # the same lock, so two launchers can never both start a worker.
        with state_lock(paths):
            ensure_no_pending_job(paths)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run-opponent.sh",
        description="tiki-taka 반대쪽 전용 세션 실행기",
    )
    participant = parser.add_mutually_exclusive_group(required=True)
    participant.add_argument(
        "--opponent",
        choices=("claude", "codex"),
        help="전용 세션으로 호출할 상대 CLI",
    )
    participant.add_argument(
        "--host",
        choices=("claude", "codex"),
        help=argparse.SUPPRESS,
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


def normalize_opponent(args: argparse.Namespace) -> None:
    if args.opponent is None:
        args.opponent = "codex" if args.host == "claude" else "claude"


def main() -> int:
    args = build_parser().parse_args()
    try:
        normalize_opponent(args)
        validate_args(args)
        effort = FAST_EFFORT if args.fast else DEFAULT_EFFORT
        if args.show_config:
            if args.opponent == "claude":
                print(
                    f"opponent=claude model={CLAUDE_MODEL} effort={effort}"
                )
            else:
                print(f"opponent=codex model={CODEX_MODEL} effort={effort}")
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
