#!/usr/bin/env python3
"""Gather the suggest-commit context and make one scoped commit.

`context` prints the fast context pass as JSON. `commit` stages only the scope, makes one commit with the given
subject, and prints what it did as JSON. Exit codes: 0 done, 1 unexpected Git failure, 2 usage error, 3 stopped
before any write, 4 the commit was rejected and the staged changes stay.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_STOPPED, EXIT_REJECTED = 0, 1, 2, 3, 4
FORBIDDEN_ARGS = frozenset({"--no-verify", "-n", "--amend", "--allow-empty", "--signoff", "-s", "--trailer", "-a",
                            "--all", "-A", "--no-gpg-sign"})
LOG_LIMIT = 20
CONVENTION_LIMIT = 10
UNTRACKED_LIMIT = 50
CONVENTION_FILES = ("AGENTS.md", "CONTRIBUTING.md", ".github/CONTRIBUTING.md", "CLAUDE.md", ".gitmessage")
CONVENTION_PATTERN = re.compile(
    r"commit ?(message|convention|format)|conventional commits?|커밋 ?(메시지|규칙|컨벤션|형식)|^\s*[-*]?\s*커밋:|"
    r"(feat|fix|docs|chore|refactor|test)\(?[a-z]*\)?: *\[|"
    r"(\[[^]]+\]|#[0-9A-Za-z]+) *(feat|fix|docs|chore|refactor|test)\(?[a-z]*\)?:", re.IGNORECASE)
IN_PROGRESS_MARKERS = (("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"),
                       ("rebase-merge", "rebase"), ("rebase-apply", "rebase"))
CONFLICT_CODES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})
SECRET_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.secret", "id_rsa*",
                "id_ed25519*", "id_ecdsa*", "credentials*", "secrets.*", ".netrc")
SECRET_EXEMPT_SUFFIXES = (".example", ".sample", ".template", ".dist", ".pub")
TRAILER_IN_SUBJECT = re.compile(r"co-authored-by:|signed-off-by:|reviewed-by:|generated with", re.IGNORECASE)


class Stop(Exception):
    """The command ends before any write, with a machine-readable code."""

    def __init__(self, code: str, reason: str, exit_code: int = EXIT_STOPPED) -> None:
        super().__init__(reason)
        self.code, self.reason, self.exit_code = code, reason, exit_code


@dataclass(frozen=True)
class Entry:
    xy: str
    path: str

    @property
    def staged(self) -> bool:
        return self.xy[0] not in " ?!"

    @property
    def untracked(self) -> bool:
        return self.xy == "??"

    @property
    def unstaged_tracked(self) -> bool:
        return not self.untracked and self.xy[1] != " "


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    banned = FORBIDDEN_ARGS.intersection(args)
    if banned:
        raise ValueError(f"forbidden git argument: {sorted(banned)}")
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def git_out(repo: Path, *args: str) -> str:
    result = run_git(repo, *args)
    if result.returncode != 0:
        raise Stop("git_failed", f"git {args[0]} failed: {(result.stderr or result.stdout).strip()}", EXIT_ERROR)
    return result.stdout


def has_head(repo: Path) -> bool:
    return run_git(repo, "rev-parse", "--verify", "-q", "HEAD").returncode == 0


def status_entries(repo: Path, paths: Sequence[str] = (), untracked: str = "all") -> list[Entry]:
    tail = ["--", *paths] if paths else []
    raw = git_out(repo, "status", "--porcelain=v1", "-z", f"--untracked-files={untracked}", *tail)
    tokens, entries, index = raw.split("\0"), [], 0
    while index < len(tokens) and tokens[index]:
        xy, path = tokens[index][:2], tokens[index][3:]
        entries.append(Entry(xy, path))
        index += 2 if "R" in xy or "C" in xy else 1
    return entries


def in_progress(repo: Path) -> str | None:
    for marker, name in IN_PROGRESS_MARKERS:
        location = git_out(repo, "rev-parse", "--git-path", marker).strip()
        if (repo / location).exists():
            return name
    return None


def is_secret_like(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    if name.endswith(SECRET_EXEMPT_SUFFIXES):
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in SECRET_NAMES)


def under(path: str, roots: Sequence[str]) -> bool:
    return any(path == root.rstrip("/") or path.startswith(root.rstrip("/") + "/") for root in roots)


def lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line]


def convention_lines(repo: Path) -> list[str]:
    found: list[str] = []
    for name in CONVENTION_FILES:
        path = repo / name
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if CONVENTION_PATTERN.search(line):
                found.append(f"{name}:{number}:{line}")
    return found[:CONVENTION_LIMIT]


def diff_sections(repo: Path, staged_only: bool, head: bool, paths: Sequence[str]) -> tuple[str, list[str]]:
    tail = ["--", *paths] if paths else []
    if head and not staged_only:
        bases = [["HEAD"]]
    elif staged_only:
        bases = [["--cached"]]
    else:
        bases = [["--cached"], []]
    stat = "".join(git_out(repo, "diff", *base, "--stat", *tail) for base in bases)
    names = [line for base in bases for line in lines(git_out(repo, "diff", *base, "--name-status", *tail))]
    return stat, names


def build_context(repo: Path, staged_only: bool, paths: Sequence[str]) -> dict:
    head = has_head(repo)
    stat, names = diff_sections(repo, staged_only, head, paths)
    entries = status_entries(repo, untracked="normal")
    untracked = [entry.path for entry in entries if entry.untracked]
    log = lines(git_out(repo, "log", "--oneline", f"-{LOG_LIMIT}")) if head else []
    return {
        "scope": "paths" if paths else "staged" if staged_only else "default",
        "has_head": head,
        "in_progress": in_progress(repo),
        "conflicts": [entry.path for entry in entries if entry.xy in CONFLICT_CODES],
        "index_empty": not any(entry.staged for entry in entries),
        "status": lines(git_out(repo, "status", "--short")),
        "diff_stat": stat,
        "diff_name_status": names,
        "untracked": untracked[:UNTRACKED_LIMIT],
        "untracked_more": max(0, len(untracked) - UNTRACKED_LIMIT),
        "log": log,
        "convention": convention_lines(repo),
    }


def check_subject(subject: str) -> str:
    cleaned = subject.strip()
    if not cleaned or "\n" in cleaned or "\r" in cleaned:
        raise Stop("subject_invalid", "the subject must be one non-empty line", EXIT_USAGE)
    if TRAILER_IN_SUBJECT.search(cleaned):
        raise Stop("subject_invalid", "the subject must not carry a trailer", EXIT_USAGE)
    return cleaned


@dataclass(frozen=True)
class Plan:
    scope: str
    to_stage: tuple[str, ...]
    to_unstage: tuple[str, ...]
    commit_paths: tuple[str, ...]


def plan_commit(entries: Sequence[Entry], staged_only: bool, paths: Sequence[str], include: Sequence[str]) -> Plan:
    staged = [entry for entry in entries if entry.staged]
    if paths:
        outside = [entry.path for entry in staged if not under(entry.path, paths)]
        if outside:
            raise Stop("staged_outside_scope", f"the index holds staged changes outside the named paths: {outside}")
        scope = "staged-paths" if staged_only else "paths"
        chosen = [entry for entry in entries if under(entry.path, paths)]
        candidates = [entry for entry in chosen if entry.staged] if staged_only else chosen
    elif staged_only or staged:
        scope, candidates = "staged", staged
    else:
        scope = "default"
        candidates = [entry for entry in entries
                      if entry.unstaged_tracked or (entry.untracked and under(entry.path, include))]
    keep = [entry for entry in candidates if not is_secret_like(entry.path)]
    staging = scope in ("paths", "default")
    to_stage = tuple(entry.path for entry in keep if staging and (entry.untracked or entry.unstaged_tracked))
    to_unstage = tuple(entry.path for entry in candidates if entry.staged and is_secret_like(entry.path))
    return Plan(scope, to_stage, to_unstage, tuple(entry.path for entry in keep))


def stage_and_commit(repo: Path, plan: Plan, subject: str) -> subprocess.CompletedProcess[str]:
    head = has_head(repo)
    if plan.to_unstage:
        unstage = ["reset", "-q", "--", *plan.to_unstage] if head else ["rm", "--cached", "-q", "--", *plan.to_unstage]
        git_out(repo, *unstage)
    if plan.to_stage:
        git_out(repo, "add", "--", *plan.to_stage)
    return run_git(repo, "commit", "-m", subject)


def build_report(repo: Path, subject: str) -> dict:
    message = git_out(repo, "log", "-1", "--format=%B").strip()
    committed = lines(git_out(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD"))
    remaining = [entry.path for entry in status_entries(repo)]
    return {
        "status": "committed",
        "hash": git_out(repo, "rev-parse", "--short", "HEAD").strip(),
        "subject": subject,
        "file_count": len(committed),
        "files_left_out": [path for path in remaining if is_secret_like(path)],
        "files_outside_scope": [path for path in remaining if not is_secret_like(path)],
        "message_has_extra_lines": message != subject,
    }


def run_commit(repo: Path, subject: str, staged_only: bool, paths: Sequence[str], include: Sequence[str]) -> dict:
    subject = check_subject(subject)
    state = in_progress(repo)
    if state:
        raise Stop("in_progress", f"a {state} is in progress")
    entries = status_entries(repo)
    conflicts = [entry.path for entry in entries if entry.xy in CONFLICT_CODES]
    if conflicts:
        raise Stop("conflicts", f"unresolved conflicts: {conflicts}")
    plan = plan_commit(entries, staged_only, paths, include)
    if not plan.commit_paths:
        raise Stop("no_changes", "the scope has no changes to commit")
    result = stage_and_commit(repo, plan, subject)
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise Stop("rejected", f"git commit failed, staged changes stay in place: {output}", EXIT_REJECTED)
    return {**build_report(repo, subject), "scope": plan.scope}


def locate(start: Path) -> tuple[Path, str]:
    inside = run_git(start, "rev-parse", "--show-toplevel", "--show-prefix")
    if inside.returncode != 0:
        raise Stop("not_a_repository", f"{start} is not a Git worktree", EXIT_USAGE)
    top, _, prefix = inside.stdout.partition("\n")
    return Path(top), prefix.strip()


def root_relative(prefix: str, path: str) -> str:
    return PurePosixPath(os.path.normpath(PurePosixPath(prefix) / path)).as_posix()


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="repository folder (default: current folder)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("context", "commit"):
        sub = commands.add_parser(name)
        sub.add_argument("--staged-only", action="store_true", help="the scope is the staged changes only")
        sub.add_argument("--path", action="append", default=[], help="a named path of the scope; repeatable")
    commands.choices["commit"].add_argument("--subject", required=True)
    commands.choices["commit"].add_argument("--include", action="append", default=[],
                                            help="an untracked file or folder that belongs to the change; repeatable")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    start = Path(args.repo).resolve()
    try:
        repo, prefix = locate(start)
        paths = [root_relative(prefix, path) for path in args.path]
        if args.command == "context":
            payload = build_context(repo, args.staged_only, paths)
        else:
            include = [root_relative(prefix, path) for path in args.include]
            payload = run_commit(repo, args.subject, args.staged_only, paths, include)
        exit_code = EXIT_OK
    except Stop as stop:
        payload, exit_code = {"status": "stopped", "code": stop.code, "reason": stop.reason}, stop.exit_code
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
