#!/usr/bin/env python3
"""Detached run that removes finished child worktrees the session created, started by the Orca status hook.

It handles one worktree at a time in a fixed order: confirm every check that needs no terminal closed, close the
never-used shell terminals, confirm that no process or listener is left, then remove the worktree and its local branch.
A run that stops between two steps leaves a worktree that still passes the checks, so the next run finishes it. Any
check that cannot be confirmed, because it does not hold or because Orca or Git fails or does not answer, keeps the
worktree and records that check. It deletes no remote branch, no ignored file, and changes no pull request.
"""

from __future__ import annotations

import fnmatch
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import orca_cleanup_state as shared  # noqa: E402
import orca_status_hook as hook  # noqa: E402

REGENERABLE = ("__pycache__", ".pytest_cache", "node_modules", "build", "dist", ".gradle", "*.tsbuildinfo")
STEP_SECONDS = float(os.environ.get("HEI5ENBUG_CLEANUP_STEP_SECONDS", "30"))
PAGES = 5


class Keep(Exception):
    """The check that keeps a worktree: its id, the reason shown, and whether no later run can change it."""

    def __init__(self, check: str, reason: str, done: bool = False) -> None:
        super().__init__(reason)
        self.check, self.reason, self.done = check, reason, done


def orca(*arguments: str) -> dict | None:
    return hook.orca_run(*arguments, timeout=STEP_SECONDS)


def git(path: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", path, *arguments], capture_output=True, text=True, timeout=STEP_SECONDS, check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired:
        raise Keep("git", f"`git {arguments[0]}` did not finish in time") from None
    except OSError:
        raise Keep("git", "git could not run") from None


def git_output(path: str, *arguments: str, check: str, reason: str) -> str:
    result = git(path, *arguments)
    if result.returncode != 0:
        raise Keep(check, reason)
    return result.stdout


def short_branch(record: dict) -> str:
    return str(record.get("branch") or "").removeprefix("refs/heads/")


def created_at(record: dict) -> float | None:
    lineage = record.get("lineage")
    value = lineage.get("createdAt") if isinstance(lineage, dict) else None
    return value / 1000 if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def worktrees_of(*arguments: str) -> list[dict] | None:
    payload = hook.orca_run("worktree", "list", *arguments, timeout=STEP_SECONDS)
    try:
        rows = payload["result"]["worktrees"]
    except (KeyError, TypeError):
        return None
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)] if isinstance(
        rows, list) else None


def resolve(create: dict, claimed: set[str]) -> tuple[str | None, bool]:
    """Return the id of the worktree the recorded command created, and whether the answer is final.

    Exactly one non-main worktree of the named repository whose creation time lies inside the command's run and that no
    earlier command of the session claimed counts; any other count records nothing, and an Orca failure leaves the
    question open.
    """
    arguments = ["--repo", create["repo"]] if create.get("repo") else []
    rows = worktrees_of(*arguments)
    if rows is None:
        return None, False
    low, high = float(create.get("start", 0)), float(create.get("end", 0))
    found = []
    for row in rows:
        created = created_at(row)
        if (not row.get("isMainWorktree") and row["id"] not in claimed and created is not None
                and low <= created <= high):
            found.append(row["id"])
    return (found[0], True) if len(found) == 1 else (None, True)


def matches(selector: str, record: dict) -> bool:
    kind, _, value = selector.partition(":")
    if kind == "id":
        return record["id"] == value
    if kind == "path":
        return bool(record.get("path")) and os.path.realpath(record["path"]) == os.path.realpath(value)
    if kind == "branch":
        return short_branch(record) == value.removeprefix("refs/heads/")
    if kind == "name":
        return record.get("displayName") == value
    return False


