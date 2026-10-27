from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable, Sequence

from refresh_core import HANDLE, SESSION_CONTEXT, RefreshError, parse_time
from refresh_orca import Orca
from refresh_screen import composer_bounds, input_state, codex_fresh, screen_host


RELOAD_DONE = re.compile(r"Reloaded: \d+ plugins?")
RELOAD_REFUSED = re.compile(r"reload changes MCP tools|/reload-plugins --force", re.IGNORECASE)
CLAUDE_COMPACTED = re.compile(r"Compacted|Conversation compacted")
CODEX_COMPACTED = re.compile(r"Context compacted")
CLAUDE_NOTHING_TO_COMPACT = re.compile(r"Not enough messages to compact")
CLAUDE_COMPACT_ERROR = re.compile(r"Error during compaction|Compaction canceled")
COMMANDS = {"reload": "/reload-plugins", "compact": "/compact", "clear": "/clear"}
COMMAND_RECORD_PREFIXES = ("<command-name>", "<local-command-caveat>", "<local-command-stdout>", "<local-command-stderr>")
CLEAR_TIMEOUT = 60.0
PROBE_KEY = "x"
DRAFT_STABLE_SECONDS = 5.0
PROBE_RETRIES = 3
PROBE_RECHECK_SECONDS = 3.0
TRANSCRIPT_TAIL_BYTES = 512 * 1024
BACKSPACE = "\x7f"
POLL_SECONDS = 2.0
FINAL_STATUSES = frozenset({"done", "skipped", "failed"})
RELOAD_TIMEOUT = 45.0
COMPACT_TIMEOUT = 300.0


def agent_host(terminal: dict) -> str | None:
    identity = str(terminal.get("agentIdentity") or "").strip().lower()
    if identity in {"claude", "claude-code", "claude code"}:
        return "claude"
    return "codex" if identity == "codex" else None


def marker_host(terminal: dict) -> str | None:
    """The host this plugin's session marker names for a terminal that Orca recorded no agentIdentity for."""
    handle = terminal.get("handle")
    if terminal.get("agentIdentity") or not isinstance(handle, str):
        return None
    host = (read_marker(handle) or {}).get("host")
    return host if host in ("claude", "codex") else None


def terminal_host(orca: Orca, terminal: dict) -> str | None:
    """Orca's agentIdentity, or, when Orca recorded none, the marker's host while that host's composer still ends the
    screen. A marker outlives the session, so a shell left in the terminal never matches."""
    host = marker_host(terminal)
    if host is None:
        return agent_host(terminal)
    try:
        lines, _ = orca.screen(terminal["handle"])
    except RefreshError:
        return None
    return host if screen_host(lines) == host else None


