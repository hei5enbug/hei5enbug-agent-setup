"""The parallel limit for agent runs on this machine and the machine-wide list of runs that count against it.

The limit is the lowest of the logical CPU count minus one, the available memory divided by one run's estimated
memory, and the host's own limit, and at least one. The estimate is 1536 MiB when the launch's working directory is a
JVM build workspace (a Gradle or Maven build file in its Git top level or in the folder itself) and 512 MiB otherwise;
`run_memory_mib` and `jvm_run_memory_mib` in the shipped `config/parallel-limit.json` replace them. A known load or
memory shortage makes it one. A CPU count or available memory that cannot be read leaves its term out and caps the
result at six. On macOS, memory pressure warning halves the limit, and critical makes it one. `HEI5ENBUG_PARALLEL_LIMIT_MAX`
and `max` in the shipped file set a further maximum.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

import machine_load
import session_memory

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "parallel-limit.json"
MAX_ENV = "HEI5ENBUG_PARALLEL_LIMIT_MAX"
UNREADABLE_CAP = 6
RUN_MEMORY_MIB = 512
JVM_RUN_MEMORY_MIB = 1536
RUN_MEMORY_KEY = "run_memory_mib"
JVM_RUN_MEMORY_KEY = "jvm_run_memory_mib"
JVM_BUILD_FILES = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "pom.xml")
PRESSURE_WARNING = 2
PRESSURE_CRITICAL = 4
CLAUDE_SUBAGENT_LIMIT_ENV = "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"
CLAUDE_SUBAGENT_LIMIT_DEFAULT = 20
CODEX_LIMIT_KEYS = ("max_concurrent_threads_per_session", "max_threads")
MAX_RUN_SECONDS = 2700
SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
PS_TIMEOUT_SECONDS = 1


def compute_limit(
    cpus: int | None,
    available_mb: int | None,
    load_average: float | None,
    memory_fraction: float | None,
    host_limit: int | None,
    maximum: int | None = None,
    run_memory_mib: int = RUN_MEMORY_MIB,
    pressure: int | None = None,
) -> int:
    """The number of agent runs that may run at once, from the counters of one moment.

    `pressure` is the macOS memory pressure level: 2 halves the limit and 4 makes it one.
    """
    shortage = (
        (load_average is not None and cpus and load_average >= machine_load.LOAD_FACTOR * cpus)
        or (memory_fraction is not None and memory_fraction < machine_load.MEMORY_FRACTION)
    )
    if shortage:
        return 1
    terms = []
    if cpus:
        terms.append(cpus - 1)
    if available_mb is not None:
        terms.append(available_mb // run_memory_mib)
    if host_limit is not None:
        terms.append(host_limit)
    if not cpus or available_mb is None:
        terms.append(UNREADABLE_CAP)
    if maximum is not None:
        terms.append(maximum)
    result = max(1, min(terms))
    if pressure == PRESSURE_CRITICAL:
        return 1
    return max(1, result // 2) if pressure == PRESSURE_WARNING else result


def git_top_level(start: Path) -> Path | None:
    """The nearest folder, from `start` upward, that holds `.git` as a folder or a file."""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


def is_jvm_workspace(cwd: str) -> bool:
    """Whether the folder itself or its Git top level holds a Gradle or Maven build file."""
    try:
        start = Path(cwd).resolve()
    except (OSError, RuntimeError):
        return False
    top = git_top_level(start)
    folders = (start,) if top is None or top == start else (start, top)
    return any((folder / name).is_file() for folder in folders for name in JVM_BUILD_FILES)


def configured_estimate(key: str, default: int) -> int:
    """A per-run memory estimate in MiB from the shipped file; a missing, non-integer, or non-positive one gives `default`."""
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError, AttributeError):
        return default
    return value if type(value) is int and value > 0 else default


def run_memory_mib(cwd: str) -> int:
    """One run's estimated memory in MiB, by the kind of workspace the launch starts in."""
    if is_jvm_workspace(cwd):
        return configured_estimate(JVM_RUN_MEMORY_KEY, JVM_RUN_MEMORY_MIB)
    return configured_estimate(RUN_MEMORY_KEY, RUN_MEMORY_MIB)


def configured_maximum() -> int | None:
    """The maximum from the environment switch, else from the shipped file; None means no maximum."""
    text = os.environ.get(MAX_ENV)
    if text is not None and text.strip().isdigit():
        return int(text) or None
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("max")
    except (OSError, ValueError, AttributeError):
        return UNREADABLE_CAP
    return value if type(value) is int and value > 0 else None


def codex_host_limit(home: Path) -> int | None:
    try:
        agents = tomllib.loads((home / "config.toml").read_text(encoding="utf-8")).get("agents")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    for key in CODEX_LIMIT_KEYS:
        value = agents.get(key) if isinstance(agents, dict) else None
        if type(value) is int and value > 0:
            return value
    return None


