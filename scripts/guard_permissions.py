"""Edit permissions, host permission requests, read limits protection, and risk records for the approval guard."""
import functools
import json
import os
import re
from pathlib import Path
import approval_state
import db_read_policy
from approval_state import Outcome
from guard_shell import (
    ASSIGNMENT, ParseError, _datagrip, _destructive_text, _digest, read_only_command, strip_prefix, tokenize,
    wrap_command,
)
from guard_paths import _expand_path_variables, _protected_path, _state_path, _static_value
from guard_expand import _expand_segment_words
import guard_temp
import guard_dispatch
from guard_dispatch import DESTRUCTIVE_COMMAND, TEMP_WRITE_EXE
from guard_tools import _classify_safely, _report_error, tabularis_connection


DATAGRIP_TOOL = "mcp__datagrip__execute_sql_query"
SECRET_REASON = (
    "This command would print a secret value. Run it through `python3 {root}/scripts/secret_exec.py --secret "
    "VAR=<source> -- <command>` instead; the value reaches the command only through an environment variable or a "
    "temporary file."
)
READ_REASON = "Read-only call; it runs without approval."
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
CLAUDE_PROTECTED_DIRS = frozenset({".git", ".claude", ".vscode", ".idea", ".husky"})
CLAUDE_PROTECTED_FILES = frozenset({
    ".bashrc", ".bash_profile", ".zshrc", ".zprofile", ".profile", ".gitconfig", ".gitmodules", ".mcp.json",
    ".claude.json", ".ripgreprc",
})
REMOTE_PROGRAM = re.compile(r"(?<![\w.-])(?:ssh|scp|rsync|sudo|su|doas)(?![\w-])")
FUNCTION_DEFINITION = re.compile(r"\(\s*\)")


def _cwd(event):
    cwd = event.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()


def _deny_secret():
    root = Path(__file__).resolve().parents[1]
    return approval_state.pre_output("deny", SECRET_REASON.format(root=root))


def _enforced_read(outcome, tool_input):
    """The tabularis input of a production read with its result limit and SQL Server safeguards, or None."""
    if outcome.exe not in (db_read_policy.ENFORCE_POSTGRES, db_read_policy.ENFORCE_SQLSERVER) \
            or not isinstance(tool_input, dict) or not isinstance(tool_input.get("query"), str):
        return None
    connection = tabularis_connection(tool_input.get("connection_id")) or (None, None)
    return db_read_policy.enforce("tabularis", tool_input, outcome.exe, connection[:2],
                                  _datagrip().session_settings(tool_input["query"]))


def _read_decision(host, outcome, tool_input):
    """A psql read runs with the server enforcing read-only mode; when that cannot be applied, it runs as before."""
    enforced = _enforced_read(outcome, tool_input)
    if enforced is not None:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": READ_REASON,
            "updatedInput": enforced,
        }}
    if outcome.exe == "psql" and isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        updated = {**tool_input, "command": read_only_command(tool_input["command"])}
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": READ_REASON,
            "updatedInput": updated,
        }}
    if host == "codex":
        return None
    return approval_state.pre_output("allow", READ_REASON)


def _claude_settings_files(project):
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    return [Path(project) / ".claude" / "settings.local.json", Path(project) / ".claude" / "settings.json",
            (Path(config) if config else Path.home() / ".claude") / "settings.json"]


