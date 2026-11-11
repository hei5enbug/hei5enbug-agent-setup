"""Hook that keeps the session's Orca worktree status, name, and tab title in step with what the session did.

It runs only in an Orca terminal, for the main session. Without a model turn it writes the Orca text that follows
mechanically from an event, on the session's own current worktree:

- after a pull or merge request is created (PostToolUse), the status `in-review` and a comment with the request's link;
- when a turn ends with a question and ran no `orca worktree set` (Stop), `--unread` and a comment that starts with a
  waiting label and the question's first line, keeping the earlier comment; the user's next prompt (UserPromptSubmit)
  restores that comment while it is still the hook's own;
- after an edit or a commit inside the worktree, whose status is `completed`, `todo`, or unset (PostToolUse),
  `in-progress`;
- after the session renames its own terminal tab with a literal title (PostToolUse), that title is remembered, and each
  later prompt (UserPromptSubmit) gets one context line that names it, so the session can retitle when its work moves on.

The `orca_status_writes` option turns these writes off. At Stop it also keeps the turn going once per state with a
one-command instruction, which Claude Code shows as Stop hook feedback rather than a hook error, and which costs model
tokens only then, when a task worktree the session changed still has its automatic name, or when the session updated
its worktree and never titled its tab. A failed read of Orca, Git, or the transcript lets the event pass. A Codex
transcript records tool calls as script text, so the hook reads Claude Code transcripts only.
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
import plugin_toggles  # noqa: E402
from orca_placement_hook import orca_arguments  # noqa: E402
from required_checks_hook import ASSIGNMENT, OPTIONS_WITH_VALUE, WRAPPERS, git_subcommand, segments_of  # noqa: E402

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"})
PULL_REQUEST_CREATORS = (("gh", "pr", "create"), ("az", "repos", "pr", "create"), ("glab", "mr", "create"))
NOT_A_PROMPT = ("<task-notification", "<local-command-", "<system-reminder")
READ_TIMEOUT_SECONDS = 3
STATE_SUBDIRECTORY = "orca-status"
DEFAULT_STATUSES = frozenset({"todo", "in-progress", "in-review", "completed"})
RESUME_STATUSES = frozenset({"", "todo", "completed"})
STATUS_RECHECK_SECONDS = 60
QUESTION_LIMIT = 80
REQUEST_URL = re.compile(
    r"https?://[^\s\"'<>)\]]+/(?:-/)?(?:pulls?|pullrequests?|merge_requests)/\d+", re.IGNORECASE
)
NO_CREATE_OPTIONS = frozenset({"--help", "-h", "--dry-run"})
PATCH_PATH = re.compile(r"^\*\*\* (?:Update|Add) File: (.+)$", re.MULTILINE)
ASSISTANT_ENTRY = re.compile(rb'"type": ?"assistant"')
USER_ENTRY = re.compile(rb'"type": ?"user"')
TOOL_RESULT_BLOCK = re.compile(rb'"type": ?"tool_result"')
TAB_TITLE_LINE = (
    "Current Orca tab title: {title}. If this prompt asks about or for work the title does not name, such as another "
    "ticket, pull request, repository, document, or goal, retitle the tab and refresh the worktree comment before "
    "starting it. A follow-up, fix, review, merge, or question on the titled work keeps the title, as does one the "
    "user set."
)
TERMINAL_HANDLE_REFERENCES = frozenset({"$ORCA_TERMINAL_HANDLE", "${ORCA_TERMINAL_HANDLE}"})
LABELS = {
    "Korean": {"review": "리뷰 대기", "question": "답변 대기"},
    "English": {"review": "Waiting for review", "question": "Waiting for you"},
}


@dataclass
class Turn:
    """What one turn, from a real user prompt to the next, did that Orca should show."""

    pull_request: bool = False
    commit: bool = False
    edits: set[str] = field(default_factory=set)
    set_any: bool = False
    named: bool = False
    rename: bool = False
    final_text: str = ""

    def asks(self) -> bool:
        return asks_in_text(self.final_text)


def asks_in_text(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and lines[-1].endswith(("?", "？"))


def question_line(turn: Turn) -> str:
    """Return the first line of the turn's closing question, cut to the comment's limit."""
    paragraphs = [paragraph for paragraph in re.split(r"\n\s*\n", turn.final_text.strip()) if paragraph.strip()]
    text = paragraphs[-1] if paragraphs else ""
    line = next((line.strip() for line in text.splitlines() if line.strip()), "").lstrip("*#>-• ").strip()
    return line if len(line) <= QUESTION_LIMIT else line[: QUESTION_LIMIT - 1].rstrip() + "…"


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


def program_words(tokens: list[str]) -> tuple[str, list[str]] | None:
    """Return the program's base name and its non-option words, after environment assignments and wrappers."""
    index = 0
    while index < len(tokens) and (ASSIGNMENT.match(tokens[index]) or tokens[index] in WRAPPERS):
        index += 1
    if index >= len(tokens):
        return None
    return os.path.basename(tokens[index]), [token for token in tokens[index + 1 :] if not token.startswith("-")]


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
        parsed = program_words(tokens)
        if parsed and not NO_CREATE_OPTIONS.intersection(tokens) and any(
            parsed[0] == words[0] and parsed[1][: len(words) - 1] == list(words[1:]) for words in PULL_REQUEST_CREATORS
        ):
            turn.pull_request = True


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
                elif block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip():
                    turn.final_text = block["text"]
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


