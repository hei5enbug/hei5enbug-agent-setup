"""Skill grants of the approval guard: the declaration a plugin ships, the `grant` and `link` commands, the transcript
evidence that a skill started, and the lookup of the declared entry a write or MCP call matches.

A plugin ships `approval-grants.json` at its root; only a plugin cache counts, because installed plugin code is what the
guard protects from the agent. The `grant` command is decided by the PreToolUse hook, which knows the session, the
event's agent and the transcript; the command itself only prints the report the hook stored. Grants live in the
session's own state file, and `approval_state.held_grants` adds a linked parent session's grants.
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Mapping, NamedTuple, Optional

import approval_state
from approval_state_declared import grant_values, keep_verdict, match_command, match_mcp, merge_grants
from approval_state_entries import Entry
from guard_paths import _resolved
from guard_proof import _plugin_cache_dirs
from guard_self import GUARD_ENTRY, RequestParser
from guard_shell import PYTHON, ParseError, strip_prefix, tokenize

DECLARATION = "approval-grants.json"
NAME = re.compile(r"[A-Za-z0-9._-]+")
TOOL_NAME = re.compile(r"mcp__[A-Za-z0-9_-]+?__[A-Za-z0-9_.-]+")
COMMAND_NAME = re.compile(r"<command-name>/?([A-Za-z0-9._:-]+)</command-name>")
TYPED_COMMAND = re.compile(
    r"\s*(?:<command-message>[^<]*</command-message>\s*)?<command-name>/?[A-Za-z0-9._:-]+</command-name>"
    r"(?:\s*<command-args>[^<]*</command-args>)?\s*")
SHELL_EXPANSION = re.compile(r"[`$]|<\(|>\(")
ENTRY_KEYS = frozenset({"command", "tool", "arguments", "never", "destructive", "extra_options"})
VERBS = ("grant", "link")
PARENT_SESSION_ENV = "HEI5ENBUG_PARENT_SESSION"
SKILL_SPEC = re.compile(r"[A-Za-z0-9._-]+(?::[A-Za-z0-9._-]+)?")
REPORT_LIMIT = 60


class Invocation(NamedTuple):
    verb: str
    skill: str = ""
    values: Mapping = {}
    error: str = ""


class Verdict(NamedTuple):
    allow: bool
    reason: str


def split_skill(spec: str) -> tuple:
    """(plugin or None, skill) of `skill` or `plugin:skill`."""
    plugin, separator, skill = spec.rpartition(":")
    return (plugin or None, skill) if separator else (None, spec)


def entry_from_json(label: str, raw) -> Entry:
    """The entry a declaration object describes; ValueError names what is wrong."""
    if not isinstance(raw, dict) or set(raw) - ENTRY_KEYS:
        raise ValueError(
            "an entry that is not an object with only command, tool, arguments, never, destructive, extra_options")
    command, tool = raw.get("command"), raw.get("tool")
    if (command is None) == (tool is None):
        raise ValueError("an entry needs exactly one of command and tool")
    if command is not None and (not isinstance(command, str) or not command.strip() or "arguments" in raw):
        raise ValueError("a command entry needs a command text and takes no arguments")
    if tool is not None and not (isinstance(tool, str) and TOOL_NAME.fullmatch(tool)):
        raise ValueError("a tool entry names the full mcp__<server>__<tool>")
    arguments, never, destructive = raw.get("arguments", {}), raw.get("never", {}), raw.get("destructive", False)
    if not isinstance(arguments, dict) or not isinstance(destructive, bool) or not isinstance(never, dict):
        raise ValueError("arguments and never are objects and destructive is true or false")
    extra_options = raw.get("extra_options", True)
    if not isinstance(extra_options, bool) or (tool is not None and "extra_options" in raw):
        raise ValueError("extra_options is true or false and belongs to a command entry")
    if any(not isinstance(name, str) or not isinstance(values, list) or not all(isinstance(v, str) for v in values)
           for name, values in never.items()):
        raise ValueError("never maps a placeholder name to a list of values")
    return Entry(label, command=command, tool=tool, arguments=arguments,
                 never={name: tuple(values) for name, values in never.items()}, destructive=destructive,
                 extra_options=extra_options)


def entry_to_json(entry: Entry) -> dict:
    raw: dict = {"command": entry.command} if entry.command is not None else {
        "tool": entry.tool, "arguments": dict(entry.arguments)}
    if entry.never:
        raw["never"] = {name: list(values) for name, values in entry.never.items()}
    if not entry.extra_options:
        raw["extra_options"] = False
    return {**raw, "destructive": True} if entry.destructive else raw


def read_declaration(path: Path) -> dict:
    """The raw entries of each declared skill; the whole file is refused when its layout is wrong."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{DECLARATION} cannot be read: {type(error).__name__}") from None
    skills = data.get("skills") if isinstance(data, dict) and set(data) == {"skills"} else None
    if not isinstance(skills, dict) or any(
            not NAME.fullmatch(name) or not isinstance(body, dict) or set(body) != {"entries"}
            or not isinstance(body["entries"], list) for name, body in skills.items()):
        raise ValueError(f'{DECLARATION} must be {{"skills": {{"<skill>": {{"entries": [...]}}}}}}')
    return {name: body["entries"] for name, body in skills.items()}


