"""MCP, file tool, and Tabularis classification for the approval guard."""
import ast
import json
import os
import re
import sys
from pathlib import Path
import approval_state
import db_read_policy
from approval_state import Outcome
from plugin_toggles import detect_host
from guard_shell import _datagrip, _digest, _merge, _read, tool_words
from guard_paths import _protected_path, _resolved, _sensitive, _state_path
from guard_proof import SELF_APPROVAL_REASON
import guard_dispatch
from guard_dispatch import _python_policy


TABULARIS_TOOL = "mcp__tabularis__run_query"
MCP_READ_VERBS = frozenset({
    "get", "list", "search", "read", "fetch", "query", "find", "lookup", "describe", "show", "view", "check",
    "count", "browse", "download", "export", "preview", "introspect", "analyze", "explain", "info", "whoami",
})
MCP_WRITE_WORDS = frozenset({
    "send", "post", "reply", "create", "update", "edit", "add", "write", "upsert", "transition", "schedule",
    "share", "copy", "move", "upload", "comment", "label", "unlabel", "mark", "unmark", "forward", "apply", "set",
    "rename", "link", "react", "reaction", "publish", "merge", "close", "reopen", "assign", "invite", "patch",
})
MCP_DESTRUCTIVE_WORDS = frozenset({"delete", "trash", "remove", "destroy", "purge", "drop", "unshare", "revoke"})
FAILURE_REASON = "The approval guard failed to check this call"
EXEC_WORDS = frozenset({"repl", "exec", "execute", "eval", "run", "code", "script", "command"})


def mcp_tool_part(tool):
    first = tool.find("__")
    if first < 0:
        return None
    second = tool.find("__", first + 2)
    if second < 0:
        return None
    return tool[second + 2:]


SQL_FIELDS = ("sql", "statement", "queryText")
SQL_LEAD = re.compile(
    r"^\s*(?:--[^\n]*\n\s*|/\*.*?\*/\s*)*\(?\s*(?:select|with|insert|update|delete|merge|upsert|replace|create|alter|"
    r"drop|truncate|explain|show|values|table|call|exec|execute|do|grant|revoke|set|begin|commit|rollback|copy|"
    r"vacuum|analyze|declare|lock)\b",
    re.IGNORECASE | re.DOTALL,
)


def _is_sql_field(key, text):
    """Explicit SQL fields always carry SQL; a generic `query` field does only when its text starts like SQL."""
    return key in SQL_FIELDS or (key == "query" and SQL_LEAD.match(text) is not None)


def _input_strings(value, sql_only=False):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and (not sql_only or _is_sql_field(key, item)):
                yield item
            elif isinstance(item, (dict, list)):
                yield from _input_strings(item, sql_only)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and not sql_only:
                yield item
            else:
                yield from _input_strings(item, sql_only)


