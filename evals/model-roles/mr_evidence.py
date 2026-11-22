"""Read a Claude run's own host record: the model and effort of every answer, its list-price cost, and its wall time."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

E2E_ROOT = Path(__file__).resolve().parents[1] / "e2e"
sys.path.insert(0, str(E2E_ROOT))

from harness import pricing, usage  # noqa: E402

SYNTHETIC_MODEL = "<synthetic>"
STATUS_FIELDS = ("session", "model", "effort")


class EvidenceError(RuntimeError):
    """The host record is missing or does not show a verified run."""


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def transcript_for(session: str, home: Path | None = None) -> Path:
    if not session or "/" in session:
        raise EvidenceError(f"unusable session id {session!r}")
    projects = (home or claude_home()) / "projects"
    found = sorted(projects.glob(f"*/{session}.jsonl")) if projects.is_dir() else []
    if not found:
        raise EvidenceError(f"no transcript for session {session} under {projects}")
    return found[-1]


def events_of(path: Path) -> list[dict[str, Any]]:
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def real_assistants(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event for event in events
        if event.get("type") == "assistant" and isinstance(event.get("message"), dict)
        and event["message"].get("model") != SYNTHETIC_MODEL
    ]


def seconds_between(events: list[dict[str, Any]]) -> float:
    stamps = [
        datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        for event in events if isinstance(event.get("timestamp"), str)
    ]
    return round((max(stamps) - min(stamps)).total_seconds(), 3) if stamps else 0.0


def run_evidence(session: str, home: Path | None = None) -> dict[str, Any]:
    """Return host_model, host_effort, cost_usd, wall_seconds, and the answer count of one Claude session."""
    events = events_of(transcript_for(session, home))
    assistants = real_assistants(events)
    if not assistants:
        raise EvidenceError(f"session {session} holds no answer from a real model")
    requests = usage.claude_requests(events)
    costs = [pricing.claude_cost(request["model"], request) for request in requests]
    if any(cost is None for cost in costs):
        raise EvidenceError(f"a model of session {session} has no listed price")
    models = sorted({event["message"]["model"] for event in assistants})
    efforts = sorted({str(event.get("effort")) for event in assistants})
    return {
        "session": session, "host_model": "|".join(models), "host_effort": "|".join(efforts),
        "cost_usd": round(sum(costs), 6), "wall_seconds": seconds_between(events), "answers": len(assistants),
    }


def status_session(status_line: str) -> dict[str, str]:
    """Read the session of a verified role runner status line: its last JSON line must show exit 0 and verified."""
    lines = [line for line in status_line.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise EvidenceError("no role runner status line")
    status = json.loads(lines[-1])
    if status.get("exit") != 0 or status.get("verified") is not True or status.get("runner") != "claude":
        raise EvidenceError("the status line shows no verified Claude run with exit 0")
    session = (status.get("evidence") or {}).get("session")
    if not isinstance(session, str):
        raise EvidenceError("the status line names no session")
    return {"session": session, "model": str(status.get("model")), "effort": str(status.get("effort"))}
