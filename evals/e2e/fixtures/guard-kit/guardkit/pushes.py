"""Find the refs that a `git push` command sends."""

from __future__ import annotations

import shlex

from .targets import SEPARATORS

VALUE_OPTIONS = {"-o", "--push-option", "--receive-pack", "--exec", "--repo"}


def pushed_refs(command: str) -> list[str]:
    refs: list[str] = []
    tokens = shlex.split(command)
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    for segment in segments:
        if segment[:2] != ["git", "push"]:
            continue
        positional: list[str] = []
        skip = False
        for token in segment[2:]:
            if skip:
                skip = False
            elif token in VALUE_OPTIONS:
                skip = True
            elif not token.startswith("-"):
                positional.append(token)
        refs.extend(positional[1:])
    return refs
