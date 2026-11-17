"""A run that talks with the scripted user: the agent runs turn by turn, and each turn that ends with a plain-text question
is answered from the task's answer sheet through the host's resume command.

A question asked through the question tool never ends a turn on Claude Code; the approver answers it (see `approval_mcp.py`).
A turn counts as ending with a question when the last line of its final message ends with a question mark, or when its last
sentence asks the user to decide, approve, confirm, or tell something. A message that ends with a list is read at the sentence
before the list. The question that the sheet sees is the paragraph of that request, with the list that follows it, and a
request for approval is judged on the whole message together with the earlier texts of the turn. The turns of one run append to one stream file, so a run reads as one conversation.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import codex_host, transcript
from .config import HOST_CODEX
from .process import ProcessResult, run_agent
from .scripted_user import KIND_TEXT, ScriptedUser, load_sheet, read_log
from .timeline import claude_timeline, codex_timeline

LOG_NAME = "scripted_user.jsonl"
QUESTION_END = re.compile(r"[?？][\s*_`'\")\]」』]*\Z")
CODEX_SANDBOX_CONFIG = 'sandbox_mode="danger-full-access"'
Runner = Callable[..., ProcessResult]


SENTENCE_END = re.compile(r"(?<=[.!?。？])\s+")
LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s")
REQUEST = re.compile(
    r"알려\s?(?:주|줘)|말씀해\s?(?:주|줘)|확인해\s?(?:주|줘)|정해\s?(?:주|줘)|골라\s?(?:주|줘)|선택해\s?(?:주|줘)|답해\s?(?:주|줘)"
    r"|승인하시겠|승인해\s?주|할까요|괜찮을까요|괜찮으신가요|let me know|please (?:confirm|tell|choose|decide|reply|answer)"
    r"|do you approve|should i\b|would you like", re.IGNORECASE)


def request_block(text: str) -> list[str]:
    """The lines of a final message that carry its request: the last paragraph, or, when that paragraph is a list, the
    paragraph before it together with the list."""
    paragraphs = [[line for line in part.splitlines() if line.strip()] for part in re.split(r"\n\s*\n", text.strip())]
    paragraphs = [part for part in paragraphs if part]
    if not paragraphs:
        return []
    if len(paragraphs) > 1 and all(LIST_ITEM.match(line) for line in paragraphs[-1]):
        return paragraphs[-2] + paragraphs[-1]
    return paragraphs[-1]


def asks_question(text: str) -> bool:
    """Whether a final message asks the user something: its last line ends with a question mark, ignoring closing marks, or
    the last sentence of its request block asks the user to decide, approve, confirm, or tell something."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return False
    if QUESTION_END.search(lines[-1].strip()):
        return True
    block = request_block(text)
    heading = [line for line in block if not LIST_ITEM.match(line)]
    sentences = [part for part in SENTENCE_END.split(" ".join(line.strip() for line in heading)) if part.strip()]
    return bool(sentences) and bool(REQUEST.search(sentences[-1]))


def question_of(text: str) -> str:
    """The request block of a final message, which is the question the sheet is asked."""
    return "\n".join(request_block(text))


def claude_final(events: Sequence[Mapping[str, Any]]) -> tuple[str, str | None]:
    """The text of the last turn and the session id the stream names."""
    result = transcript.result_event(list(events)) or {}
    init = transcript.init_event(list(events)) or {}
    text = result.get("result")
    return (text if isinstance(text, str) else ""), (init.get("session_id") or result.get("session_id"))


def claude_turn_texts(events: Sequence[Mapping[str, Any]]) -> list[str]:
    """Main-session texts of the stream after the last `result` event before the final one, so a specification shown in
    several messages of one turn is read whole."""
    last = max((i for i, event in enumerate(events) if event.get("type") == "result"), default=-1)
    before = max((i for i, event in enumerate(events[:last]) if event.get("type") == "result"), default=-1)
    return transcript.assistant_texts(list(events[before + 1:last + 1]))


def codex_main_events(result_dir: Path) -> list[dict[str, Any]]:
    """Events of the main rollout the run's CODEX_HOME holds so far: the earliest session."""
    files = sorted((result_dir / codex_host.CODEX_HOME_NAME / "sessions").rglob("rollout-*.jsonl"))
    return transcript.read_jsonl(files[0]) if files else []


def codex_final(result_dir: Path, stream: Sequence[Mapping[str, Any]]) -> tuple[str, str | None]:
    thread = next((str(event.get("thread_id")) for event in stream if event.get("type") == "thread.started" and event.get("thread_id")), None)
    return codex_host.final_answer(codex_main_events(result_dir)), thread


