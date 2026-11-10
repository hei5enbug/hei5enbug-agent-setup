"""PreToolUse hook: deny a command that creates a top-level Orca worktree or starts an agent session on low memory.

It denies `orca worktree create` with `--no-parent` and `orca orchestration worker-start` with `--worktree
new-top-level`, also inside a command substitution; a here-document body is checked only for command
substitutions, since Bash never runs it as a command. It also denies a command that starts an agent session through
Orca when the available memory is below the `session_memory_min_mb` option.

It denies a worktree whose parent belongs to another repository than the worktree itself, from `orca worktree create`,
a `worker-start` that creates a worktree, or `orca worktree set --parent-worktree`, when both repositories can be
resolved. It also denies `orca worktree set --workspace-status completed` for a worktree with uncommitted changes or commits
its upstream lacks, and, inside an Orca terminal, an `EnterWorktree` call that would create a worktree Orca never
lists. It denies `orca worktree set --display-name <name>` with a non-empty name on a worktree that `orca worktree list`
marks `isMainWorktree: true`, resolving `path:`, `id:`, `name:`, `branch:`, and `identity:` selectors through the list
and `active` or `current` through `orca worktree current` in the event's directory; an empty name restores the automatic
name and stays allowed. An unreadable Orca, an unlisted target, or a selector that matches both a main clone and
another worktree lets the command pass. The input is parsed only when its raw text contains orca and a word one of
those rules needs, or EnterWorktree.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass

import plugin_toggles
import session_memory
from required_checks_hook import ASSIGNMENT, WRAPPERS, command_of, segments_of

ORCA_PROGRAMS = frozenset({"orca", "orca-dev", "orca-ide"})
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
MAX_TEXTS = 64
DEFAULT_MIN_MB = 2048
MEMORY_OFF_VALUES = frozenset({"0", "off", "false", "no"})
AGENT_PROGRAMS = frozenset({"claude", "codex"})
PREFILTER_WORDS = (
    "no-parent", "new-top-level", "--agent", "worker-start", "--command", "completed", "parent-worktree",
    "display-name",
)
GIT_TIMEOUT_SECONDS = 2
ORCA_TIMEOUT_SECONDS = 2
MAX_LISTED_FILES = 5
REASON = (
    "Blocked: this command creates a top-level Orca worktree. Put a new worktree under its own repository's "
    "existing workspace: use `--parent-worktree active` in this repository, "
    "or `--parent-worktree id:<repoId>::<clone path>` for another repository's workspace; with orchestration, use "
    "`--worktree new-child` or an existing worktree. Only when Orca lists no workspace for the repository, or the "
    "user asked for a top-level worktree in "
    "this conversation, create it with a parent and then run `orca worktree set --worktree <id> --no-parent "
    "--json`."
)
MEMORY_REASON = (
    "Blocked: {available} MB of memory is available, below the {threshold} MB this plugin keeps free before "
    "starting another agent session. Do not retry now. Record the session as waiting for memory, in the root's "
    "status table when it belongs to a group, and continue work that needs no new session. Start it after a "
    "running session or worker of this task finishes or is cleaned up; never poll memory. When nothing of this "
    "task is running, tell the user in one line and suggest the session-triage skill to free memory. The user can "
    "lower `session_memory_min_mb`."
)
PARENT_REASON = (
    "Blocked: this worktree's parent belongs to another repository. Every worktree goes under its own repository's "
    "workspace, `--parent-worktree id:<repoId>::<clone path>`, or `active` only when the current worktree is that "
    "workspace, also in a task that changes several repositories. Tie a ticket's worktrees in several repositories by "
    "`--reference <issue link>`, a display name that starts with the ticket key, and one orchestration Run, as "
    "`instructions/orca-groups.md` says."
)
ENTER_REASON = (
    "Blocked: a worktree made with EnterWorktree is one Orca never lists. Create it through Orca so the sidebar and "
    "the board show it: `orca worktree create --repo path:<repo> --name <branch> --base-branch <base> "
    "--parent-worktree active --json`, then work in the path it returns; to continue in an existing worktree, call "
    "EnterWorktree with its `path`."
)
MAIN_CLONE_REASON = (
    "Blocked: this worktree is the repository's main clone, which other sessions share, so its display name must "
    "stay automatic. Never rename it. Label this session with `orca terminal rename --terminal "
    "\"$ORCA_TERMINAL_HANDLE\" --title \"<ticket key> <short summary>\" --json` instead."
)
COMPLETED_REASON = (
    "Blocked: this worktree is not done, so it cannot be marked completed: {remaining}. Commit and push the work, "
    "or keep the status and write what remains in `--comment`; set `completed` only when no change of the task "
    "is left."
)


def orca_arguments(tokens: list[str]) -> list[str] | None:
    index = 0
    while index < len(tokens) and (ASSIGNMENT.match(tokens[index]) or tokens[index] in WRAPPERS):
        index += 1
    if index >= len(tokens) or os.path.basename(tokens[index]) not in ORCA_PROGRAMS:
        return None
    return tokens[index + 1 :]


def creates_top_level_worktree(tokens: list[str]) -> bool:
    arguments = orca_arguments(tokens)
    if arguments is None:
        return False
    pair = [token for token in arguments if not token.startswith("-")][:2]
    if pair == ["worktree", "create"]:
        return "--no-parent" in arguments
    if pair == ["orchestration", "worker-start"]:
        if "--worktree=new-top-level" in arguments:
            return True
        return any(
            token == "--worktree" and following == "new-top-level"
            for token, following in zip(arguments, arguments[1:])
        )
    return False


def option_after(arguments: list[str], name: str) -> str | None:
    """Return the value of `--name value` or `--name=value`, or None when it is absent or has no value."""
    for token, following in zip(arguments, [*arguments[1:], None]):
        if token == name and following is not None:
            return following
        if token.startswith(name + "=") and len(token) > len(name) + 1:
            return token[len(name) + 1 :]
    return None


def starts_agent_session(tokens: list[str]) -> bool:
    arguments = orca_arguments(tokens)
    if arguments is None:
        return False
    pair = [token for token in arguments if not token.startswith("-")][:2]
    if pair == ["worktree", "create"]:
        return option_after(arguments, "--agent") is not None
    if pair == ["orchestration", "worker-start"] or pair == ["agent", "launch"]:
        return True
    if pair == ["terminal", "create"]:
        command = option_after(arguments, "--command")
        return bool(command) and any(runs_agent_program(words) for words in segments_of(command))
    return False


def runs_agent_program(tokens: list[str]) -> bool:
    index = 0
    while index < len(tokens) and (ASSIGNMENT.match(tokens[index]) or tokens[index] in WRAPPERS):
        index += 1
    return index < len(tokens) and os.path.basename(tokens[index]) in AGENT_PROGRAMS


def memory_threshold_mb() -> int:
    """Return the configured minimum free memory in MB, 0 when the gate is off."""
    value = plugin_toggles.option_value("session_memory_min_mb")
    if value in MEMORY_OFF_VALUES:
        return 0
    return int(value) if re.fullmatch(r"[0-9]+", value) else DEFAULT_MIN_MB


def memory_reason() -> str | None:
    threshold = memory_threshold_mb()
    if threshold == 0:
        return None
    available = session_memory.available_mb()
    if available is None or available >= threshold:
        return None
    return MEMORY_REASON.format(available=available, threshold=threshold)


@dataclass
class RepoRef:
    """What a selector says about a repository: its Orca id and a path inside it, or the current worktree."""

    id: str | None = None
    path: str | None = None
    current: bool = False


def repo_ref(selector: str | None, cwd: str, worktree: bool) -> RepoRef | None:
    """Resolve a `--repo`, `--worktree`, or `--parent-worktree` selector; None when it names no known repository."""
    if selector is None or selector in ("active", "current"):
        return RepoRef(path=cwd, current=True)
    if selector.startswith("id:"):
        value = selector[3:]
        if "::" in value:
            repo_id, path = value.split("::", 1)
            return RepoRef(id=repo_id or None, path=path or None)
        return None if worktree or not value else RepoRef(id=value)
    if selector.startswith("path:") and len(selector) > 5:
        return RepoRef(path=selector[5:])
    return None


def git_common_dir(path: str) -> str | None:
    output = git_output(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.realpath(output.strip()) if output and output.strip() else None


def current_repo_id() -> str | None:
    try:
        result = subprocess.run(
            ["orca", "worktree", "current", "--json"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
        value = json.loads(result.stdout)["result"]["worktree"]["repoId"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
    return value if result.returncode == 0 and isinstance(value, str) and value else None


def same_repository(first: RepoRef, second: RepoRef) -> bool | None:
    """Return whether two references name one repository, or None when that cannot be decided."""
    for left, right in ((first, second), (second, first)):
        if left.current and left.id is None and right.id is not None:
            left.id = current_repo_id()
    if first.id is not None and second.id is not None:
        return first.id == second.id
    if first.path is not None and second.path is not None:
        directories = (git_common_dir(first.path), git_common_dir(second.path))
        return directories[0] == directories[1] if all(directories) else None
    return None


def parent_denial(tokens: list[str], cwd: str) -> bool:
    """Report whether a command gives a worktree a parent that belongs to another repository."""
    arguments = orca_arguments(tokens)
    if arguments is None or "--no-parent" in arguments:
        return False
    pair = [token for token in arguments if not token.startswith("-")][:2]
    parent = option_after(arguments, "--parent-worktree")
    if pair == ["worktree", "create"]:
        target = repo_ref(option_after(arguments, "--repo"), cwd, worktree=False)
    elif pair == ["worktree", "set"]:
        target = repo_ref(option_after(arguments, "--worktree"), cwd, worktree=True)
    elif pair == ["orchestration", "worker-start"] and option_after(arguments, "--worktree") == "new-child":
        target, parent = repo_ref(option_after(arguments, "--repo"), cwd, worktree=False), "current"
    else:
        return False
    parent_ref = repo_ref(parent, cwd, worktree=True) if parent is not None else None
    if target is None or parent_ref is None:
        return False
    return same_repository(target, parent_ref) is False


def worktree_path(arguments: list[str], cwd: str) -> str | None:
    """Return the path a `--worktree` selector names, the current directory for the current worktree, or None."""
    selector = option_after(arguments, "--worktree")
    if selector is None or selector in ("active", "current"):
        return cwd
    if selector.startswith("id:") and "::" in selector:
        return selector.split("::", 1)[1] or None
    if selector.startswith("path:"):
        return selector[len("path:") :] or None
    return None


def git_output(path: str, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", path, "--no-optional-locks", *arguments],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def remaining_work(path: str) -> str | None:
    """Describe the uncommitted changes and unpushed commits of the worktree at `path`; None when none or unreadable."""
    status = git_output(path, "status", "--porcelain")
    if status is None:
        return None
    parts = []
    changes = [line[3:] for line in status.splitlines() if line.strip()]
    if changes:
        listed = ", ".join(changes[:MAX_LISTED_FILES])
        more = f", and {len(changes) - MAX_LISTED_FILES} more" if len(changes) > MAX_LISTED_FILES else ""
        parts.append(f"{len(changes)} uncommitted change{'s' if len(changes) != 1 else ''} ({listed}{more})")
    ahead = git_output(path, "rev-list", "--count", "@{upstream}..HEAD")
    if ahead is None:
        ahead = git_output(path, "rev-list", "--count", "HEAD", "--not", "--remotes")
    if ahead is not None and ahead.strip().isdigit() and int(ahead) > 0:
        count = int(ahead)
        parts.append(f"{count} commit{'s' if count != 1 else ''} its upstream lacks")
    return "; ".join(parts) or None


def completed_denial(tokens: list[str], cwd: str) -> str | None:
    arguments = orca_arguments(tokens)
    if arguments is None:
        return None
    if [token for token in arguments if not token.startswith("-")][:2] != ["worktree", "set"]:
        return None
    if option_after(arguments, "--workspace-status") != "completed":
        return None
    path = worktree_path(arguments, cwd)
    remaining = remaining_work(path) if path and os.path.isdir(path) else None
    return COMPLETED_REASON.format(remaining=remaining) if remaining else None


def orca_result(cwd: str, *arguments: str) -> dict | None:
    """Return the `result` of an `orca ... --json` command run in `cwd`, or None when it failed."""
    try:
        run = subprocess.run(
            ["orca", *arguments, "--json"], capture_output=True, text=True, timeout=ORCA_TIMEOUT_SECONDS, check=False,
            cwd=cwd if os.path.isdir(cwd) else None,
        )
        payload = json.loads(run.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    result = payload.get("result") if isinstance(payload, dict) and run.returncode == 0 else None
    return result if isinstance(result, dict) else None


def branch_name(value: object) -> str:
    return value.removeprefix("refs/heads/") if isinstance(value, str) else ""


def same_path(first: object, second: object) -> bool:
    if not (isinstance(first, str) and isinstance(second, str) and first and second):
        return False
    return os.path.realpath(first) == os.path.realpath(second)


def selects(record: dict, selector: str) -> bool:
    """Report whether a listed worktree record is the one an explicit selector names."""
    kind, _, value = selector.partition(":")
    if not value:
        return False
    if kind == "path":
        return same_path(record.get("path"), value)
    if kind == "id":
        repo_id, _, path = value.partition("::")
        return record.get("id") == value or (
            bool(path) and record.get("repoId") == repo_id and same_path(record.get("path"), path)
        )
    if kind == "name":
        return record.get("displayName") == value
    if kind == "branch":
        return branch_name(record.get("branch")) == branch_name(value)
    if kind == "identity":
        identity = record.get("identity")
        return (identity.get("key") if isinstance(identity, dict) else identity) == value
    return False


def targets_main_clone(selector: str, cwd: str) -> bool:
    """Report whether Orca lists worktrees for a selector and marks every one of them as a repository's main clone."""
    if selector in ("active", "current"):
        result = orca_result(cwd, "worktree", "current")
        record = result.get("worktree") if result else None
        return isinstance(record, dict) and record.get("isMainWorktree") is True
    result = orca_result(cwd, "worktree", "list")
    records = result.get("worktrees") if result else None
    if not isinstance(records, list):
        return False
    matches = [record for record in records if isinstance(record, dict) and selects(record, selector)]
    return bool(matches) and all(record.get("isMainWorktree") is True for record in matches)


