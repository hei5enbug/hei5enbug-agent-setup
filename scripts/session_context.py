from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


LOCAL_LINK = re.compile(r"\[([^\]]+)\]\(([^\s)]+)\)")
MAX_CONTEXT_BYTES = 9000
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
    if len(context.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("Bundled instructions exceed the context budget; move details to conditional references")
    return context


def provision_codex_explorer(root: Path) -> None:
    """Create the bundled `explorer` agent when Codex has none.

    Never overwrite an existing file: once the user owns `explorer.toml`, their
    copy wins and this function does nothing.
    """
    source = root / "standalone-agents" / "codex-explorer.toml"
    if not source.is_file():
        return
    home = os.environ.get("CODEX_HOME")
    target = (Path(home) if home else Path.home() / ".codex") / "agents" / "explorer.toml"
    if target.exists():
        return
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
                provision_codex_explorer(root)
            except OSError:
                pass
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"hei5enbug-agent-setup instructions were not loaded: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