def _edit_roots(project):
    roots = [Path(project).resolve()]
    for path in _claude_settings_files(project):
        try:
            values = json.loads(path.read_text(encoding="utf-8"))["permissions"]["additionalDirectories"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(values, list):
            roots.extend((Path(project) / os.path.expanduser(value)).resolve()
                         for value in values if isinstance(value, str) and value)
    return roots


def _editable_path(path, cwd, roots):
    """A path inside a root, outside the guard state and the host's protected paths, so the host would only prompt."""
    if "$" in path:
        return False
    candidate = (Path(cwd) / os.path.expanduser(path)).resolve()
    if (_state_path(path, cwd) or _protected_path(path, cwd) or candidate.name in CLAUDE_PROTECTED_FILES
            or CLAUDE_PROTECTED_DIRS & set(candidate.parts)):
        return False
    return any(candidate.is_relative_to(root) for root in roots)


def _session_covered(session, host="claude"):
    """Whether the session-wide key of the `session` approval scope is held."""
    return approval_state.scope_held(host, session)


def _edit_permission(session, tool_input, tool_name, cwd):
    paths = [tool_input.get(key) for key in ("file_path", "notebook_path")] if isinstance(tool_input, dict) else []
    paths = [path for path in paths if path is not None]
    if not paths or not all(isinstance(path, str) and path for path in paths):
        return None
    roots = _edit_roots(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
    if not all(_editable_path(path, cwd, roots) for path in paths):
        return None
    if _session_covered(session) or approval_state.is_approved("claude", session, [approval_state.WRITE_KEY]):
        return approval_state.permission_allow()
    if not approval_state.parent_session():
        digest = approval_state.permission_digest(tool_name, tool_input)
        grants = [approval_state.WRITE_KEY, *([approval_state.ALL_KEY] if approval_state.session_scope() else [])]
        if not approval_state.request_ask("claude", session, [], [approval_state.WRITE_KEY], "pr:" + digest, grants):
            return approval_state.permission_deny(approval_state.stop_reason("claude"))
    return None


def _plugin_file(tool_input, cwd):
    """A Read of this plugin's own files, such as its instruction references, which the host asks about only because
    they sit outside the working directories."""
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(path, str) or not path or "$" in path:
        return False
    root = Path(__file__).resolve().parents[1]
    return (Path(cwd) / os.path.expanduser(path)).resolve().is_relative_to(root)


def _plain_command(command):
    return not (_destructive_text(command) or REMOTE_PROGRAM.search(command) or DESTRUCTIVE_COMMAND.search(command))


RM_WORD = re.compile(r"(?<![\w./-])rm(?![\w-])")


def _removes_only_inside_temporary_root(command, cwd):
    """Whether a command that the guard passes holds recursive removals and every `rm` in it removes only static paths
    strictly inside a temporary root. Claude Code's own check of dangerous removals asks even when the guard passes, and
    only a PermissionRequest answer can settle it. The command is classified again with a trace of each `rm` call; a
    call the trace missed, an unresolved target, or a non-recursive removal means no. Every other command in it must be
    inert, a local read the guard itself classifies, or a write confined to a temporary root."""
    mentions = len(RM_WORD.findall(command))
    if not mentions or FUNCTION_DEFINITION.search(command):
        return False
    trace = guard_temp._REMOVAL_TRACE = []
    commands = guard_temp._COMMAND_TRACE = []
    try:
        outcome = _classify_safely(lambda: guard_dispatch.classify_text(command, cwd), command)
    finally:
        guard_temp._REMOVAL_TRACE = guard_temp._COMMAND_TRACE = None
    return (outcome.kind == "pass" and len(trace) >= mentions and all(trace)
            and all(entry is True for entry in commands))


MEMORY_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})


def _memory_project_folder(event):
    """The folder of this session's project under Claude's projects folder: the transcript path's nearest ancestor whose
    parent is named `projects`, else, only when the event has no transcript path, the folder that the sanitized
    CLAUDE_PROJECT_DIR names under `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`."""
    transcript = event.get("transcript_path") if isinstance(event, dict) else None
    if transcript is not None:
        if not isinstance(transcript, str) or not transcript:
            return None
        return next((parent for parent in Path(transcript).parents if parent.parent.name == "projects"), None)
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project:
        return None
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(configured) if configured else Path.home() / ".claude"
    return root / "projects" / re.sub(r"[^A-Za-z0-9]", "-", project)