def worktree_set(worktree: dict, *flags: str) -> bool:
    return orca_run("worktree", "set", "--worktree", f"id:{worktree['id']}", *flags) is not None


@dataclass
class State:
    """One session's memory: fired fingerprints, the comment the hook replaced, the status recheck time, and its title."""

    path: Path | None
    fired: set[str] = field(default_factory=set)
    previous_comment: str | None = None
    written_comment: str | None = None
    status_ok_until: float = 0.0
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
        for name in ("previous_comment", "written_comment", "tab_title"):
            if isinstance(data.get(name), str):
                setattr(state, name, data[name])
        if isinstance(data.get("status_ok_until"), (int, float)):
            state.status_ok_until = float(data["status_ok_until"])
        return state

    def save(self) -> bool:
        """Write the state; report False when that fails, so the caller passes instead of repeating."""
        if self.path is None:
            return True
        data = {
            "fired": sorted(self.fired),
            "previous_comment": self.previous_comment,
            "written_comment": self.written_comment,
            "status_ok_until": self.status_ok_until,
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


def labels(event: dict) -> dict[str, str]:
    language = language_guard.resolve_language(event, language_guard.detect_host())
    return LABELS["Korean" if language == "Korean" else "English"]


def board_flags(worktree: dict, status: str) -> list[str]:
    """Return the status flag, left out on a board that uses a status id other than the defaults."""
    current = worktree.get("workspaceStatus") or ""
    return ["--workspace-status", status] if current == "" or current in DEFAULT_STATUSES else []


def response_text(event: dict) -> str:
    response = event.get("tool_response")
    if isinstance(response, dict):
        return "\n".join(str(response.get(name) or "") for name in ("stdout", "output") if response.get(name))
    return response if isinstance(response, str) else ""


def created_request(output: str) -> str | None:
    """Return the link of the pull or merge request that a tool output shows as created, or None."""
    found = REQUEST_URL.findall(output)
    if found:
        return found[-1]
    try:
        data = json.loads(output)
    except ValueError:
        return None
    if isinstance(data, dict) and isinstance(data.get("pullRequestId"), int):
        repository = data.get("repository")
        web = repository.get("webUrl") if isinstance(repository, dict) else None
        number = data["pullRequestId"]
        return f"{web}/pullrequest/{number}" if isinstance(web, str) and web else f"#{number}"
    return None


def write_review(event: dict, state: State) -> None:
    link = created_request(response_text(event))
    key = f"PR:{event.get('tool_use_id') or event.get('tool_input', {}).get('command', '')}"
    if link is None or key in state.fired:
        return
    worktree = orca_worktree()
    if worktree is None:
        return
    if state.mark(key):
        worktree_set(worktree, *board_flags(worktree, "in-review"), "--comment", f"{labels(event)['review']}: {link}")


def resolve_directory(base: str | None, value: str | None) -> str | None:
    """Return `value` resolved against `base`, or None when either is unknown or `value` uses a variable."""
    if not base or not value or "$" in value or "`" in value:
        return None
    return os.path.normpath(os.path.join(base, os.path.expanduser(value)))


def git_directory(tokens: list[str], current: str | None) -> str | None:
    """Return the directory a git command works in: `current`, moved by each global `-C <dir>`."""
    index = 0
    while index < len(tokens) and (ASSIGNMENT.match(tokens[index]) or tokens[index] in WRAPPERS):
        index += 1
    directory = current
    index += 1
    while index < len(tokens) and tokens[index].startswith("-"):
        if tokens[index] == "-C":
            directory = resolve_directory(directory, tokens[index + 1] if index + 1 < len(tokens) else None)
            index += 2
        else:
            index += 2 if tokens[index] in OPTIONS_WITH_VALUE else 1
    return directory


def commit_directories(command: str, cwd: str) -> set[str]:
    """Return the directories the commit commands of `command` run in, following `cd <dir>` and `git -C <dir>`."""
    current: str | None = cwd
    found: set[str] = set()
    for tokens in segments_of(command):
        parsed = program_words(tokens)
        if parsed and parsed[0] == "cd":
            current = resolve_directory(current, parsed[1][0] if parsed[1] else None)
        elif git_subcommand(tokens) == "commit":
            directory = git_directory(tokens, current)
            if directory:
                found.add(directory)
    return found


def write_resume(state: State, paths: set[str]) -> None:
    if time.time() < state.status_ok_until:
        return
    worktree = orca_worktree()
    if worktree is None:
        state.status_ok_until = time.time() + STATUS_RECHECK_SECONDS
        state.save()
        return
    base = worktree.get("path")
    if not (isinstance(base, str) and any(inside(path, base) for path in paths)):
        return
    if (worktree.get("workspaceStatus") or "") in RESUME_STATUSES:
        worktree_set(worktree, "--workspace-status", "in-progress")
    state.status_ok_until = time.time() + STATUS_RECHECK_SECONDS
    state.save()


def write_question(event: dict, turns: list[Turn], state: State) -> None:
    last = turns[-1]
    line = question_line(last)
    key = f"Q:{len(turns)}:{line}"
    if not (last.asks() and line) or last.set_any or key in state.fired:
        return
    worktree = orca_worktree()
    if worktree is None:
        return
    current = worktree.get("comment") if isinstance(worktree.get("comment"), str) else ""
    previous = state.previous_comment if state.written_comment and current == state.written_comment else current
    comment = f"{labels(event)['question']}: {line}" + (f" · {previous}" if previous else "")
    state.fired.add(key)
    state.previous_comment, state.written_comment = previous, comment
    if state.save():
        worktree_set(worktree, "--comment", comment, "--unread")


def restore_comment(state: State) -> None:
    if state.written_comment is None:
        return
    worktree = orca_worktree()
    if worktree is None:
        return
    if worktree.get("comment") == state.written_comment:
        worktree_set(worktree, "--comment", state.previous_comment or "")
    state.previous_comment = state.written_comment = None
    state.save()


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


def handle_post_tool_use(event: dict, state: State) -> None:
    record_own_rename(event, state)
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    name = event.get("tool_name")
    if name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return
        if not ("create" in command or "commit" in command):
            return
        turn = Turn()
        command_signals(command, turn)
        if turn.pull_request:
            write_review(event, state)
        if turn.commit:
            cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
            directories = commit_directories(command, cwd)
            if directories:
                write_resume(state, directories)
    elif name in EDIT_TOOLS:
        cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
        paths = edited_paths(name, tool_input, cwd)
        if paths:
            write_resume(state, paths)


def handle_stop(event: dict, state: State, writes: bool) -> dict | None:
    if event.get("stop_hook_active") is True or not isinstance(event.get("transcript_path"), str):
        return None
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    turns = read_turns(event["transcript_path"], cwd)
    if not turns:
        return None
    text = event.get("last_assistant_message")
    if isinstance(text, str) and text.strip():
        turns[-1].final_text = text
    if writes:
        write_question(event, turns, state)
    reason = evaluate(turns, state)
    if not reason:
        return None
    if language_guard.detect_host() == "claude":
        return {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}
    return {"decision": "block", "reason": reason}


def handle(event: object) -> dict | None:
    if not applies(event):
        return None
    writes = plugin_toggles.enabled("orca_status_writes")
    name = event.get("hook_event_name")
    if name not in ("Stop", "PostToolUse", "UserPromptSubmit"):
        return None
    state = State.load(event.get("session_id"))
    if name == "Stop":
        return handle_stop(event, state, writes)
    if name == "PostToolUse":
        if writes:
            handle_post_tool_use(event, state)
        else:
            record_own_rename(event, state)
        return None
    if writes:
        restore_comment(state)
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
