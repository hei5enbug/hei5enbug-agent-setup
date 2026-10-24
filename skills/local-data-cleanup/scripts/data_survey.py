"""Survey: discover members, evaluate them, and assemble the reported items."""

from __future__ import annotations

from typing import Any

from data_checks import evaluate
from data_common import Context, iso_from_datetime, iso_from_ns
from data_git import GitProbe
from data_kinds import Only, claude_releases, codex_releases, codex_temp, plugin_versions, session_scratch
from data_measure import measure, total_size
from data_model import Evaluation, Member, consequence_of, decision_of, what_of
from data_records import claude_records, codex_records, other_entries
from data_system import Snapshot, take_snapshot

CLAUDE_KINDS = (claude_releases, plugin_versions, session_scratch)
CODEX_KINDS = (codex_releases, codex_temp)


def discover(ctx: Context, snap: Snapshot, only: Only = None) -> tuple[list[Member], list[dict]]:
    members: list[Member] = []
    notes: list[dict] = []
    if ctx.uses("claude"):
        for finder in CLAUDE_KINDS:
            members += finder(ctx, snap, only)
        found, extra = claude_records(ctx, snap, only)
        members, notes = members + found, notes + extra
    if ctx.uses("codex"):
        for finder in CODEX_KINDS:
            members += finder(ctx, snap, only)
        found, extra = codex_records(ctx, snap, only)
        members, notes = members + found, notes + extra
    return members + other_entries(ctx, snap, only), notes


def evaluate_member(ctx: Context, snap: Snapshot, git: GitProbe, member: Member) -> Evaluation:
    measures = member.measures or tuple(measure(path, member.shipped) for path in member.paths)
    return evaluate(ctx, snap, git, member, measures)


def item_of(ctx: Context, evaluations: list[Evaluation]) -> dict[str, Any]:
    first = evaluations[0].member
    paths = [path for found in evaluations for path in found.member.paths]
    measures = [item for found in evaluations for item in found.measures]
    verdict = evaluations[0].verdict
    return {
        "id": 0,
        "host": first.host,
        "kind": first.kind,
        "what": what_of(first.kind, first.host),
        "paths": paths,
        "display": ctx.display_group(paths),
        "size": total_size(measures),
        "newest_mtime": iso_from_ns(max(item.newest_ns for item in measures)),
        "identity": [list(item.identity) for item in measures],
        "verdict": verdict,
        "reasons": [dict(reason) for reason in evaluations[0].reasons] if len(evaluations) == 1 else [],
        "decision": decision_of(first.kind),
        "consequence": consequence_of(first.kind),
    }


def build_items(ctx: Context, evaluations: list[Evaluation]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Evaluation]] = {}
    singles: list[list[Evaluation]] = []
    for found in evaluations:
        member = found.member
        if found.verdict == "candidate" and member.group is not None:
            grouped.setdefault((member.kind, member.host, member.group), []).append(found)
        else:
            singles.append([found])
    return [item_of(ctx, batch) for batch in [*grouped.values(), *singles]]


def number_items(items: list[dict[str, Any]], min_size: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    kept = sorted((item for item in items if item["size"] >= min_size), key=lambda item: (-item["size"], item["display"]))
    left_out = [item for item in items if item["size"] < min_size]
    numbered = [{**item, "id": index} for index, item in enumerate(kept, start=1)]
    return numbered, {"count": len(left_out), "size": sum(item["size"] for item in left_out)}


def run_survey(ctx: Context) -> dict[str, Any]:
    snap = take_snapshot(ctx)
    git = GitProbe()
    members, notes = discover(ctx, snap)
    evaluations = [evaluate_member(ctx, snap, git, member) for member in members]
    items, omitted = number_items(build_items(ctx, evaluations), ctx.min_size)
    return {
        "command": "survey",
        "generated_at": iso_from_datetime(snap.now),
        "config": ctx.to_config(),
        "roots": ctx.root_records(),
        "items": items,
        "notes": notes,
        "omitted": omitted,
    }
