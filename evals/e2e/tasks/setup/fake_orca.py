#!/usr/bin/env python3
"""A fake `orca` command for the T21 evaluation: a JSON state file, real Git for removals, and a call log.

The state file named by FAKE_ORCA_STATE holds repos, worktrees (a folder workspace is a worktree record with
`kind: folder`), terminals, and optionally `dispatches` and `ports`. Every call is appended to `calls.jsonl` beside it.
`worktree create` and `orchestration worker-start` make a real Git worktree of the named repository, and a started
worker commits, pushes its branch, reports `worker_done` to the caller, and has its terminal released at once. A state
key `kill_parent_on_close` makes the next `terminal close` end its parent process after the close, and the
environment variable FAKE_ORCA_FAIL makes every call fail. All data is
fictional.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("FAKE_ORCA_STATE", "orca-state/state.json"))
CALLS = STATE.parent / "calls.jsonl"
VALUE_OPTIONS = frozenset({
    "--repo", "--worktree", "--parent-worktree", "--terminal", "--workspace-status", "--comment", "--display-name",
    "--title", "--name", "--base-branch", "--reference", "--command", "--timeout-ms", "--for", "--text", "--limit",
    "--to", "--from", "--subject", "--body", "--type", "--agent", "--spec", "--branch", "--cursor", "--dispatch",
    "--task-title", "--run", "--prompt", "--model", "--effort",
})
AFTER_SAVE: list = []
NEW_WORKTREES = ("new-child", "new-top-level")
HOST_COMMANDS = ("claude", "codex")
HIDDEN_TERMINAL_FIELDS = ("screen", "stream", "process", "input")


class Failure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def parse(argv: list[str]) -> tuple[list[str], dict[str, str], set[str]]:
    words: list[str] = []
    options: dict[str, str] = {}
    flags: set[str] = set()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token.startswith("--") and "=" in token:
            name, _, value = token.partition("=")
            options[name] = value
        elif token in VALUE_OPTIONS and index + 1 < len(argv):
            options[token] = argv[index + 1]
            index += 1
        elif token.startswith("--"):
            flags.add(token)
        else:
            words.append(token)
        index += 1
    return words, options, flags


def current(state: dict) -> dict:
    cwd = os.path.realpath(os.getcwd())
    best = None
    for record in state["worktrees"]:
        path = record.get("path")
        if path and (cwd == os.path.realpath(path) or cwd.startswith(os.path.realpath(path) + os.sep)):
            if best is None or len(path) > len(best["path"]):
                best = record
    if best is None:
        raise Failure("worktree_not_found", "the current directory is in no Orca worktree")
    return best


def resolve(state: dict, selector: str | None) -> dict:
    if selector in (None, "active", "current"):
        return current(state)
    kind, _, value = selector.partition(":")
    for record in state["worktrees"]:
        if kind == "id" and record["id"] == value:
            return record
        if kind == "path" and record.get("path") and os.path.realpath(record["path"]) == os.path.realpath(value):
            return record
        if kind == "branch" and record.get("branch", "").removeprefix("refs/heads/") == value.removeprefix("refs/heads/"):
            return record
        if kind == "name" and record.get("displayName") == value:
            return record
    raise Failure("worktree_not_found", f"no worktree matches {selector}")


def git(path: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", path, *arguments], capture_output=True, text=True, check=False)


def main_clone(state: dict, record: dict) -> dict:
    return next(item for item in state["worktrees"] if item.get("repoId") == record["repoId"] and item["isMainWorktree"])


def remove_worktree(state: dict, record: dict, delete_branch: bool, force: bool = False) -> dict:
    if record.get("isMainWorktree"):
        raise Failure("main_worktree", "a repository's main clone cannot be removed")
    if any(item.get("parentWorktreeId") == record["id"] for item in state["worktrees"]):
        raise Failure("has_children", "the worktree has child worktrees")
    if record.get("kind") != "folder":
        main = main_clone(state, record)
        result = git(main["path"], "worktree", "remove", *(["--force"] if force else []), record["path"])
        if result.returncode != 0:
            raise Failure("git_failed", result.stderr.strip() or "git worktree remove failed")
        branch = record.get("branch", "").removeprefix("refs/heads/")
        if delete_branch and branch:
            git(main["path"], "branch", "-D", branch)
    state["terminals"] = [item for item in state["terminals"] if item["worktreeId"] != record["id"]]
    state["worktrees"] = [item for item in state["worktrees"] if item["id"] != record["id"]]
    return {"removed": record["id"]}


def set_worktree(state: dict, record: dict, options: dict[str, str], flags: set[str]) -> dict:
    for option, field in (("--workspace-status", "workspaceStatus"), ("--comment", "comment"),
                          ("--display-name", "displayName")):
        if option in options:
            record[field] = options[option]
            if field == "displayName":
                record["displayNameMode"] = "manual" if options[option] else "automatic"
    if "--unread" in flags:
        record["unread"] = True
    if "--no-parent" in flags:
        record["parentWorktreeId"] = None
    if "--parent-worktree" in options:
        parent = options["--parent-worktree"]
        record["parentWorktreeId"] = parent.removeprefix("folder:") if parent.startswith("folder:") else (
            resolve(state, parent)["id"])
    return {"worktree": record}


def find_terminal(state: dict, handle: str | None) -> dict:
    for item in state["terminals"]:
        if item["handle"] == handle:
            return item
    raise Failure("terminal_not_found", f"no terminal {handle}")


def host_command(text: str) -> str | None:
    """Return the agent that a typed command starts, such as `claude` or `cd 'x' && codex`, or None."""
    last = text.strip().split("&&")[-1].split()
    return last[0] if len(last) == 1 and last[0] in HOST_COMMANDS else None


def read_terminal(state: dict, options: dict[str, str], flags: set[str]) -> dict:
    handle = options.get("--terminal")
    if not any(item["handle"] == handle for item in state["terminals"]):
        return {"text": ""}
    item = find_terminal(state, handle)
    shown = agent_screen(item) if item.get("agentIdentity") else (
        item.get("screen") if "--screen" in flags else item.get("stream"))
    tail = shown if isinstance(shown, list) else ([] if shown is None else shown.splitlines())
    return {"text": "", "terminal": {"handle": handle, "status": "running", "tail": tail,
                                     "source": "screen" if "--screen" in flags else "stream"}}


def agent_screen(terminal: dict) -> list[str]:
    """The screen of a terminal that runs an agent: a title line and an input line that shows the typed text."""
    return [f"{terminal['agentIdentity']} (fake)", f"> {terminal.get('input', '')}"]


def add_terminal(state: dict, worktree_id: str, title: str = "", command: str | None = None,
                 agent: str | None = None) -> str:
    """The one way a terminal is made: an agent terminal, a terminal that runs `command`, or an unused shell."""
    handle = f"term_new_{1 + sum(1 for item in state['terminals'] if item['handle'].startswith('term_new_'))}"
    terminal = {"handle": handle, "worktreeId": worktree_id, "title": title}
    agent = agent or (host_command(command) if command else None)
    if agent:
        terminal["agentIdentity"] = agent
    elif command:
        terminal["process"] = True
        terminal["screen"] = [f"% {command}"]
    else:
        terminal["screen"] = ["user@host demo %"]
        terminal["stream"] = ["user@host demo %"]
    state["terminals"].append(terminal)
    return handle


def resolve_repo(state: dict, selector: str | None) -> dict:
    """The main clone record of the repository a `--repo` selector names, or of the current worktree's repository."""
    if not selector:
        return main_clone(state, current(state))
    kind, _, value = selector.partition(":")
    for repo in state["repos"]:
        if (kind == "id" and repo["id"] == value) or (kind == "name" and repo["name"] == value) or (
                kind == "path" and os.path.realpath(repo["path"]) == os.path.realpath(value)):
            return next(item for item in state["worktrees"] if item.get("repoId") == repo["id"] and item["isMainWorktree"])
    raise Failure("repo_not_found", f"no repository matches {selector}")


