from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))


LOCAL_LINK = re.compile(r"\[([^\]]+)\]\(([^\s)]+)\)")
MAX_CONTEXT_BYTES = 9000
MAX_ROLE_CONTEXT_BYTES = 4000
ASSIGNED_ROLE_ENV = "HEI5ENBUG_ASSIGNED_ROLE"
ASSIGNED_WORKERS_HEADING = "## Assigned workers"
CROSS_REPOSITORY_REFERENCE = "cross-repository.md"
INSTRUCTIONS_VARIABLE = "$I"
IMPLEMENTATION_AGENTS = {
    "claude": {
        "hei5enbug-agent-setup:worker",
        "hei5enbug-agent-setup:sonnet-worker",
        "hei5enbug-agent-setup:designer",
    },
    "codex": {"worker", "designer"},
}
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "model-registry.json"
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
REVIEW_MODELS = tuple(REGISTRY["runner"]["review_models"])
DEFAULT_REVIEW_MODEL = REGISTRY["runner"]["default_review_model"]
DIGEST_VERSION = 1
MARKER_SCHEMA = 1
MARKER_RETENTION_SECONDS = 30 * 24 * 60 * 60
TERMINAL_HANDLE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
SESSION_TOKEN = re.compile(r"[A-Za-z0-9._-]{1,200}")
SESSION_FILES = {
    "codex": "codex.md",
    "claude": "claude-code.md",
}
CLAUDE_ASK_NOTICE_PREFIX = "Notice: these Claude Code ask rules override the guard's allow"


def render_links(content: str, path: Path, root: Path) -> str:
    instructions = root / "instructions"

    def render_link(match: re.Match[str]) -> str:
        reference = match[2].removeprefix("<").removesuffix(">")
        if reference.startswith("#") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", reference):
            return match[0]
        target = (path.parent / reference).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError(f"Unavailable bundled reference: {path.relative_to(root)} -> {reference}")
        if target.is_relative_to(instructions):
            return f"[{match[1]}]({INSTRUCTIONS_VARIABLE}/{target.relative_to(instructions).as_posix()})"
        return f"[{match[1]}](<{target.as_posix()}>)"

    return LOCAL_LINK.sub(render_link, content)


def read_instruction(path: Path, root: Path) -> str:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"{path.relative_to(root)} is empty")
    return render_links(content, path, root)


def assigned_workers_section(root: Path) -> str:
    """Return the "## Assigned workers" section of the implementation delegation rules, heading included."""
    path = root / "instructions" / "implementation-delegation.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.rstrip() == ASSIGNED_WORKERS_HEADING)
    except StopIteration as error:
        raise ValueError(f"{path.relative_to(root)} has no {ASSIGNED_WORKERS_HEADING!r} section") from error
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    content = "\n".join(lines[start:end]).strip()
    if content == ASSIGNED_WORKERS_HEADING:
        raise ValueError(f"{path.relative_to(root)} has an empty {ASSIGNED_WORKERS_HEADING!r} section")
    return render_links(content, path, root)


def context_kind(event_name: str, host: str, event: dict, environ: dict | None = None) -> str:
    """Choose "main", "core", or "implementation" for the receiving session."""
    if event_name == "SessionStart":
        return "core" if (environ if environ is not None else os.environ).get(ASSIGNED_ROLE_ENV) else "main"
    agent_type = event.get("agent_type")
    if host == "codex" and not agent_type:
        return "main"
    return "implementation" if agent_type in IMPLEMENTATION_AGENTS[host] else "core"


MAX_PROBLEM_NOTICES = 3


def _host_settings_error(error: Exception) -> None:
    print(f"hei5enbug-agent-setup host settings were not checked: {error}", file=sys.stderr)


def session_start_notices(host: str, project: Path | None = None) -> list[str]:
    """Return notices from the host settings: what `apply` changed on Codex, then at most three remaining problems."""
    notices = []
    try:
        import host_settings
        import plugin_toggles

        if host == "codex" and plugin_toggles.host_settings_mode() == "apply":
            try:
                changes = host_settings.apply(host).changes
            except Exception as error:
                _host_settings_error(error)
            else:
                if changes:
                    labels = ", ".join(change.label for change in changes)
                    notices.append(
                        f"Notice: hei5enbug changed host settings: {labels}; backups saved next to each file."
                    )
        try:
            lines = [f"Notice: {problem.text}" for problem in host_settings.check(host, project=project)]
        except Exception as error:
            _host_settings_error(error)
            lines = []
        notices.extend(lines[:MAX_PROBLEM_NOTICES])
        if len(lines) > MAX_PROBLEM_NOTICES:
            notices.append(f"Notice: and {len(lines) - MAX_PROBLEM_NOTICES} more; run host_settings.py check")
    except Exception as error:
        _host_settings_error(error)
    return notices


