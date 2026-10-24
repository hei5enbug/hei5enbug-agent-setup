"""Discovery of superseded releases, superseded plugin versions, session scratch, and stale temp entries."""

from __future__ import annotations

import os
import stat
from datetime import datetime
from typing import Iterator

from data_common import (
    NS_PER_SECOND,
    Context,
    inside,
    parse_timestamp,
    parse_version,
    real,
    reason,
)
from data_model import Member
from data_system import Process, Snapshot

Only = frozenset[str] | None


def entries_of(folder: str) -> list[str]:
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def is_folder(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def folders_of(folder: str) -> Iterator[str]:
    for name in entries_of(folder):
        path = os.path.join(folder, name)
        if is_folder(path):
            yield path


def wanted(paths: tuple[str, ...], only: Only) -> bool:
    return only is None or any(path in only for path in paths)


def version_reason(
    name: str, current_name: str, current: tuple[int, ...] | None, label: str = "current release"
) -> dict[str, str] | None:
    mine = parse_version(name)
    if mine is None:
        return reason("version", f"the version of {name} cannot be parsed")
    if current is None:
        return reason("version", f"the version of the {label} {current_name} cannot be parsed")
    if mine > current:
        return reason("version", f"{name} is newer than the {label} {current_name}")
    if mine == current:
        return reason("version", f"{name} has the same version as the {label} {current_name}")
    return None


def release_members(host: str, folder: str, current_name: str, only: Only) -> list[Member]:
    current = parse_version(current_name)
    members = []
    for name in entries_of(folder):
        path = os.path.join(folder, name)
        if name == current_name or not wanted((path,), only):
            continue
        problem = version_reason(name, current_name, current)
        members.append(Member("superseded-release", host, (path,), (problem,) if problem else ()))
    return members


def claude_releases(ctx: Context, snap: Snapshot, only: Only) -> list[Member]:
    versions = os.path.join(ctx.claude_install_dir, "versions")
    if not os.path.islink(ctx.claude_launcher) or not os.path.isdir(versions):
        return []
    target, versions_real = real(ctx.claude_launcher), real(versions)
    if not inside(target, versions_real):
        return []
    current_name = os.path.relpath(target, versions_real).split(os.sep)[0]
    return release_members("claude", versions, current_name, only)


def codex_releases(ctx: Context, snap: Snapshot, only: Only) -> list[Member]:
    members: list[Member] = []
    packages = os.path.join(ctx.codex_dir, "packages")
    for package in folders_of(packages):
        current = os.path.join(package, "current")
        if not os.path.islink(current):
            continue
        target, package_real = real(current), real(package)
        folder = os.path.dirname(target)
        if not inside(folder, package_real):
            continue
        folder_raw = os.path.join(package, os.path.relpath(folder, package_real))
        members += release_members("codex", folder_raw, os.path.basename(target), only)
    return members


def update_time(entries: list[dict]) -> tuple[datetime | None, str]:
    latest = None
    for entry in entries:
        moment = parse_timestamp(entry.get("lastUpdated") or entry.get("installedAt"))
        if moment is None:
            return None, "an install entry has a missing or unparsable update time"
        latest = moment if latest is None or moment > latest else latest
    return latest, ""


def is_claude_process(process: Process, versions: str) -> bool:
    tokens = process.tokens
    if any(os.path.basename(token) == "claude" for token in tokens[:2]):
        return True
    return bool(tokens) and tokens[0].startswith(versions + os.sep)


def plugin_owner_reason(ctx: Context, snap: Snapshot, entries: list[dict]) -> dict[str, str] | None:
    updated, problem = update_time(entries)
    if updated is None:
        return reason("owner", f"unknown: {problem}")
    if snap.processes is None:
        return reason("owner", f"unknown: the process list is unavailable ({snap.process_error})")
    versions = os.path.join(ctx.claude_install_dir, "versions")
    for process in snap.processes:
        if not is_claude_process(process, versions):
            continue
        if process.started is None or process.started < updated:
            return reason(
                "owner",
                f"a Claude Code process started before the update may still load it (process {process.pid})",
            )
    return None


def plugin_reasons(ctx: Context, snap: Snapshot, market: str, plugin: str, name: str) -> tuple[dict, ...]:
    if snap.installed.error:
        return (reason("owner", snap.installed.error),)
    entries = snap.installed.plugins.get(f"{plugin}@{market}")
    if not entries:
        return (reason("version", f"{plugin}@{market} has no install entry"),)
    installed = [parse_version(str(entry.get("version", ""))) for entry in entries]
    if any(version is None for version in installed):
        return (reason("version", f"an installed version of {plugin}@{market} cannot be parsed"),)
    lowest = min(installed)
    problem = version_reason(name, ".".join(map(str, lowest)), lowest, "lowest installed version")
    if problem:
        return (problem,)
    owner = plugin_owner_reason(ctx, snap, entries)
    return (owner,) if owner else ()


def plugin_versions(ctx: Context, snap: Snapshot, only: Only) -> list[Member]:
    members = []
    for market_path in folders_of(ctx.claude_plugin_cache):
        for plugin_path in folders_of(market_path):
            for name in entries_of(plugin_path):
                path = os.path.join(plugin_path, name)
                if not wanted((path,), only):
                    continue
                market, plugin = os.path.basename(market_path), os.path.basename(plugin_path)
                reasons = plugin_reasons(ctx, snap, market, plugin, name)
                members.append(Member("superseded-plugin-version", "claude", (path,), reasons))
    return members


def session_owner_reasons(snap: Snapshot, session_id: str, host: str) -> list[dict]:
    found = []
    if snap.processes is None:
        found.append(reason("owner", f"unknown: the process list is unavailable ({snap.process_error})"))
    elif session_id in snap.components:
        found.append(reason("owner", f"a running process names session {session_id}"))
    if host != "claude":
        return found
    if snap.sessions is None:
        found.append(reason("owner", f"unknown: {snap.sessions_error}"))
    elif any(session_id in name or session_id in text for name, text in snap.sessions):
        found.append(reason("owner", f"an active session file mentions {session_id}"))
    return found


def session_reasons(ctx: Context, snap: Snapshot, project: str, session_id: str) -> tuple[dict, ...]:
    found = session_owner_reasons(snap, session_id, "claude")
    record = os.path.join(ctx.claude_dir, "projects", project, session_id + ".jsonl")
    try:
        age_ns = snap.now.timestamp() * NS_PER_SECOND - os.stat(record).st_mtime_ns
        if age_ns < ctx.recent_hours * 3600 * NS_PER_SECOND:
            found.append(reason("owner", f"the record of session {session_id} changed within the recent window"))
    except OSError:
        pass
    return tuple(found)


def session_scratch(ctx: Context, snap: Snapshot, only: Only) -> list[Member]:
    members = []
    for temp_root in ctx.temp_roots:
        for project_path in folders_of(temp_root):
            project = os.path.basename(project_path)
            for name in entries_of(project_path):
                path = os.path.join(project_path, name)
                if not (is_folder(path) or os.path.islink(path)) or not wanted((path,), only):
                    continue
                members.append(
                    Member("ended-session-scratch", "claude", (path,), session_reasons(ctx, snap, project, name))
                )
    return members


def codex_temp(ctx: Context, snap: Snapshot, only: Only) -> list[Member]:
    members = []
    for folder in (".tmp", "tmp"):
        base = os.path.join(ctx.codex_dir, folder)
        for name in entries_of(base):
            path = os.path.join(base, name)
            if wanted((path,), only):
                members.append(Member("stale-temp-entries", "codex", (path,), group=folder))
    return members