def create_worktree(state: dict, options: dict[str, str], agent: str | None, shell_terminal: bool) -> dict:
    main = resolve_repo(state, options.get("--repo"))
    name = options.get("--name")
    if not name:
        raise Failure("name_required", "--name is required")
    branch = options.get("--branch") or name
    path = Path(main["path"]).parent / f"{Path(main['path']).name}-{name}"
    result = git(main["path"], "worktree", "add", "-q", "-b", branch, str(path), options.get("--base-branch", "main"))
    if result.returncode != 0:
        raise Failure("git_failed", result.stderr.strip() or "git worktree add failed")
    parent = options.get("--parent-worktree")
    record = {
        "id": f"{main['repoId']}::{path}", "repoId": main["repoId"], "path": str(path), "kind": "git",
        "isMainWorktree": False, "branch": f"refs/heads/{branch}", "displayName": name, "displayNameMode": "manual",
        "workspaceStatus": None, "comment": "", "references": [], "childWorktreeIds": [],
        "parentWorktreeId": resolve(state, parent)["id"] if parent else main["id"],
        "lineage": {"createdAt": int(time.time() * 1000)},
    }
    state["worktrees"].append(record)
    if agent or shell_terminal:
        add_terminal(state, record["id"], title=agent or "zsh", agent=agent)
    return record


