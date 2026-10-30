from __future__ import annotations

import ctypes
import os
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from refresh_core import RefreshError

CTL_KERN = 1
KERN_PROCARGS2 = 49
PROC_PIDPATHINFO_MAXSIZE = 4096
COMMAND_TIMEOUT = 15.0
RELEASE = re.compile(r"^\d+(?:\.\d+)+")
DELETED_SUFFIX = " (deleted)"
PRINT_FLAGS = frozenset({"-p", "--print"})
DROPPED_OPTIONS = frozenset({"-c", "--continue", "-r", "--resume", "--session-id", "--fork-session", *PRINT_FLAGS})
HELP_OPTION = re.compile(r"^  (-\S.*?)(?:\s{2,}|$)")


def split_nul(data: bytes) -> list[str]:
    return [os.fsdecode(part) for part in data.split(b"\0") if part]


def env_mapping(items: Sequence[str]) -> dict[str, str]:
    pairs = (item.partition("=") for item in items if "=" in item)
    return {name: value for name, _, value in pairs}


def parse_procargs2(data: bytes) -> tuple[list[str], dict[str, str]] | None:
    """Split a KERN_PROCARGS2 buffer: argc, the executable path, padding NULs, argc argv strings, then the environment."""
    if len(data) < 4:
        return None
    argc = struct.unpack("=i", data[:4])[0]
    end = data.find(b"\0", 4)
    if argc < 0 or end < 0:
        return None
    position = end
    while position < len(data) and data[position] == 0:
        position += 1
    argv: list[bytes] = []
    while len(argv) < argc:
        stop = data.find(b"\0", position)
        if stop < 0:
            return None
        argv.append(data[position:stop])
        position = stop + 1
    return [os.fsdecode(item) for item in argv], env_mapping(split_nul(data[position:]))


def libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def read_args_macos(pid: int) -> tuple[list[str], dict[str, str]] | None:
    library = libc()
    mib = (ctypes.c_int * 3)(CTL_KERN, KERN_PROCARGS2, pid)
    size = ctypes.c_size_t(0)
    if library.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0 or size.value == 0:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if library.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
        return None
    return parse_procargs2(buffer.raw[:size.value])


def read_args_linux(pid: int) -> tuple[list[str], dict[str, str]] | None:
    try:
        argv = split_nul(Path(f"/proc/{pid}/cmdline").read_bytes())
        environment = split_nul(Path(f"/proc/{pid}/environ").read_bytes())
    except OSError:
        return None
    return argv, env_mapping(environment)


def exe_path_macos(pid: int) -> str | None:
    try:
        library = ctypes.CDLL("libproc.dylib", use_errno=True)
    except OSError:
        return None
    buffer = ctypes.create_string_buffer(PROC_PIDPATHINFO_MAXSIZE)
    length = library.proc_pidpath(pid, buffer, PROC_PIDPATHINFO_MAXSIZE)
    return os.fsdecode(buffer.raw[:length]) if length > 0 else None


