"""Trust this plugin's Codex hooks again after a release resets their trust, but only for an untouched official copy.

Codex ties hook trust to a hash of every plugin file, so each marketplace update leaves the hooks `modified`. The plugin
re-trusts only its own hooks, only while the installed copy is a clean git checkout of the official repository whose HEAD
the official repository itself vouches for, and confirms the result through `hooks/list`. Local refs and tags prove
nothing, so HEAD must be a commit the official remote advertises right now for `main` or a `v*` tag, or an ancestor of
its current `main`; any network or verification failure refuses.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Sequence

PLUGIN_ID = "hei5enbug-agent-setup@hei5enbug"
OFFICIAL_URL = "https://github.com/hei5enbug/hei5enbug-agent-setup.git"
OFFICIAL_REMOTES = frozenset({OFFICIAL_URL, OFFICIAL_URL.removesuffix(".git")})
INSTALL_MARKER = ".codex-marketplace-install.json"
UNTRUSTED = frozenset({"untrusted", "modified"})
MAIN = "refs/heads/main"
TAGS = "refs/tags/v*"
PROBE_REF = "refs/official/main"
GIT_TIMEOUT_SECONDS = 20
NETWORK_TIMEOUT_SECONDS = 120


class TrustError(Exception):
    """Why the hooks were not trusted automatically."""


def candidates(hooks: Sequence[object]) -> list[dict]:
    """This plugin's hooks that Codex reports untrusted or modified, with the fields a trust write needs."""
    return [
        hook for hook in hooks
        if isinstance(hook, dict) and hook.get("pluginId") == PLUGIN_ID and hook.get("trustStatus") in UNTRUSTED
        and isinstance(hook.get("key"), str) and hook["key"].startswith(f"{PLUGIN_ID}:")
        and not any(character in hook["key"] for character in '"\\\n')
        and isinstance(hook.get("currentHash"), str) and hook["currentHash"]
        and isinstance(hook.get("sourcePath"), str)
    ]


def plugin_root(hooks: Sequence[dict]) -> Path:
    """The one installed plugin folder every hook file comes from: the parent of the `hooks` folder holding them."""
    roots = set()
    for hook in hooks:
        source = Path(hook["sourcePath"])
        if source.parent.name != "hooks" or not source.is_absolute():
            raise TrustError(f"hook file outside a plugin hooks folder: {source}")
        roots.add(source.parent.parent)
    if len(roots) != 1:
        raise TrustError("the hooks come from more than one plugin folder")
    return roots.pop()


def _git(root: Path, *args: str, timeout: float = GIT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    environment = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "--no-optional-locks", "-C", str(root),
             *args],
            capture_output=True, text=True, timeout=timeout, env=environment, stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TrustError(f"git could not run: {error}") from error


def _git_output(root: Path, *args: str, timeout: float = GIT_TIMEOUT_SECONDS) -> str:
    completed = _git(root, *args, timeout=timeout)
    if completed.returncode != 0:
        raise TrustError(f"git {args[0]} failed in {root}")
    return completed.stdout


def advertised(root: Path) -> tuple[str | None, set[str]]:
    """The commit the official remote advertises now for `main`, and the commits its `v*` tags point to, peeled."""
    tags: dict[str, str] = {}
    main = None
    for line in _git_output(root, "ls-remote", "--", OFFICIAL_URL, MAIN, TAGS, timeout=NETWORK_TIMEOUT_SECONDS).splitlines():
        commit, _, ref = line.partition("\t")
        if ref == MAIN:
            main = commit
        elif ref.startswith("refs/tags/v"):
            name = ref.removesuffix("^{}")
            if ref.endswith("^{}") or name not in tags:
                tags[name] = commit
    return main, set(tags.values())


def on_official_main(root: Path, head: str) -> bool:
    """Whether HEAD is an ancestor of the official `main` tip, fetched into a scratch repository that borrows the
    checkout's objects, so the installed copy's own `.git` is never written."""
    objects = Path(_git_output(root, "rev-parse", "--path-format=absolute", "--git-path", "objects").strip())
    with tempfile.TemporaryDirectory(prefix="codex-hook-trust-") as scratch:
        probe = Path(scratch) / "probe.git"
        _git_output(Path(scratch), "init", "--bare", "-q", str(probe))
        (probe / "objects" / "info" / "alternates").write_text(f"{objects}\n", encoding="utf-8")
        _git_output(probe, "fetch", "--no-tags", "-q", "--", OFFICIAL_URL, f"+{MAIN}:{PROBE_REF}",
                    timeout=NETWORK_TIMEOUT_SECONDS)
        return _git(probe, "merge-base", "--is-ancestor", head, PROBE_REF).returncode == 0