def _auto_memory_file(tool_input, event, cwd):
    """Whether a Write, Edit, or MultiEdit targets a Markdown file inside this session's own auto-memory folder, after
    both the file and the folder resolve through links, and the folder stays inside the project folder."""
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(path, str) or not path or "\0" in path or not path.endswith(".md") or path.endswith("/.md"):
        return False
    project = _memory_project_folder(event)
    if project is None:
        return False
    try:
        folder = (project / "memory").resolve()
        target = (Path(cwd) / os.path.expanduser(path)).resolve()
        return folder.is_relative_to(project.resolve()) and target != folder and target.is_relative_to(folder)
    except (OSError, RuntimeError, ValueError):
        return False


def _claude_permission(session, outcome, tool_input, tool_name, cwd, event=None):
    """Claude's PermissionRequest answers `allow` only for what the session's write approval already covers."""
    if outcome.kind in ("pass", "write") and tool_name in MEMORY_TOOLS and _auto_memory_file(tool_input, event, cwd):
        return approval_state.permission_allow()
    if outcome.kind == "pass":
        if tool_name in EDIT_TOOLS:
            return _edit_permission(session, tool_input, tool_name, cwd)
        if tool_name == "Read" and _plugin_file(tool_input, cwd):
            return approval_state.permission_allow()
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if tool_name == "Bash" and outcome.exe == TEMP_WRITE_EXE:
            return approval_state.permission_allow()
        if tool_name == "Bash" and isinstance(command, str) and _plain_command(command) and (
                _session_covered(session) or approval_state.is_approved("claude", session, [approval_state.WRITE_KEY])):
            return approval_state.permission_allow()
        if tool_name == "Bash" and isinstance(command, str) and _removes_only_inside_temporary_root(command, cwd):
            return approval_state.permission_allow()
        return None
    if approval_state.all_granted("claude", session, outcome):
        return approval_state.permission_allow()
    once_keys, session_keys = approval_state.split_outcome(outcome)
    if outcome.kind == "read" or outcome.every_time or once_keys or not session_keys:
        return None
    return approval_state.permission_allow() if approval_state.is_approved("claude", session, session_keys) else None


@functools.lru_cache(maxsize=None)
def _codex_config(path, mtime, size):
    try:
        import tomllib
    except ImportError:
        return None
    try:
        with open(path, "rb") as stream:
            config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError, UnicodeError):
        return None
    return config if isinstance(config, dict) else None


def _tool_label(value):
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)


def _mcp_prompt_mode(home, tool):
    """Whether the tool's effective approval mode in Codex's config.toml is prompt, so the native window asks."""
    first = tool.find("__")
    second = tool.find("__", first + 2) if first >= 0 else -1
    if second < 0:
        return False
    server_label, tool_label = tool[first + 2:second], tool[second + 2:]
    path = home / "config.toml"
    try:
        stat = path.stat()
    except OSError:
        return False
    servers = (_codex_config(str(path), stat.st_mtime_ns, stat.st_size) or {}).get("mcp_servers")
    if not isinstance(servers, dict):
        return False
    for name, server in servers.items():
        if not isinstance(server, dict) or _tool_label(name) != server_label:
            continue
        tools = server.get("tools")
        settings = [setting for key, setting in (tools.items() if isinstance(tools, dict) else [])
                    if _tool_label(key) == tool_label and isinstance(setting, dict) and "approval_mode" in setting]
        mode = settings[0]["approval_mode"] if settings else server.get("default_tools_approval_mode")
        return mode == "prompt"
    return False


def native_ready(event):
    """Whether Codex's own approval window can ask for this call: native approval is on, the session is interactive
    and not a child, the plugin-owned rules file is current, and an MCP tool's approval mode is prompt."""
    if not isinstance(event, dict) or event.get("permission_mode") != "default":
        return False
    if os.environ.get("HEI5ENBUG_PARENT_SESSION"):
        return False
    try:
        import host_settings
        if not host_settings.CODEX_NATIVE_APPROVAL:
            return False
        home = host_settings.resolve_codex_home()
        current = (home / "rules" / host_settings.RULES_NAME).read_text(encoding="utf-8")
        if current != host_settings.rules_text(host_settings.ROOT):
            return False
        tool = event.get("tool_name")
        return _mcp_prompt_mode(home, tool) if isinstance(tool, str) and tool.startswith("mcp__") else True
    except (OSError, UnicodeError, ImportError, ValueError):
        return False