def main_clone_rename_denial(tokens: list[str], cwd: str) -> bool:
    """Report whether a command gives a repository's main clone a display name."""
    arguments = orca_arguments(tokens)
    if arguments is None or [token for token in arguments if not token.startswith("-")][:2] != ["worktree", "set"]:
        return False
    name = option_after(arguments, "--display-name")
    selector = option_after(arguments, "--worktree")
    return bool(name and name.strip() and selector and targets_main_clone(selector, cwd))


def creates_worktree_through_host(raw: str) -> bool:
    """Report whether `raw` is an EnterWorktree call, inside an Orca terminal, that creates a worktree."""
    if not os.environ.get("ORCA_TERMINAL_HANDLE"):
        return False
    try:
        event = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(event, dict) or event.get("tool_name") != "EnterWorktree":
        return False
    tool_input = event.get("tool_input")
    path = tool_input.get("path") if isinstance(tool_input, dict) else None
    return not (isinstance(path, str) and path.strip())


def split_heredocs(text: str) -> tuple[str, list[str]]:
    """Return the text without here-document bodies, and the bodies whose delimiter is unquoted."""
    kept: list[str] = []
    expanded: list[str] = []
    pending: list[tuple[str, bool, bool]] = []
    body: list[str] = []
    for line in text.split("\n"):
        if pending:
            delimiter, strip_tabs, unquoted = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                pending.pop(0)
                if unquoted:
                    expanded.append("\n".join(body))
                body = []
            else:
                body.append(line)
            continue
        kept.append(line)
        pending = [(match[3], match[1] == "-", not match[2]) for match in HEREDOC.finditer(line)]
    if pending and pending[0][2]:
        expanded.append("\n".join(body))
    return "\n".join(kept), expanded


