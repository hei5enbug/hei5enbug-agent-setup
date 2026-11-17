from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str = ""


ALLOW = Decision("allow")