def _installed_paths(cache: Path) -> dict:
    """{(marketplace, plugin): install path} from the `installed_plugins.json` beside a cache, which names the version the
    host loads; a missing or unreadable file lists nothing."""
    try:
        listed = json.loads((cache.parent / "installed_plugins.json").read_text(encoding="utf-8")).get("plugins")
    except (OSError, ValueError, AttributeError):
        return {}
    paths: dict = {}
    for key, records in listed.items() if isinstance(listed, dict) else ():
        name, _, marketplace = key.partition("@") if isinstance(key, str) else ("", "", "")
        for record in records if isinstance(records, list) else ():
            if isinstance(record, dict) and isinstance(record.get("installPath"), str) and name and marketplace:
                paths[(marketplace, name)] = Path(record["installPath"])
    return paths


def _claude_cache() -> Path:
    """The plugin cache of the Claude Code installation this session runs on, whose `installed_plugins.json` names the
    versions it loads."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(os.path.abspath(Path(base) / "plugins" / "cache"))


def declaration_files(plugin: Optional[str]) -> list:
    """(plugin name, declaration path) of each plugin that ships a declaration, limited to one plugin when it is named. The
    version is the install path that the running Claude Code installation's `installed_plugins.json` lists, so a
    rolled-back plugin uses its older declaration and a plugin that file does not list has none. A file that resolves
    outside the plugin caches is skipped."""
    caches = _plugin_cache_dirs()
    found: dict = {}
    for key, install in _installed_paths(_claude_cache()).items():
        if plugin in (None, key[1]):
            found[key] = install / DECLARATION
    inside = [root.resolve() for root in caches]
    return [(key[1], path) for key, path in sorted(found.items())
            if path.is_file() and any(root in path.resolve().parents for root in inside)]


def declared_entries(plugin: Optional[str], skill: str) -> tuple:
    """(plugin name, raw entries) of the one installed plugin whose declaration names the skill; ValueError otherwise."""
    matches = []
    for name, path in declaration_files(plugin):
        try:
            entries = read_declaration(path).get(skill)
        except ValueError:
            if plugin:
                raise
            continue
        if entries is not None:
            matches.append((name, entries))
    if not matches:
        raise ValueError(f"no installed plugin has a {DECLARATION} that declares the skill {skill}")
    if len({name for name, _ in matches}) > 1:
        raise ValueError(f"more than one installed plugin declares the skill {skill}; name it as plugin:skill")
    return matches[0]


def started_skills(transcript) -> set:
    """The skills the main thread of a Claude Code transcript started: a command the user typed or a Skill tool call."""
    started = set()
    try:
        with open(transcript, encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if '"Skill"' not in line and "<command-name>" not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                started.update(_started_in(record))
    except (OSError, TypeError, ValueError):
        return set()
    return started


def _started_in(record) -> list:
    if not isinstance(record, dict) or record.get("isSidechain") is True:
        return []
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if record.get("type") == "user" and isinstance(content, str) and not record.get("isMeta"):
        return COMMAND_NAME.findall(content) if TYPED_COMMAND.fullmatch(content) else []
    if record.get("type") == "assistant" and isinstance(content, list):
        return [item["input"]["skill"] for item in content
                if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") == "Skill"
                and isinstance(item.get("input"), dict) and isinstance(item["input"].get("skill"), str)]
    return []


def start_evidence(transcript, plugin: Optional[str], skill: str) -> Optional[str]:
    """The plugin the transcript's start of the skill names ("" when it names none), or None without a start."""
    for spec in sorted(started_skills(transcript)):
        started_plugin, started_skill = split_skill(spec)
        if started_skill == skill and (plugin is None or started_plugin in (None, plugin)):
            return plugin or started_plugin or ""
    return None


