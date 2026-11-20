"""The language role of the GPT role comparison runs on the existing Korean writing evaluation: tasks t1, t3, and t5, one run
per candidate writer, graded by one Claude grader (no Astra grader). A draft passes a task when the grader reports no missing and
no added fact in it."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import gr_core

KW_RUN = gr_core.REPO_ROOT / "evals" / "korean-writing" / "kw_run.py"
GRADER = "claude:claude-opus-5-5"
TASKS = ("t1", "t3", "t5")
ROLE = "language"
EFFORT = "high"


def kw_argv(out: Path, writers: tuple[str, ...], tasks: tuple[str, ...] = TASKS, runs: int = 1) -> list[str]:
    argv = [sys.executable, str(KW_RUN), "run", "--out", str(out), "--grader", GRADER, "--tasks", ",".join(tasks), "--runs", str(runs),
            "--parallel", "1", "--max-hours", "3"]
    for writer in writers:
        argv += ["--writer", f"codex:{writer}"]
    return argv


def read_all(folder: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def results(kw_out: Path) -> list[dict[str, Any]]:
    """One result per finished draft: pass from the grader's missing and added facts, cost from the draft's token usage."""
    drafts = [item for item in read_all(kw_out / "drafts") if item.get("ok")]
    grades = [item for item in read_all(kw_out / "grades") if "grade" in item]
    out = []
    for draft in drafts:
        grade = next((item for item in grades if item["task"] == draft["task"] and item["run"] == draft["run"]), None)
        if grade is None:
            continue
        label = next((key for key, writer in grade["key"].items() if writer == draft["writer"]), None)
        entry = grade["grade"]["drafts"].get(label) if label else None
        if entry is None:
            continue
        ranking = grade["grade"].get("ranking") or []
        failures = [f"missing fact {item}" for item in entry["missing_facts"]] + [f"added fact {item}" for item in entry["added_facts"]]
        out.append({
            "role": ROLE, "case": draft["task"], "model": draft["writer"], "effort": EFFORT, "rep": draft["run"], "passed": not failures,
            "failures": failures, "cost_usd": gr_core.usage_cost(draft["writer"], draft.get("usage") or {}),
            "wall_seconds": round(float(draft["secs"]), 3), "rollout": "", "rank": ranking.index(label) + 1 if label in ranking else None,
            "unnatural": len(entry["unnatural"]),
        })
    return out


def unit_cost(kw_out: Path) -> float:
    """Writer cost at list price plus the grader's reported cost, for every call the folder holds."""
    total = sum(gr_core.usage_cost(item["writer"], item.get("usage") or {}) for item in read_all(kw_out / "drafts") if item.get("ok"))
    return round(total + sum(float((item.get("res") or {}).get("cost") or 0) for item in read_all(kw_out / "grades")), 6)
