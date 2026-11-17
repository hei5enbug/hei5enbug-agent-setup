#!/usr/bin/env python3
"""A fake `orca` command for the T21 evaluation: a JSON state file, real Git for removals, and a call log.

The state file named by FAKE_ORCA_STATE holds repos, worktrees (a folder workspace is a worktree record with
`kind: folder`), and terminals. Every call is appended to `calls.jsonl` beside it. All data is fictional.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("FAKE_ORCA_STATE", "orca-state/state.json"))
CALLS = STATE.parent / "calls.jsonl"
VALUE_OPTIONS = frozenset({
    "--repo", "--worktree", "--parent-worktree", "--terminal", "--workspace-status", "--comment", "--display-name",
    "--title", "--name", "--base-branch", "--reference", "--command", "--timeout-ms", "--for", "--text", "--limit",
    "--to", "--from", "--subject", "--body", "--type",
})
HOST_COMMANDS = ("claude", "codex")
HIDDEN_TERMINAL_FIELDS = ("screen", "stream", "process")


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
    shown = item.get("screen") if "--screen" in flags else item.get("stream")
    tail = shown if isinstance(shown, list) else ([] if shown is None else shown.splitlines())
    return {"text": "", "terminal": {"handle": handle, "status": "running", "tail": tail,
                                     "source": "screen" if "--screen" in flags else "stream"}}


def create_terminal(state: dict, options: dict[str, str]) -> dict:
    target = resolve(state, options.get("--worktree"))
    number = 1 + sum(1 for item in state["terminals"] if item["handle"].startswith("term_new_"))
    handle = f"term_new_{number}"
    terminal = {"handle": handle, "worktreeId": target["id"], "title": options.get("--title", "")}
    command = options.get("--command")
    agent = host_command(command) if command else None
    if agent:
        terminal["agentIdentity"] = agent
    elif command:
        terminal["process"] = True
        terminal["screen"] = [f"% {command}"]
    else:
        terminal["screen"] = ["user@host demo %"]
        terminal["stream"] = ["user@host demo %"]
    state["terminals"].append(terminal)
    return {"terminal": {"handle": handle}}


def send_terminal(state: dict, options: dict[str, str]) -> dict:
    terminal = find_terminal(state, options.get("--terminal"))
    text = options.get("--text", "")
    state.setdefault("sent", []).append({"handle": terminal["handle"], "text": text})
    agent = host_command(text)
    if agent and not terminal.get("agentIdentity") and not terminal.get("process"):
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
        repo = options.get("--repo", "").removeprefix("id:")
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
    if command == "terminal create":
        return create_terminal(state, options)
    if command == "terminal send":
        return send_terminal(state, options)
    if command == "terminal wait":
        return {"wait": {"satisfied": bool(find_terminal(state, options.get("--terminal")).get("agentIdentity"))}}
    if command == "orchestration send":
        message = {"to": options.get("--to"), "from": options.get("--from"), "subject": options.get("--subject", ""),
                   "body": options.get("--body", "")}
        state.setdefault("messages", []).append(message)
        return {"message": message}
    if command == "terminal close":
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
        return {"ports": []}
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
    print(json.dumps({"ok": True, "result": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