def substitutions(text: str, shell_quotes: bool = True) -> list[str]:
    """Return the contents of each outermost `$(...)` and backtick command substitution.

    With shell quoting, an escaped `$` or backtick and text inside single quotes stay literal; a here-document body
    has no such quoting, so it is scanned with `shell_quotes` off.
    """
    found: list[str] = []
    index = 0
    in_double = False
    while index < len(text):
        char = text[index]
        if shell_quotes and char == "\\":
            index += 2
        elif shell_quotes and char == "'" and not in_double:
            end = text.find("'", index + 1)
            index = len(text) if end < 0 else end + 1
        elif shell_quotes and char == '"':
            in_double = not in_double
            index += 1
        elif text.startswith("$(", index) and not text.startswith("$((", index):
            depth, end = 1, index + 2
            while end < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[end], 0)
                end += 1
            found.append(text[index + 2 : end - 1] if depth == 0 else text[index + 2 :])
            index = end
        elif text[index] == "`":
            end = text.find("`", index + 1)
            found.append(text[index + 1 :] if end < 0 else text[index + 1 : end])
            index = len(text) if end < 0 else end + 1
        else:
            index += 1
    return found


def texts_to_check(command: str) -> list[str]:
    pending = [command]
    checked: list[str] = []
    while pending and len(checked) < MAX_TEXTS:
        kept, bodies = split_heredocs(pending.pop())
        checked.append(kept)
        pending.extend(substitutions(kept))
        for body in bodies:
            pending.extend(substitutions(body, shell_quotes=False))
    return checked


