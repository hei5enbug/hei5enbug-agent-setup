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
IMPLEMENTATION_AGENTS = {
    "claude": {
        "hei5enbug-agent-setup:worker",
        "hei5enbug-agent-setup:sonnet-worker",
        "hei5enbug-agent-setup:designer",
    },
    "codex": {"worker", "designer"},
}
REVIEW_MODELS = (
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "gpt-6-astra",
    "gpt-6-luna",
    "gpt-6.1-sol",
)
DEFAULT_REVIEW_MODEL = "gpt-6-astra"
DIGEST_VERSION = 1
MARKER_SCHEMA = 1
MARKER_RETENTION_SECONDS = 30 * 24 * 60 * 60
TERMINAL_HANDLE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
SESSION_FILES = {
    "codex": "codex.md",
    "claude": "claude-code.md",
}


def absolute_links(content: str, path: Path, root: Path) -> str:
    def absolute_link(match: re.Match[str]) -> str:
        reference = match[2].removeprefix("<").removesuffix(">")
        if reference.startswith("#") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", reference):
            return match[0]
        target = (path.parent / reference).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError(f"Unavailable bundled reference: {path.relative_to(root)} -> {reference}")
        return f"[{match[1]}](<{target.as_posix()}>)"

    return LOCAL_LINK.sub(absolute_link, content)


def read_instruction(path: Path, root: Path) -> str:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"{path.relative_to(root)} is empty")
    return absolute_links(content, path, root)


def assigned_workers_section(root: Path) -> str:
    """Return the "## Assigned workers" section of the implementation execution rules, heading included."""
    path = root / "instructions" / "implementation-execution.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.rstrip() == ASSIGNED_WORKERS_HEADING)
    except StopIteration as error:
        raise ValueError(f"{path.relative_to(root)} has no {ASSIGNED_WORKERS_HEADING!r} section") from error
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    content = "\n".join(lines[start:end]).strip()
    if content == ASSIGNED_WORKERS_HEADING:
        raise ValueError(f"{path.relative_to(root)} has an empty {ASSIGNED_WORKERS_HEADING!r} section")
    return absolute_links(content, path, root)


def context_kind(event_name: str, host: str, event: dict, environ: dict | None = None) -> str:
    """Choose "main", "core", or "implementation" for the receiving session."""
    if event_name == "SessionStart":
        return "core" if (environ if environ is not None else os.environ).get(ASSIGNED_ROLE_ENV) else "main"
    agent_type = event.get("agent_type")
    if host == "codex" and not agent_type:
        return "main"
    return "implementation" if agent_type in IMPLEMENTATION_AGENTS[host] else "core"


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
        rule = "Apply the common rules throughout this session."
        limit = MAX_CONTEXT_BYTES
    else:
        sources = [read_instruction(session_dir / "core.md", root)]
        if kind == "implementation":
            sources.append(assigned_workers_section(root))
        rule = "Apply these rules throughout this session."
        limit = MAX_ROLE_CONTEXT_BYTES
    context = (
        f"hei5enbug-agent-setup instructions for {host}.\n"
        f"Source directory: {root.as_posix()}\n"
        f"{rule}\n\n"
        + "\n\n".join(sources)
        + "\n"
    )
    if kind == "main":
        if host == "codex":
            import language_guard

            context += f"\nResponse language: {language_guard.codex_language()}.\n"
        else:
            import plugin_toggles

            option = plugin_toggles.option_value("implementation_worker")
            if option == "haiku":
                route = "Haiku worker, `hei5enbug-agent-setup:worker` (`implementation_worker`=`haiku`)"
            elif option == "sonnet":
                route = "Sonnet: `hei5enbug-agent-setup:sonnet-worker` (`implementation_worker`=`sonnet`)"
            else:
                route = "Codex (`implementation_worker`=`codex`)"
            review = plugin_toggles.option_value("review_model")
            if review not in REVIEW_MODELS:
                review = DEFAULT_REVIEW_MODEL
            context += (
                f"\nImplementation worker route: {route}.\n"
                f"Review model: `{review}` (`review_model`), `xhigh`.\n"
            )
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
    "researcher": "codex-researcher.toml",
    "designer": "codex-designer.toml",
    "reviewer": "codex-reviewer.toml",
}
RETIRED_CODEX_AGENTS = {
    "scout": {
        "910da79ee988b53f4a94186a469c4479c7e34bf61bec8dfd27ef1ab73cc171da",
        "e81d0cfcd3a4986204c289fb8c457bd279ba8c2d24d43679d02b1661581301e7",
    },
    "explorer": {"bfde4fbbe2740152ad537d576612a34619a57a45adb56072e3f945610ef820af"},
    "worker": {
        "ce4488d0323832dc1563481875e7c26d693092c94865c37a4b4b89afd8274f83",
        "249b194b8c9e0cea3ff687298e58cee99ca6c330f79e04162029a60e2ecfeff0",
    },
    "designer": {"c8c525a3a7fdfb5adbff1cf7474d24dfba35527eb070f4a5206c164b248d43ed"},
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


def main() -> int:
    try:
        event = json.load(sys.stdin)
        event_name = event["hook_event_name"]
        if event_name not in {"SessionStart", "SubagentStart"}:
            raise ValueError("Unsupported hook event")
        root = Path(__file__).resolve().parents[1]
        codex_root = os.environ.get("PLUGIN_ROOT")
        host = "codex" if codex_root and Path(codex_root).resolve() == root else "claude"
        context = render_context(root, host, context_kind(event_name, host, event))
        if host == "codex":
            try:
                provision_codex_agents(root)
            except OSError:
                pass
        if event_name == "SessionStart":
            try:
                write_terminal_marker(root, host, event)
            except (OSError, ValueError):
                pass
            if host == "codex":
                try:
                    apply_codex_auto_settings(root)
                except Exception:
                    pass
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"hei5enbug-agent-setup instructions were not loaded: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