def append_session_notices(context: str, notices: list[str], limit: int) -> str:
    """Append each notice that fits the context limit, shortening the ask-rule notice before dropping it."""
    for notice in notices:
        options = [notice]
        if notice.startswith(CLAUDE_ASK_NOTICE_PREFIX + ":"):
            options.append(CLAUDE_ASK_NOTICE_PREFIX + ".")
        for text in options:
            candidate = context + text + "\n"
            if len(candidate.encode("utf-8")) <= limit:
                context = candidate
                break
    return context


def render_claude_settings(worker: str | None = None) -> str:
    import plugin_toggles

    if worker is None:
        model, effort, notice = plugin_toggles.worker_setting("claude")
        suffix = f" ({notice})" if notice else ""
        worker = f"`{model}` at `{effort}`.{suffix}"
    option = plugin_toggles.option_value("implementation_worker")
    route = {
        "auto": "Auto (`auto`)",
        "codex": "Codex (`codex`)",
        "haiku": "Haiku (`haiku`)",
        "sol": "Sol (`sol`)",
        "sonnet": "Sonnet (`sonnet`)",
    }.get(option, "Auto (`auto`)")
    review = plugin_toggles.option_value("review_model")
    if review not in REVIEW_MODELS:
        review = DEFAULT_REVIEW_MODEL
    return (
        f"Implementation worker route: {route}.\n"
        f"Worker agent model: {worker}\n"
        f"Review model: `{review}`.\n"
    )


def render_context(root: Path, host: str, kind: str = "main") -> str:
    try:
        host_file = SESSION_FILES[host]
    except KeyError as error:
        raise ValueError(f"Unsupported host: {host}") from error
    if kind not in {"main", "core", "implementation"}:
        raise ValueError(f"Unsupported context kind: {kind}")
    session_dir = root / "instructions" / "session"
    if kind == "main":
        sources = [read_instruction(session_dir / name, root) for name in ("core.md", "common.md", host_file)]
        limit = MAX_CONTEXT_BYTES
        import plugin_toggles

        if not plugin_toggles.enabled("orca_worktree"):
            sources[1] = "\n".join(
                line for line in sources[1].split("\n") if CROSS_REPOSITORY_REFERENCE not in line
            )
    else:
        sources = [read_instruction(session_dir / "core.md", root)]
        if kind == "implementation":
            sources.append(assigned_workers_section(root))
        limit = MAX_ROLE_CONTEXT_BYTES
    context = (
        f"hei5enbug-agent-setup instructions for {host}.\n"
        f"Source directory: {root.as_posix()}\n"
        f"Instructions (`{INSTRUCTIONS_VARIABLE}`): {(root / 'instructions').as_posix()}. "
        f"Every `{INSTRUCTIONS_VARIABLE}/` link below names a file in that directory.\n\n"
        + "\n\n".join(sources)
        + "\n"
    )
    if kind == "main":
        model, effort, notice = plugin_toggles.worker_setting(host)
        suffix = f" ({notice})" if notice else ""
        worker = f"`{model}` at `{effort}`.{suffix}"
        if host == "codex":
            import language_guard

            context += f"\nCodex worker model: {worker}\nResponse language: {language_guard.codex_language()}.\n"
        else:
            context += "\n" + render_claude_settings(worker)
        if suffix and len(context.encode("utf-8")) > limit:
            context = context.replace(suffix, "", 1)
    if len(context.encode("utf-8")) > limit:
        raise ValueError("Bundled instructions exceed the context budget; move details to conditional references")
    return context


