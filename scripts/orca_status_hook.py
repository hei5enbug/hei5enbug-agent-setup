"""Hook that keeps the session's tab title in step with its work and reminds it of a missing name or tab title.

It runs only in an Orca terminal, for the main session. It reads Orca, Git, and the transcript. Its writes to Orca are
closing a never-used shell terminal at a session's first prompt, and the removal of a finished child worktree that the
session created, which a detached run does (`orca_cleanup_run.py`).

- At the first prompt of a session (UserPromptSubmit), each terminal of the session's worktree other than the session's
  own is closed when it is a never-used shell terminal: Orca lists no agent in it, its screen shows one shell prompt
  with an empty input line, and its output holds no command. A terminal that runs a process, holds typed input, or
  shows an earlier command stays, as does any terminal that cannot be read in time. The hook starts no process for
  this unless `ORCA_USER_DATA_PATH`, which Orca sets in every terminal it manages, is set.
- After a session's Bash command that creates a worktree (`orca worktree create`, `orca orchestration worker-start`) or
  starts an agent in one (`orca terminal create`, `orca orchestration worker-start`), the command is recorded from the
  tool input (PostToolUse). At a prompt and at the end of a turn (UserPromptSubmit, Stop), when a recorded worktree is
  neither removed nor kept for good and no run is active, the hook starts the detached run in a process session of its
  own, so it returns within its time limit and the run survives the closing of the session's terminal. At the first
  event after a run ends the user gets one line (`systemMessage`) naming each removed and kept worktree, and the next
  prompt adds the same facts once to the session's context. The run starts only when `ORCA_USER_DATA_PATH` is set and
  a recorded worktree is still to be checked, so a prompt or turn end with nothing recorded starts no process.
- After the session renames its own terminal tab with a literal title (PostToolUse), that title is remembered, and each
  later prompt (UserPromptSubmit) gets one context line that names it, so the session can retitle when its work moves on.
- At Stop it keeps the turn going once per state with a one-command instruction, which Claude Code shows as Stop hook
  feedback rather than a hook error, and which costs model tokens only then, when a task worktree the session changed
  still has its automatic name, or when the session updated its worktree and never titled its tab.

A failed read of Orca, Git, or the transcript lets the event pass. A Codex transcript records tool calls as script
text, so the Stop reminders read Claude Code transcripts only.
"""

from __future__ import annotations

import os
import sys

if __name__ == "__main__" and not os.environ.get("ORCA_TERMINAL_HANDLE"):
    raise SystemExit(0)

import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import approval_state_store  # noqa: E402
import hook_runtime  # noqa: E402
import language_guard  # noqa: E402
import orca_cleanup_state  # noqa: E402
from orca_cleanup_state import has_option, option_values  # noqa: E402
from orca_placement_hook import orca_arguments  # noqa: E402
from required_checks_hook import git_subcommand, segments_of  # noqa: E402

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"})
NOT_A_PROMPT = ("<task-notification", "<local-command-", "<system-reminder")
READ_TIMEOUT_SECONDS = 3
STATE_SUBDIRECTORY = "orca-status"
PATCH_PATH = re.compile(r"^\*\*\* (?:Update|Add) File: (.+)$", re.MULTILINE)
ASSISTANT_ENTRY = re.compile(rb'"type": ?"assistant"')
USER_ENTRY = re.compile(rb'"type": ?"user"')
TOOL_RESULT_BLOCK = re.compile(rb'"type": ?"tool_result"')
TAB_TITLE_LINE = (
    "Current Orca tab title: {title}. If this prompt asks about or for work the title does not name, such as another "
    "ticket, pull request, repository, document, or goal, retitle the tab before starting it. "
    "A follow-up, fix, review, merge, or question on the titled work keeps the title, as does one the user set."
)
TERMINAL_HANDLE_REFERENCES = frozenset({"$ORCA_TERMINAL_HANDLE", "${ORCA_TERMINAL_HANDLE}"})
TIDY_FINGERPRINT = "T1"
ORCA_TERMINAL_MARKER = "ORCA_USER_DATA_PATH"
TIDY_TERMINAL_LIMIT = 8
TIDY_SECONDS = 2
PROMPT_ENDINGS = frozenset("$%#>\u276f\u279c\u03bb\u00bb\ue0b0")
BANNER = "Last login"


