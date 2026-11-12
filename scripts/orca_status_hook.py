"""Hook that keeps the session's tab title in step with its work and reminds it of a missing name or tab title.

It runs only in an Orca terminal, for the main session, and writes nothing to Orca: it only reads Orca, Git, and the
transcript.

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


def has_option(arguments: list[str], *names: str) -> bool:
    return any(token in names or token.startswith(tuple(f"{name}=" for name in names)) for token in arguments)


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


def orca_run(*arguments: str) -> dict | None:
    """Run an `orca` command with `--json`; return its parsed result, or None when it failed or took too long."""
    try:
        result = subprocess.run(
            ["orca", *arguments, "--json"],
            capture_output=True,
            text=True,
            timeout=READ_TIMEOUT_SECONDS,
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


@dataclass
class State:
    """One session's memory: fired fingerprints and its tab title."""

    path: Path | None
    fired: set[str] = field(default_factory=set)
    tab_title: str | None = None

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
        return state

    def save(self) -> bool:
        """Write the state; report False when that fails, so the caller passes instead of repeating."""
        if self.path is None:
            return True
        data = {
            "fired": sorted(self.fired),
            "tab_title": self.tab_title,
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


def option_values(arguments: list[str], name: str) -> list[str]:
    """Return the value of each `name` option in `arguments`, written as `name value` or `name=value`."""
    values = []
    for index, token in enumerate(arguments):
        if token == name and index + 1 < len(arguments):
            values.append(arguments[index + 1])
        elif token.startswith(f"{name}="):
            values.append(token[len(name) + 1 :])
    return values


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
        return handle_stop(event, state)
    if name == "PostToolUse":
        record_own_rename(event, state)
        return None
    return title_context(state)


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
