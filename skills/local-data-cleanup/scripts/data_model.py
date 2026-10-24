"""Members found by discovery and the evaluation of their checks."""

from __future__ import annotations

from dataclasses import dataclass

from data_common import RECORDS_CONSEQUENCE
from data_measure import Measure


@dataclass(frozen=True)
class Member:
    kind: str
    host: str
    paths: tuple[str, ...]
    reasons: tuple[dict[str, str], ...] = ()
    group: str | None = None
    full_checks: bool = True
    measures: tuple[Measure, ...] | None = None


@dataclass(frozen=True)
class Evaluation:
    member: Member
    measures: tuple[Measure, ...]
    verdict: str
    reasons: tuple[dict[str, str], ...]


KIND_WHAT = {
    "superseded-release": "Superseded {Host} release",
    "superseded-plugin-version": "Cached plugin version older than the installed one",
    "ended-session-scratch": "Scratch folder of an ended Claude Code session",
    "stale-temp-entries": "Stale Codex temporary entries",
    "old-session-records": "Old {Host} session records",
    "other": "Other entry in the {Host} data folder",
}


def what_of(kind: str, host: str) -> str:
    return KIND_WHAT[kind].format(Host="Claude Code" if host == "claude" else "Codex")


def decision_of(kind: str) -> str | None:
    return "user" if kind == "old-session-records" else None


def consequence_of(kind: str) -> str | None:
    return RECORDS_CONSEQUENCE if kind == "old-session-records" else None

