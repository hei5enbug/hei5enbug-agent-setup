#!/usr/bin/env python3
"""A fake `orca` command for the T21, T31 to T34, and T67 evaluations: a JSON state file, real Git, and a call log.

The state file named by FAKE_ORCA_STATE holds repos, worktrees (a folder workspace is a worktree record with
`kind: folder`), terminals, and the messages sent between sessions. An agent terminal has `agentIdentity`. A shell
terminal has a `prompt`, its earlier `history`, `typed` input not yet submitted, and a `process` while a command runs;
sending a host command to one that is idle makes it an agent terminal. Every call is appended to `calls.jsonl` beside
the state file, in call order, with the caller's terminal handle. A state may also hold `dispatches` and `ports`.
`worktree create` and `orchestration worker-start` make a real Git worktree of the named repository, and a started
worker commits, pushes its branch, reports `worker_done` to the caller, and has its terminal released at once. A state
key `kill_parent_on_close` makes the next `terminal close` end its parent process after the close, and the environment
variable FAKE_ORCA_FAIL makes every call fail. A shell terminal may carry explicit `screen` and `stream` lists that
replace what its prompt, history, and typed input would show. All data is fictional.
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
    "--to", "--from", "--subject", "--body", "--type", "--types", "--dispatch", "--agent", "--spec", "--branch",
    "--cursor", "--task-title", "--run", "--prompt", "--model", "--effort",
})
HOSTS = frozenset({"claude", "codex"})
AFTER_SAVE: list = []
NEW_WORKTREES = ("new-child", "new-top-level")


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
    handle = handle or os.environ.get("ORCA_TERMINAL_HANDLE")
    for item in state["terminals"]:
        if item["handle"] == handle:
            return item
    raise Failure("terminal_not_found", f"no terminal {handle}")


def is_shell(terminal: dict) -> bool:
    return not terminal.get("agentIdentity") and "prompt" in terminal


def screen_lines(terminal: dict) -> list[str]:
    if not is_shell(terminal) or "screen" in terminal:
        shown = list(terminal.get("screen", []))
        return [*shown, f"> {terminal['typed']}"] if terminal.get("agentIdentity") and "typed" in terminal else shown
    shown = list(terminal.get("history", []))
    return shown if terminal.get("process") else [*shown, terminal["prompt"] + terminal.get("typed", "")]


def stream_lines(terminal: dict) -> list[str]:
    if not is_shell(terminal) or "stream" in terminal:
        return list(terminal.get("stream", terminal.get("screen", [])))
    return [*terminal.get("history", []), terminal["prompt"] + terminal.get("typed", "")]


def listed_terminal(terminal: dict) -> dict:
    entry = {"handle": terminal["handle"], "worktreeId": terminal["worktreeId"], "title": terminal.get("title", ""),
             "connected": True, "writable": True, "preview": "\n".join(screen_lines(terminal)[-4:])}
    if terminal.get("agentIdentity"):
        entry["agentIdentity"] = terminal["agentIdentity"]
    return entry


def read_terminal(terminal: dict, screen: bool) -> dict:
    return {"handle": terminal["handle"], "status": "running",
            "tail": screen_lines(terminal) if screen else stream_lines(terminal),
            "source": "screen" if screen else "stream"}


def send_terminal(terminal: dict, options: dict[str, str], flags: set[str]) -> dict:
    text, enter = options.get("--text", ""), "--enter" in flags
    receipt = {"send": {"handle": terminal["handle"], "accepted": True}}
    if not is_shell(terminal):
        if "typed" in terminal:
            for char in text:
                terminal["typed"] = terminal["typed"][:-1] if char == "\x7f" else terminal["typed"] + char
            if enter:
                terminal.setdefault("received", []).append(terminal["typed"])
                terminal["typed"] = ""
        elif enter:
            terminal.setdefault("received", []).append(text)
        return receipt
    if terminal.get("process"):
        terminal.setdefault("input", []).append(text)
        return receipt
    typed = terminal.get("typed", "")
    terminal["typed"] = typed[:-1] if text == "\x7f" else typed + text
    if enter:
        command, terminal["typed"] = terminal["typed"].strip(), ""
        agent = host_command(command)
        if agent:
            terminal["agentIdentity"] = agent
            terminal["screen"] = [f"{agent} ready"]
        elif command:
            terminal["history"] = [*terminal.get("history", []), terminal["prompt"] + command]
            terminal["process"] = command
    return receipt


def host_command(text: str) -> str | None:
    """Return the agent that a typed command starts, such as `claude` or `cd 'x' && codex`, or None."""
    last = text.strip().split("&&")[-1].split()
    return last[0] if last and last[0] in HOSTS and (len(last) == 1 or last[1].startswith("-")) else None


def add_terminal(state: dict, worktree_id: str, title: str = "", command: str = "") -> str:
    """The one way a terminal is made: an agent terminal, a terminal that runs `command`, or a never-used shell."""
    worktree = next(item for item in state["worktrees"] if item["id"] == worktree_id)
    handle = f"term_new_{len(state['terminals']) + 1}"
    created = {"handle": handle, "worktreeId": worktree_id, "title": title,
               "prompt": f"{worktree.get('displayName', 'demo')} % ", "history": [], "typed": "", "process": None}
    command = command.strip()
    agent = host_command(command)
    if agent:
        created.update(agentIdentity=agent, screen=[f"{agent} ready"], typed="")
    elif command:
        created.update(history=[created["prompt"] + command], process=command)
    state["terminals"].append(created)
    return handle


def create_terminal(state: dict, options: dict[str, str]) -> dict:
    worktree = resolve(state, options.get("--worktree"))
    handle = add_terminal(state, worktree["id"], options.get("--title", ""), options.get("--command", ""))
    return {"terminal": {"handle": handle, "worktreeId": worktree["id"]}}


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
        add_terminal(state, record["id"], title=agent or "zsh", command=agent or "")
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
    if command == "worktree create":
        return {"worktree": create_worktree(state, options, options.get("--agent"), True)}
    if command == "orchestration worker-start":
        return start_worker(state, options)
    if command == "orchestration worker-list":
        return {"workers": state.get("dispatches", [])}
    if command in ("orchestration worker-show", "orchestration worker-release", "orchestration worker-read"):
        dispatch = next((item for item in state.get("dispatches", []) if item["dispatchId"] == options.get("--dispatch")),
                        None)
        if dispatch is None:
            raise Failure("dispatch_not_found", f"no dispatch {options.get('--dispatch')}")
        return {"worker": dispatch, "text": ""}
    if command == "terminal list":
        selector = options.get("--worktree")
        target = resolve(state, selector)["id"] if selector else None
        return {"terminals": [listed_terminal(item) for item in state["terminals"]
                              if target is None or item["worktreeId"] == target]}
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
        return {"terminal": read_terminal(find_terminal(state, options.get("--terminal")), "--screen" in flags)}
    if command == "terminal send":
        return send_terminal(find_terminal(state, options.get("--terminal")), options, flags)
    if command == "terminal create":
        return create_terminal(state, options)
    if command == "terminal wait":
        found = find_terminal(state, options.get("--terminal"))
        return {"wait": {"handle": found["handle"], "satisfied": bool(found.get("agentIdentity"))}}
    if command == "orchestration send":
        message = {key: options.get(f"--{key}", "") for key in ("to", "from", "subject", "body", "type")}
        state.setdefault("messages", []).append(message)
        return {"message": {"id": f"msg_{len(state['messages'])}", **message}}
    if command in ("orchestration check", "orchestration inbox"):
        handle = os.environ.get("ORCA_TERMINAL_HANDLE")
        return {"messages": [item for item in state.get("messages", []) if item.get("to") == handle]}
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
    except OSError:
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