def _native_tool(tool_name):
    return isinstance(tool_name, str) and (tool_name == "Bash" or tool_name.startswith("mcp__"))


def _native_covers(tool_name, outcome):
    """Whether the native window may stand in for the code flow: a Bash call always, an MCP or DataGrip call only when
    it asks once per session, because the window's mode comes from a file that a CLI override can change."""
    if not _native_tool(tool_name):
        return False
    return tool_name == "Bash" or not approval_state.split_outcome(outcome)[0]


def _native_pre(session, outcome, tool_input, wrapped):
    """Codex PreToolUse while the native window can ask: a Bash call that needs approval runs through the wrapper,
    whose prefix rule shows the window. MCP calls and wrapper calls need no change, and no code is issued."""
    once_keys, session_keys = approval_state.split_outcome(outcome)
    if wrapped or not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        return None
    if approval_state.all_granted("codex", session, outcome) or (
            not once_keys and approval_state.is_approved("codex", session, session_keys)):
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "Approval needed: " + approval_state.describe(outcome),
        "updatedInput": {**tool_input, "command": wrap_command(tool_input["command"])},
    }}


def codex_permission(session, outcome, tool_use_id, tool_input, tool_name, event):
    """Codex PermissionRequest: allow what is already approved; otherwise let the native window ask and remember
    which session keys that window grants once the call completes."""
    if outcome.kind == "read" or approval_state.permission_allowed("codex", session, outcome, tool_use_id):
        return approval_state.permission_allow()
    once_keys, session_keys = approval_state.split_outcome(outcome)
    if (outcome.kind not in ("write", "always", "sensitive", "request") or not (once_keys or session_keys)
            or not _native_covers(tool_name, outcome) or approval_state.session_key(session) is None
            or not native_ready(event)):
        return None
    request_id = "pr:" + approval_state.permission_digest(tool_name, tool_input)
    grants = approval_state.scope_keys(outcome, session_keys)
    if not approval_state.request_ask("codex", session, once_keys, session_keys, request_id, grants):
        return approval_state.permission_deny(approval_state.stop_reason("codex"))
    return None


def _record_risk(host, session, tool_use_id, tool, outcome):
    """Record the call's kind for the Claude Code mod's transcript marker; a file edit is the session write it asks for.
    A failure here never changes the decision."""
    try:
        if host != "claude":
            return
        if isinstance(tool, str) and tool in EDIT_TOOLS and outcome.kind == "pass":
            outcome = outcome._replace(kind="write")
        approval_state.record_risk(host, session, tool_use_id, outcome)
    except Exception:
        return


LIMITS_READS = frozenset({"ls", "cat", "head", "tail", "grep", "wc", "stat", "file", "jq"})
LIMITS_WRITERS = frozenset({"tee", "mv", "cp", "install", "ln", "truncate", "rm", "rmdir", "unlink", "shred"})
LIMITS_REMOVERS = frozenset({"rm", "rmdir", "mv", "unlink", "shred"})
QUOTE_MARKS = re.compile(r"[\"'\\]")
DYNAMIC_MARKS = ("$", "`", "<(", ">(")


def _limits_write_form(segment, words):
    """Whether a simple command writes: an output redirection, or a writing program."""
    program, _ = strip_prefix(words)
    name = os.path.basename(program[0]) if program else ""
    return (any(">" in operator and target != "/dev/null" for _, operator, target in segment.redirects)
            or name in LIMITS_WRITERS or name == "dd" and any(word.startswith("of=") for word in program[1:])
            or name == "sed" and any(re.fullmatch(r"-[A-Za-z]*i[A-Za-z]*|--in-place(?:=.*)?", word)
                                     for word in program[1:]))


