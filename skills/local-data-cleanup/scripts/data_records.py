"""Discovery of old session records and of the other top-level entries of the data folders."""

from __future__ import annotations

import os
import re

from data_common import DAY_SECONDS, NS_PER_SECOND, Context, reason
from data_kinds import Only, entries_of, folders_of, is_folder, wanted
from data_measure import measure
from data_model import Member
from data_system import Snapshot

DIGITS = {"year": re.compile(r"[0-9]{4}"), "month": re.compile(r"[0-9]{2}"), "day": re.compile(r"[0-9]{2}")}
KNOWN_ENTRIES = frozenset({"projects", "plugins", "packages", "sessions", "archived_sessions", ".tmp", "tmp"})
KIND = "old-session-records"


def cutoff_ns(ctx: Context, snap: Snapshot) -> int:
    return int((snap.now.timestamp() - ctx.age_days * DAY_SECONDS) * NS_PER_SECOND)


def old_member(host: str, paths: tuple[str, ...], group: str, cutoff: int) -> Member | None:
    measures = tuple(measure(path) for path in paths)
    if max(item.newest_ns for item in measures) >= cutoff:
        return None
    return Member(KIND, host, paths, group=group, measures=measures)


def claude_pairs(project_path: str) -> list[tuple[str, ...]]:
    pairs = []
    for name in entries_of(project_path):
        if not name.endswith(".jsonl"):
            continue
        record = os.path.join(project_path, name)
        companion = os.path.join(project_path, name[: -len(".jsonl")])
        pairs.append((record, companion) if os.path.lexists(companion) else (record,))
    return pairs


def claude_records(ctx: Context, snap: Snapshot, only: Only) -> tuple[list[Member], list[dict]]:
    projects = os.path.join(ctx.claude_dir, "projects")
    cutoff, members = cutoff_ns(ctx, snap), []
    for project_path in folders_of(projects):
        for paths in claude_pairs(project_path):
            member = old_member("claude", paths, os.path.basename(project_path), cutoff) if wanted(paths, only) else None
            if member:
                members.append(member)
    notes = [] if members or not os.path.isdir(projects) else [empty_note(ctx, "claude", projects)]
    return members, notes


def empty_note(ctx: Context, host: str, folder: str) -> dict:
    return {
        "host": host,
        "kind": KIND,
        "text": f"nothing older than {ctx.age_days} days under {ctx.display(folder)}; nothing reclaimable there",
    }


def codex_day_folders(sessions: str) -> list[tuple[str, str]]:
    found = []
    for year in entries_of(sessions):
        for month in entries_of(os.path.join(sessions, year)):
            for day in entries_of(os.path.join(sessions, year, month)):
                matches = DIGITS["year"].fullmatch(year) and DIGITS["month"].fullmatch(month) and DIGITS["day"].fullmatch(day)
                path = os.path.join(sessions, year, month, day)
                if matches and (is_folder(path) or os.path.islink(path)):
                    found.append((f"{year}/{month}", path))
    return found


def codex_records(ctx: Context, snap: Snapshot, only: Only) -> tuple[list[Member], list[dict]]:
    sessions = os.path.join(ctx.codex_dir, "sessions")
    archived = os.path.join(ctx.codex_dir, "archived_sessions")
    cutoff = cutoff_ns(ctx, snap)
    day_members, archive_members = [], []
    for group, path in codex_day_folders(sessions):
        member = old_member("codex", (path,), group, cutoff) if wanted((path,), only) else None
        if member:
            day_members.append(member)
    for name in entries_of(archived):
        path = os.path.join(archived, name)
        member = old_member("codex", (path,), "archived", cutoff) if wanted((path,), only) else None
        if member:
            archive_members.append(member)
    notes = []
    for folder, found in ((sessions, day_members), (archived, archive_members)):
        if os.path.isdir(folder) and not found:
            notes.append(empty_note(ctx, "codex", folder))
    return day_members + archive_members, notes


def other_entries(ctx: Context, snap: Snapshot, only: Only) -> list[Member]:
    members = []
    for host, base in (("claude", ctx.claude_dir), ("codex", ctx.codex_dir)):
        if not ctx.uses(host):
            continue
        for name in entries_of(base):
            path = os.path.join(base, name)
            if name in KNOWN_ENTRIES or not wanted((path,), only):
                continue
            problem = reason("kind", "not a kind this skill reclaims")
            members.append(Member("other", host, (path,), (problem,), full_checks=False))
    return members