def _parse(verb: str, args: list) -> Invocation:
    parser = RequestParser(add_help=False, allow_abbrev=False)
    if verb == "grant":
        parser.add_argument("--skill", required=True)
        parser.add_argument("--value", action="append", default=[])
    parsed = parser.parse_args(args)
    if verb == "link":
        return Invocation("link")
    if not SKILL_SPEC.fullmatch(parsed.skill):
        raise ValueError("--skill names one skill, as <skill> or <plugin>:<skill>")
    values: dict = {}
    for item in parsed.value:
        name, separator, value = item.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("--value takes name=value")
        values[name] = [*values.get(name, []), value]
    return Invocation("grant", parsed.skill, values)


def invocation(command: str, cwd: str) -> Optional[Invocation]:
    """The `approval_guard.py grant` or `link` call a Bash command is, else None; invalid arguments give an Invocation
    with `error` set."""
    if SHELL_EXPANSION.search(command):
        return None
    try:
        segments = tokenize(command)
        if len(segments) != 1 or segments[0].redirects:
            return None
        words, assignments = strip_prefix(segments[0].words)
        if assignments or words != segments[0].words or len(words) < 3 or not PYTHON.fullmatch(os.path.basename(words[0])):
            return None
        if _resolved(words[1], cwd) != GUARD_ENTRY or words[2] not in VERBS:
            return None
    except ParseError:
        return None
    try:
        return _parse(words[2], words[3:])
    except ValueError as error:
        return Invocation(words[2], error=str(error))


def parent_link(environ) -> Optional[str]:
    """The HEI5ENBUG_PARENT_SESSION value for this session: the inherited one, else this session's own."""
    existing = environ.get(PARENT_SESSION_ENV)
    if existing:
        return existing
    claude_id = environ.get("CLAUDE_CODE_SESSION_ID")
    if environ.get("CLAUDECODE") and claude_id:
        return f"claude:{claude_id}"
    codex_id = environ.get("CODEX_SESSION_ID") or environ.get("CODEX_THREAD_ID")
    return f"codex:{codex_id}" if codex_id else None


def _describe(raw) -> str:
    text = raw.get("command") or raw.get("tool") if isinstance(raw, dict) else None
    return approval_state.redact(str(text))[:REPORT_LIMIT] if text else "an entry"


def _report(label: str, kept: list, ignored: list, accepted: Mapping, refused: tuple) -> str:
    lines = [f"Recorded the grant of {label} for this session: {len(kept)} entries kept, {len(ignored)} ignored."]
    lines += [f"Ignored entry {index}: {text} ({reason})" for index, text, reason in ignored]
    for name, values in sorted(accepted.items()):
        lines.append(f"Granted {name}: " + ", ".join(values))
    lines += [f"Refused {name}={value}: {reason}" for name, value, reason in refused]
    return "\n".join(lines)


def _keep(label: str, raws: list, cwd: str) -> tuple:
    kept, ignored = [], []
    for index, raw in enumerate(raws, 1):
        try:
            entry = entry_from_json(label, raw)
        except ValueError as error:
            ignored.append((index, _describe(raw), str(error)))
            continue
        verdict = keep_verdict(entry, cwd)
        if verdict.kept:
            kept.append(entry)
        else:
            ignored.append((index, _describe(raw), verdict.reason))
    return kept, ignored


