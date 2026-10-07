from __future__ import annotations

import hashlib
import json
import os
import re
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
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"hei5enbug-agent-setup instructions were not loaded: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
