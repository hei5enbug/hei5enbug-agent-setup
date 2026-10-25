"""Records shown on the dashboard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Service:
    name: str
    healthy: bool
    latency_ms: int