def denial(host: str, session, event: Mapping) -> Optional[str]:
    """Why this event may not grant, or None. The grant works only on Claude Code, whose transcript shows the start."""
    if host != "claude":
        return "A skill grant works on Claude Code only, because it needs the main session's transcript."
    if approval_state.session_key(session) is None:
        return "The session is unknown, so a grant cannot be recorded."
    if approval_state.parent_session() or event.get("agent_id"):
        return "Only the main session can grant; a subagent, a worker, or a child session cannot."
    return None


def decide_grant(host: str, event: Mapping, request: Invocation) -> Verdict:
    session, cwd = event.get("session_id"), event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    reason = denial(host, session, event)
    if reason:
        return Verdict(False, f"The grant of {request.skill} was denied and nothing was granted. {reason}")
    plugin, skill = split_skill(request.skill)
    hint = start_evidence(event.get("transcript_path"), plugin, skill)
    if hint is None:
        return Verdict(False, f"The grant of {request.skill} was denied and nothing was granted: the main session's "
                              "transcript shows no start of that skill, by a typed command or a Skill tool call.")
    try:
        owner, raws = declared_entries(plugin or hint or None, skill)
    except ValueError as error:
        return Verdict(False, f"The grant of {request.skill} was denied and nothing was granted: {error}.")
    label = f"{owner}:{skill}"
    kept, ignored = _keep(label, raws, cwd)
    result = grant_values(kept, request.values)
    held = approval_state.session_grants(host, session).get(label, {}).get("values", {})
    merged = merge_grants(held, result.accepted)
    report = _report(label, kept, ignored, result.accepted, result.refused)
    approval_state.record_grant(host, session, label, {
        "plugin": owner, "skill": skill, "at": time.time(), "entries": [entry_to_json(e) for e in kept],
        "values": {name: list(values) for name, values in merged.items()}, "report": report})
    return Verdict(True, report)


def decide(name: str, host: str, event: Mapping, request: Invocation):
    """The PreToolUse output for a `grant` or `link` call; the other events of such a call need no decision."""
    if name != "PreToolUse":
        return None
    if request.error:
        return approval_state.pre_output("deny", request.error)
    if request.verb == "link":
        return approval_state.pre_output("allow", "Printing this session's link for a child process")
    verdict = decide_grant(host, event, request)
    return approval_state.pre_output("allow" if verdict.allow else "deny", verdict.reason)


def matching_skill(host: str, session, tool: str, tool_input, command: Optional[str], cwd: str) -> Optional[str]:
    """The `<plugin>:<skill>` whose kept entry the write (a Bash command) or MCP call matches, else None. A session with
    no grant costs no classification."""
    held = approval_state.held_grants(host, session)
    if not held:
        return None
    entries, grants = [], {}
    for label, record in held.items():
        grants[label] = {name: tuple(values) for name, values in record["values"].items()}
        for raw in record["entries"]:
            try:
                entries.append(entry_from_json(label, raw))
            except ValueError:
                continue
    if command is not None:
        found = match_command(command, entries, grants, cwd)
    else:
        found = match_mcp(tool, tool_input, entries, grants, cwd)
    return found.skill if found else None


def run_cli(verb: str, args: list, environ=None) -> int:
    """`approval_guard.py grant` prints the report the hook stored for this session; `link` prints the child link."""
    environ = os.environ if environ is None else environ
    try:
        request = _parse(verb, args)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    link = parent_link(environ)
    if verb == "link":
        print(link) if link else print("No session id is available to link.", file=sys.stderr)
        return 0 if link else 1
    host, _, session = (link or "").partition(":")
    held = approval_state.session_grants(host, session) if session else {}
    plugin, skill = split_skill(request.skill)
    for label, record in held.items():
        if record["skill"] == skill and plugin in (None, record["plugin"]):
            print(record["report"])
            return 0
    print(f"No grant of {request.skill} was recorded: the guard did not run for this call, or it is off.",
          file=sys.stderr)
    return 1