@dataclass
class Turn:
    """What one turn, from a real user prompt to the next, did that the Stop reminders judge."""

    commit: bool = False
    edits: set[str] = field(default_factory=set)
    set_any: bool = False
    named: bool = False
    rename: bool = False


def is_real_prompt(entry: dict, message: dict) -> bool:
    if entry.get("isMeta") or entry.get("isSidechain"):
        return False
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        blocks = [block for block in content if isinstance(block, dict)]
        if any(block.get("type") == "tool_result" for block in blocks):
            return False
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not text and not blocks:
            return False
    else:
        return False
    return not text.lstrip().startswith(NOT_A_PROMPT)


def command_signals(command: str, turn: Turn) -> None:
    for tokens in segments_of(command):
        arguments = orca_arguments(tokens)
        if arguments is not None:
            pair = [token for token in arguments if not token.startswith("-")][:2]
            if pair == ["worktree", "set"]:
                turn.set_any = True
                turn.named = turn.named or has_option(arguments, "--display-name")
            elif pair == ["terminal", "rename"]:
                turn.rename = True
            continue
        if git_subcommand(tokens) == "commit":
            turn.commit = True


def edited_paths(name: str, tool_input: dict, cwd: str) -> set[str]:
    if name == "apply_patch":
        patch = tool_input.get("command") or tool_input.get("input")
        paths = PATCH_PATH.findall(patch) if isinstance(patch, str) else []
    else:
        value = tool_input.get("file_path") or tool_input.get("notebook_path")
        paths = [value] if isinstance(value, str) and value else []
    return {os.path.normpath(os.path.join(cwd, path.strip())) for path in paths}


def tool_signals(block: dict, turn: Turn, cwd: str) -> None:
    name = block.get("name")
    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
    if name == "Bash" and isinstance(tool_input.get("command"), str):
        command_signals(tool_input["command"], turn)
    elif name in EDIT_TOOLS:
        turn.edits |= edited_paths(name, tool_input, cwd)


def inside(path: str, base: str) -> bool:
    base = os.path.normpath(base)
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def read_turns(path: str, cwd: str = "/") -> list[Turn]:
    """Return the turns of a Claude Code transcript in order; a turn starts at each real user prompt."""
    turns: list[Turn] = []
    with open(path, "rb") as stream:
        for line in stream:
            if not ASSISTANT_ENTRY.search(line) and (not USER_ENTRY.search(line) or TOOL_RESULT_BLOCK.search(line)):
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message") if isinstance(entry, dict) else None
            if not isinstance(message, dict) or entry.get("isSidechain"):
                continue
            if entry.get("type") == "user":
                if is_real_prompt(entry, message):
                    turns.append(Turn())
                continue
            if not turns:
                turns.append(Turn())
            turn = turns[-1]
            content = message.get("content")
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tool_signals(block, turn, cwd)
    return turns


