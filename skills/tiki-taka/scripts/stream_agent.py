#!/usr/bin/env python3
"""상대 코딩 에이전트를 감시하며 짧은 진행 상태와 최종 응답을 분리한다."""

from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO


PHASE_LABELS = {
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
MIN_PHASE_EMIT_SECONDS = 60


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: dict) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
    )


def mark_uncertain(path: Path, reason: str) -> None:
    atomic_write_text(path, reason + "\n")


def format_elapsed(seconds: float) -> str:
    whole = max(0, int(seconds))
    minutes, remainder = divmod(whole, 60)
    return f"{minutes:02d}:{remainder:02d}"


def progress_line(
    provider: str,
    exchange: int,
    maximum: int,
    phase: str,
    elapsed: float,
    event_age: float | None = None,
) -> str:
    opponent = "Codex" if provider == "codex" else "Claude"
    line = (
        f"[tiki-taka] 교환 {exchange}/{maximum} · {opponent} · "
        f"{PHASE_LABELS[phase]} · {format_elapsed(elapsed)}"
    )
    if event_age is not None:
        line += f" · 마지막 이벤트 {max(0, int(event_age))}초 전"
    return line


def read_stream(
    name: str,
    stream: BinaryIO,
    messages: queue.Queue[tuple[str, bytes | None]],
) -> None:
    try:
        for line in iter(stream.readline, b""):
            messages.put((name, line))
    finally:
        messages.put((name, None))