def start_worker(state: dict, options: dict[str, str]) -> dict:
    """A worker that finishes at once: it commits a file, pushes its branch, reports to the caller, and is released."""
    target = options.get("--worktree", "current")
    record = (create_worktree(state, options, None, False) if target in NEW_WORKTREES
              else resolve(state, None if target == "current" else target))
    number = 1 + len(state.setdefault("dispatches", []))
    work = Path(record["path"])
    (work / f"worker-{number}.txt").write_text(f"worker {number}\n", encoding="utf-8")
    git(record["path"], "add", "-A")
    git(record["path"], "-c", "user.name=Demo", "-c", "user.email=demo@example.com", "commit", "-q", "-m",
        f"Worker {number} result")
    branch = record["branch"].removeprefix("refs/heads/")
    pushed = git(record["path"], "push", "-q", "-u", "origin", branch)
    outcome = "succeeded" if pushed.returncode == 0 else "failed"
    dispatch = {"dispatchId": f"ctx_{number}", "taskId": f"task_{number}", "state": outcome, "liveness": "exited",
                "terminal": f"term_worker_{number}", "terminalState": "released", "workspace": record["id"],
                "host": "local"}
    state["dispatches"].append(dispatch)
    caller = os.environ.get("ORCA_TERMINAL_HANDLE", "")
    state.setdefault("messages", []).append({"to": caller, "from": dispatch["terminal"], "subject": "worker_done",
                                             "body": f"{branch} pushed"})
    return {"worker": dispatch, "worktree": record}


def create_terminal(state: dict, options: dict[str, str]) -> dict:
    target = resolve(state, options.get("--worktree"))
    handle = add_terminal(state, target["id"], options.get("--title", ""), options.get("--command"))
    return {"terminal": {"handle": handle}}


def send_terminal(state: dict, options: dict[str, str], flags: set[str]) -> dict:
    terminal = find_terminal(state, options.get("--terminal"))
    text = options.get("--text", "")
    state.setdefault("sent", []).append({"handle": terminal["handle"], "text": text})
    agent = host_command(text)
    if terminal.get("agentIdentity"):
        if text == "\x7f":
            terminal["input"] = terminal.get("input", "")[:-1]
        elif "--enter" in flags:
            terminal["input"] = ""
        else:
            terminal["input"] = terminal.get("input", "") + text
    elif agent and not terminal.get("process"):
        terminal["agentIdentity"] = agent
        for field in HIDDEN_TERMINAL_FIELDS:
            terminal.pop(field, None)
    return {"send": {"handle": terminal["handle"], "accepted": True}}


