from __future__ import annotations

import argparse
import shutil
import tempfile
import uuid
from pathlib import Path

from opponent_commands import (
    claude_participant_command,
    codex_mcp_off,
    codex_participant_command,
    run_supervised,
    show_failure_log,
    supervisor_command,
)
from opponent_state import (
    CLAUDE_MODEL,
    CODEX_MODEL,
    LOCK_WAIT_SECONDS,
    RunnerError,
    StatePaths,
    atomic_write_text,
    ensure_no_pending_job,
    initialize_or_load_state,
    read_required,
    state_lock,
)
from opponent_verify import (
    claude_result_is_error,
    claude_transcript_problem,
    codex_rollout_problem,
    extract_claude_model,
    extract_codex_session,
)


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
        if args.opponent == "codex":
            mcp_off = codex_mcp_off(repo)
            participant = codex_participant_command(repo, output, effort, session_id, mcp_off)
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
            problem = codex_rollout_problem(session_id, effort)
            if problem is not None:
                atomic_write_text(paths.uncertain, problem + "\n")
                raise RunnerError(problem)
            active_model = CODEX_MODEL
        else:
            first_call = not session_id
            if first_call:
                session_id = str(uuid.uuid4())
                active_model = CLAUDE_MODEL
            else:
                active_model = read_required(paths.model, "상대 모델")
                if active_model != CLAUDE_MODEL:
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
            first_return_code = run_supervised(command, log, allow_failure=True)
            active_model = extract_claude_model(events)

            result_is_error = claude_result_is_error(events)
            if first_return_code != 0:
                show_failure_log(log)
                raise RunnerError(
                    f"반대쪽 에이전트 호출이 실패했습니다({first_return_code})."
                )

            if result_is_error:
                atomic_write_text(
                    paths.uncertain,
                    "Claude가 오류 결과를 반환했습니다.\n",
                )
                raise RunnerError("Claude가 오류 결과를 반환했습니다.")

            if active_model is None:
                atomic_write_text(
                    paths.uncertain,
                    "Claude 응답에 모델 증거가 없습니다.\n",
                )
                raise RunnerError("Claude 응답에 모델 증거가 없어 모델을 확인하지 못했습니다.")
            problem = claude_transcript_problem(session_id, effort)
            if problem is not None:
                atomic_write_text(paths.uncertain, problem + "\n")
                raise RunnerError(problem)

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
    # The detached worker starts while its launcher may still hold the lock
    # for the pid-file write, so it waits briefly instead of failing.
    wait_seconds = LOCK_WAIT_SECONDS if args.worker else 0.0
    with state_lock(paths, wait_seconds=wait_seconds):
        if not args.worker:
            ensure_no_pending_job(paths)
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
