"""Find the refs that a `git push` command sends."""

from __future__ import annotations

import re
import shlex

from .targets import SEPARATORS

VALUE_OPTIONS = {"-o", "--push-option", "--receive-pack", "--exec", "--repo"}
REDIRECT = re.compile(r"^(\d*|&)?>>?")
BARE_REDIRECT = re.compile(r"^(\d*|&)?>>?$")


def push_arguments(segment: list[str]) -> list[str] | None:
    if not segment or segment[0] != "git":
        return None
    index = 1
    while index + 1 < len(segment) and segment[index] in ("-C", "-c"):
        index += 2
    if index >= len(segment) or segment[index] != "push":
        return None
    return segment[index + 1:]


def segment_refs(arguments: list[str], push_default: str, remote_push_config: bool) -> list[str]:
    positional: list[str] = []
    everything = tags = False
    skip = False
    for token in arguments:
        if skip:
            skip = False
        elif REDIRECT.match(token):
            skip = bool(BARE_REDIRECT.match(token))
        elif token in VALUE_OPTIONS:
            skip = True
        elif token in ("--all", "--mirror"):
            everything = True
        elif token == "--tags":
            tags = True
        elif not token.startswith("-"):
            positional.append(token)
    named = positional[1:]
    refs: list[str] = []
    for item in named:
        source = item.lstrip("+").split(":", 1)[0] if ":" in item else item.lstrip("+")
        if source:
            refs.append(source)
    if everything:
        refs.append("*")
    if tags:
        refs.append("refs/tags/*")
    if not named and not everything and not tags:
        refs.append("*" if push_default == "matching" or remote_push_config else "HEAD")
    return refs


def pushed_refs(command: str, push_default: str = "simple", remote_push_config: bool = False) -> list[str]:
    segments: list[list[str]] = [[]]
    for token in shlex.split(command):
        if token in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    refs: list[str] = []
    for segment in segments:
        arguments = push_arguments(segment)
        if arguments is None:
            continue
        for ref in segment_refs(arguments, push_default, remote_push_config):
            if ref not in refs:
                refs.append(ref)
    return refs