def run(words: list[str], options: dict[str, str], flags: set[str], state: dict) -> dict:
    command = " ".join(words[:2])
    if command == "status":
        return {"runtime": {"reachable": True}}
    if command == "repo list":
        return {"repos": state["repos"]}
    if command == "worktree list":
        repo = resolve_repo(state, options["--repo"])["repoId"] if options.get("--repo") else None
        return {"worktrees": [item for item in state["worktrees"] if not repo or item.get("repoId") == repo]}
    if command == "worktree current":
        return {"worktree": current(state)}
    if command == "worktree show":
        return {"worktree": resolve(state, options.get("--worktree"))}
    if command == "worktree set":
        return set_worktree(state, resolve(state, options.get("--worktree")), options, flags)
    if command == "worktree rm":
        return remove_worktree(state, resolve(state, options.get("--worktree")), "--delete-branch" in flags,
                               "--force" in flags)
    if command == "terminal list":
        selector = options.get("--worktree")
        target = resolve(state, selector)["id"] if selector else None
        return {"terminals": [{key: value for key, value in item.items() if key not in HIDDEN_TERMINAL_FIELDS}
                              for item in state["terminals"] if target is None or item["worktreeId"] == target]}
    if command == "worktree create":
        return {"worktree": create_worktree(state, options, options.get("--agent"), True)}
    if command == "orchestration worker-start":
        return start_worker(state, options)
    if command == "orchestration worker-list":
        return {"workers": state.get("dispatches", [])}
    if command == "terminal create":
        return create_terminal(state, options)
    if command == "terminal send":
        return send_terminal(state, options, flags)
    if command == "terminal wait":
        return {"wait": {"satisfied": bool(find_terminal(state, options.get("--terminal")).get("agentIdentity"))}}
    if command == "orchestration send":
        message = {"to": options.get("--to"), "from": options.get("--from"), "subject": options.get("--subject", ""),
                   "body": options.get("--body", "")}
        state.setdefault("messages", []).append(message)
        return {"message": message}
    if command == "terminal close":
        if state.pop("kill_parent_on_close", False):
            AFTER_SAVE.append(lambda: os.kill(os.getppid(), signal.SIGKILL))
        before = len(state["terminals"])
        state["terminals"] = [item for item in state["terminals"] if item["handle"] != options.get("--terminal")]
        return {"closed": before - len(state["terminals"])}
    if command == "terminal rename":
        for item in state["terminals"]:
            if item["handle"] == options.get("--terminal"):
                item["title"] = options.get("--title", "")
        return {"rename": {"handle": options.get("--terminal"), "title": options.get("--title", "")}}
    if command == "terminal read":
        return read_terminal(state, options, flags)
    if command == "reference find":
        key = words[2] if len(words) > 2 else ""
        return {"worktrees": [item for item in state["worktrees"]
                              if any(key and (key in ref or ref in key) for ref in item.get("references", []))]}
    if command == "ports":
        selector = options.get("--worktree")
        target = resolve(state, selector)["id"] if selector else None
        return {"ports": [item for item in state.get("ports", []) if target is None or item.get("worktreeId") == target]}
    if command == "jira connection":
        return {"connected": False}
    if command == "orchestration run-list":
        return {"runs": []}
    return {}


def log(argv: list[str], ok: bool) -> None:
    try:
        cwd = os.getcwd()
    except FileNotFoundError:
        cwd = os.environ.get("PWD", "")
    entry = {"time": time.time(), "cwd": cwd, "handle": os.environ.get("ORCA_TERMINAL_HANDLE"), "argv": argv,
             "ok": ok}
    with CALLS.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry) + "\n")


def main(argv: list[str]) -> int:
    arguments = [token for token in argv if token != "--json"]
    if arguments[:2] == ["skills", "get"]:
        log(arguments, True)
        print("fake orca: use `orca <group> <command> --json`; groups: repo, worktree, terminal, reference, ports.")
        return 0
    if os.environ.get("FAKE_ORCA_FAIL"):
        log(arguments, False)
        print(json.dumps({"ok": False, "error": {"code": "runtime_unavailable", "message": "the fake runtime is down"}}))
        return 1
    words, options, flags = parse(arguments)
    state = load()
    try:
        result = run(words, options, flags, state)
    except Failure as failure:
        log(arguments, False)
        print(json.dumps({"ok": False, "error": {"code": failure.code, "message": str(failure)}}))
        return 1
    save(state)
    log(arguments, True)
    print(json.dumps({"ok": True, "result": result}), flush=True)
    for action in AFTER_SAVE:
        action()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