def _limits_command_outcome(command, cwd=None):
    """An every-time outcome for a command that touches the database read limits file or its folder, unless it only
    reads. Words and redirection targets are compared after quote and escape removal, simple joins through fixed
    variables are followed, and a write whose path cannot be resolved counts when the folder is the working folder."""
    path = db_read_policy.limits_path()
    folder = path.parent
    ask = Outcome("always", [f"db-limits:{_digest(command)}"], ["Change to the database read limits file"],
                  every_time=True)

    def mentions(text):
        text = QUOTE_MARKS.sub("", text)
        expanded = os.path.expandvars(text).replace("~/", f"{Path.home()}/")
        return any(name in value for value in (text, expanded) for name in (path.name, str(folder)))

    try:
        segments = tokenize(command)
    except ParseError:
        return ask if mentions(command) else None
    home = folder.resolve()

    def within(candidate):
        return candidate == home or home in candidate.parents

    statics, directory = {}, Path(cwd or os.getcwd()).resolve()
    named = dynamic = writes = False
    inside = within(directory)
    for segment in segments:
        words = _expand_segment_words(segment, statics)
        if all(ASSIGNMENT.match(word) for word in words):
            for word in words:
                key, _, value = word.partition("=")
                fixed = _static_value(os.path.expandvars(value), statics, os.environ)
                if fixed is None:
                    statics.pop(key, None)
                else:
                    statics[key] = fixed
            continue
        targets = [_expand_path_variables(target, statics) for _, operator, target in segment.redirects
                   if "<<" not in operator]
        program, _ = strip_prefix(words)
        name = os.path.basename(program[0]) if program else ""
        for text in (*words, *targets):
            plain = QUOTE_MARKS.sub("", os.path.expandvars(text))
            dynamic = dynamic or any(mark in plain for mark in DYNAMIC_MARKS)
            named = named or mentions(text)
            for candidate in {plain, plain.partition("=")[2]} - {""}:
                if any(mark in candidate for mark in DYNAMIC_MARKS) or candidate.startswith("-") or " " in candidate:
                    continue
                try:
                    resolved = (directory / os.path.expanduser(candidate)).resolve()
                except (OSError, RuntimeError, ValueError):
                    continue
                if within(resolved):
                    named = inside = True
                elif name in LIMITS_REMOVERS and resolved != Path("/") and home.is_relative_to(resolved):
                    named = True
        writes = writes or _limits_write_form(segment, words)
        if name == "cd" and len(program) == 2 and not any(mark in program[1] for mark in DYNAMIC_MARKS):
            try:
                directory = (directory / os.path.expanduser(QUOTE_MARKS.sub("", program[1]))).resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            inside = inside or within(directory)
    if named:
        plain_read = not any(mark in command for mark in ("$(", "`", "<(", ">(")) and all(
            segment.words and os.path.basename(segment.words[0]) in LIMITS_READS and not any(
                ">" in operator and target != "/dev/null" for _, operator, target in segment.redirects)
            for segment in segments if not all(ASSIGNMENT.match(word) for word in segment.words))
        return None if plain_read else ask
    return ask if dynamic and writes and inside else None


def _capture_plan(host, session, tool, event):
    """After a successful PostgreSQL plan statement on a production connection, record its estimate for the session."""
    try:
        tool_input = event.get("tool_input")
        datagrip = _datagrip()
        if tool == DATAGRIP_TOOL:
            target = datagrip.database_target(tool_input)
        else:
            connection = tabularis_connection(tool_input.get("connection_id")) if isinstance(tool_input, dict) else None
            sql = tool_input.get("query") if isinstance(tool_input, dict) else None
            target = (connection[0], connection[1], connection[2] == "postgresql", sql) \
                if connection and isinstance(sql, str) else None
        if target is None or not target[2] or not db_read_policy.is_production(target[1]):
            return
        kind, read = datagrip.read_shape(target[3])
        if kind == "plan":
            db_read_policy.record_plan(host, session, "datagrip" if tool == DATAGRIP_TOOL else "tabularis", target[0],
                                       read, event.get("tool_response"))
    except Exception as error:
        _report_error(error)
