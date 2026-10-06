#!/usr/bin/env python3
"""Session approval guard for Claude Code: approve a kind of outward-facing write once per session.

Selected actions (`git tag`, a tag push, `gh release` writes, and MCP tools that write) ask the first time in a
session. After the user lets one run, the PostToolUse event records its key for that session, and later actions of the
same kind in the same session are allowed without a prompt. Destructive actions always ask. Everything the guard does not
recognize prints nothing, so the host keeps its normal behavior.

The guard never allows an action whose keys were not recorded for the same session by the main session, and never
allows a compound command that holds a subcommand it does not understand. Without a data directory, a string session
id, or with an `agent_id` event, nothing is allowed or recorded. Any error prints nothing and exits 0. Codex prints
nothing for every event.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None

DATAGRIP_TOOL = "mcp__datagrip__execute_sql_query"
STATE_FILE = "session_approvals.json"
LOCK_FILE = "session_approvals.lock"
RETENTION_SECONDS = 7 * 24 * 60 * 60
TAG_LOOKUP_TIMEOUT = 3

DESTRUCTIVE_REASON = "Always asks: this action cannot be undone."
UNVERIFIABLE_REASON = "Contains a command the session approval cannot verify."

SEPARATORS = {"&&", "||", ";", "|", "|&", "&"}
PUNCTUATION = set("();<>|&")
OPAQUE_COMMAND = re.compile(
    r"\$\(|`|<<|\beval\b|\bxargs\b|\b(?:bash|sh|zsh|dash|ksh)\s+-[A-Za-z]*c\b|\\\n"
)
SCAN_KEYS = (("git tag", "git:tag"), ("git push", "git:push-tag"), ("gh release", "gh:release"))
SCAN_DESTRUCTIVE = re.compile(
    r"\bgh\s+(?:release|repo)\s+delete|\bgit\s+tag\b[^;&|]*\s(?:-d|--delete|-f|--force)\b"
    r"|\bgit\s+push\b[^;&|]*\s(?:-[A-Za-z]*[fd][A-Za-z]*|--force\S*|--delete|--mirror|--prune|\+\S+|:\S+)(?:\s|$)"
)
EXPANSION_TOKEN = re.compile(r"[${}`!\\]|^~")
GLOB_TOKEN = re.compile(r"[*?\[\]]")
RISKY_CONFIG_KEY = re.compile(
    r"ssh|hook|fsmonitor|pager|editor|helper|alias|insteadof|pushurl|proxy|include|exec|program|askpass|command|gpg"
    r"|filter|textconv|url",
    re.I,
)
TAG_VALUE_OPTIONS = {"-m", "-F", "-u", "--message", "--file", "--local-user", "--cleanup"}
TAG_LIST_OPTIONS = re.compile(
    r"^(?:-l|--list|-n\d*|-v|--verify|--contains(?:=.*)?|--no-contains(?:=.*)?|--points-at(?:=.*)?|--merged(?:=.*)?"
    r"|--no-merged(?:=.*)?|--sort(?:=.*)?|--format(?:=.*)?|--column(?:=.*)?|--no-column)$"
)
PUSH_DESTRUCTIVE_OPTIONS = {"--force", "--force-if-includes", "--delete", "--mirror", "--prune"}
PUSH_BENIGN_OPTIONS = {
    "-u", "--set-upstream", "-v", "--verbose", "-q", "--quiet", "-n", "--dry-run", "--no-verify", "--atomic",
    "--progress", "--no-progress", "--thin", "--no-thin",
}
SINGLE_DASH_CLUSTER = re.compile(r"^-[A-Za-z0-9]+$")
RELEASE_VALUE_FLAGS = {"--title", "-t", "--notes", "-n", "--target"}
RELEASE_SWITCH_FLAGS = {"--generate-notes", "--notes-from-tag", "--latest", "--draft", "--prerelease", "--verify-tag"}
READ_VERBS = {
    "get", "list", "search", "read", "fetch", "query", "find", "lookup", "describe", "show", "view", "check",
    "count", "browse", "download", "export", "preview", "introspect", "analyze", "explain",
}
DESTRUCTIVE_WORDS = {"delete", "trash", "remove", "destroy", "purge", "drop", "unshare", "revoke"}
WRITE_WORDS = {
    "send", "post", "reply", "create", "update", "edit", "add", "write", "upsert", "transition", "schedule",
    "share", "copy", "move", "upload", "comment", "label", "unlabel", "mark", "unmark", "forward", "apply", "set",
    "rename", "link", "react", "reaction", "publish", "merge", "close", "reopen", "assign", "invite", "patch",
}

Result = tuple  # (keys: set[str], destructive: bool, fully_known: bool)


def expands(token: str) -> bool:
    return bool(EXPANSION_TOKEN.search(token))


def unsafe(token: str) -> bool:
    return expands(token) or bool(GLOB_TOKEN.search(token))


def lex(command: str) -> list:
    text = re.sub(r"\r\n|\n|\r", " ; ", command)
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.commenters = ""
    lexer.whitespace_split = True
    return list(lexer)


def split_subcommands(tokens: list) -> list:
    commands = [[]]
    for token in tokens:
        if token in SEPARATORS:
            commands.append([])
        else:
            commands[-1].append(token)
    return [words for words in commands if words]


def scan_opaque(command: str) -> Result:
    keys = {key for needle, key in SCAN_KEYS if needle in command}
    return keys, bool(SCAN_DESTRUCTIVE.search(command)), False


def join_directory(base, argument):
    if base is None or not argument or unsafe(argument):
        return None
    return str((Path(base) / argument).resolve())


def tag_exists(directory, name: str) -> bool:
    if directory is None or not name or name.startswith("-") or unsafe(name):
        return False
    try:
        completed = subprocess.run(
            ["git", "-C", directory, "rev-parse", "-q", "--verify", f"refs/tags/{name}"],
            capture_output=True,
            timeout=TAG_LOOKUP_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def git_remotes(directory):
    if directory is None:
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", directory, "remote"], capture_output=True, text=True, timeout=TAG_LOOKUP_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return set((completed.stdout or "").split())


def classify_tag(args: list, state: dict) -> Result:
    positionals = []
    destructive = False
    listing = False
    unknown = False
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg in TAG_VALUE_OPTIONS:
            index += 1
            continue
        if arg.startswith("--") and arg.split("=", 1)[0] in {"--message", "--file", "--local-user", "--cleanup"}:
            continue
        if arg in ("-d", "--delete", "-f", "--force"):
            destructive = True
        elif SINGLE_DASH_CLUSTER.match(arg) and re.search(r"[df]", arg[1:]) and not TAG_LIST_OPTIONS.match(arg):
            destructive = True
        elif TAG_LIST_OPTIONS.match(arg):
            listing = True
        elif arg.startswith("-"):
            if unsafe(arg):
                unknown = True
        else:
            positionals.append(arg)
            if expands(arg):
                unknown = True
    if destructive:
        return set(), True, True
    if unknown:
        return set(), False, False
    if not listing and any(unsafe(item) for item in positionals):
        return set(), False, False
    if listing or not args:
        return set(), False, True
    if positionals:
        state["created"].add(positionals[0])
    return {"git:tag"}, False, True


def classify_push(args: list, state: dict, directory) -> Result:
    positionals = []
    tag_flag = False
    destructive = False
    unknown = False
    for arg in args:
        if arg in PUSH_DESTRUCTIVE_OPTIONS or arg.startswith("--force-with-lease"):
            destructive = True
        elif SINGLE_DASH_CLUSTER.match(arg) and re.search(r"[fd]", arg[1:]):
            destructive = True
        elif arg in ("--tags", "--follow-tags"):
            tag_flag = True
        elif arg in PUSH_BENIGN_OPTIONS:
            pass
        elif arg.startswith("-"):
            unknown = True
        else:
            positionals.append(arg)
    if any(item.startswith(("+", ":")) or item.startswith("-") for item in positionals):
        destructive = True
    if destructive:
        return set(), True, True
    refspecs = positionals[1:]
    plain = not unknown and not any(unsafe(item) for item in positionals)
    is_tag_push = (
        tag_flag
        or any(item.startswith("refs/tags/") for item in refspecs)
        or (plain and bool(refspecs) and all(item in state["created"] or tag_exists(directory, item) for item in refspecs))
    )
    if not is_tag_push:
        return set(), False, False
    remote_known = not positionals or (plain and positionals[0] in (git_remotes(directory) or set()))
    known = plain and remote_known and not (tag_flag and refspecs)
    return {"git:push-tag"}, False, known


def classify_git(words: list, state: dict) -> Result:
    directory = state["dir"]
    index = 1
    while index < len(words):
        word = words[index]
        if word == "-C" and index + 1 < len(words):
            directory = join_directory(directory, words[index + 1])
            index += 2
        elif word == "-c" and index + 1 < len(words):
            key = words[index + 1].split("=", 1)[0]
            if RISKY_CONFIG_KEY.search(key) or unsafe(words[index + 1]):
                return set(), False, False
            index += 2
        elif word.startswith(("--git-dir=", "--work-tree=")):
            if unsafe(word):
                return set(), False, False
            directory = None
            index += 1
        elif word in ("--no-pager", "-P"):
            index += 1
        else:
            break
    if index >= len(words):
        return set(), False, False
    subcommand, args = words[index], words[index + 1:]
    if subcommand == "tag":
        return classify_tag(args, state)
    if subcommand == "push":
        return classify_push(args, state, directory)
    return set(), False, False


def release_write_is_known(args: list) -> bool:
    positionals = 0
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        name = arg.split("=", 1)[0]
        if arg.startswith("-"):
            if name in RELEASE_VALUE_FLAGS:
                if "=" not in arg:
                    if index >= len(args):
                        return False
                    index += 1
            elif name not in RELEASE_SWITCH_FLAGS:
                return False
        else:
            positionals += 1
            if unsafe(arg):
                return False
    return positionals == 1


def classify_gh(words: list) -> Result:
    if len(words) < 3 or any(unsafe(word) or word.startswith("-") for word in words[1:3]):
        return set(), False, False
    area, action = words[1], words[2]
    if area == "repo" and action.startswith("delete"):
        return set(), True, True
    if area == "release":
        if action.startswith("delete"):
            return set(), True, True
        if action in ("create", "edit"):
            return {"gh:release"}, False, release_write_is_known(words[3:])
        if action == "upload":
            return {"gh:release"}, False, False
    return set(), False, False


def classify_subcommand(words: list, state: dict) -> Result:
    if any(word and all(char in PUNCTUATION for char in word) for word in words):
        return set(), False, False
    head = words[0]
    if head == "echo":
        return set(), False, not any(unsafe(word) for word in words[1:])
    if head == "cd":
        if len(words) == 2:
            state["dir"] = join_directory(state["dir"], words[1])
            return set(), False, True
        return set(), False, False
    if head == "git":
        return classify_git(words, state)
    if head == "gh":
        return classify_gh(words)
    return set(), False, False


def classify_bash(command, cwd) -> Result:
    if not isinstance(command, str) or not command.strip():
        return set(), False, False
    if OPAQUE_COMMAND.search(command):
        return scan_opaque(command)
    try:
        subcommands = split_subcommands(lex(command))
    except ValueError:
        return scan_opaque(command)
    state = {"dir": cwd if isinstance(cwd, str) and cwd else os.getcwd(), "created": set()}
    keys: set = set()
    destructive = False
    known = True
    for words in subcommands:
        sub_keys, sub_destructive, sub_known = classify_subcommand(words, state)
        keys |= sub_keys
        destructive = destructive or sub_destructive
        known = known and (sub_known or sub_destructive)
    return keys, destructive, known


def tool_word_list(tool_part: str) -> list:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", tool_part)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", spaced)
    return [word for word in re.split(r"[_\-\s]+", spaced.lower()) if word]


def tool_words(tool_part: str) -> set:
    return set(tool_word_list(tool_part))


def classify_mcp(tool_name: str) -> Result:
    if tool_name == DATAGRIP_TOOL:
        return set(), False, False
    parts = tool_name.split("__", 2)
    if len(parts) < 3:
        return set(), False, False
    ordered = tool_word_list(parts[2])
    words = set(ordered)
    if words & DESTRUCTIVE_WORDS:
        return {f"mcp:{tool_name}"}, True, True
    if ordered and ordered[0] in READ_VERBS:
        return set(), False, False
    if words & WRITE_WORDS:
        return {f"mcp:{tool_name}"}, False, True
    return set(), False, False


def classify(tool_name, tool_input, cwd) -> Result:
    if tool_name == "Bash":
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        return classify_bash(command, cwd)
    if isinstance(tool_name, str) and tool_name.startswith("mcp__"):
        return classify_mcp(tool_name)
    return set(), False, False


def data_directory():
    value = os.environ.get("CLAUDE_PLUGIN_DATA")
    return Path(value) if value else None


def read_state(directory: Path) -> dict:
    try:
        loaded = json.loads((directory / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def approved_keys(directory, session_id) -> set:
    if directory is None or not isinstance(session_id, str) or not session_id:
        return set()
    entry = read_state(directory).get(session_id)
    if not isinstance(entry, dict) or not isinstance(entry.get("time"), (int, float)):
        return set()
    if entry["time"] < time.time() - RETENTION_SECONDS or not isinstance(entry.get("keys"), list):
        return set()
    return {key for key in entry["keys"] if isinstance(key, str)}


def record_keys(directory: Path, session_id: str, keys: set) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / LOCK_FILE, "a", encoding="utf-8") as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        now = time.time()
        state = {
            sid: entry
            for sid, entry in read_state(directory).items()
            if isinstance(entry, dict)
            and isinstance(entry.get("time"), (int, float))
            and entry["time"] >= now - RETENTION_SECONDS
            and isinstance(entry.get("keys"), list)
        }
        existing = {key for key in state.get(session_id, {}).get("keys", []) if isinstance(key, str)}
        state[session_id] = {"time": now, "keys": sorted(existing | keys)}
        descriptor, temporary = tempfile.mkstemp(prefix=".session-approvals-", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream)
            os.replace(temporary, directory / STATE_FILE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def permission(decision: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


def handle_pre_tool_use(event: dict):
    keys, destructive, known = classify(event.get("tool_name"), event.get("tool_input"), event.get("cwd"))
    if destructive:
        return permission("ask", DESTRUCTIVE_REASON)
    if not keys:
        return None
    approved = set() if event.get("agent_id") else approved_keys(data_directory(), event.get("session_id"))
    listed = ", ".join(sorted(keys))
    if not known:
        return permission("ask", UNVERIFIABLE_REASON)
    if keys <= approved:
        return permission("allow", f"Approved earlier in this session: {listed}")
    return permission("ask", f"First time in this session: approving it allows {listed} for the rest of the session.")


def handle_post_tool_use(event: dict) -> None:
    if event.get("agent_id"):
        return
    keys, destructive, _ = classify(event.get("tool_name"), event.get("tool_input"), event.get("cwd"))
    session_id = event.get("session_id")
    directory = data_directory()
    if destructive or not keys or directory is None or not isinstance(session_id, str) or not session_id:
        return
    record_keys(directory, session_id, keys)


def detect_host() -> str:
    root = Path(__file__).resolve().parents[1]
    codex_root = os.environ.get("PLUGIN_ROOT")
    return "codex" if codex_root and Path(codex_root).resolve() == root else "claude"


def handle(event):
    if not isinstance(event, dict) or detect_host() == "codex":
        return None
    name = event.get("hook_event_name")
    if name == "PreToolUse":
        return handle_pre_tool_use(event)
    if name == "PostToolUse":
        handle_post_tool_use(event)
    return None


def main() -> int:
    try:
        output = handle(json.load(sys.stdin))
    except Exception:
        output = None
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
