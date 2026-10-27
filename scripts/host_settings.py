"""Check, and on Codex fix, the host settings that cause extra approval prompts or stop the approval guard.

`check` reports problems and writes nothing. `apply` changes only the allowlist below and only on the Codex host:
`[features] plugin_hooks` through `codex features enable`, and, while CODEX_NATIVE_APPROVAL is on, the plugin-owned
`rules/hei5enbug.rules` and, while the approval_guard toggle is on, `default_tools_approval_mode = "prompt"` on every
`[mcp_servers.<name>]` table plus each existing per-tool `approval_mode` line.
Each changed file is first copied to `<file>.bak-hei5enbug-<YYYYMMDD>`. Other `rules/*.rules` are only reported, and
`rules/hei5enbug.rules` is never written when it is a symbolic link or lacks the plugin-owned header line.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections import namedtuple
from copy import deepcopy
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import plugin_toggles  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CODEX_NATIVE_APPROVAL = True
GUARD_SERVERS = ("datagrip", "tabularis")
RULES_NAME = "hei5enbug.rules"
MAX_LINE = 119
ASK_RULES_MESSAGE = "these Claude Code ask rules override the guard's allow"
PROMPT_MODE = "default_tools_approval_mode"
READ_ONLY_WORDS = {
    "kubectl": {"get", "describe", "logs"},
    "helm": {"list", "get", "status"},
    "az": {"list", "show"},
    "git": {"status", "log", "diff", "show"},
}
CODEX_COMMAND_TIMEOUT_SECONDS = 10

Problem = namedtuple("Problem", "id text")
Change = namedtuple("Change", "label text")
Result = namedtuple("Result", "changes notes")


def _line(text: str) -> str:
    return text if len(text) <= MAX_LINE else text[: MAX_LINE - 3] + "..."


def resolve_claude_dir(value=None) -> Path:
    return Path(value or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def resolve_codex_home(value=None) -> Path:
    return Path(value or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def resolve_project(value=None) -> Path:
    return Path(value or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())


def _claude_permissions(path: Path) -> dict:
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    permissions = settings.get("permissions") if isinstance(settings, dict) else None
    return permissions if isinstance(permissions, dict) else {}


def _claude_ask_rules(permissions: dict) -> list[str]:
    ask = permissions.get("ask")
    if not isinstance(ask, list):
        return []
    return [
        rule
        for rule in ask
        if isinstance(rule, str)
        and "\n" not in rule
        and "\r" not in rule
        and (rule == "Bash" or rule.startswith("Bash(") or rule.startswith("mcp__"))
    ]


def _short_name(name: str) -> str:
    return name if len(name) <= 19 else name[:16] + "..."


def _claude_problems(claude_dir: Path, project: Path) -> list[Problem]:
    permissions = [
        _claude_permissions(path)
        for path in (
            claude_dir / "settings.json",
            project / ".claude" / "settings.json",
            project / ".claude" / "settings.local.json",
        )
    ]
    problems = []
    mode = next((item["defaultMode"] for item in reversed(permissions) if "defaultMode" in item), None)
    if mode == "dontAsk":
        problems.append(Problem("claude-dontask", "Claude Code defaultMode dontAsk denies every approval the guard asks for."))
    rules = [rule for item in permissions for rule in _claude_ask_rules(item)][:3]
    if rules:
        problems.append(Problem("claude-ask-rules", ASK_RULES_MESSAGE + ": " + ", ".join(_short_name(r) for r in rules) + "."))
    return problems


def _read_config(path: Path) -> tuple[dict | None, str | None]:
    """Return the parsed Codex config and None, or None and "missing" or "invalid"."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeDecodeError):
        return None, "invalid"
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None, "invalid"
    return config, None


def _plugin_hooks_enabled(config: dict) -> bool:
    features = config.get("features")
    return isinstance(features, dict) and features.get("plugin_hooks") is True


def _servers(config: dict) -> dict[str, dict]:
    servers = config.get("mcp_servers")
    return {name: server for name, server in servers.items() if isinstance(server, dict)} if isinstance(servers, dict) else {}


def _guard_servers(config: dict) -> dict[str, dict]:
    return {name: server for name, server in _servers(config).items() if name in GUARD_SERVERS}


def _tool_settings(server: dict) -> dict[str, dict]:
    tools = server.get("tools")
    return {tool: setting for tool, setting in tools.items() if isinstance(setting, dict)} if isinstance(tools, dict) else {}


