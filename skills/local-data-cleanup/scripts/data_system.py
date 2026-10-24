"""One snapshot of the machine state the checks need: processes, open files, links, plugins, sessions."""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from dataclasses import dataclass
from functools import cached_property
from datetime import datetime, timezone
from typing import Any

from data_common import Context, real, reason_of

PS_COMMAND = ["ps", "-axww", "-o", "pid=,lstart=,args="]
LSOF_COMMAND = ["lsof", "-n", "-P", "-F", "n"]
COMMAND_TIMEOUT = 180
SESSION_READ_LIMIT = 64 * 1024
SESSION_FILE_LIMIT = 2000
MONTHS = {name: index for index, name in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
PS_LINE = re.compile(
    r"^\s*(\d+)\s+[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})\s+(\d{4})\s+(.*)$"
)


@dataclass(frozen=True)
class Process:
    pid: int
    started: datetime | None
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class LinkInfo:
    link: str
    target: str
    real: str


@dataclass(frozen=True)
class Installed:
    plugins: dict[str, list[dict[str, Any]]]
    error: str | None


@dataclass(frozen=True)
class Snapshot:
    now: datetime
    processes: tuple[Process, ...] | None
    process_error: str
    named: dict[str, int]
    components: frozenset[str]
    open_paths: frozenset[str] | None
    open_error: str
    links: tuple[LinkInfo, ...]
    installed: Installed
    sessions: tuple[tuple[str, str], ...] | None
    sessions_error: str
    real_roots: tuple[str, ...]
    real_protect: tuple[str, ...]

    @cached_property
    def link_targets(self) -> list[str]:
        targets = [info.real for info in self.links]
        for entries in self.installed.plugins.values():
            targets += [real(entry["installPath"]) for entry in entries]
        return targets


def run_command(command: list[str]) -> tuple[str | None, str]:
    environment = {**os.environ, "LC_ALL": "C"}
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, errors="replace", env=environment, timeout=COMMAND_TIMEOUT
        )
    except FileNotFoundError:
        return None, f"{command[0]} is not available"
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"{command[0]} failed: {error}"
    if done.returncode != 0:
        detail = (done.stderr.strip().splitlines() or ["no error message"])[0]
        return None, f"{command[0]} exited with status {done.returncode}: {detail}"
    return done.stdout, ""


def parse_started(match: re.Match[str]) -> datetime | None:
    month = MONTHS.get(match.group(2))
    if month is None:
        return None
    try:
        naive = datetime(int(match.group(7)), month, int(match.group(3)), int(match.group(4)),
                         int(match.group(5)), int(match.group(6)))
    except ValueError:
        return None
    return naive.astimezone()


def parse_processes(text: str) -> tuple[Process, ...]:
    found = []
    for line in text.splitlines():
        match = PS_LINE.match(line)
        if match:
            found.append(Process(int(match.group(1)), parse_started(match), tuple(match.group(8).split())))
    return tuple(found)


def add_with_ancestors(table: dict[str, int], path: str, pid: int) -> None:
    while path and path != os.sep and path not in table:
        table[path] = pid
        path = os.path.dirname(path)


def token_paths(token: str, prefixes: tuple[str, ...]) -> list[str]:
    found = []
    candidates = [token] + ([token.split("=", 1)[1]] if "=" in token else [])
    for candidate in candidates:
        if candidate.startswith(os.sep):
            found.append(os.path.normpath(candidate))
            if candidate.startswith(prefixes):
                found.append(real(candidate))
    return found


def index_processes(
    processes: tuple[Process, ...], prefixes: tuple[str, ...]
) -> tuple[dict[str, int], frozenset[str]]:
    named: dict[str, int] = {}
    components: set[str] = set()
    for process in processes:
        for token in process.tokens:
            components.add(token)
            components.update(part for part in token.split(os.sep) if part)
            for path in token_paths(token, prefixes):
                add_with_ancestors(named, path, process.pid)
    return named, frozenset(components)


def parse_open_paths(text: str) -> frozenset[str]:
    table: dict[str, int] = {}
    for line in text.splitlines():
        if line.startswith("n/"):
            add_with_ancestors(table, line[1:], 0)
    return frozenset(table)


def read_links(ctx: Context) -> tuple[LinkInfo, ...]:
    candidates: list[str] = []
    if ctx.uses("codex"):
        candidates += sorted(glob.glob(os.path.join(glob.escape(ctx.codex_dir), "packages", "*", "current")))
    if ctx.uses("claude"):
        candidates.append(ctx.claude_launcher)
    found = []
    for link in candidates:
        if os.path.islink(link):
            found.append(LinkInfo(link, os.readlink(link), real(link)))
    return tuple(found)


def read_installed(ctx: Context) -> Installed:
    path = os.path.join(ctx.claude_dir, "plugins", "installed_plugins.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return Installed({}, "the installed plugin list does not exist")
    except (OSError, ValueError) as error:
        return Installed({}, f"the installed plugin list cannot be read: {error}")
    plugins = data.get("plugins") if isinstance(data, dict) else None
    valid = isinstance(plugins, dict) and all(
        isinstance(entries, list)
        and all(isinstance(entry, dict) and isinstance(entry.get("installPath"), str) for entry in entries)
        for entries in plugins.values()
    )
    if not valid:
        return Installed({}, "the installed plugin list is malformed")
    return Installed(plugins, None)


def read_sessions(ctx: Context) -> tuple[tuple[tuple[str, str], ...] | None, str]:
    folder = os.path.join(ctx.claude_dir, "sessions")
    if not os.path.isdir(folder):
        return (), ""
    texts: list[tuple[str, str]] = []
    try:
        for current, _, names in os.walk(folder):
            for name in names:
                if len(texts) >= SESSION_FILE_LIMIT:
                    return None, "too many session files to read"
                with open(os.path.join(current, name), "rb") as handle:
                    texts.append((name, handle.read(SESSION_READ_LIMIT).decode("utf-8", errors="replace")))
    except OSError as error:
        return None, f"the session files cannot be read: {reason_of(error)}"
    return tuple(texts), ""


def take_snapshot(ctx: Context) -> Snapshot:
    ps_text, process_error = run_command(PS_COMMAND)
    processes = parse_processes(ps_text) if ps_text is not None else None
    if processes is not None and not processes:
        processes, process_error = None, "ps returned no processes"
    roots = [path for _, path in ctx.roots()]
    prefixes = tuple(dict.fromkeys(roots + [real(path) for path in roots]))
    named, components = index_processes(processes or (), prefixes)
    lsof_text, open_error = run_command(LSOF_COMMAND)
    open_paths = parse_open_paths(lsof_text) if lsof_text else None
    if lsof_text is not None and not open_paths:
        open_paths, open_error = None, "lsof returned no open files"
    sessions, sessions_error = read_sessions(ctx) if ctx.uses("claude") else ((), "")
    return Snapshot(
        now=datetime.now(timezone.utc),
        processes=processes,
        process_error=process_error,
        named=named,
        components=components,
        open_paths=open_paths,
        open_error=open_error,
        links=read_links(ctx),
        installed=read_installed(ctx) if ctx.uses("claude") else Installed({}, "not scanned"),
        sessions=sessions,
        sessions_error=sessions_error,
        real_roots=ctx.real_roots(),
        real_protect=tuple(real(path) for path in ctx.protect),
    )