def tabularis_connection(identifier):
    override = os.environ.get("HEI5ENBUG_TABULARIS_DIR")
    if override:
        directory = Path(override).expanduser()
    elif sys.platform == "darwin":
        directory = Path.home() / "Library" / "Application Support" / "tabularis"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        directory = Path(appdata) / "tabularis"
    else:
        directory = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "tabularis"
    try:
        entries = json.loads((directory / "connections.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(entries, dict):
        entries = entries.get("connections")
    if not isinstance(identifier, str) or not isinstance(entries, list):
        return None
    connections = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        connection_id, name, params = entry.get("id"), entry.get("name"), entry.get("params")
        driver = params.get("driver") if isinstance(params, dict) else None
        if isinstance(connection_id, str) and connection_id and isinstance(name, str):
            connections.append((connection_id, name, driver if isinstance(driver, str) else None))
    matches = [connection for connection in connections if connection[0] == identifier]
    if not matches:
        matches = [connection for connection in connections if connection[1] == identifier]
    return matches[0] if len(matches) == 1 else None


def classify_tabularis(tool_input, host=None, session=None):
    arguments = tool_input if isinstance(tool_input, dict) else {}
    identifier, sql = arguments.get("connection_id"), arguments.get("query")
    connection = tabularis_connection(identifier)
    connection_id = connection[0] if connection else identifier if isinstance(identifier, str) else "unknown"
    name = connection[1] if connection else "an unidentified connection"
    text = sql if isinstance(sql, str) else ""
    always = Outcome("always", [f"sql:always:tabularis:{connection_id}:{_digest(text)}"],
                     [f"tabularis query on {name}"], every_time=True,
                     critical=db_read_policy.is_production(name if connection else None))
    write = Outcome("write", ["mcp:session"], [f"tabularis query on {name}"])
    datagrip = _datagrip()
    driver = connection[2] if connection else None
    postgres = {"postgresql": True, "sqlserver": False, "sqlserver-entra": False}.get(driver)
    if datagrip.asks_every_time(text, postgres, name if connection else None):
        return always
    if not connection or postgres is None or not isinstance(sql, str):
        return always._replace(critical=True) if approval_state.session_scope() else write
    if datagrip.is_read(sql, postgres):
        return db_read_policy.read_outcome(host or detect_host(), session, "tabularis", connection_id, name, postgres,
                                           sql, datagrip.read_shape(sql) if postgres else None)
    keywords, destructive = datagrip.query_facts(sql, postgres, name)
    if destructive:
        return always
    if not keywords and approval_state.session_scope():
        return always._replace(critical=True)
    return Outcome("write", ["mcp:session"], [f"tabularis write on {name}"])


UNSPLIT_READ_PREFIXES = ("get", "list", "search", "fetch", "read", "describe", "show", "find", "lookup", "count", "check")


def _unsplit_read(words):
    """A tool name written as one lowercase run, like getjiraissue, reads when a read verb leads and no write word follows."""
    if len(words) != 1:
        return False
    for prefix in UNSPLIT_READ_PREFIXES:
        if words[0].startswith(prefix) and len(words[0]) > len(prefix):
            rest = words[0][len(prefix):]
            return not any(word in rest for word in MCP_WRITE_WORDS | MCP_DESTRUCTIVE_WORDS)
    return False


def _code_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("language", "lang"):
                continue
            yield from _code_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _code_strings(item)
    elif isinstance(value, str):
        yield value


def _looks_python(code):
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    return any(not (isinstance(node, ast.Expr) and isinstance(node.value, (ast.Name, ast.Constant)))
               for node in tree.body)


def _classify_executable(tool, tool_input, cwd):
    """Classify the code an executable MCP tool runs with the shell and Python classifiers.

    A forbidden or secret result and an every-time result are kept, and a sensitive result adds its sensitive-read
    approval to the session write; any other code is a session write. Returns None when the input holds no code.
    """
    language = None
    if isinstance(tool_input, dict):
        language = next((tool_input[key].lower() for key in ("language", "lang")
                         if isinstance(tool_input.get(key), str)), None)
    verdicts = []
    for code in _code_strings(tool_input):
        python = _looks_python(code) if language is None else language in ("py", "py3") or "python" in language
        verdicts.append(_python_policy(code, cwd, 0, dict(os.environ)) if python else guard_dispatch.classify_text(code, cwd))
    if not verdicts:
        return None
    for kind in ("forbidden", "secret"):
        found = next((verdict for verdict in verdicts if verdict.kind == kind), None)
        if found is not None:
            return found
    every_time = [verdict for verdict in verdicts if verdict.every_time]
    if every_time:
        return _merge("always", [verdict._replace(keys=[key for key in verdict.keys if key not in approval_state.SESSION_KEYS])
                                 for verdict in every_time])
    if any(verdict.kind == "sensitive" for verdict in verdicts):
        return Outcome("sensitive", [approval_state.SENSITIVE_KEY], [f"MCP execution tool {tool}"], None,
                       ["mcp:session"])
    return Outcome("write", ["mcp:session"], [f"MCP execution tool {tool}"])


def classify_mcp(tool, tool_input=None, cwd=None, host=None, session=None):
    if tool == TABULARIS_TOOL:
        return classify_tabularis(tool_input, host, session)
    part = mcp_tool_part(tool)
    words = tool_words(part) if part else []
    sql = list(_input_strings(tool_input, sql_only=True))
    datagrip = _datagrip() if sql else None
    if any(datagrip.is_destructive(text) for text in sql):
        return Outcome("always", [f"mcp:{tool}:{_digest(json.dumps(sql))}"], [f"destructive SQL in MCP tool {tool}"],
                       every_time=True, critical=True)
    if any(word in MCP_DESTRUCTIVE_WORDS for word in words):
        return Outcome("always", [f"mcp:{tool}"], [f"destructive MCP tool {tool}"], every_time=True)
    action = tool_input.get("action") if isinstance(tool_input, dict) else None
    action_words = tool_words(action) if isinstance(action, str) else []
    if set(action_words) & MCP_DESTRUCTIVE_WORDS:
        return Outcome("always", [f"mcp:{tool}"], [f"destructive MCP action via {tool}"], every_time=True)
    if sql:
        if all(datagrip.is_read(text, True) or datagrip.is_read(text, False) for text in sql):
            return _read()
        return Outcome("write", ["mcp:session"], [f"MCP SQL write via {tool}"])
    if set(words) & EXEC_WORDS:
        verdict = _classify_executable(tool, tool_input, cwd or os.getcwd())
        if verdict is not None:
            return verdict
    if set(action_words) & (MCP_WRITE_WORDS | EXEC_WORDS):
        return Outcome("write", ["mcp:session"], [f"MCP write action via {tool}"])
    if set(action_words) & MCP_READ_VERBS:
        return _read()
    if set(words) & EXEC_WORDS:
        return Outcome("write", ["mcp:session"], [f"MCP execution tool {tool}"])
    if not words:
        return Outcome("write", [f"mcp:{tool}"], [f"MCP tool {tool}"])
    if _unsplit_read(words[-1:]) and not any(word in MCP_WRITE_WORDS for word in words[:-1]):
        return _read()
    if words[0] in MCP_READ_VERBS:
        return _read()
    if not any(word in MCP_WRITE_WORDS for word in words) and any(word in MCP_READ_VERBS for word in words):
        return _read()
    return Outcome("write", ["mcp:session"], [f"MCP write: {tool}"])


def _report_error(error):
    print(f"approval_guard: classifier error: {type(error).__name__}", file=sys.stderr)


def _classify_safely(classifier, identity):
    try:
        return classifier()
    except Exception as error:
        _report_error(error)
        return Outcome("always", ["guard:unclassified:" + _digest(identity)], [FAILURE_REASON], every_time=True,
                       critical=True)


def classify_file_tool(tool, tool_input, cwd):
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool == "apply_patch":
        patch = tool_input.get("command", tool_input.get("patch", tool_input.get("input", "")))
        paths = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", patch, re.M)
    else:
        paths = [tool_input[key] for key in ("file_path", "notebook_path") if isinstance(tool_input.get(key), str)]
    if tool != "Read" and any(_state_path(path, cwd) for path in paths):
        return Outcome("forbidden", [], [SELF_APPROVAL_REASON])
    if tool != "Read" and any(_resolved(path, cwd) == db_read_policy.limits_path().resolve() for path in paths):
        return Outcome("always", [f"db-limits:{_digest(' '.join(paths))}"], ["Change to the database read limits file"],
                       every_time=True)
    if tool == "Read" and any(_protected_path(path, cwd) for path in paths):
        return _sensitive(" ".join(paths))
    return Outcome("pass", [], [])
