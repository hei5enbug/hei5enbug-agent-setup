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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import language_guard  # noqa: E402


LOCAL_LINK = re.compile(r"\[([^\]]+)\]\(([^\s)]+)\)")
MAX_CONTEXT_BYTES = 9000
DIGEST_VERSION = 1
MARKER_SCHEMA = 1
MARKER_RETENTION_SECONDS = 30 * 24 * 60 * 60
TERMINAL_HANDLE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
SESSION_FILES = {
    "codex": "codex.md",
    "claude": "claude-code.md",
}


def read_instruction(path: Path, root: Path) -> str:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"{path.relative_to(root)} is empty")

    def absolute_link(match: re.Match[str]) -> str:
        reference = match[2].removeprefix("<").removesuffix(">")
        if reference.startswith("#") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", reference):
            return match[0]
        target = (path.parent / reference).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError(f"Unavailable bundled reference: {path.relative_to(root)} -> {reference}")
        return f"[{match[1]}](<{target.as_posix()}>)"

    return LOCAL_LINK.sub(absolute_link, content)


def render_context(root: Path, host: str) -> str:
    try:
        host_file = SESSION_FILES[host]
    except KeyError as error:
        raise ValueError(f"Unsupported host: {host}") from error
    session_dir = root / "instructions" / "session"
    content = "\n\n".join(
        read_instruction(path, root)
        for path in (session_dir / "common.md", session_dir / host_file)
    )
    context = (
        f"hei5enbug-agent-setup instructions for {host}.\n"
        f"Source directory: {root.as_posix()}\n"
        "Apply the common rules throughout this session. "
        "Read conditional references only before their matching action.\n\n"
        f"{content}\n"
    )
    if host == "codex":
        context += f"\nResponse language: {language_guard.codex_language()}.\n"
    if len(context.encode("utf-8")) > MAX_CONTEXT_BYTES:
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
}
RETIRED_CODEX_AGENTS = {
    "scout": {"910da79ee988b53f4a94186a469c4479c7e34bf61bec8dfd27ef1ab73cc171da"},
    "explorer": {"bfde4fbbe2740152ad537d576612a34619a57a45adb56072e3f945610ef820af"},
    "worker": {"ce4488d0323832dc1563481875e7c26d693092c94865c37a4b4b89afd8274f83"},
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
        context = render_context(root, host)
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
