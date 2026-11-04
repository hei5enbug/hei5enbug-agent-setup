"""Scan the commits and tags a `git push` command sends, starting from the refs the command names."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import boundary_git

if TYPE_CHECKING:
    from boundary_shell import Target

UNRESOLVED = re.compile(r"[$`]")
TAG_KEYWORD = "tag"
BRANCH_FLAGS = ("--all", "--branches")


@dataclass(frozen=True)
class PushContext:
    """What a push scan needs beyond the command: where it goes, how to expand a word, and which repositories are protected."""

    destination: str | None
    expand: Callable[[str], str]
    is_protected: Callable[[str], bool]


def _refspecs(target: Target) -> list[str]:
    specs: list[str] = []
    words = list(target.positionals[1:])
    while words:
        word = words.pop(0)
        if word == TAG_KEYWORD and words:
            specs.append(f"refs/tags/{words.pop(0)}")
        else:
            specs.append(word)
    return specs


def _resolve(top: Path, source: str) -> str | None:
    if source.startswith("-"):
        return None
    return boundary_git.try_git(top, "rev-parse", "--verify", "-q", f"{source}^{{commit}}")


def pushed_revisions(target: Target, top: Path, expand: Callable[[str], str]) -> list[str]:
    """The `git rev-list` starting points for everything the push sends.

    A push that names no ref can send several branches, since push.default and remote.<name>.push decide, and a ref
    that does not exist yet may be created by the same command; both take HEAD's and every local branch's commits.
    """
    if target.has_option("-d", "--delete"):
        return []
    revisions: list[str] = []
    if target.has_option(*BRANCH_FLAGS):
        revisions.append("--branches")
    if target.has_option("--mirror"):
        revisions.append("--all")
    if target.has_option("--tags"):
        revisions.append("--tags")
    specs = _refspecs(target)
    missing = False
    for spec in specs:
        text = expand(spec).removeprefix("+")
        if UNRESOLVED.search(text):
            raise boundary_git.CheckError(f"the ref {spec} the push sends holds a variable that cannot be resolved")
        source = text.split(":", 1)[0]
        if not source:
            continue
        resolved = f"--glob={source}" if "*" in source else _resolve(top, source)
        missing = missing or resolved is None
        revisions.extend([resolved] if resolved else [])
    implicit = not specs and not target.has_option(*BRANCH_FLAGS, "--mirror", "--tags")
    spread = missing or implicit or (not specs and target.has_option("--follow-tags"))
    if spread and boundary_git.has_head(top):
        revisions.append("HEAD")
    if spread:
        revisions.append("--branches")
    return revisions


def already_pushed(where: Path | str, context: PushContext, target: Target) -> list[str]:
    """Revision arguments that leave out the remote-tracking refs of a configured destination remote that is protected."""
    name = context.destination
    config = target.git_config
    if not name or name not in boundary_git.git_lines(where, "remote", config=config):
        return []
    urls = [
        *boundary_git.git_lines(where, "remote", "get-url", "--all", "--push", name, config=config),
        *boundary_git.git_lines(where, "remote", "get-url", "--all", name, config=config),
    ]
    return ["--not", f"--remotes={name}"] if any(context.is_protected(url) for url in urls) else []


def push_findings(target: Target, top: Path, where: Path | str, words, context: PushContext) -> list[str]:
    findings: list[str] = []
    revisions = pushed_revisions(target, top, context.expand)
    if revisions:
        findings.extend(boundary_git.range_findings(top, revisions + already_pushed(where, context, target), words))
    tags = boundary_git.local_tags(top)
    if target.has_option("--tags", "--follow-tags"):
        names = list(tags)
    else:
        names = [re.sub(r"^\+|:.*$", "", spec).removeprefix("refs/tags/") for spec in _refspecs(target)]
    for name in dict.fromkeys(names):
        if name in tags:
            findings.extend(boundary_git.tag_findings(top, name, tags[name], words))
    return findings
