"""Build the fake Orca, the fake plugin commands, and the seeded session state for T81 beside the notes-cli repository.

Everything lives in the run's work folder, the parent of `repo`: an installed copy of the plugin, an older plugin folder
a session loaded, one Claude Code session whose last turn ended while a background command still owes its notification,
one idle Codex session, the session markers, a fake `orca` and fake `claude` and `codex` on `fake-bin/`, and the state
folders `orca-state/`, `plugin-state/`, and `orca-user/`. The installed copy is made from the variant's exported plugin
folder, `E2E_PLUGIN_DIR`, so the session runs the code under test; without it the harness checkout stands in.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = Path(os.environ.get("E2E_PLUGIN_DIR") or HERE.parents[3])
PLUGIN_ID = "hei5enbug-agent-setup@hei5enbug"
CLAUDE_HANDLE = "term_demo_a"
CODEX_HANDLE = "term_demo_b"
OLD_VERSION = "0.9.0"
VANISH_AFTER_SECONDS = 75
COPY_IGNORE = shutil.ignore_patterns(".git", "evals", "docs", "tests", "__pycache__", ".venv", "node_modules", ".pytest_cache")


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_digest(root: Path):
    spec = importlib.util.spec_from_file_location("t81_session_context", root / "scripts" / "session_context.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def background_transcript(path: Path) -> None:
    """A finished turn that started a background command; its notification has not arrived."""
    now = stamp()
    jsonl(path, [
        {"type": "user", "message": {"role": "user", "content": "배포 롤아웃이 끝날 때까지 기다렸다가 알려줘"}, "timestamp": now},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "롤아웃 대기 명령을 백그라운드로 시작했습니다."},
            {"type": "tool_use", "id": "toolu_demo", "name": "Bash", "input": {"command": "sleep 3600", "run_in_background": True}}]},
         "timestamp": now},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_demo",
                                                                  "content": "Command running in background with ID: bg1"}]},
         "timestamp": now},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "끝나면 알려 드리겠습니다."}]},
         "timestamp": now},
        {"type": "system", "subtype": "turn_duration", "durationMs": 1, "timestamp": now},
    ])


def codex_rollout(path: Path) -> None:
    now = stamp()
    jsonl(path, [{"type": "event_msg", "timestamp": now, "payload": {"type": "task_started"}},
                 {"type": "event_msg", "timestamp": now, "payload": {"type": "task_complete"}}])


def terminal(handle: str, host: str, title: str, transcript: Path, screen: list[str], idle: bool, work: Path) -> dict:
    return {"handle": handle, "agentIdentity": host, "connected": True, "writable": True, "orphaned": False, "title": title,
            "worktreePath": str(work / title), "screen": screen, "draft": None, "idle": idle, "transcript": str(transcript)}


def write_marker(directory: Path, handle: str, host: str, root: Path, digest: str, transcript: Path) -> None:
    (directory / f"{handle}.json").write_text(json.dumps({
        "schema": 1, "host": host, "root": root.as_posix(), "digest": digest, "written_at": stamp(), "source": "startup",
        "transcript_path": str(transcript)}), encoding="utf-8")


def install(directory: Path, binary: Path, name: str, source: Path) -> None:
    program = binary / name
    shutil.copy(source, program)
    program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main(repo_argument: str) -> None:
    work = Path(repo_argument).resolve().parent
    claude_root = work / "claude-plugins" / "hei5enbug-agent-setup"
    installed = claude_root / json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    older = claude_root / OLD_VERSION
    shutil.copytree(PLUGIN_ROOT, installed, ignore=COPY_IGNORE)
    older.mkdir(parents=True)
    version = installed.name
    digest = load_digest(installed).instructions_digest(installed)

    transcripts = work / "transcripts"
    transcripts.mkdir()
    claude_log, codex_log = transcripts / "claude-session.jsonl", transcripts / "codex-rollout.jsonl"
    background_transcript(claude_log)
    codex_rollout(codex_log)

    markers = work / "orca-user" / "hei5enbug-agent-setup" / "terminals"
    markers.mkdir(parents=True)
    write_marker(markers, CLAUDE_HANDLE, "claude", older, digest, claude_log)
    write_marker(markers, CODEX_HANDLE, "codex", installed, digest, codex_log)

    claude_screen = ["● 롤아웃 대기 명령을 백그라운드로 시작했습니다. 끝나면 알려 드리겠습니다.", "─" * 40, "❯ ", "─" * 40,
                     "  ⏵⏵ auto mode on (shift+tab to cycle)"]
    codex_screen = ["• 정리했습니다.", "› Ask Codex to do anything", "  GPT-6-Luna low · /tmp/work"]
    state_dir, plugin_dir = work / "orca-state", work / "plugin-state"
    state_dir.mkdir()
    plugin_dir.mkdir()
    (state_dir / "state.json").write_text(json.dumps({"vanish_after_seconds": VANISH_AFTER_SECONDS, "terminals": [
        terminal(CLAUDE_HANDLE, "claude", "demo-a", claude_log, claude_screen, False, work),
        terminal(CODEX_HANDLE, "codex", "demo-b", codex_log, codex_screen, True, work)]}, indent=2), encoding="utf-8")
    (plugin_dir / "state.json").write_text(json.dumps({
        "release": "2.1.326",
        "claude_record": {"id": PLUGIN_ID, "scope": "user", "enabled": True, "version": version, "installPath": str(installed)}},
        indent=2), encoding="utf-8")

    binary = work / "fake-bin"
    binary.mkdir()
    install(work, binary, "orca", HERE / "fake_orca_sessions.py")
    install(work, binary, "claude", HERE / "fake_plugin_cli.py")
    install(work, binary, "codex", HERE / "fake_plugin_cli.py")


if __name__ == "__main__":
    main(sys.argv[1])