def exe_path_linux(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return None


def exe_path_lsof(pid: int) -> str | None:
    """The first `txt` entry of `lsof -p`, which is the process's executable."""
    try:
        result = subprocess.run(["lsof", "-p", str(pid), "-Fn"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=COMMAND_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line == "ftxt" and lines[index + 1].startswith("n"):
            return lines[index + 1][1:]
    return None


def list_processes() -> list[tuple[int, str]]:
    """(pid, command name) pairs; only the name is read from `ps`, never the arguments."""
    try:
        result = subprocess.run(["ps", "-axo", "pid=,comm="], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=COMMAND_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    processes = []
    for line in result.stdout.splitlines():
        pid, _, name = line.strip().partition(" ")
        if pid.isdigit() and name.strip():
            processes.append((int(pid), name.strip()))
    return processes


@dataclass(frozen=True)
class ProcessOs:
    """Every operating system call the process lookup makes, replaceable in tests."""

    list_processes: Callable[[], list[tuple[int, str]]] = list_processes
    read_args: Callable[[int], tuple[list[str], dict[str, str]] | None] = (
        read_args_macos if sys.platform == "darwin" else read_args_linux)
    exe_path: Callable[[int], str | None] = exe_path_macos if sys.platform == "darwin" else exe_path_linux
    lsof_path: Callable[[int], str | None] = exe_path_lsof
    exists: Callable[[str], bool] = os.path.exists
    which: Callable[[str], str | None] = shutil.which
    realpath: Callable[[str], str] = os.path.realpath
    version_text: Callable[[str], str | None] = lambda path: command_output([path, "--version"])
    help_text: Callable[[str], str | None] = lambda path: command_output([path, "--help"])


def command_output(argv: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(list(argv), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=COMMAND_TIMEOUT,
                                check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


@dataclass(frozen=True)
class SessionProcess:
    pid: int
    argv: tuple[str, ...]
    env: dict[str, str]
    exe: str | None

    @property
    def config_dir(self) -> str | None:
        return self.env.get("CLAUDE_CONFIG_DIR") or None


def find_session_process(handle: str, system: ProcessOs | None = None) -> SessionProcess | None:
    """The interactive Claude Code process of an Orca terminal, matched on `ORCA_TERMINAL_HANDLE` in its own environment.

    A child started inside the terminal inherits the handle. It is ignored when its start-up environment names another entry
    point or when it runs in print mode, whose start-up environment still carries the parent's `cli`. More than one match is
    ambiguous and raises.
    """
    system = system or ProcessOs()
    found: list[SessionProcess] = []
    for pid, name in system.list_processes():
        if Path(name).name != "claude":
            continue
        args = system.read_args(pid)
        if args is None:
            continue
        argv, env = args
        if env.get("ORCA_TERMINAL_HANDLE") != handle or env.get("CLAUDE_CODE_ENTRYPOINT", "cli") != "cli":
            continue
        if PRINT_FLAGS.intersection(argv):
            continue
        exe = system.exe_path(pid) or system.lsof_path(pid)
        found.append(SessionProcess(pid, tuple(argv), env, exe))
    if len(found) > 1:
        raise RefreshError("session_process_ambiguous", "More than one interactive Claude Code process claims this terminal.")
    return found[0] if found else None


def release_of(path: str | None) -> str | None:
    """The release named by an executable's file or version-folder name, such as `.../versions/2.1.311`."""
    if not path:
        return None
    candidate = Path(path.removesuffix(DELETED_SUFFIX))
    for name in (candidate.name, candidate.parent.name):
        if RELEASE.fullmatch(name):
            return name
    return None


def release_key(release: str) -> tuple[int, ...]:
    return tuple(int(part) for part in release.split("."))


def installed_release(system: ProcessOs | None = None) -> tuple[str | None, str | None]:
    """(version, executable path) of the `claude` that is current on PATH: the resolved link's version name, else `--version`."""
    system = system or ProcessOs()
    path = system.which("claude")
    if not path:
        return None, None
    version = release_of(system.realpath(path))
    if version is None:
        match = RELEASE.match((system.version_text(path) or "").strip())
        version = match.group(0) if match else None
    return version, path


def release_report(process: SessionProcess, system: ProcessOs | None = None) -> dict:
    """The running release and, when it is older than the installed one or its executable is gone, `host_release_outdated`."""
    system = system or ProcessOs()
    running = release_of(process.exe)
    report: dict = {"release": running}
    current, _ = installed_release(system)
    gone = bool(process.exe) and (process.exe.endswith(DELETED_SUFFIX) or not system.exists(process.exe))
    older = bool(running and current and release_key(running) < release_key(current))
    if older or gone:
        report["host_release_outdated"] = {"running": running, "installed": current, **({"executable_missing": True} if gone else {})}
    return report


def option_table(help_text: str | None) -> dict[str, str]:
    """Option name to arity from commander help: `flag`, `one` (`<v>`), `many` (`<v...>` or `[v...]`), or `optional` (`[v]`).

    A short alias shares the arity of the long option it is listed with.
    """
    table: dict[str, str] = {}
    for line in (help_text or "").splitlines():
        found = HELP_OPTION.match(line)
        if not found:
            continue
        pieces = [piece.split(None, 1) for piece in found.group(1).split(", ")]
        placeholder = next((piece[1].strip() for piece in pieces if len(piece) > 1), "")
        if not placeholder:
            arity = "flag"
        elif placeholder.endswith("...>") or placeholder.endswith("...]"):
            arity = "many"
        else:
            arity = "one" if placeholder.startswith("<") else "optional"
        table.update({piece[0]: arity for piece in pieces})
    return table


def relaunch_arguments(argv: Sequence[str], table: dict[str, str]) -> list[str] | None:
    """The original arguments to relaunch with: option values kept, the positional prompt dropped, and the options that conflict
    with `--resume <id>` (`--continue`, `--resume`, `--session-id`, `--fork-session`, `--print`) removed.

    Returns None when the table is empty or an option is not in it, because the values cannot then be told from a prompt.
    """
    kept: list[str] = []
    items = list(argv[1:])
    if not table:
        return None
    index = 0
    while index < len(items):
        token = items[index]
        index += 1
        if token == "--":
            break
        if not token.startswith("-") or token == "-":
            continue
        name, equals, _ = token.partition("=") if token.startswith("--") else (token, "", "")
        arity = table.get(name)
        if arity is None:
            return None
        values: list[str] = []
        if not equals and arity == "one" and index < len(items):
            values, index = [items[index]], index + 1
        elif not equals and arity in ("many", "optional"):
            limit = 1 if arity == "optional" else len(items)
            while index < len(items) and len(values) < limit and not items[index].startswith("-"):
                values.append(items[index])
                index += 1
        if name not in DROPPED_OPTIONS:
            kept.extend([token, *values])
    return kept


def launch_arguments(claude: str, argv: Sequence[str], system: ProcessOs | None = None) -> list[str] | None:
    """`relaunch_arguments` using the option table that the current `claude --help` prints."""
    system = system or ProcessOs()
    return relaunch_arguments(argv, option_table(system.help_text(claude)))


def session_release(handle: str, system: ProcessOs | None = None) -> dict:
    """`release_report` for the terminal's Claude Code process; empty when it is not found or not unique."""
    try:
        process = find_session_process(handle, system)
    except RefreshError:
        return {}
    return release_report(process, system) if process else {}
