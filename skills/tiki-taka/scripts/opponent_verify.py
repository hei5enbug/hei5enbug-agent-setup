from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from opponent_state import CLAUDE_MODEL, CODEX_MODEL, SYNTHETIC_MODEL, RunnerError


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


def codex_rollout_problem(session_id: str, effort: str) -> str | None:
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    sessions = home / "sessions"
    rollouts = sorted(sessions.glob(f"**/rollout-*{session_id}.jsonl")) if sessions.is_dir() else []
    if not rollouts:
        return f"Codex 대화 {session_id}의 rollout 기록을 찾을 수 없어 모델과 사고 강도를 확인하지 못했습니다."
    rollout = rollouts[-1]
    try:
        lines = rollout.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return f"Codex rollout 기록을 읽을 수 없습니다: {error}"
    turns = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("type") == "turn_context":
            payload = entry.get("payload")
            turns.append(payload if isinstance(payload, dict) else {})
    if not turns:
        return f"Codex rollout 기록에 turn_context가 없습니다: {rollout}"
    for turn in turns:
        if turn.get("model") != CODEX_MODEL or turn.get("effort") != effort:
            return (
                f"Codex 기록의 모델과 사고 강도는 {turn.get('model')!r}, {turn.get('effort')!r}이며 "
                f"고정 값 {CODEX_MODEL!r}, {effort!r}과 다릅니다."
            )
    return None


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def claude_transcript_problem(session_id: str, effort: str) -> str | None:
    projects = claude_home() / "projects"
    transcripts = sorted(projects.glob(f"*/{session_id}.jsonl")) if projects.is_dir() else []
    if not transcripts:
        return f"Claude 대화 {session_id}의 기록을 찾을 수 없어 사고 강도를 확인하지 못했습니다."
    transcript = transcripts[-1]
    try:
        lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return f"Claude 대화 기록을 읽을 수 없습니다: {error}"
    assistants = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("type") == "assistant":
            assistants.append(entry)
    if not assistants:
        return f"Claude 기록에 assistant 항목이 없습니다: {transcript}"
    verified = []
    for entry in assistants:
        message = entry.get("message")
        if isinstance(message, dict) and message.get("model") == SYNTHETIC_MODEL:
            continue
        verified.append(entry)
    if not verified:
        return f"Claude 기록에 실제 모델이 응답한 assistant 항목이 없습니다: {transcript}"
    for entry in verified:
        message = entry.get("message")
        model = message.get("model") if isinstance(message, dict) else None
        if model != CLAUDE_MODEL:
            return (
                f"Claude 기록의 모델은 {model!r}이며 "
                f"고정 값 {CLAUDE_MODEL!r}과 다릅니다."
            )
        if entry.get("effort") != effort:
            return (
                f"Claude 기록의 사고 강도는 {entry.get('effort')!r}이며 "
                f"고정 값 {effort!r}과 다릅니다."
            )
    return None


def extract_claude_model(events: Path) -> str | None:
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
                if model == CLAUDE_MODEL:
                    return str(model)
    except OSError:
        pass
    return None


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
