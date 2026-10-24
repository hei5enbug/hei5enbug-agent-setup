"""Delete: re-check the selected items, remove their members, and verify what must stay unchanged."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from typing import Any

from data_common import Context, InputError, reason, real, reason_of, within
from data_git import GitProbe
from data_measure import is_protected_name, is_sidecar, measure, total_size
from data_survey import discover, evaluate_member
from data_system import Snapshot, take_snapshot

SCAN_DEPTH = 2


class RemovalError(Exception):
    """A member cannot be removed safely."""


@dataclass(frozen=True)
class Baseline:
    links: dict[str, str]
    protected: tuple[str, ...]


def parse_selection(values: list[str]) -> list[int]:
    chosen: list[int] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                raise InputError(f"invalid item number {part!r}")
            if int(part) not in chosen:
                chosen.append(int(part))
    return chosen


def select_items(plan: dict[str, Any], chosen: list[int]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in plan["items"]}
    refused = [
        f"{number} ({by_id[number]['verdict']})" if number in by_id else f"{number} (unknown)" for number in chosen
        if number not in by_id or by_id[number]["verdict"] != "offer"
    ]
    if refused:
        raise InputError("nothing was deleted; these ids are not offered: " + ", ".join(refused))
    return [by_id[number] for number in chosen]


def scan_protected(base: str, depth: int = SCAN_DEPTH) -> list[str]:
    found: list[str] = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return found
    for name in names:
        path = os.path.join(base, name)
        if is_protected_name(name) and not is_sidecar(name):
            found.append(path)
        elif depth > 1 and os.path.isdir(path) and not os.path.islink(path):
            found += scan_protected(path, depth - 1)
    return found


def take_baseline(ctx: Context, snap: Snapshot, plan: dict[str, Any]) -> Baseline:
    protected = list(ctx.protect)
    for item in plan["items"]:
        if item["verdict"] == "protected":
            protected += item["paths"]
    for base in (ctx.claude_dir, ctx.codex_dir):
        protected += scan_protected(base) if os.path.isdir(base) else []
    for entries in snap.installed.plugins.values():
        protected += [entry["installPath"] for entry in entries]
    existing = [path for path in dict.fromkeys(protected) if os.path.lexists(path) and not is_sidecar(path)]
    return Baseline({info.link: info.target for info in snap.links}, tuple(existing))


def recheck(ctx: Context, snap: Snapshot, git: GitProbe, item: dict[str, Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for path, identity in zip(item["paths"], item["identity"]):
        try:
            info = os.lstat(path)
        except OSError:
            found.append(reason("identity", f"{ctx.display(path)} no longer exists"))
            continue
        if [info.st_dev, info.st_ino] != identity:
            found.append(reason("identity", f"{ctx.display(path)} was replaced after the survey"))
    if found:
        return found
    members, _ = discover(ctx, snap, frozenset(item["paths"]))
    members = [m for m in members if m.kind == item["kind"] and m.host == item["host"]]
    covered = {path for member in members for path in member.paths}
    for path in item["paths"]:
        if path not in covered:
            found.append(reason("kind", f"{ctx.display(path)} no longer matches the rule that made it a candidate"))
    for member in members:
        result = evaluate_member(ctx, snap, git, member)
        if result.verdict != "candidate":
            found += list(result.reasons)
    return list({(r["check"], r["detail"]): r for r in found}.values())


def prepare_folders(top: str) -> None:
    root_info, root_real = os.lstat(top), real(top)
    stack = [top]
    while stack:
        folder = stack.pop()
        info = os.lstat(folder)
        if not stat.S_ISDIR(info.st_mode):
            continue
        if info.st_dev != root_info.st_dev or not within(real(folder), root_real):
            raise RemovalError(f"{folder} crosses a mount point or leaves the item")
        if stat.S_IMODE(info.st_mode) & stat.S_IRWXU != stat.S_IRWXU:
            os.chmod(folder, stat.S_IMODE(info.st_mode) | stat.S_IRWXU)
        stack += [os.path.join(folder, name) for name in os.listdir(folder)]


def remove_member(path: str) -> None:
    info = os.lstat(path)
    if stat.S_ISDIR(info.st_mode):
        prepare_folders(path)
        shutil.rmtree(path)
    else:
        os.unlink(path)


def remove_item(item: dict[str, Any]) -> tuple[int, str | None]:
    """Remove every member; return the size measured just before and a failure reason."""
    freed = total_size([measure(path) for path in item["paths"]])
    for path in item["paths"]:
        try:
            remove_member(path)
        except (OSError, RemovalError, shutil.Error) as error:
            detail = reason_of(error) if isinstance(error, OSError) else str(error)
            return freed, f"{path}: {detail}"
    return freed, None


def verify(baseline: Baseline, ctx: Context) -> dict[str, Any]:
    details: list[str] = []
    links_ok = protected_ok = True
    for link, target in baseline.links.items():
        now = os.readlink(link) if os.path.islink(link) else None
        if now != target:
            links_ok = False
            details.append(f"link {ctx.display(link)} changed from {target} to {now}")
    for path in baseline.protected:
        if not os.path.lexists(path):
            protected_ok = False
            details.append(f"protected path {ctx.display(path)} no longer exists")
    return {"links_unchanged": links_ok, "protected_unchanged": protected_ok, "details": details}


def process_item(
    ctx: Context, snap: Snapshot, git: GitProbe, item: dict[str, Any], report: dict[str, list]
) -> None:
    problems = recheck(ctx, snap, git, item)
    if problems:
        report["skipped"].append({"id": item["id"], "display": item["display"], "reasons": problems})
        return
    freed, failure = remove_item(item)
    gone = all(not os.path.lexists(path) for path in item["paths"])
    failure = failure or (None if gone else "a member still exists after removal")
    report["deleted"].append(
        {"id": item["id"], "display": item["display"], "paths": item["paths"], "freed": freed, "gone": gone}
    )
    if failure:
        report["failed"].append({"id": item["id"], "display": item["display"], "reason": failure})


def run_delete(plan: dict[str, Any], chosen: list[int]) -> tuple[dict[str, Any], int]:
    if not chosen:
        note = "nothing selected; nothing was deleted"
        return {"command": "delete", "selected": [], "deleted": [], "note": note}, 0
    items = select_items(plan, chosen)
    ctx = Context.from_config(plan["config"])
    snap, git = take_snapshot(ctx), GitProbe()
    baseline = take_baseline(ctx, snap, plan)
    report: dict[str, list] = {"deleted": [], "skipped": [], "failed": []}
    for item in items:
        process_item(ctx, snap, git, item, report)
    verification = verify(baseline, ctx)
    freed_total = sum(entry["freed"] for entry in report["deleted"] if entry["gone"])
    output = {"command": "delete", "selected": chosen, **report, "freed_total": freed_total, "verification": verification}
    clean = not report["skipped"] and not report["failed"]
    ok = clean and verification["links_unchanged"] and verification["protected_unchanged"]
    return output, 0 if ok else 1
