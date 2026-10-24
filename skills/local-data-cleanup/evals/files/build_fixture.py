#!/usr/bin/env python3
"""Build a demo Claude Code and Codex data tree for the local-data-cleanup evals, then survey it once.

Run it with an empty temporary folder before each eval case and use that folder as <fixture> in the prompt.
Never point an eval case at the real home folder.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "local_data.py"
DAY = 86400
MIB = 1024 * 1024
OLD = 90 * DAY
PROJECT = "-work-demo"


def write(path: Path, size: int = 0, text: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        path.write_text(text, encoding="utf-8")
    else:
        path.write_bytes(os.urandom(size))
    return path


def age(root: Path, seconds_ago: float) -> None:
    """Set every entry under root, and root itself, to the same past modification time."""
    when = time.time() - seconds_ago
    for current, folders, files in os.walk(root, topdown=False):
        for name in files + folders:
            os.utime(Path(current) / name, (when, when), follow_symlinks=False)
    os.utime(root, (when, when), follow_symlinks=False)


def build_claude(dest: Path) -> None:
    claude = dest / "claude"
    cache = claude / "plugins" / "cache" / "demo-market" / "demo-plugin"
    for version, size in (("1.0.0", 2 * MIB), ("2.0.0", 2 * MIB)):
        write(cache / version / "skills" / "demo" / "SKILL.md", text="# Demo\n")
        write(cache / version / "assets.bin", size)
    installed = {
        "version": 2,
        "plugins": {
            "demo-plugin@demo-market": [
                {
                    "scope": "user",
                    "installPath": str(cache / "2.0.0"),
                    "version": "2.0.0",
                    "installedAt": "2000-01-01T00:00:00.000Z",
                    "lastUpdated": "2000-01-01T00:00:00.000Z",
                }
            ]
        },
    }
    write(claude / "plugins" / "installed_plugins.json", text=json.dumps(installed, indent=2))
    write(claude / "settings.json", text="{}\n")
    write(claude / "projects" / PROJECT / "memory" / "MEMORY.md", text="- demo memory\n")
    for session in ("demo-a", "demo-b", "demo-c"):
        write(claude / "projects" / PROJECT / f"{session}.jsonl", text="{}\n")
    age(claude, OLD)
    for session in ("demo-a", "demo-b", "demo-c"):
        transcript = claude / "projects" / PROJECT / f"{session}.jsonl"
        recent = 600 if session == "demo-a" else 3 * DAY
        when = time.time() - recent
        os.utime(transcript, (when, when))
    install = dest / "claude-install" / "versions"
    for version in ("1.0.0", "1.0.1", "1.0.2"):
        write(install / version, MIB)
    age(dest / "claude-install", OLD)
    launcher = dest / "bin" / "claude"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.symlink_to(install / "1.0.2")


def build_temp(dest: Path) -> None:
    temp = dest / "tmp" / "claude-temp" / PROJECT
    for session, size in (("demo-a", 6 * MIB), ("demo-b", 3 * MIB), ("demo-c", 4 * MIB)):
        write(temp / session / "scratchpad" / "work.bin", size)
    age(dest / "tmp", OLD)


def build_codex(dest: Path) -> None:
    codex = dest / "codex"
    releases = codex / "packages" / "demo-daemon" / "releases"
    for index, version in enumerate(("1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4")):
        write(releases / version / "bin" / "demo-daemon", (index + 1) * MIB)
    write(codex / "demo.sqlite", 12 * MIB)
    write(codex / "config.toml", text="model = \"demo\"\n")
    write(codex / "auth.json", text="{}\n")
    write(codex / "history.jsonl", text="{}\n")
    old_day = datetime.now(timezone.utc) - timedelta(days=60)
    for offset in range(3):
        day = old_day - timedelta(days=offset)
        folder = codex / "sessions" / day.strftime("%Y/%m/%d")
        write(folder / f"rollout-{day.strftime('%Y-%m-%d')}T10-00-00-0199aaaa-0000-7000-8000-00000000000{offset}.jsonl", 2 * MIB)
    for index in range(4):
        (codex / ".tmp" / f"git-demo{index}").mkdir(parents=True, exist_ok=True)
    age(codex, 60 * DAY)
    current = codex / "packages" / "demo-daemon" / "current"
    current.symlink_to(releases / "1.0.4")
    today = codex / "sessions" / datetime.now(timezone.utc).strftime("%Y/%m/%d")
    write(today / "rollout-today-demo.jsonl", MIB)


def survey(dest: Path) -> dict:
    command = [
        sys.executable, str(SCRIPT), "survey", "--host", "both", "--min-size", "0",
        "--claude-dir", str(dest / "claude"),
        "--claude-plugin-cache", str(dest / "claude" / "plugins" / "cache"),
        "--claude-install-dir", str(dest / "claude-install"),
        "--claude-launcher", str(dest / "bin" / "claude"),
        "--codex-dir", str(dest / "codex"),
        "--temp-root", str(dest / "tmp" / "claude-temp"),
        "--out", str(dest / "work" / "reference-survey.json"),
    ]
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("CLAUDE_", "CODEX_"))}
    environment["HOME"] = str(dest / "home")
    completed = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"survey failed ({completed.returncode}): {completed.stderr or completed.stdout}")
    return json.loads(completed.stdout)


def peer_file(report: dict, keep_session: str) -> dict:
    verdicts = []
    for item in report["items"]:
        if item["verdict"] != "candidate":
            continue
        keep = any(Path(path).name == keep_session for path in item["paths"])
        verdict = "keep" if keep else "delete"
        reason = "a process list entry still names this session" if keep else "confirmed superseded or ended"
        verdicts.append({"id": item["id"], "verdict": verdict, "reason": reason})
    return {"host": "codex", "model": "gpt-6-astra", "verdicts": verdicts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", help="an empty or missing folder for the fixture")
    destination = Path(parser.parse_args().dest).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"destination is not empty: {destination}")
    (destination / "home").mkdir(parents=True, exist_ok=True)
    (destination / "work").mkdir(parents=True, exist_ok=True)
    build_claude(destination)
    build_temp(destination)
    build_codex(destination)
    report = survey(destination)
    peer = peer_file(report, "demo-b")
    (destination / "work" / "peer.json").write_text(json.dumps(peer, indent=2), encoding="utf-8")
    print(json.dumps({"fixture": str(destination), "peer": str(destination / "work" / "peer.json")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
