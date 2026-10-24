"""The safety checks every path of a member must pass."""

from __future__ import annotations

import os

from data_common import NS_PER_SECOND, HOUR_SECONDS, Context, inside, reason, within, real
from data_git import GitProbe, enclosing_worktree
from data_measure import Measure, is_protected_name
from data_model import Evaluation, Member
from data_system import Snapshot

Reasons = list[dict[str, str]]


def protected_reasons(ctx: Context, snap: Snapshot, path: str, measure: Measure) -> Reasons:
    found: Reasons = []
    name = os.path.basename(path)
    if is_protected_name(name):
        found.append(reason("protected", f"{ctx.display(path)} is a protected name"))
    for inner in measure.protected:
        found.append(reason("protected", f"{ctx.display(inner)} is a state database or credential"))
    path_real = real(path)
    for protect, protect_real in zip(ctx.protect, snap.real_protect):
        covers = within(path_real, protect_real) or within(protect_real, path_real)
        if covers or within(path, protect) or within(protect, path):
            found.append(reason("protected", f"{ctx.display(path)} overlaps the protected path {protect}"))
    return found


def outside_reasons(ctx: Context, snap: Snapshot, path: str, measure: Measure) -> Reasons:
    if measure.is_symlink:
        return [reason("outside", f"{ctx.display(path)} is a symbolic link")]
    if not any(inside(real(path), root) for root in snap.real_roots):
        return [reason("outside", f"{ctx.display(path)} resolves outside the known data roots")]
    return []


def recent_reasons(ctx: Context, snap: Snapshot, path: str, measure: Measure) -> Reasons:
    limit_ns = int((snap.now.timestamp() - ctx.recent_hours * HOUR_SECONDS) * NS_PER_SECOND)
    if measure.newest_ns >= limit_ns:
        return [reason("recent", f"something under {ctx.display(path)} changed within the last {ctx.recent_hours:g} hours")]
    return []


def link_reasons(ctx: Context, snap: Snapshot, path: str) -> Reasons:
    path_real = real(path)
    for target in snap.link_targets:
        if within(path_real, target) or within(target, path_real):
            return [reason("link", f"{ctx.display(path)} holds or is a link target in use: {ctx.display(target)}")]
    return []


def owner_reasons(ctx: Context, snap: Snapshot, path: str) -> Reasons:
    if snap.processes is None:
        return [reason("owner", f"unknown: the process list is unavailable ({snap.process_error})")]
    pid = snap.named.get(real(path)) or snap.named.get(path)
    if pid:
        return [reason("owner", f"process {pid} names {ctx.display(path)} in its arguments")]
    return []


def open_reasons(ctx: Context, snap: Snapshot, path: str) -> Reasons:
    if snap.open_paths is None:
        return [reason("open", f"unknown: open files cannot be listed ({snap.open_error})")]
    if real(path) in snap.open_paths or path in snap.open_paths:
        return [reason("open", f"a process holds a file or its working folder open under {ctx.display(path)}")]
    return []


def git_reasons(ctx: Context, git: GitProbe, path: str, measure: Measure) -> Reasons:
    worktrees = list(measure.worktrees)
    outer = enclosing_worktree(path)
    if not worktrees and outer is None:
        return []
    if not git.available:
        return [reason("git", f"unknown: git is not available to inspect the work tree near {ctx.display(path)}")]
    found: Reasons = []
    for tree in worktrees:
        problem = git.status(tree)
        if problem:
            found.append(reason("git", f"work tree {ctx.display(tree)}: {problem}"))
    if outer is not None:
        problem = git.status(os.path.dirname(path), os.path.basename(path))
        if problem:
            found.append(reason("git", f"{ctx.display(path)} inside a Git work tree: {problem}"))
    return found


def path_reasons(ctx: Context, snap: Snapshot, git: GitProbe, path: str, measure: Measure, prior: bool) -> Reasons:
    if not measure.present:
        return [reason("unreadable", f"{ctx.display(path)} cannot be read: {measure.error}")]
    found = outside_reasons(ctx, snap, path, measure)
    if measure.unreadable:
        found.append(reason("unreadable", f"a folder under {ctx.display(path)} cannot be listed: {measure.unreadable[0]}"))
    found += recent_reasons(ctx, snap, path, measure)
    found += link_reasons(ctx, snap, path)
    found += owner_reasons(ctx, snap, path)
    found += open_reasons(ctx, snap, path)
    if not (prior or found):
        found += git_reasons(ctx, git, path, measure)
    return found


def unique(items: Reasons) -> tuple[dict[str, str], ...]:
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for item in items:
        seen.setdefault((item["check"], item["detail"]), item)
    return tuple(seen.values())


def evaluate(
    ctx: Context, snap: Snapshot, git: GitProbe, member: Member, measures: tuple[Measure, ...]
) -> Evaluation:
    protected: Reasons = []
    for path, measured in zip(member.paths, measures):
        protected += protected_reasons(ctx, snap, path, measured)
    if protected:
        return Evaluation(member, measures, "protected", unique(protected))
    found: Reasons = list(member.reasons)
    if member.full_checks:
        for path, measured in zip(member.paths, measures):
            found += path_reasons(ctx, snap, git, path, measured, bool(found))
    reasons = unique(found)
    return Evaluation(member, measures, "report-only" if reasons else "candidate", reasons)