def instructions_digest(root: Path) -> str:
    """Hash every executable instruction file and the renderer, independent of where the plugin is installed."""
    files = sorted(
        path
        for path in (root / "instructions").rglob("*.md")
        if not path.name.endswith(".ko.md")
    )
    files.append(root / "scripts" / "session_context.py")
    digest = hashlib.sha256(f"v{DIGEST_VERSION}".encode())
    for path in files:
        digest.update(b"\0" + path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def marker_directory() -> Path | None:
    value = os.environ.get("ORCA_USER_DATA_PATH")
    if not value:
        return None
    base = Path(value).expanduser()
    return base / "hei5enbug-agent-setup" / "terminals" if base.is_absolute() else None


def interactive_session(host: str, transcript: object) -> bool:
    """A child `claude -p` or `codex exec` inherits the terminal's Orca variables but must not claim its marker."""
    if host == "claude":
        return os.environ.get("CLAUDE_CODE_ENTRYPOINT", "cli") == "cli"
    if not isinstance(transcript, str):
        return False
    try:
        with open(transcript, encoding="utf-8") as stream:
            meta = json.loads(stream.readline())
    except (OSError, ValueError):
        return False
    payload = meta.get("payload") if isinstance(meta, dict) else None
    return isinstance(payload, dict) and payload.get("source") == "cli"


def write_terminal_marker(root: Path, host: str, event: dict) -> None:
    """Record which instructions this Orca terminal's interactive session loaded, so a later refresh can target it."""
    directory = marker_directory()
    handle = os.environ.get("ORCA_TERMINAL_HANDLE")
    if directory is None or not isinstance(handle, str) or not TERMINAL_HANDLE.fullmatch(handle):
        return
    if not interactive_session(host, event.get("transcript_path")):
        return
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    source = event.get("source")
    transcript = event.get("transcript_path")
    payload = {
        "schema": MARKER_SCHEMA,
        "host": host,
        "root": root.as_posix(),
        "digest": instructions_digest(root),
        "source": source if isinstance(source, str) else None,
        "transcript_path": transcript if isinstance(transcript, str) and Path(transcript).is_absolute() else None,
        "written_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".marker-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, directory / f"{handle}.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    cutoff = time.time() - MARKER_RETENTION_SECONDS
    for stale in directory.glob("*.json"):
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass


CODEX_AGENTS = {
    "scout": "codex-scout.toml",
    "worker": "codex-worker.toml",
    "designer": "codex-designer.toml",
    "reviewer": "codex-reviewer.toml",
}
RETIRED_CODEX_AGENTS = {
    "scout": {
        "910da79ee988b53f4a94186a469c4479c7e34bf61bec8dfd27ef1ab73cc171da",
        "e81d0cfcd3a4986204c289fb8c457bd279ba8c2d24d43679d02b1661581301e7",
        "49e5f7dab3d3b9384b49250e8622fd57cf65b600d7eb1b3b5b1732554ef1b5c7",
        "57ca9a0c1b168c1491b71f2df46964042c42bed4cc0de8f200ea2060a12734e1",
    },
    "explorer": {"bfde4fbbe2740152ad537d576612a34619a57a45adb56072e3f945610ef820af"},
    "worker": {
        "ce4488d0323832dc1563481875e7c26d693092c94865c37a4b4b89afd8274f83",
        "249b194b8c9e0cea3ff687298e58cee99ca6c330f79e04162029a60e2ecfeff0",
        "89d72db180d2d0a16707804125af045ac5bb81baa2d751bad078747258b84d49",
    },
    "designer": {
        "c8c525a3a7fdfb5adbff1cf7474d24dfba35527eb070f4a5206c164b248d43ed",
        "be8b8dc3f856bd8fdab5e15f17b464deab2e50819d3a7d060cccbc2847b7610a",
    },
    "reviewer": {
        "5d2bd7dd2786e5824cfed218fb2a3ff0ae966d193a0495782cbe70defafc9cca",
        "b06153c12413af3da6a587bb13bbbb3ef3907d20c65d273dd928c5097d92539d",
    },
    "researcher": {"940a7daace75165d8eceeece93a3c4960c42d187754738a744244059d5a0e5c1"},
}


def retire_codex_agents(agents: Path) -> None:
    """Remove an agent file an earlier version wrote, only while it is byte-identical to that bundled file.

    A retired name that is still bundled is provisioned again from the current file.
    """
    for name, digests in RETIRED_CODEX_AGENTS.items():
        target = agents / f"{name}.toml"
        try:
            if hashlib.sha256(target.read_bytes()).hexdigest() in digests:
                target.unlink()
        except OSError:
            pass


def provision_codex_agents(root: Path) -> None:
    """Create each bundled Codex agent that Codex does not have yet.

    Never overwrite a file the user changed: once the user owns an agent file,
    their copy wins and this function leaves it alone.
    """
    home = os.environ.get("CODEX_HOME")
    agents = (Path(home) if home else Path.home() / ".codex") / "agents"
    retire_codex_agents(agents)
    for name, bundled in CODEX_AGENTS.items():
        source = root / "standalone-agents" / bundled
        target = agents / f"{name}.toml"
        if not source.is_file() or target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_text(encoding="utf-8")
        try:
            with target.open("x", encoding="utf-8") as stream:
                stream.write(content)
        except FileExistsError:
            pass


SUBAGENT_BLOCK = (
    "<!-- hei5enbug:subagents -->\n"
    "When hei5enbug-agent-setup is active, use subagents according to its situation-based delegation rules.\n"
    "<!-- /hei5enbug:subagents -->\n"
)
SUBAGENT_PATTERN = re.compile(
    r"<!-- hei5enbug:subagents -->.*?<!-- /hei5enbug:subagents -->\n?",
    re.DOTALL,
)
ASK_FLAG = "default_mode_request_user_input"
CODEX_COMMAND_TIMEOUT_SECONDS = 3
AUTO_SETTINGS_STATE = "codex-auto-settings.json"


def codex_home() -> Path:
    home = os.environ.get("CODEX_HOME")
    return Path(home) if home else Path.home() / ".codex"


def atomic_write_bytes(target: Path, data: bytes) -> None:
    target = Path(os.path.realpath(target))
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


def sync_subagent_block(wanted: bool) -> bool:
    """Make `$CODEX_HOME/AGENTS.md` contain the marked block exactly when `wanted`, leaving other text untouched."""
    target = codex_home() / "AGENTS.md"
    try:
        text = target.read_bytes().decode("utf-8")
    except FileNotFoundError:
        text = None
    present = text is not None and SUBAGENT_PATTERN.search(text) is not None
    if wanted:
        if present:
            return True
        text = text or ""
        if text and not text.endswith("\n"):
            text += "\n"
        if text:
            text += "\n"
        atomic_write_bytes(target, (text + SUBAGENT_BLOCK).encode("utf-8"))
        return True
    if not present:
        return True

    result = []
    position = 0
    for match in SUBAGENT_PATTERN.finditer(text):
        before = text[position:match.start()]
        if before.endswith("\n\n"):
            before = before[:-1]
        result.append(before)
        position = match.end()
    result.append(text[position:])
    atomic_write_bytes(target, "".join(result).encode("utf-8"))
    return True


def run_codex(*arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["codex", *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=CODEX_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return result.stdout if result.returncode == 0 else None


def ask_flag_state() -> bool | None:
    """Return the effective state of the question flag, or None when it cannot be determined."""
    listing = run_codex("features", "list")
    if listing is None:
        return None
    for line in listing.splitlines():
        parts = line.split()
        if parts and parts[0] == ASK_FLAG:
            value = parts[-1].casefold()
            return {"true": True, "false": False}.get(value)
    return None


def sync_ask_flag(wanted: bool, enabled_by_plugin: bool) -> tuple[bool, bool]:
    """Return (settled, enabled_by_plugin) after reconciling the question flag with the toggle."""
    if wanted:
        state = ask_flag_state()
        if state is None:
            return False, enabled_by_plugin
        if state:
            return True, enabled_by_plugin
        if run_codex("features", "enable", ASK_FLAG) is None:
            return False, enabled_by_plugin
        return True, True
    if not enabled_by_plugin:
        return True, False
    if run_codex("features", "disable", ASK_FLAG) is None:
        return False, True
    return True, False


def plugin_version(root: Path) -> str:
    try:
        manifest = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        version = manifest.get("version")
        return version if isinstance(version, str) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def auto_settings_state_path() -> Path | None:
    value = os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    return Path(value) / AUTO_SETTINGS_STATE if value else None


def load_auto_settings_state(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def settled_for(state: dict, key: str, version: str, value: bool) -> bool:
    entry = state.get(key)
    return (
        state.get("version") == version
        and isinstance(entry, dict)
        and entry.get("value") is value
        and entry.get("ok") is True
    )


def apply_codex_auto_settings(root: Path) -> None:
    """Reconcile the Codex-wide settings this plugin manages; every failure is retried at the next session."""
    import plugin_toggles

    version = plugin_version(root)
    state_path = auto_settings_state_path()
    previous = load_auto_settings_state(state_path)
    if previous.get("version") != version:
        previous = {"ask_tool_enabled_by_plugin": previous.get("ask_tool_enabled_by_plugin") is True}
    state = {
        "version": version,
        "ask_tool_enabled_by_plugin": previous.get("ask_tool_enabled_by_plugin") is True,
    }

    policy = plugin_toggles.enabled("subagent_policy")
    if settled_for(previous, "subagent_policy", version, policy):
        state["subagent_policy"] = previous["subagent_policy"]
    else:
        try:
            ok = sync_subagent_block(policy)
        except (OSError, ValueError):
            ok = False
        state["subagent_policy"] = {"value": policy, "ok": ok}

    ask = plugin_toggles.enabled("codex_ask_tool")
    if settled_for(previous, "codex_ask_tool", version, ask):
        state["codex_ask_tool"] = previous["codex_ask_tool"]
    else:
        ok, state["ask_tool_enabled_by_plugin"] = sync_ask_flag(ask, state["ask_tool_enabled_by_plugin"])
        state["codex_ask_tool"] = {"value": ask, "ok": ok}

    if state_path is None or state == previous:
        return
    try:
        atomic_write_bytes(state_path, json.dumps(state, sort_keys=True).encode("utf-8"))
    except OSError:
        pass


def record_codex_worker(session) -> None:
    """Fix this Codex session's worker pair to the one announced in its context."""
    import approval_state
    import plugin_toggles

    model, effort, _ = plugin_toggles.worker_setting("codex")
    approval_state.record_worker_pair("codex", session, model, effort)


def session_settings_path(event: dict) -> Path | None:
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    session = event.get("session_id")
    if not data or not isinstance(session, str) or not SESSION_TOKEN.fullmatch(session):
        return None
    return Path(data) / "session-settings" / f"{session}.txt"


def write_session_settings(path: Path, block: str) -> None:
    atomic_write_bytes(path, block.encode("utf-8"))
    cutoff = time.time() - MARKER_RETENTION_SECONDS
    for stale in path.parent.glob("*.txt"):
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass


def prompt_settings_notice(event: dict) -> None:
    try:
        import plugin_toggles

        if (
            plugin_toggles.detect_host() != "claude"
            or os.environ.get(ASSIGNED_ROLE_ENV)
            or os.environ.get("HEI5ENBUG_PARENT_SESSION")
            or event.get("agent_id")
        ):
            return
        path = session_settings_path(event)
        if path is None:
            return
        block = render_claude_settings()
        try:
            previous = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            previous = None
        if previous == block:
            path.touch()
            return
        write_session_settings(path, block)
        if previous is not None:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "hei5enbug-agent-setup settings changed during this session. "
                    "These lines replace the earlier ones:\n" + block
                ),
            }}))
    except Exception:
        pass