def _unprompted(config: dict) -> list[str]:
    """Names of the MCP servers whose default mode or an existing per-tool mode is not prompt."""
    return [
        name for name, server in _servers(config).items()
        if server.get(PROMPT_MODE) != "prompt"
        or any("approval_mode" in setting and setting["approval_mode"] != "prompt" for setting in _tool_settings(server).values())
    ]


OWNER_MARK = "# hei5enbug-agent-setup plugin-owned file"


def rules_text(plugin_root) -> str:
    wrapper = json.dumps((Path(plugin_root) / "scripts" / "approve_wrapper.sh").as_posix(), ensure_ascii=False)
    return (
        OWNER_MARK + ": hei5enbug rewrites it at session start when host_settings is apply.\n"
        "# Put your own rules in another file under rules/.\n"
        f'prefix_rule(pattern=[{wrapper}], decision="prompt", justification="hei5enbug: approve writes once for this session")\n'
    )


def _rule_blocks(text: str) -> list[str]:
    """Return each top-level `prefix_rule(...)` call, skipping comments and string contents."""
    blocks = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "#":
            newline = text.find("\n", index)
            index = length if newline < 0 else newline + 1
        elif char in "\"'":
            index = _skip_string(text, index)
        elif text.startswith("prefix_rule", index) and (index == 0 or not (text[index - 1].isalnum() or text[index - 1] == "_")):
            cursor = index + len("prefix_rule")
            while cursor < length and text[cursor] in " \t":
                cursor += 1
            if cursor < length and text[cursor] == "(":
                end = _balanced_end(text, cursor)
                if end is None:
                    break
                blocks.append(text[index:end])
                index = end
            else:
                index = cursor
        else:
            index += 1
    return blocks


def _skip_string(text: str, start: int) -> int:
    quote = text[start]
    triple = text.startswith(quote * 3, start)
    index = start + (3 if triple else 1)
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif triple and text.startswith(quote * 3, index):
            return index + 3
        elif not triple and text[index] == quote:
            return index + 1
        elif not triple and text[index] == "\n":
            return index
        else:
            index += 1
    return len(text)


def _balanced_end(text: str, start: int) -> int | None:
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "#":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
            continue
        if char in "\"'":
            index = _skip_string(text, index)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _rule_fields(block: str) -> tuple[list, str] | None:
    try:
        call = ast.parse(block.strip(), mode="eval").body
        if not isinstance(call, ast.Call):
            return None
        fields = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords if kw.arg in ("pattern", "decision")}
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    pattern, decision = fields.get("pattern"), fields.get("decision")
    if not isinstance(pattern, list) or not isinstance(decision, str):
        return None
    return pattern, decision


def _alternatives(element) -> list[str]:
    if isinstance(element, str):
        return [element]
    if isinstance(element, list):
        return [item for item in element if isinstance(item, str)]
    return []


def _read_only_prefix(pattern: list) -> bool:
    if not pattern:
        return False
    executables = {Path(item).name for item in _alternatives(pattern[0])}
    for name, words in READ_ONLY_WORDS.items():
        if name not in executables:
            continue
        if name == "az":
            return any(word in words for element in pattern[1:] for word in _alternatives(element))
        return len(pattern) > 1 and any(word in words for word in _alternatives(pattern[1]))
    return False


def _pattern_words(pattern: list) -> str:
    words = []
    for position, element in enumerate(pattern[:3]):
        alternatives = [Path(item).name if position == 0 else item for item in _alternatives(element)]
        words.append("|".join(dict.fromkeys(alternatives[:3])))
    text = " ".join(words)
    return text if len(text) <= 40 else text[:37] + "..."


def _user_rule_problems(rules_dir: Path) -> list[Problem]:
    problems = []
    try:
        files = sorted(path for path in rules_dir.glob("*.rules") if path.name != RULES_NAME and path.is_file())
    except OSError:
        return problems
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for block in _rule_blocks(text):
            fields = _rule_fields(block)
            if fields is None:
                continue
            pattern, decision = fields
            if decision in ("prompt", "forbidden") and _read_only_prefix(pattern):
                problems.append(Problem(
                    "codex-user-rule",
                    _line(f'Codex rules/{path.name} {decision} "{_pattern_words(pattern)}" blocks or asks for reads the guard allows.'),
                ))
    return problems


