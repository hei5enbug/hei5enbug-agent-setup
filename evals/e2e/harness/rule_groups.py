"""Rule groups of the always-loaded session instructions: every bullet and paragraph of the four session files, with its
bytes, the hosts that load it, and the `remove` entry that cuts it out of an exported plugin.

The group list is information for choosing removal candidates; it chooses none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from . import markdown_parts as mp

SESSION_FILES = (
    "instructions/session/core.md", "instructions/session/common.md",
    "instructions/session/claude-code.md", "instructions/session/codex.md",
)
HOSTS_OF = {
    "instructions/session/core.md": ("claude", "codex"), "instructions/session/common.md": ("claude", "codex"),
    "instructions/session/claude-code.md": ("claude",), "instructions/session/codex.md": ("codex",),
}
WORKER_FILES = ("instructions/session/core.md",)
MIN_START_WORDS = 3
SLUG_WORDS = 5
SLUG_NON_WORD = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Group:
    file: str
    kind: str
    start: str
    size: int

    @property
    def hosts(self) -> tuple[str, ...]:
        return HOSTS_OF[self.file]

    @property
    def in_worker_context(self) -> bool:
        return self.file in WORKER_FILES

    @property
    def slug(self) -> str:
        words = SLUG_NON_WORD.sub(" ", self.start.lower()).split()
        return "-".join([Path(self.file).stem, *words[:SLUG_WORDS]])

    @property
    def removal(self) -> dict[str, str]:
        """The `remove` entry of a variant that cuts this group out."""
        return {"file": self.file, "start": self.start}


def canonical_starts(parts: Sequence[mp.Part]) -> dict[int, str]:
    """For each bullet and paragraph (by line index) the shortest first words, at least three, that no other one of the file
    shares, so the `remove` entry built from it matches exactly one part."""
    chosen: dict[int, str] = {}
    body = mp.units(parts)
    for part in body:
        words = part.text.split()
        for count in range(min(MIN_START_WORDS, len(words)), len(words) + 1):
            prefix = " ".join(words[:count])
            if sum(1 for other in body if mp.starts_with(other, prefix)) == 1:
                chosen[part.first] = prefix
                break
        else:
            chosen[part.first] = part.text
    return chosen


def list_groups(texts: Mapping[str, str]) -> list[Group]:
    """Every bullet and paragraph of the session files present in `texts`, in file order."""
    groups: list[Group] = []
    for name in SESSION_FILES:
        if name not in texts:
            continue
        parts = mp.parse_parts(texts[name])
        starts = canonical_starts(parts)
        groups += [Group(name, part.kind, starts[part.first], part.size) for part in mp.units(parts)]
    return groups


def read_texts(root: Path) -> dict[str, str]:
    """The session files of a working tree; a missing file is left out."""
    return {name: (root / name).read_text(encoding="utf-8") for name in SESSION_FILES if (root / name).is_file()}


def host_totals(groups: Sequence[Group]) -> dict[str, int]:
    """Bytes of the groups each host's main session loads, and the bytes an implementation worker's core context loads."""
    totals = {host: sum(group.size for group in groups if host in group.hosts) for host in ("claude", "codex")}
    return {**totals, "worker": sum(group.size for group in groups if group.in_worker_context)}