def content_text(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    blocks = message.get("content")
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()


def codex_event(event: dict) -> tuple[str | None, dict | None]:
    event_type = event.get("type")
    if event_type == "turn.started":
        return "analyzing", None
    if event_type == "turn.completed":
        usage = event.get("usage")
        return "completed", usage if isinstance(usage, dict) else None
    if event_type in ("turn.failed", "error"):
        return "failed", None
    if event_type not in ("item.started", "item.updated", "item.completed"):
        return None, None

    item = event.get("item")
    if not isinstance(item, dict):
        return None, None
    item_type = item.get("type")
    if item_type in (
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "web_search",
    ):
        return "inspecting", None
    if item_type in ("reasoning", "analysis"):
        return "analyzing", None
    if item_type in ("plan", "plan_update"):
        return "organizing", None
    if item_type == "agent_message":
        return "answering", None
    return None, None


def claude_event(event: dict) -> tuple[str | None, dict | None, str]:
    event_type = event.get("type")
    if event_type == "system":
        return "starting", None, ""
    if event_type == "result":
        usage = event.get("usage")
        result = event.get("result")
        phase = "failed" if event.get("is_error") else "completed"
        return (
            phase,
            usage if isinstance(usage, dict) else None,
            result if isinstance(result, str) else "",
        )
    if event_type == "assistant":
        message = event.get("message")
        if isinstance(message, dict):
            blocks = message.get("content")
            if isinstance(blocks, list) and any(
                isinstance(block, dict) and block.get("type") == "tool_use"
                for block in blocks
            ):
                return "inspecting", None, content_text(message)
            return "answering", None, content_text(message)
    if event_type == "stream_event":
        inner = event.get("event")
        if isinstance(inner, dict):
            inner_type = inner.get("type")
            if inner_type == "content_block_start":
                block = inner.get("content_block")
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    return "inspecting", None, ""
                return "answering", None, ""
            if inner_type == "message_start":
                return "analyzing", None, ""
    return None, None, ""


def terminate_process(process: subprocess.Popen[bytes]) -> None:
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


def run_agent(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("오류: 실행할 상대 CLI 명령이 없습니다.", file=sys.stderr)
        return 2

    prompt_path = Path(args.prompt_file)
    output_path = Path(args.output_file)
    events_path = Path(args.events_file)
    log_path = Path(args.log_file)
    progress_path = Path(args.progress_file)
    uncertain_path = Path(args.uncertain_file)

    started = time.monotonic()
    last_event = started
    last_emit = 0.0
    phase = "starting"
    usage: dict | None = None
    latest_assistant_text = ""
    final_result = ""
    signal_received: int | None = None

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal signal_received
        signal_received = signum

    previous_handlers = {
        signum: signal.signal(signum, handle_signal)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }

    def write_progress(state: str) -> None:
        now = time.monotonic()
        value = {
            "state": state,
            "phase": phase,
            "provider": args.provider,
            "model": args.model,
            "exchange": args.exchange,
            "max_exchanges": args.max_exchanges,
            "elapsed_seconds": int(now - started),
            "last_event_seconds": int(now - last_event),
            "updated_at": int(time.time()),
        }
        if usage is not None:
            value["usage"] = usage
        atomic_write_json(progress_path, value)

    def emit(force: bool = False, include_event_age: bool = False) -> None:
        nonlocal last_emit
        now = time.monotonic()
        if not force and now - last_emit < MIN_PHASE_EMIT_SECONDS:
            return
        age = now - last_event if include_event_age else None
        print(
            progress_line(
                args.provider,
                args.exchange,
                args.max_exchanges,
                phase,
                now - started,
                age,
            ),
            file=sys.stderr,
            flush=True,
        )
        last_emit = now

    process: subprocess.Popen[bytes] | None = None
    try:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with (
            prompt_path.open("rb") as prompt,
            events_path.open("ab") as events,
            log_path.open("ab") as log,
        ):
            process = subprocess.Popen(
                command,
                cwd=args.repo,
                stdin=prompt,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            assert process.stdout is not None
            assert process.stderr is not None

            messages: queue.Queue[tuple[str, bytes | None]] = queue.Queue()
            threads = [
                threading.Thread(
                    target=read_stream,
                    args=("stdout", process.stdout, messages),
                    daemon=True,
                ),
                threading.Thread(
                    target=read_stream,
                    args=("stderr", process.stderr, messages),
                    daemon=True,
                ),
            ]
            for thread in threads:
                thread.start()

            open_streams = 2
            write_progress("running")
            emit(force=True)

            while process.poll() is None or open_streams:
                now = time.monotonic()
                if signal_received is not None:
                    phase = "interrupted"
                    reason = "상대 에이전트 실행 중 현재 호출이 중단되었습니다."
                    mark_uncertain(uncertain_path, reason)
                    write_progress("uncertain")
                    emit(force=True)
                    terminate_process(process)
                    return 128 + signal_received

                if now - started >= args.timeout_seconds:
                    phase = "timed_out"
                    reason = (
                        f"상대 에이전트가 {args.timeout_seconds}초 안에 "
                        "응답을 끝내지 못했습니다."
                    )
                    mark_uncertain(uncertain_path, reason)
                    write_progress("uncertain")
                    emit(force=True)
                    terminate_process(process)
                    return 124

                try:
                    stream_name, raw = messages.get(timeout=0.5)
                except queue.Empty:
                    if now - last_emit >= args.heartbeat_seconds:
                        write_progress("running")
                        emit(force=True, include_event_age=True)
                    continue

                if raw is None:
                    open_streams -= 1
                    continue

                last_event = time.monotonic()
                if stream_name == "stderr":
                    log.write(raw)
                    log.flush()
                    continue

                events.write(raw)
                events.flush()
                try:
                    event = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(event, dict):
                    continue

                previous_phase = phase
                if args.provider == "codex":
                    next_phase, event_usage = codex_event(event)
                    event_result = ""
                else:
                    next_phase, event_usage, event_result = claude_event(event)
                    if event.get("type") == "assistant":
                        assistant_text = content_text(event.get("message"))
                        if assistant_text:
                            latest_assistant_text = assistant_text

                if event_usage is not None:
                    usage = event_usage
                if event_result:
                    final_result = event_result
                if next_phase is not None:
                    phase = next_phase
                write_progress("running")
                if phase != previous_phase:
                    emit(force=phase in ("completed", "failed"))

            return_code = process.wait()

        if args.provider == "claude" and return_code == 0:
            response = final_result.strip() or latest_assistant_text.strip()
            if response:
                atomic_write_text(output_path, response + "\n")

        if return_code != 0:
            phase = "failed"
            reason = f"상대 에이전트 CLI가 종료 코드 {return_code}을 반환했습니다."
            mark_uncertain(uncertain_path, reason)
            write_progress("uncertain")
            emit(force=True)
            return return_code

        if phase == "failed":
            write_progress("failed")
        else:
            completion_already_emitted = phase == "completed"
            phase = "completed"
            write_progress("completed")
            if not completion_already_emitted:
                emit(force=True)
        return 0
    except (OSError, ValueError) as error:
        phase = "failed"
        reason = f"상대 에이전트를 실행할 수 없습니다: {error}"
        mark_uncertain(uncertain_path, reason)
        write_progress("uncertain")
        print(f"오류: {reason}", file=sys.stderr)
        if process is not None:
            terminate_process(process)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="상대 코딩 에이전트의 진행 상태를 간결하게 표시합니다."
    )
    parser.add_argument("--provider", choices=("codex", "claude"), required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--events-file", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--uncertain-file", required=True)
    parser.add_argument("--exchange", type=int, required=True)
    parser.add_argument("--max-exchanges", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--heartbeat-seconds", type=int, default=60)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.timeout_seconds < 1:
        print("오류: 실행 시간 제한은 1초 이상이어야 합니다.", file=sys.stderr)
        return 2
    if args.heartbeat_seconds < 10:
        print("오류: 진행 출력 간격은 10초 이상이어야 합니다.", file=sys.stderr)
        return 2
    return run_agent(args)


if __name__ == "__main__":
    raise SystemExit(main())