def verify_checkout(root: Path) -> None:
    """Raise unless the folder is a clean checkout of the official repository at a commit the official remote vouches for.

    Only the marketplace install marker may sit beside the tracked files; any other untracked, ignored, staged, or
    modified file, or a tracked file marked skip-worktree or assume-unchanged, means the copy was edited locally."""
    root = Path(root).resolve()
    top = _git_output(root, "rev-parse", "--show-toplevel").strip()
    if not top or Path(top).resolve() != root:
        raise TrustError(f"{root} is not the top of a git checkout")
    remote = _git_output(root, "config", "--get", "remote.origin.url").strip()
    if remote not in OFFICIAL_REMOTES:
        raise TrustError(f"the checkout's origin is not the official repository: {remote}")
    entries = [entry for entry in _git_output(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching", "--ignore-submodules=none",
    ).split("\0") if entry]
    if any(entry != f"?? {INSTALL_MARKER}" for entry in entries):
        raise TrustError("the installed copy has local changes")
    flagged = [line for line in _git_output(root, "ls-files", "-v", "-z").split("\0") if line and (line[0].islower() or line[0] == "S")]
    if flagged:
        raise TrustError("the installed copy marks tracked files skip-worktree or assume-unchanged, which hides local edits")
    head = _git_output(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    main, released = advertised(root)
    if head == main or head in released:
        return
    if main is None or not on_official_main(root, head):
        raise TrustError("the official repository advertises no main or v* tag commit that contains HEAD")


def trust_writes(hooks: Sequence[dict]) -> list[dict]:
    """The `config/value/write` parameters that record each hook's current hash as trusted."""
    return [
        {"keyPath": f'hooks.state."{hook["key"]}"', "value": {"trusted_hash": hook["currentHash"]}, "mergeStrategy": "replace"}
        for hook in hooks
    ]


def _read_reply(stream, message_id: int) -> dict:
    for line in iter(stream.readline, ""):
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("id") == message_id:
            if "error" in message:
                raise TrustError(f"codex app-server rejected request {message_id}: {str(message['error'])[:300]}")
            return message
    raise TrustError(f"codex app-server ended before answering request {message_id}")


def app_server_calls(command: Sequence[str], env: dict, cwd: str, calls: Sequence[tuple[str, dict]], timeout: float) -> list:
    """Run one Codex app-server, send `initialize` and then each call in order, and return each call's result."""
    try:
        child = subprocess.Popen(
            list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace", cwd=cwd, env=env, start_new_session=True,
        )
    except OSError as error:
        raise TrustError(f"cannot start codex app-server: {error}") from error

    def kill() -> None:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    timer = threading.Timer(timeout, kill)
    timer.start()
    try:
        def send(message: dict) -> None:
            child.stdin.write(json.dumps(message) + "\n")
            child.stdin.flush()

        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "codex_hook_trust", "version": "1"}}})
        _read_reply(child.stdout, 1)
        send({"method": "initialized"})
        results = []
        for index, (method, params) in enumerate(calls, start=2):
            send({"id": index, "method": method, "params": params})
            results.append(_read_reply(child.stdout, index).get("result"))
        return results
    except OSError as error:
        raise TrustError(f"codex app-server connection failed: {error}") from error
    finally:
        timer.cancel()
        kill()
        for stream in (child.stdin, child.stdout):
            try:
                stream.close()
            except OSError:
                pass
        child.wait()


def listed_hooks(result: object, cwd: str) -> list:
    data = result.get("data") if isinstance(result, dict) else None
    wanted = Path(cwd).resolve()
    for entry in data if isinstance(data, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("cwd"), str) and Path(entry["cwd"]).resolve() == wanted:
            hooks = entry.get("hooks")
            return hooks if isinstance(hooks, list) else []
    raise TrustError(f"codex app-server listed no hooks entry for {cwd}")


def heal(hooks: Sequence[object], command: Sequence[str], env: dict, cwd: str, timeout: float) -> list:
    """Trust this plugin's untrusted hooks from a verified official copy and return the hooks Codex lists afterwards.

    Raise TrustError when there is nothing to trust, the copy fails verification, a write fails, or any of those hooks
    is still untrusted afterwards."""
    targets = candidates(hooks)
    if not targets:
        raise TrustError(f"no untrusted {PLUGIN_ID} hooks to trust")
    verify_checkout(plugin_root(targets))
    calls = [("config/value/write", params) for params in trust_writes(targets)]
    results = app_server_calls(command, env, cwd, [*calls, ("hooks/list", {"cwds": [cwd]})], timeout)
    after = listed_hooks(results[-1], cwd)
    keys = {hook["key"] for hook in targets}
    trusted = {hook.get("key") for hook in after if isinstance(hook, dict) and hook.get("trustStatus") == "trusted"}
    if not keys <= trusted:
        raise TrustError(f"Codex still lists {len(keys - trusted)} {PLUGIN_ID} hooks as untrusted")
    return after
