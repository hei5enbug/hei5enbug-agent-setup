"""Fixture folders, isolated environments, and child processes for the local-data-cleanup tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPT_DIR / "local_data.py"
OLD_DAYS = 60
ISOLATED_VARIABLES = (
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "CLAUDE_CODE_TMPDIR",
    "CLAUDE_CODE_PLUGIN_CACHE_DIR",
    "TMPDIR",
)
HOLD_CODE = "import sys,time;print('ready',flush=True);time.sleep(300)"
OPEN_CODE = "import sys,time;f=open(sys.stdin.readline().strip());print('ready',flush=True);time.sleep(300)"
CHILD_TIMEOUT = 20


@dataclass(frozen=True)
class Result:
    code: int
    data: Any
    stderr: str


def make_readable_again(root: Path) -> None:
    for current, folders, _ in os.walk(root):
        for name in folders:
            path = os.path.join(current, name)
            if not os.path.islink(path):
                os.chmod(path, 0o755)


class FixtureCase(unittest.TestCase):
    """A fixture home with Claude Code and Codex folders, run through the real script."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.addCleanup(make_readable_again, self.root)
        self.home = self.root / "home"
        self.claude = self.home / ".claude"
        self.cache = self.claude / "plugins" / "cache"
        self.install = self.home / ".local" / "share" / "claude"
        self.launcher = self.home / ".local" / "bin" / "claude"
        self.codex = self.home / ".codex"
        self.temp = self.root / "tmp" / "claude-1000"
        self.work = self.root / "work"
        self.out = self.root / "out"
        for folder in (self.home, self.temp, self.work, self.out, self.launcher.parent):
            folder.mkdir(parents=True, exist_ok=True)

    def env(self, **extra: str) -> dict[str, str]:
        environment = {k: v for k, v in os.environ.items() if k not in ISOLATED_VARIABLES}
        environment.update(HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1", LC_ALL="C")
        environment.update(extra)
        return environment

    def run_script(self, *args: str, environment: dict[str, str] | None = None) -> Result:
        done = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=self.work,
            env=environment or self.env(),
            timeout=300,
        )
        data = json.loads(done.stdout) if done.stdout.strip() else None
        return Result(done.returncode, data, done.stderr)

    def root_options(self) -> list[str]:
        return [
            "--claude-dir", str(self.claude),
            "--claude-plugin-cache", str(self.cache),
            "--claude-install-dir", str(self.install),
            "--claude-launcher", str(self.launcher),
            "--codex-dir", str(self.codex),
            "--temp-root", str(self.temp),
        ]

    def survey(self, *extra: str, host: str = "both", environment: dict[str, str] | None = None) -> Result:
        arguments = ["survey", "--host", host, "--min-size", "0", *self.root_options(), *extra]
        return self.run_script(*arguments, "--out", str(self.out / "survey.json"), environment=environment)

    def merge(self, survey: Result, verdicts: dict[int, str], peer_host: str = "codex", model: str = "demo-model") -> Result:
        entries = [{"id": number, "verdict": verdict, "reason": f"demo reason {number}"} for number, verdict in verdicts.items()]
        peer = {"host": peer_host, "model": model, "verdicts": entries}
        (self.out / "peer.json").write_text(json.dumps(peer), encoding="utf-8")
        return self.run_script(
            "merge", "--survey", str(self.out / "survey.json"), "--peer", str(self.out / "peer.json"),
            "--self-host", "claude" if peer_host == "codex" else "codex", "--out", str(self.out / "plan.json"),
        )

    def offer_all(self, survey: Result) -> Result:
        verdicts = {item["id"]: "delete" for item in survey.data["items"] if item["verdict"] == "candidate"}
        return self.merge(survey, verdicts)

    def delete(self, *selected: str) -> Result:
        arguments = [value for number in selected for value in ("--select", number)]
        return self.run_script("delete", "--plan", str(self.out / "plan.json"), *arguments)

    def write(self, path: Path, size: int = 16384) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        return path

    def age(self, path: Path, days: float = OLD_DAYS) -> None:
        moment = time.time() - days * 86400
        for current, folders, files in os.walk(path, topdown=False):
            for name in [*folders, *files]:
                os.utime(os.path.join(current, name), (moment, moment), follow_symlinks=False)
        os.utime(path, (moment, moment), follow_symlinks=False)

    def scratch(self, session: str, project: str = "demo-project", size: int = 16384) -> Path:
        folder = self.temp / project / session
        self.write(folder / "data.bin", size)
        self.age(folder)
        return folder

    def spawn(self, code: str = HOLD_CODE, *args: str, cwd: Path | None = None, argv0: str | None = None) -> subprocess.Popen:
        command = [argv0 or sys.executable, "-c", code, *args]
        process = subprocess.Popen(
            command, executable=sys.executable, cwd=cwd or self.work, env=self.env(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.stop, process)
        return process

    def stop(self, process: subprocess.Popen) -> None:
        process.kill()
        process.wait(timeout=CHILD_TIMEOUT)
        for stream in (process.stdin, process.stdout):
            if stream:
                stream.close()

    def wait_ready(self, process: subprocess.Popen) -> None:
        self.assertEqual("ready", process.stdout.readline().strip())

    def hold_open(self, path: Path) -> subprocess.Popen:
        process = self.spawn(OPEN_CODE)
        process.stdin.write(str(path) + "\n")
        process.stdin.flush()
        self.wait_ready(process)
        return process

    def git(self, repo: Path, *args: str) -> None:
        command = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", *args]
        subprocess.run(command, cwd=repo, env=self.env(), check=True, capture_output=True)

    def make_repo(self, folder: Path, dirty: bool) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.git(folder, "init", "-q")
        self.write(folder / "tracked.txt", 100)
        self.git(folder, "add", "tracked.txt")
        self.git(folder, "commit", "-q", "-m", "demo")
        if dirty:
            self.write(folder / "untracked.txt", 100)

    def item(self, result: Result, fragment: str) -> dict[str, Any]:
        matches = [item for item in result.data["items"] if fragment in item["display"]]
        self.assertEqual(1, len(matches), f"{fragment}: {[i['display'] for i in result.data['items']]}")
        return matches[0]

    def checks_of(self, item: dict[str, Any]) -> set[str]:
        return {reason["check"] for reason in item["reasons"]}

    def tree(self, root: Path) -> list[str]:
        return sorted(str(path.relative_to(root)) for path in root.rglob("*"))