def event_cwd(raw: str) -> str:
    try:
        value = json.loads(raw).get("cwd")
    except (ValueError, AttributeError):
        value = None
    return value if isinstance(value, str) and value else os.getcwd()


def deny(reason: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def main() -> int:
    raw = sys.stdin.read()
    if "EnterWorktree" in raw and creates_worktree_through_host(raw):
        deny(ENTER_REASON)
        return 0
    if "orca" not in raw or not (
        any(word in raw for word in PREFILTER_WORDS) or ("agent" in raw and "launch" in raw)
    ):
        return 0
    command = command_of(raw)
    if command is None:
        return 0
    segments = [tokens for text in texts_to_check(command) for tokens in segments_of(text)]
    if any(creates_top_level_worktree(tokens) for tokens in segments):
        deny(REASON)
    elif any(parent_denial(tokens, event_cwd(raw)) for tokens in segments):
        deny(PARENT_REASON)
    elif any(starts_agent_session(tokens) for tokens in segments):
        reason = memory_reason()
        if reason:
            deny(reason)
    else:
        cwd = event_cwd(raw)
        reason = next((r for r in (completed_denial(tokens, cwd) for tokens in segments) if r), None)
        if reason is None and any(main_clone_rename_denial(tokens, cwd) for tokens in segments):
            reason = MAIN_CLONE_REASON
        if reason:
            deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