def main() -> int:
    try:
        event = json.load(sys.stdin)
        event_name = event["hook_event_name"]
        if event_name == "UserPromptSubmit":
            prompt_settings_notice(event)
            return 0
        if event_name not in {"SessionStart", "SubagentStart"}:
            raise ValueError("Unsupported hook event")
        root = Path(__file__).resolve().parents[1]
        codex_root = os.environ.get("PLUGIN_ROOT")
        host = "codex" if codex_root and Path(codex_root).resolve() == root else "claude"
        kind = context_kind(event_name, host, event)
        context = render_context(root, host, kind)
        if event_name == "SessionStart":
            limit = MAX_CONTEXT_BYTES if kind == "main" else MAX_ROLE_CONTEXT_BYTES
            cwd = event.get("cwd")
            project = Path(cwd) if isinstance(cwd, str) and cwd else None
            context = append_session_notices(context, session_start_notices(host, project), limit)
        if host == "codex":
            try:
                provision_codex_agents(root)
            except OSError:
                pass
        if event_name == "SessionStart":
            if host == "claude" and kind == "main":
                try:
                    path = session_settings_path(event)
                    if path is not None:
                        write_session_settings(path, render_claude_settings())
                except Exception:
                    pass
            try:
                write_terminal_marker(root, host, event)
            except (OSError, ValueError):
                pass
            if host == "codex":
                try:
                    apply_codex_auto_settings(root)
                except Exception:
                    pass
                if kind == "main":
                    try:
                        record_codex_worker(event.get("session_id"))
                    except Exception:
                        pass
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"hei5enbug-agent-setup instructions were not loaded: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