def _confirmed_hook_problem() -> Problem | None:
    try:
        import approval_state

        digest = approval_state.hooks_hash("codex")
        if digest is None:
            return None
        heartbeats = approval_state.state_dir().parent / "heartbeats"
    except ImportError:
        return None
    try:
        confirmed = (heartbeats / "confirmed-codex").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        confirmed = None
    if digest == confirmed:
        return None
    return Problem("codex-hooks-trust", "The approval guard is unconfirmed on Codex; trust the plugin hooks in /hooks.")


def _codex_problems(host: str, codex_home: Path) -> list[Problem]:
    problems = []
    config, state = _read_config(codex_home / "config.toml")
    if state is None and not _plugin_hooks_enabled(config):
        problems.append(Problem("codex-plugin-hooks", "Codex runs no approval guard until [features] plugin_hooks = true."))
    if host != "codex":
        return problems
    if state == "invalid":
        problems.append(Problem("codex-config-invalid", "Codex config.toml is not valid TOML; hei5enbug did not check it."))
    hook = _confirmed_hook_problem()
    if hook is not None:
        problems.append(hook)
    rules_dir = codex_home / "rules"
    if CODEX_NATIVE_APPROVAL:
        try:
            current = (rules_dir / RULES_NAME).read_text(encoding="utf-8")
        except FileNotFoundError:
            problems.append(Problem("codex-rules-file", f"Codex rules/{RULES_NAME} is missing; run host_settings.py apply."))
        except (OSError, UnicodeDecodeError):
            problems.append(Problem("codex-rules-file", f"Codex rules/{RULES_NAME} is unreadable."))
        else:
            if current == rules_text(ROOT):
                pass
            elif (rules_dir / RULES_NAME).is_symlink() or not current.startswith(OWNER_MARK):
                problems.append(Problem(
                    "codex-rules-file", f"Codex rules/{RULES_NAME} is not plugin-owned; apply will not overwrite it."))
            else:
                problems.append(Problem("codex-rules-file", f"Codex rules/{RULES_NAME} is outdated; run host_settings.py apply."))
    if config is not None and CODEX_NATIVE_APPROVAL and _servers(config):
        if not plugin_toggles.enabled("approval_guard"):
            problems.append(Problem(
                "codex-mcp-skipped", "Codex MCP prompt mode is skipped because the approval_guard toggle is off."))
        else:
            names = _unprompted(config)
            if names:
                more = f" (+{len(names) - 3} more)" if len(names) > 3 else ""
                problems.append(Problem(
                    "codex-mcp-mode",
                    _line(f'Codex MCP servers without "prompt" approval: {", ".join(names[:3])}{more}; run host_settings.py apply.'),
                ))
    elif config is not None:
        for name, server in _guard_servers(config).items():
            prompted = sorted(tool for tool, setting in _tool_settings(server).items() if setting.get("approval_mode") == "prompt")
            if prompted:
                problems.append(Problem(
                    "codex-mcp-tool-prompt",
                    _line(f'Codex MCP {name} tools with approval_mode "prompt" ask even for reads: {", ".join(prompted[:3])}.'),
                ))
    problems.extend(_user_rule_problems(rules_dir))
    return problems


def check(host: str, claude_dir=None, codex_home=None, project=None) -> list[Problem]:
    """Return the problems found for `host`; write nothing."""
    if host == "claude":
        problems = _claude_problems(resolve_claude_dir(claude_dir), resolve_project(project))
    else:
        problems = []
    return problems + _codex_problems(host, resolve_codex_home(codex_home))


def _today() -> str:
    return date.today().strftime("%Y%m%d")


def _backup(path: Path) -> Path | None:
    """Copy `path` beside itself; return the new backup, or None when none was needed or one exists for today."""
    real = Path(os.path.realpath(path))
    if not real.is_file():
        return None
    backup = real.with_name(f"{real.name}.bak-hei5enbug-{_today()}")
    if backup.exists():
        return None
    shutil.copy2(real, backup)
    return backup


