"""Measure a path without following symlinks: size on disk, newest mtime, and risky entries inside."""

from __future__ import annotations

import fnmatch
import os
import stat
from dataclasses import dataclass

from data_common import reason_of

BLOCK_BYTES = 512
CREDENTIAL_NAMES = frozenset({"auth.json", ".credentials.json"})
PROTECTED_NAMES = frozenset(
    {
        "config.toml",
        "settings.json",
        "settings.local.json",
        "history.jsonl",
        "session_index.jsonl",
        "installed_plugins.json",
        "known_marketplaces.json",
        "CLAUDE.md",
        "AGENTS.md",
        "memory",
        "memories",
        "agent-memory",
        "rules",
        "skills",
        "agents",
        "hooks.json",
        "jobs",
        "daemon",
        ".credentials.json",
        "auth.json",
    }
)
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
MAX_LISTED = 5


def is_state_or_credential(name: str) -> bool:
    return name in CREDENTIAL_NAMES or fnmatch.fnmatchcase(name, "*.sqlite*") or name.endswith(".db")


def is_protected_name(name: str) -> bool:
    return name in PROTECTED_NAMES or name.startswith("config.toml.") or is_state_or_credential(name)


def is_sidecar(name: str) -> bool:
    return name.endswith(SIDECAR_SUFFIXES)


@dataclass(frozen=True)
class Measure:
    path: str
    present: bool
    is_symlink: bool = False
    identity: tuple[int, int] = (0, 0)
    blocks: int = 0
    linked: tuple[tuple[tuple[int, int], int], ...] = ()
    newest_ns: int = 0
    unreadable: tuple[str, ...] = ()
    protected: tuple[str, ...] = ()
    worktrees: tuple[str, ...] = ()
    error: str = ""


class Walk:
    def __init__(self) -> None:
        self.blocks = 0
        self.linked: dict[tuple[int, int], int] = {}
        self.newest = 0
        self.unreadable: list[str] = []
        self.protected: list[str] = []
        self.worktrees: list[str] = []

    def record(self, info: os.stat_result) -> None:
        self.newest = max(self.newest, info.st_mtime_ns)
        blocks = info.st_blocks * BLOCK_BYTES
        if info.st_nlink > 1 and not stat.S_ISDIR(info.st_mode):
            self.linked[(info.st_dev, info.st_ino)] = blocks
        else:
            self.blocks += blocks

    def visit(self, entry: os.DirEntry[str], directory: str, stack: list[str]) -> None:
        if entry.name == ".git" and directory not in self.worktrees:
            self.worktrees.append(directory)
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as error:
            self.unreadable.append(f"{entry.path}: {reason_of(error)}")
            return
        self.record(info)
        if is_state_or_credential(entry.name):
            self.protected.append(entry.path)
        if stat.S_ISDIR(info.st_mode):
            stack.append(entry.path)

    def descend(self, top: str) -> None:
        stack = [top]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as scanned:
                    entries = list(scanned)
            except OSError as error:
                self.unreadable.append(f"{directory}: {reason_of(error)}")
                continue
            for entry in entries:
                self.visit(entry, directory, stack)


def measure(path: str) -> Measure:
    try:
        root = os.lstat(path)
    except OSError as error:
        return Measure(path, False, error=reason_of(error))
    walk = Walk()
    walk.record(root)
    if stat.S_ISDIR(root.st_mode):
        walk.descend(path)
    return Measure(
        path=path,
        present=True,
        is_symlink=stat.S_ISLNK(root.st_mode),
        identity=(root.st_dev, root.st_ino),
        blocks=walk.blocks,
        linked=tuple(walk.linked.items()),
        newest_ns=walk.newest,
        unreadable=tuple(walk.unreadable[:MAX_LISTED]),
        protected=tuple(walk.protected[:MAX_LISTED]),
        worktrees=tuple(walk.worktrees),
    )


def total_size(measures: tuple[Measure, ...] | list[Measure]) -> int:
    linked: dict[tuple[int, int], int] = {}
    total = 0
    for item in measures:
        total += item.blocks
        linked.update(item.linked)
    return total + sum(linked.values())