def read_marker(handle: str) -> dict | None:
    directory = SESSION_CONTEXT.marker_directory()
    if directory is None or not HANDLE.fullmatch(handle):
        return None
    try:
        payload = json.loads((directory / f"{handle}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def compact_reason(host: str, marker: dict | None, target: dict, mode: str) -> str | None:
    if mode == "never":
        return None
    if mode == "always":
        return "requested"
    if marker is None:
        return "session_started_before_markers"
    if marker.get("schema") != SESSION_CONTEXT.MARKER_SCHEMA or marker.get("host") != host:
        return "marker_unrecognized"
    if marker.get("digest") != target.get("digest"):
        return "instructions_changed"
    loaded_root = marker.get("root")
    if host == "codex" and loaded_root != target.get("root"):
        return "codex_root_replaced"
    if host == "claude" and not (isinstance(loaded_root, str) and Path(loaded_root).is_dir()):
        return "claude_root_removed"
    return None


def plan_sessions(orca: Orca, state: dict, mode: str, only: Sequence[str]) -> list[dict]:
    initiator = os.environ.get("ORCA_TERMINAL_HANDLE")
    sessions: list[dict] = []
    for terminal in orca.terminals():
        host = terminal_host(orca, terminal)
        handle = terminal.get("handle")
        if host is None or not isinstance(handle, str) or not HANDLE.fullmatch(handle):
            continue
        if only and handle not in only:
            continue
        target = state["hosts"].get(host, {})
        entry = {
            "handle": handle,
            "host": host,
            "title": terminal.get("title"),
            "worktree": terminal.get("worktreePath"),
            "initiator": handle == initiator,
            "screen_identified": marker_host(terminal) is not None,
            "actions": [],
            "status": "pending",
            "detail": None,
        }
        if "error" in target:
            entry.update(status="blocked", detail=f"{host}_update_failed")
        else:
            if host == "claude":
                entry["actions"].append("reload")
            reason = compact_reason(host, read_marker(handle), target, mode)
            if reason:
                entry["actions"].append("compact")
                entry["compact_reason"] = reason
            if not entry["actions"]:
                entry.update(status="done", detail="already_current")
        sessions.append(entry)
    return sessions


def settle(read: Callable[[], object], until: Callable[[object], bool], sleep: Callable[[float], None], seconds: float = 3.0) -> object:
    deadline = time.time() + seconds
    value = read()
    while not until(value) and time.time() < deadline:
        sleep(0.3)
        value = read()
    return value


def claude_draft_state(orca: Orca, handle: str, draft: str, sleep: Callable[[float], None] = time.sleep) -> str:
    """Tell typed text from Claude Code's ghost prompt suggestion; return `empty`, `text`, or `interrupted`.

    Orca reports both as `draft`. Typing one character replaces a suggestion but appends to typed text, and a
    backspace restores the original draft. The backspace is sent only when the draft shows exactly the probe's own
    character, so input that arrives during the probe is never deleted.
    """
    orca.keys(handle, PROBE_KEY)
    try:
        probed = settle(lambda: orca.draft(handle), lambda value: value != draft, sleep)
    except RefreshError:
        return "interrupted"
    if probed not in (PROBE_KEY, draft + PROBE_KEY):
        return "interrupted"
    orca.keys(handle, BACKSPACE)
    try:
        restored = settle(lambda: orca.draft(handle), lambda value: value == draft, sleep)
    except RefreshError:
        return "interrupted"
    if restored != draft:
        return "interrupted"
    return "empty" if probed == PROBE_KEY else "text"


def terminal_gone(entry: dict, live: dict[str, dict]) -> bool:
    """True when the session's terminal left Orca's list or no longer runs the entry's agent host."""
    terminal = live.get(entry["handle"])
    return terminal is None or (marker_host(terminal) or agent_host(terminal)) != entry["host"]


def probe_left_input_clean(orca: Orca, handle: str, draft: str) -> bool:
    """True when the draft is back to its pre-probe value or empty, so no probe character of ours remains."""
    try:
        after = settle(lambda: orca.draft(handle), lambda value: value == draft or not (isinstance(value, str) and value.strip()), time.sleep, PROBE_RECHECK_SECONDS)
    except RefreshError:
        return False
    return after == draft or not (isinstance(after, str) and after.strip())


def ready(orca: Orca, entry: dict, live: dict[str, dict]) -> tuple[str | None, list[str]]:
    """Return (None, screen) when a command can be sent safely, otherwise the reason to wait."""
    if terminal_gone(entry, live):
        return "terminal_gone", []
    terminal = live[entry["handle"]]
    if terminal.get("connected") is not True or terminal.get("writable") is not True or terminal.get("orphaned") is True:
        return "terminal_unavailable", []
    if not orca.idle(entry["handle"]):
        return "busy", []
    lines, draft = orca.screen(entry["handle"])
    if entry.get("screen_identified") and screen_host(lines) != entry["host"]:
        return "input_unknown", lines
    entry["observed_draft"] = draft if isinstance(draft, str) else None
    if not (isinstance(draft, str) and draft.strip()):
        state = input_state(entry["host"], lines)
        return (None if state == "empty" else ("unsent_input" if state == "text" else "input_unknown")), lines
    if entry["host"] != "claude" or entry.get("typed_draft") == draft:
        return "unsent_input", lines
    seen = entry.get("draft_seen")
    if not seen or seen[0] != draft:
        entry["draft_seen"] = (draft, time.time())
        return "input_settling", lines
    if time.time() - seen[1] < DRAFT_STABLE_SECONDS:
        return "input_settling", lines
    verdict = claude_draft_state(orca, entry["handle"], draft)
    if verdict == "interrupted":
        retries = entry.get("probe_retries") or 0
        if retries < PROBE_RETRIES and probe_left_input_clean(orca, entry["handle"], draft):
            entry["probe_retries"] = retries + 1
            entry.pop("draft_seen", None)
            return "input_settling", lines
        return "probe_interrupted", lines
    if verdict == "text":
        entry["typed_draft"] = draft
        return "unsent_input", lines
    return None, lines


def result_counts(lines: Sequence[str]) -> dict[str, int]:
    """Count result lines on screen; agent TUIs repaint, so a new result shows up as a higher count."""
    patterns = {
        "reloaded": RELOAD_DONE,
        "refused": RELOAD_REFUSED,
        "claude_compacted": CLAUDE_COMPACTED,
        "codex_compacted": CODEX_COMPACTED,
        "nothing_to_compact": CLAUDE_NOTHING_TO_COMPACT,
    }
    return {name: sum(1 for line in lines if pattern.search(line)) for name, pattern in patterns.items()}


def transcript_size(path: object) -> int:
    try:
        return Path(str(path)).stat().st_size if isinstance(path, str) else 0
    except OSError:
        return 0


def transcript_records(path: object, offset: int) -> list[dict]:
    """Return every complete JSON record appended to a host transcript after byte `offset`."""
    if not isinstance(path, str) or not Path(path).is_file():
        return []
    with open(path, "rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        stream.seek(offset if 0 <= offset <= size else 0)
        chunk = stream.read()
    complete = chunk[: chunk.rfind(b"\n") + 1]
    records = []
    for line in complete.decode("utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def transcript_outcome(host: str, action: str, records: list[dict]) -> str | None:
    for record in records:
        content = str(record.get("content") or "") if record.get("subtype") == "local_command" else ""
        if host == "claude" and action == "reload" and content:
            if RELOAD_REFUSED.search(content):
                return "failed:reload_needs_force"
            if RELOAD_DONE.search(content):
                return "done"
        if host == "claude" and action == "compact" and content:
            if CLAUDE_NOTHING_TO_COMPACT.search(content):
                return "nothing_to_compact"
            if CLAUDE_COMPACT_ERROR.search(content):
                return "failed:compact_error"
        if host == "codex" and action == "compact" and record.get("type") == "compacted":
            return "done"
    return None


def claude_has_prompts(path: object) -> bool:
    """True unless the transcript proves the user never sent a prompt, so /clear cannot lose a conversation."""
    if not isinstance(path, str) or not Path(path).is_file():
        return True
    if Path(path).stat().st_size > TRANSCRIPT_TAIL_BYTES:
        return True
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return True
        message = record.get("message") if isinstance(record, dict) and record.get("type") == "user" else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            text = content.strip()
            if text not in COMMANDS.values() and not text.startswith(COMMAND_RECORD_PREFIXES):
                return True
        elif isinstance(content, list) and any(isinstance(part, dict) and part.get("type") == "text" for part in content):
            return True
    return False


def last_item_is(lines: Sequence[str], echo: str, result: re.Pattern) -> bool:
    """True when the newest conversation item above the Claude Code composer is `echo` followed by `result`."""
    bounds = composer_bounds(lines)
    if bounds is None:
        return False
    above = lines[:bounds[0]]
    echoes = [index for index, line in enumerate(above) if line.strip().startswith("❯")]
    return bool(echoes) and above[echoes[-1]].strip() == f"❯ {echo}" and any(result.search(line) for line in above[echoes[-1] + 1:])


def newer_marker(entry: dict, marker: dict | None, target: dict) -> bool:
    """True only for a marker rewritten after the command was sent that carries the target instructions."""
    if not marker or marker == entry.get("marker_snapshot") or marker.get("digest") != target.get("digest"):
        return False
    written = parse_time(marker.get("written_at"))
    return bool(written and written >= entry["marker_before"])


def verify(orca: Orca, entry: dict, target: dict) -> str | None:
    """Return `done`, `nothing_to_compact`, `failed:<code>`, or None while still waiting."""
    action = entry["actions"][0]
    elapsed = time.time() - entry["sent_at"]
    marker = read_marker(entry["handle"])
    records = transcript_records(entry.get("transcript"), entry.get("transcript_offset", 0))
    from_transcript = transcript_outcome(entry["host"], action, records)
    if from_transcript:
        if entry["host"] == "codex":
            entry["note"] = "instructions_load_on_next_turn"
        return from_transcript
    if action == "clear":
        if newer_marker(entry, marker, target):
            entry["note"] = "empty_session_cleared"
            return "done"
        return "failed:clear_unconfirmed" if elapsed > CLEAR_TIMEOUT else None
    lines, _ = orca.screen(entry["handle"])
    grew = {name: count > entry["before"].get(name, 0) for name, count in result_counts(lines).items()}
    before_lines = entry.get("before_lines", [])
    if action == "reload":
        if grew["refused"] or (last_item_is(lines, "/reload-plugins", RELOAD_REFUSED) and not last_item_is(before_lines, "/reload-plugins", RELOAD_REFUSED)):
            return "failed:reload_needs_force"
        if grew["reloaded"] or (last_item_is(lines, "/reload-plugins", RELOAD_DONE) and not last_item_is(before_lines, "/reload-plugins", RELOAD_DONE)):
            return "done"
        return "failed:reload_unconfirmed" if elapsed > RELOAD_TIMEOUT else None
    if entry["host"] == "claude":
        if newer_marker(entry, marker, target):
            return "done"
        if grew["nothing_to_compact"]:
            return "nothing_to_compact"
        if grew["claude_compacted"]:
            entry.setdefault("compacted_at", time.time())
            if time.time() - entry["compacted_at"] > 30:
                return "failed:instructions_unconfirmed"
    elif grew["codex_compacted"]:
        entry["note"] = "instructions_load_on_next_turn"
        return "done"
    return "failed:compact_unconfirmed" if elapsed > COMPACT_TIMEOUT else None


def finish(entry: dict, outcome: str) -> None:
    finished = entry["actions"].pop(0)
    entry.setdefault("completed", []).append(finished if outcome == "done" else f"{finished}:{outcome[7:]}")
    if outcome != "done":
        entry.update(status="failed", detail=outcome[7:], actions=[])
    else:
        entry.update(status="pending" if entry["actions"] else "done", detail=None if entry["actions"] else "applied")


def step(orca: Orca, entry: dict, target: dict, live: dict[str, dict]) -> None:
    if entry["status"] == "sent":
        outcome = verify(orca, entry, target)
        if outcome is None:
            return
        if outcome == "nothing_to_compact":
            if claude_has_prompts((read_marker(entry["handle"]) or {}).get("transcript_path")):
                outcome = "failed:compact_needs_more_messages"
            else:
                entry["actions"][0] = "clear"
                entry.update(status="pending", detail="empty_session_needs_clear")
                return
        finish(entry, outcome)
        return
    if entry["status"] != "pending" or not entry["actions"]:
        return
    reason, lines = ready(orca, entry, live)
    entry["detail"] = reason
    if reason == "terminal_gone":
        entry.update(status="skipped", actions=[])
        return
    if reason == "probe_interrupted":
        entry.update(status="failed", detail="probe_interrupted_check_input", actions=[])
        return
    if entry["host"] == "codex" and reason in (None, "busy"):
        screen = lines if reason is None else orca.screen(entry["handle"])[0]
        if codex_fresh(screen):
            entry.update(status="done", detail="fresh_session_loads_on_first_turn", actions=[])
            return
    if reason:
        return
    marker = read_marker(entry["handle"])
    if entry["actions"][0] == "clear" and claude_has_prompts((marker or {}).get("transcript_path")):
        entry["actions"].insert(0, "compact")
        finish(entry, "failed:compact_needs_more_messages")
        return
    if entry["host"] == "claude" and orca.draft(entry["handle"]) != entry.get("observed_draft"):
        entry["detail"] = "input_changed"
        return
    entry["before"] = result_counts(lines)
    entry["before_lines"] = lines
    entry["transcript"] = (marker or {}).get("transcript_path")
    entry["transcript_offset"] = transcript_size(entry["transcript"])
    entry["marker_before"] = parse_time((marker or {}).get("written_at")) or 0.0
    entry["marker_snapshot"] = marker
    entry["sent_at"] = time.time()
    orca.send(entry["handle"], COMMANDS[entry["actions"][0]])
    entry["status"] = "sent"


def drive(orca: Orca, sessions: list[dict], state: dict, deadline: float, sleep: Callable[[float], None] = time.sleep, expire: str = "skipped") -> None:
    """Send commands until `deadline`, then stop starting new ones and keep verifying the ones already sent.

    A session still pending at the deadline takes the `expire` status: `skipped`, or `deferred` for the helper.
    """
    while True:
        if time.time() >= deadline:
            for entry in sessions:
                if entry["status"] == "pending":
                    entry.update(status=expire, detail=entry.get("detail") or "deadline_reached")
        active = [entry for entry in sessions if entry["status"] in {"pending", "sent"}]
        if not active:
            return
        try:
            live = {item.get("handle"): item for item in orca.terminals()}
        except RefreshError:
            live = None
        for entry in active:
            if live is None:
                entry["detail"] = "terminal_list_unavailable"
                continue
            if entry["status"] == "pending" and time.time() >= deadline:
                entry.update(status=expire, detail=entry.get("detail") or "deadline_reached")
                continue
            try:
                step(orca, entry, state["hosts"][entry["host"]], live)
            except RefreshError as error:
                entry.update(status="failed", detail=error.code, actions=[])
        sleep(POLL_SECONDS)