def orca_run(*arguments: str, timeout: float = READ_TIMEOUT_SECONDS) -> dict | None:
    """Run an `orca` command with `--json`; return its parsed result, or None when it failed or took too long."""
    try:
        result = subprocess.run(
            ["orca", *arguments, "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if result.returncode != 0 or not isinstance(payload, dict) or payload.get("ok") is False:
        return None
    return payload


def orca_worktree() -> dict | None:
    """Return the worktree record of this terminal's Orca worktree, or None when Orca cannot tell in time."""
    payload = orca_run("worktree", "current")
    try:
        record = payload["result"]["worktree"]
    except (KeyError, TypeError):
        return None
    return record if isinstance(record, dict) and isinstance(record.get("id"), str) else None


def terminal_lines(handle: str, screen: bool) -> list[str] | None:
    """Return the lines of a terminal's rendered screen or accumulated output, or None when they cannot be read."""
    payload = orca_run("terminal", "read", "--terminal", handle, *(["--screen"] if screen else []))
    try:
        terminal = payload["result"]["terminal"]
    except (KeyError, TypeError):
        return None
    tail = terminal.get("tail") if isinstance(terminal, dict) else None
    if not isinstance(terminal, dict) or terminal.get("status", "running") != "running" or terminal.get("draft"):
        return None
    if isinstance(tail, str):
        return tail.splitlines()
    return tail if isinstance(tail, list) and all(isinstance(line, str) for line in tail) else None


def is_prompt_line(line: str) -> bool:
    stripped = line.rstrip()
    return bool(stripped) and stripped[-1] in PROMPT_ENDINGS


def never_used(handle: str) -> bool:
    """True only when the terminal shows one shell prompt with an empty input line and its output holds no command."""
    shown = terminal_lines(handle, screen=True)
    if shown is None or len([line for line in shown if line.strip()]) != 1 or not is_prompt_line(
        next(line for line in shown if line.strip())
    ):
        return False
    output = terminal_lines(handle, screen=False)
    return output is not None and all(
        not line.strip() or is_prompt_line(line) or line.lstrip().startswith(BANNER) for line in output
    )


def close_never_used_terminals(worktree: dict) -> None:
    """Close each never-used shell terminal of `worktree` other than this session's own."""
    payload = orca_run("terminal", "list", "--worktree", f'id:{worktree["id"]}')
    try:
        rows = payload["result"]["terminals"]
    except (KeyError, TypeError):
        return
    own = os.environ.get("ORCA_TERMINAL_HANDLE")
    deadline = time.monotonic() + TIDY_SECONDS
    candidates = [
        row["handle"]
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("handle"), str)
        and row["handle"] != own
        and not row.get("agentIdentity")
        and row.get("worktreeId", worktree["id"]) == worktree["id"]
    ] if isinstance(rows, list) else []
    for handle in candidates[:TIDY_TERMINAL_LIMIT]:
        if time.monotonic() > deadline:
            return
        if never_used(handle):
            orca_run("terminal", "close", "--terminal", handle)


@dataclass
class State:
    """One session's memory: fired fingerprints, its tab title, and the worktrees it created."""

    path: Path | None
    fired: set[str] = field(default_factory=set)
    tab_title: str | None = None
    creates: list[dict] = field(default_factory=list)
    agents: list[dict] = field(default_factory=list)
    cwd: str | None = None
    seq: int = 0
    shown_user: int = 0
    shown_context: int = 0

    @classmethod
    def load(cls, session_id: object) -> State:
        key = approval_state_store.session_key(session_id)
        if key is None:
            return cls(None)
        state = cls(approval_state_store.state_dir().parent / STATE_SUBDIRECTORY / f"{key}.json")
        try:
            data = json.loads(state.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return state
        if not isinstance(data, dict):
            return state
        fired = data.get("fired")
        state.fired = {item for item in fired if isinstance(item, str)} if isinstance(fired, list) else set()
        if isinstance(data.get("tab_title"), str):
            state.tab_title = data["tab_title"]
        for name in ("creates", "agents"):
            if isinstance(data.get(name), list):
                setattr(state, name, [item for item in data[name] if isinstance(item, dict)])
        if isinstance(data.get("cwd"), str):
            state.cwd = data["cwd"]
        for name in ("seq", "shown_user", "shown_context"):
            value = data.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(state, name, int(value))
        return state

    def save(self) -> bool:
        """Write the state; report False when that fails, so the caller passes instead of repeating."""
        if self.path is None:
            return True
        data = {
            "fired": sorted(self.fired),
            "tab_title": self.tab_title,
            "creates": self.creates,
            "agents": self.agents,
            "cwd": self.cwd,
            "seq": self.seq,
            "shown_user": self.shown_user,
            "shown_context": self.shown_context,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".orca-status-", dir=self.path.parent)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
            os.replace(temporary, self.path)
            cutoff = time.time() - approval_state_store.RETENTION_SECONDS
            for other in self.path.parent.glob("*.json"):
                if other != self.path and other.stat().st_mtime < cutoff:
                    other.unlink(missing_ok=True)
        except OSError:
            return False
        return True

    def mark(self, fingerprint: str) -> bool:
        self.fired.add(fingerprint)
        return self.save()


def response_text(event: dict) -> str:
    response = event.get("tool_response")
    if isinstance(response, dict):
        return "\n".join(str(response.get(name) or "") for name in ("stdout", "output") if response.get(name))
    return response if isinstance(response, str) else ""


def literal_rename_title(command: str) -> str | None:
    """Return the title that the last `orca terminal rename` of this session's own terminal sets, if readable."""
    handle = os.environ.get("ORCA_TERMINAL_HANDLE")
    found = None
    for tokens in segments_of(command):
        arguments = orca_arguments(tokens)
        if arguments is None:
            continue
        if [token for token in arguments if not token.startswith("-")][:2] != ["terminal", "rename"]:
            continue
        terminals, titles = option_values(arguments, "--terminal"), option_values(arguments, "--title")
        if not terminals or not titles or not (terminals[-1] in TERMINAL_HANDLE_REFERENCES or terminals[-1] == handle):
            continue
        title = " ".join(titles[-1].split())
        if title and "$" not in title and "`" not in title:
            found = title
    return found


def rename_confirmed(output: str, title: str) -> bool:
    """True when the output holds the JSON of an `orca terminal rename` that set `title`: result.rename.title."""
    decoder = json.JSONDecoder()
    index = output.find("{")
    while index != -1:
        try:
            data, end = decoder.raw_decode(output, index)
        except ValueError:
            index = output.find("{", index + 1)
            continue
        result = data.get("result") if isinstance(data, dict) else None
        rename = result.get("rename") if isinstance(result, dict) else None
        if isinstance(rename, dict) and isinstance(rename.get("title"), str):
            if " ".join(rename["title"].split()) == title:
                return True
        index = output.find("{", end)
    return False


def record_title(command: str, state: State, output: str) -> None:
    title = literal_rename_title(command)
    if title is not None and title != state.tab_title and rename_confirmed(output, title):
        state.tab_title = title
        state.save()


def title_context(state: State) -> dict | None:
    if not state.tab_title:
        return None
    line = TAB_TITLE_LINE.format(title=state.tab_title)
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": line}}


RENAME_COMMAND = '`orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE" --title "<ticket key> <short summary>" --json`'
END_TURN = "then end the turn without repeating the reply."
R4_REASON = f"This session's terminal tab has no title for its task. Run {RENAME_COMMAND}, {END_TURN}"


def r3_reason(worktree: dict, rename: bool) -> str:
    name = f'`orca worktree set --worktree id:{worktree["id"]} --display-name "<ticket key> <short summary>" --json`'
    commands = name + (f" and {RENAME_COMMAND}" if rename else "")
    return f"This task worktree still has its automatic name. Run {commands}, {END_TURN}"


def evaluate(turns: list[Turn], state: State) -> str | None:
    """Return the reason to block the stop with, or None."""
    needs_rename = not any(turn.rename for turn in turns) and "R4" not in state.fired
    if any(turn.edits or turn.commit for turn in turns) and "R3" not in state.fired:
        worktree = orca_worktree()
        if worktree is None:
            return None
        base = worktree.get("path")
        in_worktree = isinstance(base, str) and (
            any(turn.commit for turn in turns) or any(inside(path, base) for turn in turns for path in turn.edits)
        )
        if worktree.get("isMainWorktree") is True or worktree.get("displayNameMode") != "automatic":
            state.mark("R3")
        elif in_worktree and state.mark("R3") and (not needs_rename or state.mark("R4")):
            return r3_reason(worktree, needs_rename)
    if needs_rename and any(turn.set_any for turn in turns) and state.mark("R4"):
        return R4_REASON
    return None


def applies(event: object) -> bool:
    if not os.environ.get("ORCA_TERMINAL_HANDLE"):
        return False
    if os.environ.get("HEI5ENBUG_ASSIGNED_ROLE") or os.environ.get("HEI5ENBUG_PARENT_SESSION"):
        return False
    return isinstance(event, dict) and not event.get("agent_id")


def record_own_rename(event: dict, state: State) -> None:
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if event.get("tool_name") == "Bash" and isinstance(command, str) and "rename" in command:
        record_title(command, state, response_text(event))


def record_creations(event: dict, state: State) -> None:
    """Remember the worktrees and agent sessions a Bash command of this session creates, from its tool input."""
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if event.get("tool_name") != "Bash" or not isinstance(command, str) or "orca" not in command:
        return
    creates, agents = orca_cleanup_state.parse_command(command)
    if not creates and not agents:
        return
    start, end = orca_cleanup_state.window_of(time.time(), event.get("duration_ms"))
    for item in creates:
        state.seq += 1
        state.creates.append({**item, "seq": state.seq, "start": start, "end": end})
    state.agents.extend(agents)
    state.creates = state.creates[-orca_cleanup_state.MAX_RECORDS :]
    state.agents = state.agents[-orca_cleanup_state.MAX_RECORDS :]
    if isinstance(event.get("cwd"), str):
        state.cwd = event["cwd"]
    state.save()


def cleanup_step(name: str, event: dict, state: State) -> tuple[str | None, str | None]:
    """Start the detached run when a created worktree is due, and return the user line and the context line to show.

    Nothing starts and nothing is shown for a session that created no worktree, or while a run is active; the lines
    name each worktree the last run removed or kept, the user line at the first event after it and the context line at
    the next prompt.
    """
    if state.path is None or not state.creates:
        return None, None
    cwd = event.get("cwd")
    if isinstance(cwd, str) and cwd != state.cwd:
        state.cwd = cwd
        state.save()
    results = orca_cleanup_state.read_results(orca_cleanup_state.result_path(state.path))
    if (
        name in ("Stop", "UserPromptSubmit")
        and os.environ.get(ORCA_TERMINAL_MARKER)
        and orca_cleanup_state.needs_run(state.creates, len(state.agents), results)
    ):
        orca_cleanup_state.start_run(state.path)
    if orca_cleanup_state.run_active(state.path):
        return None, None
    user = orca_cleanup_state.unseen_notices(results, state.shown_user)
    context = orca_cleanup_state.unseen_notices(results, state.shown_context) if name == "UserPromptSubmit" else []
    if user:
        state.shown_user = max(item["seq"] for item in user)
    if context:
        state.shown_context = max(item["seq"] for item in context)
    if user or context:
        state.save()
    return (
        orca_cleanup_state.notice_line(user) if user else None,
        orca_cleanup_state.notice_line(context) if context else None,
    )


def with_notices(output: dict | None, name: str, user: str | None, context: str | None) -> dict | None:
    if user:
        output = {**(output or {}), "systemMessage": user}
    if context:
        specific = dict((output or {}).get("hookSpecificOutput") or {"hookEventName": name})
        specific["additionalContext"] = "\n".join(filter(None, [specific.get("additionalContext"), context]))
        output = {**(output or {}), "hookSpecificOutput": specific}
    return output


def handle_stop(event: dict, state: State) -> dict | None:
    if event.get("stop_hook_active") is True or not isinstance(event.get("transcript_path"), str):
        return None
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    turns = read_turns(event["transcript_path"], cwd)
    if not turns:
        return None
    reason = evaluate(turns, state)
    if not reason:
        return None
    if language_guard.detect_host() == "claude":
        return {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}
    return {"decision": "block", "reason": reason}


def handle(event: object) -> dict | None:
    if not applies(event):
        return None
    name = event.get("hook_event_name")
    if name not in ("Stop", "PostToolUse", "UserPromptSubmit"):
        return None
    state = State.load(event.get("session_id"))
    if name == "Stop":
        output = handle_stop(event, state)
    elif name == "PostToolUse":
        record_own_rename(event, state)
        record_creations(event, state)
        output = None
    else:
        if (
            os.environ.get(ORCA_TERMINAL_MARKER)
            and state.path is not None
            and TIDY_FINGERPRINT not in state.fired
            and state.mark(TIDY_FINGERPRINT)
        ):
            worktree = orca_worktree()
            if worktree is not None:
                close_never_used_terminals(worktree)
        output = title_context(state)
    user, context = cleanup_step(name, event, state)
    return with_notices(output, name, user, context)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        output = handle(event)
    except Exception as error:
        hook_runtime.report_error("orca_status_hook.py", error)
        output = None
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(hook_runtime.run("orca_status_hook.py", main))