def processes_inside(path: str) -> bool | None:
    """True when a process has its working directory inside `path`, None when that cannot be read."""
    base = os.path.realpath(path)
    mine = os.getpid()
    directories: list[str] = []
    if os.path.isdir("/proc/self"):
        for name in os.listdir("/proc"):
            if name.isdigit() and int(name) != mine:
                try:
                    directories.append(os.readlink(f"/proc/{name}/cwd"))
                except OSError:
                    continue
    else:
        try:
            result = subprocess.run(["lsof", "-d", "cwd", "-Fpn"], capture_output=True, text=True,
                                    timeout=STEP_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if not result.stdout:
            return None
        pid = None
        for line in result.stdout.splitlines():
            if line.startswith("p"):
                pid = int(line[1:]) if line[1:].isdigit() else None
            elif line.startswith("n") and pid != mine:
                directories.append(line[1:])
    return any(hook.inside(os.path.realpath(item), base) for item in directories)


def dispatch_states(worktree_id: str) -> list[str] | None:
    """The state of every Dispatch Orca lists for the worktree, or None when the list cannot be read."""
    states: list[str] = []
    cursor = None
    for _ in range(PAGES):
        payload = orca("orchestration", "worker-list", "--limit", "100", *(["--cursor", cursor] if cursor else []))
        try:
            result = payload["result"]
            rows = result["workers"]
        except (KeyError, TypeError):
            return None
        if not isinstance(rows, list):
            return None
        for row in rows:
            if isinstance(row, dict) and row.get("workspace") == worktree_id:
                states.append(str(row.get("state")) if not row.get("outcome") else "failed")
        cursor = result.get("nextCursor") if isinstance(result, dict) else None
        if not cursor:
            return states
    return None


def check_ignored(path: str) -> None:
    for line in git_output(path, "status", "--porcelain", "--ignored", check="git", reason="git status failed").splitlines():
        if line.startswith("!! "):
            ignored = line[3:].strip().strip('"')
            name = ignored.rstrip("/").rsplit("/", 1)[-1]
            if not any(fnmatch.fnmatchcase(name, pattern) for pattern in REGENERABLE):
                raise Keep("ignored", f"`{ignored}` is ignored and not a regenerable name")


def check_pushed(path: str) -> None:
    if git_output(path, "status", "--porcelain", check="git", reason="git status failed").strip():
        raise Keep("uncommitted", "it has an uncommitted change")


def check_upstream(path: str, fetch: bool) -> str:
    """Return the upstream branch once the branch has one and no commit of it is missing there."""
    if fetch and git(path, "fetch", "--quiet").returncode != 0:
        raise Keep("fetch", "`git fetch` failed")
    upstream = git(path, "rev-parse", "--abbrev-ref", "@{upstream}")
    if upstream.returncode != 0 or not upstream.stdout.strip():
        raise Keep("no-upstream", "its branch has no upstream")
    count = git_output(path, "rev-list", "--count", "@{upstream}..HEAD", check="git", reason="git rev-list failed")
    if not count.strip().isdigit():
        raise Keep("git", "git rev-list gave no count")
    if int(count) > 0:
        raise Keep("unpushed", f"{int(count)} commit{'s are' if int(count) != 1 else ' is'} not pushed")
    return upstream.stdout.strip()


def terminals_of(record: dict) -> list[str]:
    """The handles of the worktree's terminals, once every one is a never-used shell terminal and none is this session's."""
    payload = orca("terminal", "list", "--worktree", f'id:{record["id"]}')
    try:
        rows = payload["result"]["terminals"]
    except (KeyError, TypeError):
        raise Keep("orca", "Orca did not list its terminals") from None
    if not isinstance(rows, list):
        raise Keep("orca", "Orca did not list its terminals")
    rows = [row for row in rows if isinstance(row, dict) and isinstance(row.get("handle"), str)
            and row.get("worktreeId", record["id"]) == record["id"]]
    if any(row["handle"] == os.environ.get("ORCA_TERMINAL_HANDLE") for row in rows):
        raise Keep("own-worktree", "this session's terminal is in it", done=True)
    if any(row.get("agentIdentity") for row in rows):
        raise Keep("agent-open", "an agent session is still open in it")
    if not all(hook.never_used(row["handle"]) for row in rows):
        raise Keep("terminal", "a terminal in it is not a never-used shell terminal")
    return [row["handle"] for row in rows]


def confirm_quiet(record: dict) -> None:
    deadline = time.monotonic() + min(3.0, STEP_SECONDS)
    while True:
        found = processes_inside(record["path"])
        if found is None:
            raise Keep("process", "it could not be read whether a process runs there")
        if not found or time.monotonic() >= deadline:
            break
        time.sleep(0.3)
    if found:
        raise Keep("process", "a process still has its working directory in it")
    payload = orca("ports", "--worktree", f'id:{record["id"]}')
    try:
        ports = payload["result"]["ports"]
    except (KeyError, TypeError):
        raise Keep("listener", "Orca did not list its ports") from None
    if not isinstance(ports, list) or ports:
        raise Keep("listener", "a process listens on a port there")


def repo_name(record: dict, rows: list[dict]) -> str:
    repos = hook.orca_run("repo", "list", timeout=STEP_SECONDS)
    try:
        for repo in repos["result"]["repos"]:
            if repo.get("id") == record.get("repoId"):
                return str(repo.get("displayName") or repo.get("name"))
    except (KeyError, TypeError, AttributeError):
        pass
    main = next((row for row in rows if row.get("repoId") == record.get("repoId") and row.get("isMainWorktree")), None)
    return os.path.basename(main["path"]) if main else str(record.get("repoId"))


class Run:
    def __init__(self, state_path: Path, deadline: float) -> None:
        self.state_path = state_path
        self.deadline = deadline
        self.results_path = shared.result_path(state_path)
        self.results = shared.read_results(self.results_path)
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        self.creates = [item for item in data.get("creates", []) if isinstance(item, dict)]
        self.agents = [item for item in data.get("agents", []) if isinstance(item, dict)
                       and isinstance(item.get("selector"), str)]
        self.cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else None

    def save(self) -> None:
        shared.write_results(self.results_path, self.results)

    def notice(self, entry: dict, fingerprint: str, text: str) -> None:
        if entry.get("noticed") == fingerprint:
            return
        entry["noticed"] = fingerprint
        sequence = 1 + max([item.get("seq", 0) for item in self.results["notices"] if isinstance(item, dict)] or [0])
        self.results["notices"].append({"seq": sequence, "text": text})

    def agent_ran(self, create: dict, record: dict) -> bool:
        return bool(create.get("agent")) or any(matches(item["selector"], record) for item in self.agents)

    def worker_ran(self, create: dict, record: dict) -> bool:
        return bool(create.get("worker")) or any(item.get("worker") and matches(item["selector"], record)
                                                 for item in self.agents)

    def removed_before(self, record: dict) -> bool:
        return any(isinstance(item, dict) and (item.get("id") == record["id"] or (
            item.get("repoId") == record.get("repoId") and item.get("branch") and item["branch"] == short_branch(record)))
                   for item in self.results["removed"])

    def check(self, create: dict, entry: dict, record: dict, rows: list[dict]) -> None:
        """Raise `Keep` for the first check that keeps the worktree; return when every check passed and it is gone."""
        path = record["path"]
        if record.get("isMainWorktree"):
            raise Keep("main-clone", "it is a repository's main clone", done=True)
        if self.cwd and hook.inside(os.path.realpath(self.cwd), os.path.realpath(path)):
            raise Keep("own-worktree", "this session works in it", done=True)
        if self.removed_before(record):
            raise Keep("created-again", "it was created again after the hook removed that branch's worktree", done=True)
        if record.get("childWorktreeIds") or any(row.get("parentWorktreeId") == record["id"] for row in rows):
            raise Keep("has-children", "it has a child worktree")
        if self.worker_ran(create, record):
            states = dispatch_states(record["id"])
            if not states or any(state != "succeeded" for state in states):
                raise Keep("dispatch", "a worker Dispatch there did not succeed or cannot be read")
        check_pushed(path)
        check_upstream(path, fetch=True)
        check_ignored(path)
        handles = terminals_of(record)
        for handle in handles:
            if orca("terminal", "close", "--terminal", handle) is None:
                raise Keep("orca", "Orca could not close a terminal there")
        confirm_quiet(record)
        check_pushed(path)
        entry.update({"remote": check_upstream(path, fetch=False), "branch": short_branch(record)})
        if orca("worktree", "rm", "--worktree", f'id:{record["id"]}', "--delete-branch") is None:
            raise Keep("orca", "Orca did not remove it")

    def finish_removed(self, entry: dict, record: dict, rows: list[dict]) -> None:
        branch = short_branch(record)
        main = next((row for row in rows if row.get("repoId") == record.get("repoId") and row.get("isMainWorktree")), None)
        deleted = None
        if main and branch:
            listing = git(main["path"], "branch", "--list", branch)
            deleted = listing.returncode == 0 and not listing.stdout.strip()
        entry.update({"state": "removed", "done": True, "reason": None, "check": None})
        self.results["removed"].append({"id": record["id"], "repoId": record.get("repoId"), "branch": branch})
        outcome = {True: "Orca deleted the local branch", False: "Orca retained the local branch",
                   None: "it is not known whether Orca deleted the local branch"}[deleted]
        self.notice(entry, "removed", f"removed worktree `{branch}` of `{repo_name(record, rows)}`; its work is on "
                                      f"`{entry.get('remote')}`, and {outcome}.")

    def handle(self, create: dict, rows: list[dict]) -> None:
        entry = self.results["entries"].setdefault(str(create["seq"]), {"state": "pending"})
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        if not entry.get("worktree_id"):
            claimed = {item.get("worktree_id") for item in self.results["entries"].values()
                       if isinstance(item, dict) and item.get("state") not in ("removed", "gone")}
            found, final = resolve(create, claimed)
            if not final:
                return
            if found is None:
                entry.update({"state": "none", "done": True})
                return
            entry["worktree_id"] = found
        record = next((row for row in rows if row["id"] == entry["worktree_id"]), None)
        if record is None:
            entry.update({"state": "gone", "done": True})
            return
        if not self.agent_ran(create, record):
            entry.update({"state": "left", "agents_seen": len(self.agents)})
            return
        entry["agents_seen"] = len(self.agents)
        label = f"`{short_branch(record)}` of `{repo_name(record, rows)}`"
        try:
            self.check(create, entry, record, rows)
        except Keep as keep:
            entry.update({"state": "kept", "check": keep.check, "reason": keep.reason, "done": keep.done})
            self.notice(entry, f"kept:{keep.check}", f"Kept {label}: {keep.reason}.")
            return
        after = worktrees_of()
        if after is not None and any(row["id"] == record["id"] for row in after):
            entry.update({"state": "kept", "check": "orca", "reason": "Orca still lists it after the removal",
                          "done": False})
            return
        self.finish_removed(entry, record, rows)

    def run(self) -> None:
        pending = [item for item in self.creates if isinstance(item.get("seq"), int)]
        rows = worktrees_of()
        for create in sorted(pending, key=lambda item: item["seq"]):
            entry = self.results["entries"].get(str(create["seq"]))
            if isinstance(entry, dict) and (entry.get("state") in shared.DONE_STATES or entry.get("done") is True):
                continue
            if time.monotonic() > self.deadline:
                break
            if rows is None:
                if isinstance(entry, dict) and entry.get("worktree_id"):
                    entry.update({"state": "kept", "check": "orca", "reason": "Orca did not answer"})
                continue
            try:
                self.handle(create, rows)
            except Exception as error:
                self.results["entries"].setdefault(str(create["seq"]), {})
                self.results["entries"][str(create["seq"])].update(
                    {"state": "kept", "check": "error", "reason": f"the cleanup hit an internal error ({type(error).__name__})"})
            self.save()
            if self.results["entries"][str(create["seq"])].get("state") == "removed":
                rows = worktrees_of() or rows
        self.save()


def arm_watchdog(lock: Path) -> None:
    """End this run and every process it started after `run_seconds()`, whatever Orca or Git is doing."""

    def stop() -> None:
        lock.unlink(missing_ok=True)
        if os.getpgrp() == os.getpid():
            os.killpg(os.getpid(), signal.SIGKILL)
        os.kill(os.getpid(), signal.SIGKILL)

    timer = threading.Timer(shared.run_seconds(), stop)
    timer.daemon = True
    timer.start()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 2
    state_path = Path(argv[1])
    lock = shared.lock_path(state_path)
    try:
        lock.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}), encoding="utf-8")
    except OSError:
        return 1
    arm_watchdog(lock)
    try:
        Run(state_path, time.monotonic() + shared.run_seconds() * 0.8).run()
    finally:
        lock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