def resume_claude(argv: Sequence[str], session_id: str, answer: str) -> list[str]:
    """The first command with `--resume <session>` before the prompt and the answer as the prompt."""
    cut = list(argv).index("--")
    return [*argv[:cut], "--resume", session_id, "--", answer]


def resume_codex(argv: Sequence[str], thread_id: str, answer: str) -> list[str]:
    """`codex exec resume <thread>` with the first command's options, except the sandbox and folder flags, which the resume
    form may not take: the sandbox moves to a config override, and the folder is the process's working directory."""
    cut = list(argv).index("--")
    options, kept, skip = list(argv[:cut]), [], False
    for item in options:
        if skip:
            skip = False
        elif item in ("-s", "-C"):
            skip = True
        else:
            kept.append(item)
    head = kept.index("exec") + 1
    return [*kept[:head], "resume", *kept[head:], "-c", CODEX_SANDBOX_CONFIG, thread_id, "--", answer]


def merge(results: Sequence[ProcessResult]) -> ProcessResult:
    """One result for all turns: summed wall time, the first start and the last end, the last return code."""
    return ProcessResult(
        returncode=results[-1].returncode, timed_out=any(r.timed_out for r in results), wall_seconds=sum(r.wall_seconds for r in results),
        started_at=results[0].started_at, ended_at=results[-1].ended_at, error=next((r.error for r in results if r.error), None),
        orphans_killed=sum(r.orphans_killed for r in results), leftover_killed=sum(r.leftover_killed for r in results),
        interrupted=any(r.interrupted for r in results))


def run_turns(
    argv: Sequence[str], *, host: str, cwd: Path, env: Mapping[str, str], result_dir: Path, sheet_path: Path, wall_seconds: float,
    sigint_grace: float, sigterm_grace: float, interrupt: threading.Event | None = None, runner: Runner = run_agent,
) -> ProcessResult:
    """Run the first turn, then answer each plain-text question from the sheet and resume until the turn ends without one, the
    sheet ends the conversation, a turn fails, or the wall time of the task is used up."""
    user = ScriptedUser(load_sheet(sheet_path), result_dir / LOG_NAME)
    stream_path, stderr_path = result_dir / "stream.jsonl", result_dir / "stderr.txt"
    results: list[ProcessResult] = []
    command, append = list(argv), False
    while True:
        left = wall_seconds - sum(item.wall_seconds for item in results)
        result = runner(command, cwd, env, stream_path, stderr_path, left, sigint_grace, sigterm_grace, interrupt=interrupt, append=append)
        results.append(result)
        if result.timed_out or result.interrupted or result.error or result.returncode != 0 or wall_seconds - sum(item.wall_seconds for item in results) <= 0:
            break
        stream = transcript.read_jsonl(stream_path)
        text, session = codex_final(result_dir, stream) if host == HOST_CODEX else claude_final(stream)
        if not session or not asks_question(text):
            break
        whole = "\n\n".join(codex_texts(result_dir) if host == HOST_CODEX else claude_turn_texts(stream)) or text
        exchange = user.answer(question_of(text), KIND_TEXT, specification=whole, stream_offset=len(stream))
        if exchange.answer is None:
            break
        command = (resume_codex if host == HOST_CODEX else resume_claude)(argv, session, exchange.answer)
        append = True
    return merge(results)


def codex_texts(result_dir: Path) -> list[str]:
    """Assistant texts of the main rollout since its second to last turn end, for the specification of a Codex turn."""
    events = codex_main_events(result_dir)
    ends = [i for i, event in enumerate(events) if event.get("type") == "event_msg" and codex_host.payload_of(event).get("type") == "task_complete"]
    start = ends[-2] + 1 if len(ends) >= 2 else 0
    return codex_host.assistant_messages(events[start:])


def attach(
    view: Mapping[str, Any], result_dir: Path, host: str, main_events: Sequence[Mapping[str, Any]], *, scripted: bool = False,
) -> dict[str, Any]:
    """The view plus `conversation`, the exchanges of the scripted user and the ordered timeline, when the run kept a log or
    its task has a scripted user. A scripted run in which the agent asked nothing still gets the timeline, so a check can see
    its edits. `main_events` are the stream events of a Claude Code run, or the events of the main rollout of a Codex run."""
    exchanges = read_log(result_dir / LOG_NAME)
    if not exchanges and not scripted:
        return dict(view)
    build = codex_timeline if host == HOST_CODEX else claude_timeline
    return {**view, "conversation": {"exchanges": exchanges, "timeline": build(main_events, exchanges)}}
