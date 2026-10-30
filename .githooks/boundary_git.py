"""Scan what a commit, push, or tag would publish, reading it from Git."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from public_boundary import _decode_text, read_blobs, scan_identity, scan_text

Words = tuple[re.Pattern[str], ...]
ZERO_SHA = re.compile(r"^0+$")
SKIPPED_MODES = ("120000", "160000")


class CheckError(Exception):
    """A scan could not run to completion."""


def git(cwd: Path | str, *args: str, config: tuple[str, ...] = (), stdin: bytes | None = None) -> bytes:
    command = ["git", *(part for pair in config for part in ("-c", pair)), *args]
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, input=stdin)
    except OSError as error:
        raise CheckError(f"git {args[0]} could not start: {error.strerror}") from error
    if done.returncode != 0:
        raise CheckError(f"git {args[0]} failed")
    return done.stdout


def try_git(cwd: Path | str, *args: str) -> str | None:
    try:
        return git(cwd, *args).decode("utf-8", "replace").strip()
    except CheckError:
        return None


def toplevel(cwd: Path | str) -> Path | None:
    top = try_git(cwd, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def _paths(raw: bytes) -> list[str]:
    return [item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]


def _scan_blobs(blobs: dict[str, bytes], words: Words) -> list[str]:
    findings = []
    for name, data in blobs.items():
        text = _decode_text(data)
        if text is not None:
            findings.extend(scan_text(name, text, words=words))
    return findings


def staged_findings(top: Path, words: Words) -> list[str]:
    changed = set(_paths(git(top, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")))
    entries: dict[str, str] = {}
    for record in git(top, "ls-files", "-s", "-z", "--full-name").split(b"\0"):
        meta, _, raw_path = record.partition(b"\t")
        name = raw_path.decode("utf-8", "surrogateescape")
        if record and name in changed and meta.split()[0].decode() not in SKIPPED_MODES:
            entries[name] = meta.split()[1].decode()
    return _scan_blobs(read_blobs(top, entries), words)


def worktree_findings(top: Path, words: Words) -> list[str]:
    findings = []
    for name in _paths(git(top, "diff", "--name-only", "--diff-filter=ACMR", "-z")):
        path = top / name
        if path.is_file() and not path.is_symlink():
            text = _decode_text(path.read_bytes())
            if text is not None:
                findings.extend(scan_text(name, text, words=words))
    return findings


def identity_findings(cwd: Path | str, words: Words, config: tuple[str, ...] = (), author: bool = True) -> list[str]:
    roles = (("author", "GIT_AUTHOR_IDENT"), ("committer", "GIT_COMMITTER_IDENT"))
    findings = []
    for label, variable in roles if author else roles[1:]:
        ident = git(cwd, "var", variable, config=config).decode("utf-8", "replace")
        findings.extend(scan_identity(f"{label} identity", ident, words))
    return findings


def message_findings(label: str, text: str, words: Words) -> list[str]:
    return scan_text(label, text, words=words)


def _split_object(data: bytes) -> tuple[dict[str, str], str]:
    header, _, body = data.decode("utf-8", "replace").partition("\n\n")
    fields = {}
    for line in header.splitlines():
        key, _, value = line.partition(" ")
        fields.setdefault(key, value)
    return fields, body


def tag_findings(top: Path, name: str, sha: str, words: Words) -> list[str]:
    fields, body = _split_object(git(top, "cat-file", "tag", sha))
    return scan_identity(f"tag {name} tagger", fields.get("tagger", ""), words) + message_findings(
        f"tag {name} message", body, words
    )


def _commit_findings(top: Path, shas: list[str], words: Words) -> list[str]:
    findings = []
    for sha, data in read_blobs(top, {sha: sha for sha in shas}).items():
        fields, body = _split_object(data)
        label = f"commit {sha[:12]}"
        findings.extend(message_findings(f"{label} message", body, words))
        findings.extend(scan_identity(f"{label} author", fields.get("author", ""), words))
        findings.extend(scan_identity(f"{label} committer", fields.get("committer", ""), words))
    return findings


def _changed_paths(top: Path, shas: list[str]) -> set[str]:
    raw = git(
        top, "diff-tree", "--stdin", "--no-commit-id", "--name-only", "-r", "-z", "--root", "--diff-filter=ACMR",
        stdin=("\n".join(shas) + "\n").encode(),
    )
    return set(_paths(raw))


def _tip_blobs(top: Path, tip: str, paths: set[str]) -> dict[str, str]:
    entries = {}
    for record in git(top, "ls-tree", "-r", "-z", tip).split(b"\0"):
        meta, _, raw_path = record.partition(b"\t")
        name = raw_path.decode("utf-8", "surrogateescape")
        parts = meta.split()
        if record and name in paths and parts[0].decode() not in SKIPPED_MODES and parts[1] == b"blob":
            entries[name] = parts[2].decode()
    return entries


def range_findings(top: Path, rev_args: list[str], tip: str, words: Words) -> list[str]:
    shas = git(top, "rev-list", *rev_args).decode().split()
    if not shas:
        return []
    paths = _changed_paths(top, shas)
    blobs = read_blobs(top, _tip_blobs(top, tip, paths))
    return _commit_findings(top, shas, words) + _scan_blobs(blobs, words)


def local_tags(top: Path) -> dict[str, str]:
    raw = git(top, "for-each-ref", "--format=%(objecttype) %(objectname) %(refname)", "refs/tags").decode()
    tags = {}
    for line in raw.splitlines():
        kind, sha, ref = line.split(" ", 2)
        if kind == "tag":
            tags[ref.removeprefix("refs/tags/")] = sha
    return tags


def has_head(top: Path) -> bool:
    return try_git(top, "rev-parse", "-q", "--verify", "HEAD") is not None


def push_ref_findings(top: Path, line: str, words: Words) -> list[str]:
    parts = line.split()
    if len(parts) < 4 or ZERO_SHA.match(parts[1]):
        return []
    local_ref, local_sha, _remote_ref, remote_sha = parts[:4]
    findings = []
    if try_git(top, "cat-file", "-t", local_sha) == "tag":
        findings.extend(tag_findings(top, local_ref.removeprefix("refs/tags/"), local_sha, words))
    fresh = [local_sha, "--not", "--remotes"]
    if ZERO_SHA.match(remote_sha):
        return findings + range_findings(top, fresh, local_sha, words)
    try:
        return findings + range_findings(top, [f"{remote_sha}..{local_sha}"], local_sha, words)
    except CheckError:
        return findings + range_findings(top, fresh, local_sha, words)


def pre_push_findings(top: Path, stdin_text: str, words: Words) -> list[str]:
    findings = []
    for line in stdin_text.splitlines():
        findings.extend(push_ref_findings(top, line, words))
    return list(dict.fromkeys(findings))
