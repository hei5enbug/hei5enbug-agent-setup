"""Aggregate graded task-runs into the per-candidate table and apply the decision rule."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

MIN_RUNS_PER_SIDE = 5


def load_grades(out: Path) -> list:
    rows = []
    for path in sorted((out / "grades").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if "grade" in record:
            rows.append(record)
    return rows


def load_drafts(out: Path) -> list:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((out / "drafts").glob("*.json"))]


def graded_counts(rows: list, graders: list) -> dict:
    return {grader: sum(1 for row in rows if row["grader"] == grader) for grader in graders}


def per_grader_counts(rows: list, graders: list) -> dict:
    stats = {grader: {name: Counter() for name in ("first", "first_all", "missing", "added", "unnatural", "drafts")}
             for grader in graders}
    for row in rows:
        mine, key, grade = stats[row["grader"]], row["key"], row["grade"]
        for label, entry in grade["drafts"].items():
            writer = key[label]
            mine["drafts"][writer] += 1
            mine["missing"][writer] += bool(entry["missing_facts"])
            mine["added"][writer] += bool(entry["added_facts"])
            mine["unnatural"][writer] += len(entry["unnatural"])
        for name, field in (("first", "ranking"), ("first_all", "ranking_all")):
            if grade.get(field):
                mine[name][key[grade[field][0]]] += 1
    return stats


def writer_stats(drafts: list, writers: list) -> dict:
    stats = {writer: {"ok": 0, "failed": 0, "secs": [], "cost": [], "output_tokens": []} for writer in writers}
    for record in drafts:
        mine = stats.setdefault(record["writer"], {"ok": 0, "failed": 0, "secs": [], "cost": [], "output_tokens": []})
        if not record["ok"]:
            mine["failed"] += 1
            continue
        mine["ok"] += 1
        mine["secs"].append(record["secs"])
        if record.get("cost") is not None:
            mine["cost"].append(record["cost"])
        mine["output_tokens"].append((record.get("usage") or {}).get("output_tokens", 0))
    return stats


def first_place_agreement(rows: list, graders: list) -> tuple:
    by_run = {}
    for row in rows:
        ranking = row["grade"].get("ranking") or []
        by_run.setdefault((row["task"], row["run"]), {})[row["grader"]] = row["key"][ranking[0]] if ranking else None
    both = [picks for picks in by_run.values() if all(grader in picks for grader in graders)]
    agreed = sum(1 for picks in both if len({picks[grader] for grader in graders}) == 1)
    return agreed, len(both)


def decide(stats: dict, graded: dict, writers: list, complete: bool = True) -> dict:
    """A candidate wins only when graders of both families graded every task-run, every grader ranks it first on more
    than half of its graded task-runs, and no grader reports a missing or added fact in any of its drafts."""
    if not complete:
        return {"verdict": "inconclusive", "winner": None}
    winners = []
    for writer in writers:
        majority = all(graded[grader] and stats[grader]["first"][writer] * 2 > graded[grader] for grader in stats)
        fact_clean = all(stats[grader]["missing"][writer] == 0 and stats[grader]["added"][writer] == 0 for grader in stats)
        if majority and fact_clean:
            winners.append(writer)
    if len(winners) == 1:
        return {"verdict": "winner", "winner": winners[0]}
    return {"verdict": "inconclusive", "winner": None}


def summarize(out: Path) -> dict:
    rows, drafts = load_grades(out), load_drafts(out)
    graders = sorted({row["grader"] for row in rows})
    writers = sorted({record["writer"] for record in drafts})
    stats = per_grader_counts(rows, graders)
    graded = graded_counts(rows, graders)
    writing = writer_stats(drafts, writers)
    agreed, both = first_place_agreement(rows, graders)
    runs_per_side = min((writing[w]["ok"] for w in writers), default=0)
    hosts = {str(row.get("spec", "")).partition(":")[0] for row in rows}
    task_runs = len({(row["task"], row["run"]) for row in rows})
    complete = {"codex", "claude"} <= hosts and all(graded[g] == task_runs for g in graders)
    return {"graders": graders, "writers": writers, "stats": stats, "graded": graded, "writing": writing,
            "agreement": [agreed, both], "decision": decide(stats, graded, writers, complete),
            "unconfirmed": runs_per_side < MIN_RUNS_PER_SIDE}


def format_report(summary: dict) -> str:
    graders, stats, writing = summary["graders"], summary["stats"], summary["writing"]
    header = ["candidate", "drafts"]
    for title in ("1st", "missing fact", "added fact", "unnatural"):
        header += [f"{title} [{grader}]" for grader in graders]
    header += ["median s", "cost usd"]
    lines = ["\t".join(header)]
    for writer in summary["writers"]:
        w = writing[writer]
        cells = [writer, str(w["ok"])]
        cells += [str(stats[g]["first"][writer]) for g in graders]
        cells += [f"{stats[g]['missing'][writer]}/{stats[g]['drafts'][writer]}" for g in graders]
        cells += [f"{stats[g]['added'][writer]}/{stats[g]['drafts'][writer]}" for g in graders]
        cells += [str(stats[g]["unnatural"][writer]) for g in graders]
        cells += [str(round(statistics.median(w["secs"]))) if w["secs"] else "-",
                  str(round(sum(w["cost"]), 3)) if w["cost"] else "n/a"]
        lines.append("\t".join(cells))
    agreed, both = summary["agreement"]
    lines.append(f"graded task-runs per grader: {summary['graded']}")
    lines.append(f"graders agree on first place: {agreed} of {both}")
    if summary["unconfirmed"]:
        lines.append(f"unconfirmed: fewer than {MIN_RUNS_PER_SIDE} drafts per candidate")
    decision = summary["decision"]
    lines.append("verdict: " + (f"winner {decision['winner']}" if decision["winner"]
                                else "inconclusive, the current language and review models stay"))
    return "\n".join(lines)
