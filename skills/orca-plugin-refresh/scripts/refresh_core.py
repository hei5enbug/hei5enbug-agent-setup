from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Sequence


PLUGIN = "hei5enbug-agent-setup"
MARKETPLACE = "hei5enbug"
PLUGIN_ID = f"{PLUGIN}@{MARKETPLACE}"
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
HOSTS = ("claude", "codex")
RUN_ID = re.compile(r"^[0-9a-f]{32}$")
HANDLE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
RUN_STATE_WAIT_SECONDS = 60.0


class RefreshError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def parse_time(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def load_plugin_script(name: str):
    path = PLUGIN_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"hei5enbug_{name}", path)
    if spec is None or spec.loader is None or not path.is_file():
        raise RefreshError("plugin_incomplete", f"The plugin's {name}.py is missing.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SESSION_CONTEXT = load_plugin_script("session_context")
CODEX_HOOK_TRUST = load_plugin_script("codex_hook_trust")


def executable(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RefreshError("command_missing", f"Required command is unavailable: {name}.")
    return path


def run(argv: Sequence[str], *, timeout: float = 60.0, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(list(argv), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise RefreshError("command_timeout", f"{Path(argv[0]).name} did not finish in {int(timeout)} seconds.") from error
    except OSError as error:
        raise RefreshError("command_failed", f"{Path(argv[0]).name} could not start.") from error
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
        raise RefreshError("command_failed", f"{Path(argv[0]).name} {' '.join(argv[1:3])} failed: {detail[0][:200]}")
    return result


def run_json(argv: Sequence[str], *, timeout: float = 60.0) -> object:
    result = run(argv, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RefreshError("invalid_json", f"{Path(argv[0]).name} returned unreadable JSON.") from error


def state_root() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    root = base / PLUGIN / "orca-plugin-refresh"
    (root / "runs").mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def run_path(run_id: str) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise RefreshError("invalid_run_id", "The run ID is invalid.")
    return state_root() / "runs" / f"{run_id}.json"


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=1)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_run(run_id: str) -> dict:
    try:
        return json.loads(run_path(run_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RefreshError("run_missing", "No saved update run matches that ID.") from error


@contextmanager
def exclusive(name: str, wait_seconds: float = 0.0) -> Iterator[None]:
    """Hold one machine-wide lock so only one process sends commands to Orca sessions at a time."""
    path = state_root() / f"{name}.lock"
    deadline = time.time() + wait_seconds
    with path.open("a+") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.time() >= deadline:
                    raise RefreshError("already_running", "Another refresh run is still sending commands to sessions.") from error
                time.sleep(1.0)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update_run(run_id: str, change: Callable[[dict], dict | None]) -> dict:
    """Read, change, and save one run's state under its own short lock, so concurrent writers never lose an update.

    A `change` that returns None saves nothing.
    """
    with exclusive("run-state", wait_seconds=RUN_STATE_WAIT_SECONDS):
        saved = change(load_run(run_id))
        if saved is None:
            return load_run(run_id)
        save_json(run_path(run_id), saved)
        return saved