def host_limit(host: str) -> int | None:
    """The host's own concurrency limit when it is known: Claude Code's documented default or its variable, a Codex setting."""
    if host == "codex":
        return codex_host_limit(Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    text = os.environ.get(CLAUDE_SUBAGENT_LIMIT_ENV, "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else CLAUDE_SUBAGENT_LIMIT_DEFAULT


def darwin_sysctl(name: bytes, kind: type) -> int | None:
    """One integer sysctl value on macOS through sysctlbyname, without starting a process."""
    try:
        import ctypes

        value = kind(0)
        size = ctypes.c_size_t(ctypes.sizeof(value))
        if ctypes.CDLL(None).sysctlbyname(name, ctypes.byref(value), ctypes.byref(size), None, 0) == 0:
            return value.value
    except (OSError, ValueError, AttributeError):
        return None
    return None


def darwin_memory_bytes() -> int | None:
    """Physical memory on macOS."""
    import ctypes

    return darwin_sysctl(b"hw.memsize", ctypes.c_uint64)


def memory_pressure_level() -> int | None:
    """The macOS memory pressure level (1 normal, 2 warning, 4 critical), or None elsewhere or when unreadable."""
    if sys.platform != "darwin":
        return None
    import ctypes

    return darwin_sysctl(b"kern.memorystatus_vm_pressure_level", ctypes.c_int32)


def read_available_mb(fraction: float | None) -> int | None:
    """Available memory in MB without starting a process: the test override, /proc/meminfo, or the macOS free share of physical memory."""
    override = os.environ.get(session_memory.TEST_OVERRIDE)
    if override is not None:
        return int(override) if override.isdigit() else None
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="utf-8") as handle:
                return session_memory.parse_meminfo(handle.read())
    except OSError:
        return None
    total = darwin_memory_bytes() if sys.platform == "darwin" else None
    return int(total * fraction) // session_memory.MEBIBYTE if total and fraction is not None else None


def current_limit(host: str, cwd: str = ".") -> int:
    counters = machine_load.system_counters(cwd)
    return compute_limit(
        counters.cpu_count, read_available_mb(counters.memory_available_fraction), counters.load_average,
        counters.memory_available_fraction,
        host_limit(host), configured_maximum(), run_memory_mib(cwd), memory_pressure_level(),
    )


def state_dir() -> Path:
    import approval_state_store

    return approval_state_store.state_dir().parent / "runs"


def pid_alive(pid: object) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_field(pid: int, field: str) -> str:
    try:
        result = subprocess.run(
            ["ps", "-o", f"{field}=", "-p", str(pid)], capture_output=True, text=True, timeout=PS_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def host_pid() -> int:
    """The process that stands for a launch: this hook's parent, or that parent's parent when it is only a shell."""
    parent = os.getppid()
    name = os.path.basename(process_field(parent, "comm"))
    grand = process_field(parent, "ppid")
    return int(grand) if name in SHELLS and grand.isdigit() and int(grand) > 1 else parent


@contextmanager
def locked():
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / ".lock", "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield directory / "running.json"
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_entries(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return [
        entry for entry in entries or []
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("session"), str)
        and type(entry.get("started")) in (int, float)
    ]


def write_entries(path: Path, entries: list[dict]) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps({"entries": entries}, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def live_entries(entries: list[dict], now: float, alive=pid_alive) -> list[dict]:
    """The entries still running: not older than the run time limit and with a process that still exists."""
    return [entry for entry in entries if now - entry["started"] <= MAX_RUN_SECONDS and alive(entry.get("pid"))]


def over_limit(entries: list[dict], session: str, limit: int) -> bool:
    """Whether one more run from `session` would exceed the limit; a session with no running run of its own may always start one."""
    own = sum(1 for entry in entries if entry["session"] == session)
    return own > 0 and len(entries) >= limit


def add_entry(entries: list[dict], entry: dict) -> list[dict]:
    return [*[item for item in entries if item["id"] != entry["id"]], entry]


def remove_entries(entries: list[dict], run_id: str | None = None, session: str | None = None, kind: str | None = None) -> list[dict]:
    """The entries without the one named by `run_id`, else without the oldest background run of the session and kind."""
    if run_id is not None:
        return [entry for entry in entries if entry["id"] != run_id]
    pool = sorted(
        (entry for entry in entries if entry.get("background") and entry["session"] == session
         and (kind is None or entry.get("kind") == kind)),
        key=lambda entry: entry["started"],
    )
    return [entry for entry in entries if not pool or entry["id"] != pool[0]["id"]]


def now() -> float:
    return time.time()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Print the parallel agent limit this machine gives now.")
    parser.add_argument("--host", choices=("claude", "codex"), default="claude")
    print(current_limit(parser.parse_args(argv).host))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
