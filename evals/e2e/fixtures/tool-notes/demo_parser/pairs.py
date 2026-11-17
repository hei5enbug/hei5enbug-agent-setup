"""Split settings lines into keys and values."""

from __future__ import annotations


def parse_pair(line: str) -> tuple[str, str]:
    key, value = line.split("=", 1)
    return key.strip(), value.strip()


def parse_lines(lines: list[str]) -> dict[str, str]:
    return dict(parse_pair(line) for line in lines)