def _write(path: Path, data: bytes) -> None:
    target = Path(os.path.realpath(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".hei5enbug-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        try:
            os.chmod(temporary, target.stat().st_mode & 0o7777)
        except OSError:
            os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _run_codex(codex_bin: str, codex_home: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            [codex_bin, *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=CODEX_COMMAND_TIMEOUT_SECONDS,
            check=False,
            env={**os.environ, "CODEX_HOME": str(codex_home)},
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return result.stdout if result.returncode == 0 else None


def _enable_plugin_hooks(config_path: Path, codex_home: Path, codex_bin: str, result: Result) -> None:
    listing = _run_codex(codex_bin, codex_home, "features", "list")
    if listing is None or not any(line.split()[:1] == ["plugin_hooks"] for line in listing.splitlines()):
        result.notes.append("codex features list does not show plugin_hooks; set [features] plugin_hooks = true by hand.")
        return
    before = config_path.read_bytes()
    created = _backup(config_path)
    _run_codex(codex_bin, codex_home, "features", "enable", "plugin_hooks")
    config, _ = _read_config(config_path)
    if config is not None and _plugin_hooks_enabled(config):
        result.changes.append(Change("plugin_hooks", f"enabled [features] plugin_hooks in {config_path.name} (backup saved)"))
        return
    if created is not None and config_path.read_bytes() == before:
        created.unlink(missing_ok=True)
    result.notes.append("codex features enable plugin_hooks did not take effect; set it by hand.")


TABLE_HEADER = re.compile(r"^[ \t]*\[(?!\[)(.*?)\][ \t]*(?:#.*)?\r?\n?$")
ANY_TABLE = re.compile(r"^[ \t]*\[")


def _table_path(line: str) -> tuple | None:
    """The dotted key path of a plain `[a.b.c]` table header line, or None for any other line."""
    match = TABLE_HEADER.match(line)
    if match is None:
        return None
    try:
        node = tomllib.loads(f"[{match.group(1)}]\n")
    except tomllib.TOMLDecodeError:
        return None
    path = []
    while isinstance(node, dict) and len(node) == 1:
        key, node = next(iter(node.items()))
        path.append(key)
    return tuple(path)


def _set_key(lines: list[str], start: int, end: int, key: str, insert: bool) -> bool:
    """Set `key = "prompt"` in the table whose header is lines[start]; replace its line, else insert one when allowed."""
    ending = "\r\n" if lines[start].endswith("\r\n") else "\n"
    pattern = re.compile(rf"^([ \t]*){key}[ \t]*=")
    for index in range(start + 1, end):
        match = pattern.match(lines[index])
        if match:
            tail = "\r\n" if lines[index].endswith("\r\n") else ("\n" if lines[index].endswith("\n") else "")
            lines[index] = f'{match.group(1)}{key} = "prompt"{tail}'
            return True
    if not insert:
        return False
    if not lines[start].endswith("\n"):
        lines[start] += ending
    lines.insert(start + 1, f'{key} = "prompt"{ending}')
    return True


def _edit_prompt_modes(text: str, config: dict) -> tuple[str, dict, list[Change], list[str]]:
    """Set prompt on each MCP server's default mode and on each existing per-tool approval_mode line.

    Returns the new text, the config it must parse to, one Change per edited table, and notes for what needs a hand edit.
    """
    lines = text.splitlines(keepends=True)
    servers = _servers(config)
    expected = deepcopy(config)
    edited: set[tuple] = set()
    headers = [(index, _table_path(line)) for index, line in enumerate(lines)]
    boundaries = [index for index, line in enumerate(lines) if ANY_TABLE.match(line)]
    for index, path in reversed(headers):
        if not path or path[0] != "mcp_servers" or len(path) < 2 or path[1] not in servers:
            continue
        server = servers[path[1]]
        end = next((bound for bound in boundaries if bound > index), len(lines))
        if len(path) == 2 and server.get(PROMPT_MODE) != "prompt":
            if _set_key(lines, index, end, PROMPT_MODE, True):
                edited.add(path)
                expected["mcp_servers"][path[1]][PROMPT_MODE] = "prompt"
        elif len(path) == 4 and path[2] == "tools":
            setting = _tool_settings(server).get(path[3], {})
            if "approval_mode" in setting and setting["approval_mode"] != "prompt":
                if _set_key(lines, index, end, "approval_mode", False):
                    edited.add(path)
                    expected["mcp_servers"][path[1]]["tools"][path[3]]["approval_mode"] = "prompt"
    changes, notes = [], []
    for name, server in servers.items():
        if server.get(PROMPT_MODE) != "prompt":
            if ("mcp_servers", name) in edited:
                changes.append(Change(f"mcp {name}", f'set {PROMPT_MODE} = "prompt" on [mcp_servers.{name}] (backup saved)'))
            else:
                notes.append(f"[mcp_servers.{name}] is not a plain table header; set {PROMPT_MODE} by hand.")
        for tool, setting in _tool_settings(server).items():
            if "approval_mode" not in setting or setting["approval_mode"] == "prompt":
                continue
            if ("mcp_servers", name, "tools", tool) in edited:
                changes.append(Change(
                    f"mcp {name}.{tool}", f'set approval_mode = "prompt" on [mcp_servers.{name}.tools.{tool}] (backup saved)'))
            else:
                notes.append(f"[mcp_servers.{name}.tools.{tool}] approval_mode is not a plain line; set it by hand.")
    return "".join(lines), expected, changes, notes


def _apply_mcp_prompt(config_path: Path, result: Result) -> None:
    if not plugin_toggles.enabled("approval_guard"):
        return
    config, _ = _read_config(config_path)
    if config is None or not _unprompted(config):
        return
    original = config_path.read_bytes().decode("utf-8")
    text, expected, changes, notes = _edit_prompt_modes(original, config)
    result.notes.extend(notes)
    if not changes:
        return
    try:
        valid = tomllib.loads(text) == expected
    except tomllib.TOMLDecodeError:
        valid = False
    if not valid:
        result.notes.append(f"The {PROMPT_MODE} edit would not parse as intended; wrote nothing to {config_path.name}.")
        return
    _backup(config_path)
    _write(config_path, text.encode("utf-8"))
    result.changes.extend(changes)


def _apply_rules_file(rules_path: Path, plugin_root, result: Result) -> None:
    wanted = rules_text(plugin_root)
    try:
        current = rules_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = None
    except UnicodeDecodeError:
        current = ""
    if current == wanted:
        return
    if rules_path.is_symlink():
        result.notes.append(f"rules/{RULES_NAME} is a symbolic link; wrote nothing there.")
        return
    if current is not None and not current.startswith(OWNER_MARK):
        result.notes.append(f"rules/{RULES_NAME} is not plugin-owned; wrote nothing there.")
        return
    if current is not None:
        _backup(rules_path)
    _write(rules_path, wanted.encode("utf-8"))
    verb = "created" if current is None else "updated"
    result.changes.append(Change(f"rules/{RULES_NAME}", f"{verb} rules/{RULES_NAME}" + ("" if current is None else " (backup saved)")))


def apply(host: str, claude_dir=None, codex_home=None, codex_bin: str = "codex", plugin_root=ROOT) -> Result:
    """Fix the allowlisted Codex settings; on any other host change nothing."""
    result = Result([], [])
    if host != "codex":
        result.notes.append("Claude Code host: host_settings.py changes no settings; it only reports them.")
        return result
    home = resolve_codex_home(codex_home)
    config_path = home / "config.toml"
    config, state = _read_config(config_path)
    if state == "invalid":
        result.notes.append(f"{config_path.name} is not valid TOML; wrote nothing there.")
    elif config is not None and not _plugin_hooks_enabled(config):
        _enable_plugin_hooks(config_path, home, codex_bin, result)
    if CODEX_NATIVE_APPROVAL:
        _apply_rules_file(home / "rules" / RULES_NAME, plugin_root, result)
        if state != "invalid":
            _apply_mcp_prompt(config_path, result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="host_settings.py", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--host", choices=("claude", "codex"))
    parser.add_argument("--claude-dir")
    parser.add_argument("--codex-home")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except SystemExit as error:
        return 2 if error.code not in (0, None) else 0
    import plugin_toggles

    host = arguments.host or plugin_toggles.detect_host()
    try:
        if arguments.command == "check":
            problems = check(host, arguments.claude_dir, arguments.codex_home)
            if arguments.json:
                print(json.dumps({"host": host, "problems": [{"id": p.id, "message": p.text} for p in problems]}))
            else:
                for problem in problems:
                    print(problem.text)
        else:
            result = apply(host, arguments.claude_dir, arguments.codex_home, arguments.codex_bin)
            if arguments.json:
                print(json.dumps({
                    "host": host,
                    "changes": [{"label": c.label, "message": c.text} for c in result.changes],
                    "notes": result.notes,
                }))
            else:
                for change in result.changes:
                    print(change.text)
                for note in result.notes:
                    print(note)
    except OSError as error:
        print(f"host_settings.py failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
