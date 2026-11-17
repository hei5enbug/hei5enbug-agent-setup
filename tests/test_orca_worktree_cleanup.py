"""The Orca status hook removes a finished child worktree its session created, in a detached run, and never otherwise."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
HOOK = SCRIPTS / "orca_status_hook.py"
SETUP = REPO_ROOT / "evals" / "e2e" / "tasks" / "setup"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SETUP))
import handoff_common  # noqa: E402
import orca_cleanup_state  # noqa: E402
import orca_status_hook  # noqa: E402

SESSION = "s1"
BRANCH = "feature/ABC-123"
IGNORED = "build/\nnode_modules/\n.env\n"
SHELL_LINE = "user@host demo %"


def git(path, *arguments):
    done = subprocess.run(["git", "-C", str(path), *arguments], capture_output=True, text=True, check=False)
    return done.stdout.strip()


class World:
    """Demo-a's main clone with a fake Orca, a hook environment, and helpers that play the session."""

    def __init__(self, base: Path):
        self.repo = base / "work" / "repo"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("# demo-a\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=Demo", "-c", "user.email=demo@example.com", "commit", "-q", "-m", "Initial")
        handoff_common.build(str(self.repo))
        self.work = self.repo.parent
        self.state_dir = base / "xdg"
        self.processes: list[subprocess.Popen] = []
        self.env = {
            "PATH": f"{self.work / 'fake-bin'}:{os.environ['PATH']}", "HOME": str(base / "home"),
            "XDG_STATE_HOME": str(self.state_dir), "ORCA_TERMINAL_HANDLE": "term_demo_a",
            "ORCA_USER_DATA_PATH": str(base / "orca-user-data"),
            "FAKE_ORCA_STATE": str(self.work / "orca-state" / "state.json"), "HEI5ENBUG_CLEANUP_STEP_SECONDS": "3",
        }

    def orca(self, *arguments, cwd=None, env=None):
        done = subprocess.run([str(self.work / "fake-bin" / "orca"), *arguments, "--json"], cwd=cwd or self.repo,
                              env={**os.environ, **self.env, **(env or {})}, capture_output=True, text=True)
        return json.loads(done.stdout)

    def state(self) -> dict:
        return json.loads((self.work / "orca-state" / "state.json").read_text(encoding="utf-8"))

    def save_state(self, state: dict) -> None:
        (self.work / "orca-state" / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def calls(self) -> list[list[str]]:
        path = self.work / "orca-state" / "calls.jsonl"
        return [json.loads(line)["argv"] for line in path.read_text().splitlines()] if path.exists() else []

    def hook_state_path(self) -> Path:
        return self.state_dir / "hei5enbug-agent-setup" / "orca-status" / f"{SESSION}.json"

    def result(self) -> dict:
        return orca_cleanup_state.read_results(orca_cleanup_state.result_path(self.hook_state_path()))

    def fire(self, event: str, command: str | None = None, cwd=None, env=None, timeout: float = 30):
        payload = {"hook_event_name": event, "session_id": SESSION, "cwd": str(cwd or self.repo)}
        if event == "PostToolUse":
            payload.update({"tool_name": "Bash", "tool_input": {"command": command}, "tool_response": {"stdout": ""}})
        start = time.monotonic()
        done = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(payload), capture_output=True,
                              text=True, env={**os.environ, **self.env, **(env or {})}, timeout=timeout)
        output = json.loads(done.stdout) if done.stdout.strip() else {}
        return SimpleNamespace(output=output, seconds=time.monotonic() - start, code=done.returncode,
                               error=done.stderr)

    def wait_run(self, seconds: float = 40) -> None:
        lock = orca_cleanup_state.lock_path(self.hook_state_path())
        deadline = time.monotonic() + seconds
        while lock.exists() and orca_cleanup_state.lock_is_live(lock):
            assert time.monotonic() < deadline, "the cleanup run did not end"
            time.sleep(0.1)

    def end_turn(self, **options):
        self.fire("Stop", **options)
        self.wait_run()

    def create(self, name="ABC-123", repo="demo-b", branch=BRANCH, agent=False, record=True, extra=""):
        command = f"orca worktree create --repo id:{repo} --name {name} --branch {branch}"
        command += " --agent claude" if agent else ""
        command += extra
        wt = self.orca(*command.split()[1:])["result"]["worktree"]
        if record:
            self.fire("PostToolUse", f"{command} --json")
        return wt

    def work_in(self, wt: dict, record=True) -> None:
        (Path(wt["path"]) / ".gitignore").write_text(IGNORED, encoding="utf-8")
        command = f"orca orchestration worker-start --worktree id:{wt['id']} --agent claude --spec work"
        self.orca(*command.split()[1:])
        if record:
            self.fire("PostToolUse", f"{command} --json")
        (Path(wt["path"]) / "build").mkdir()
        (Path(wt["path"]) / "build" / "out.txt").write_text("x", encoding="utf-8")
        (Path(wt["path"]) / "node_modules").mkdir()
        (Path(wt["path"]) / "node_modules" / "m.js").write_text("x", encoding="utf-8")

    def r1(self, **options) -> dict:
        wt = self.create(**options)
        self.work_in(wt)
        return wt

    def present(self, wt: dict) -> bool:
        return Path(wt["path"]).exists() and any(item["id"] == wt["id"] for item in self.state()["worktrees"])

    def local_branch(self, wt: dict) -> str:
        main = Path(wt["path"]).parent / Path(wt["path"]).name.split("-")[0]
        return git(main, "branch", "--list", BRANCH)

    def remote_branch(self) -> str:
        return git(self.work / "demo-b-origin.git", "branch", "--list", BRANCH)

    def terminals(self) -> set[str]:
        return {item["handle"] for item in self.state()["terminals"]}

    def edit_terminal(self, handle: str, **fields) -> None:
        state = self.state()
        next(item for item in state["terminals"] if item["handle"] == handle).update(fields)
        self.save_state(state)

    def add_terminal(self, terminal: dict) -> None:
        state = self.state()
        state["terminals"].append(terminal)
        self.save_state(state)

    def shell_handles(self, wt: dict) -> list[str]:
        return [item["handle"] for item in self.state()["terminals"] if item["worktreeId"] == wt["id"]]

    def reasons(self) -> dict[str, str | None]:
        return {key: entry.get("check") for key, entry in self.result()["entries"].items()}

    def close(self) -> None:
        for process in self.processes:
            process.kill()
            process.wait()


@pytest.fixture
def world(tmp_path):
    instance = World(tmp_path)
    yield instance
    instance.close()


def test_종료된_워커가_푸시한_작업은_턴이_끝나면_셸_터미널과_워크트리와_로컬_브랜치가_사라지고_원격_브랜치는_남는다(world):
    # given
    wt = world.r1()
    shell = world.shell_handles(wt)
    # when
    world.end_turn()
    # then
    assert shell and not set(shell) & world.terminals()
    assert not world.present(wt) and world.local_branch(wt) == ""
    assert BRANCH in world.remote_branch()
    assert (world.repo.parent / "demo-b").is_dir() and world.repo.is_dir()


def test_제거하면_사용자에게_한_줄을_먼저_보이고_다음_프롬프트의_맥락에_같은_내용을_한_번만_더한다(world):
    # given
    world.r1()
    world.end_turn()
    # when
    first = world.fire("PostToolUse", "ls")
    prompt = world.fire("UserPromptSubmit")
    again = world.fire("UserPromptSubmit")
    # then
    line = first.output["systemMessage"]
    assert BRANCH in line and "demo-b" in line and f"origin/{BRANCH}" in line and "deleted the local branch" in line
    assert "additionalContext" not in json.dumps(first.output)
    context = prompt.output["hookSpecificOutput"]["additionalContext"]
    assert BRANCH in context and f"origin/{BRANCH}" in context and "systemMessage" not in prompt.output
    assert "Orca cleanup" not in json.dumps(again.output)


def test_워커의_터미널이_열려_있으면_작업이_끝나_보여도_아무것도_닫거나_지우지_않는다(world):
    # given
    wt = world.r1()
    world.add_terminal({"handle": "term_worker", "worktreeId": wt["id"], "title": "claude", "agentIdentity": "claude"})
    before = set(world.shell_handles(wt))
    # when
    world.end_turn()
    # then
    assert world.present(wt) and set(world.shell_handles(wt)) == before
    assert "agent-open" in world.reasons().values()


def test_Dispatch가_실패했거나_읽을_수_없으면_워크트리를_지키고_터미널도_닫지_않는다(world):
    # given
    wt = world.r1()
    state = world.state()
    state["dispatches"][0]["state"] = "failed"
    world.save_state(state)
    before = set(world.shell_handles(wt))
    # when
    world.end_turn()
    # then
    assert world.present(wt) and set(world.shell_handles(wt)) == before
    assert "dispatch" in world.reasons().values()


@pytest.mark.parametrize(("setup", "check"), [
    ("unpushed", "unpushed"), ("dirty", "uncommitted"), ("no_upstream", "no-upstream"),
])
def test_푸시하지_않은_커밋과_커밋하지_않은_변경과_업스트림_없는_브랜치는_각각_그_검사_이름으로_지켜진다(world, setup, check):
    # given
    wt = world.r1()
    path = Path(wt["path"])
    if setup == "unpushed":
        (path / "more.txt").write_text("m", encoding="utf-8")
        git(path, "add", "-A")
        git(path, "-c", "user.name=D", "-c", "user.email=d@example.com", "commit", "-q", "-m", "more")
    elif setup == "dirty":
        (path / "wip.txt").write_text("w", encoding="utf-8")
    else:
        git(path, "branch", "--unset-upstream")
    # when
    world.end_turn()
    # then
    assert world.present(wt)
    assert check in world.reasons().values()


def test_정해진_목록에_없는_무시_파일은_이름을_밝히고_지키며_파일은_그대로_둔다(world):
    # given
    wt = world.r1()
    env_file = Path(wt["path"]) / ".env"
    env_file.write_text("SECRET=demo\n", encoding="utf-8")
    # when
    world.end_turn()
    # then
    assert world.present(wt) and env_file.read_text(encoding="utf-8") == "SECRET=demo\n"
    notice = [item["text"] for item in world.result()["notices"]]
    assert "ignored" in world.reasons().values() and any(".env" in text for text in notice)


@pytest.mark.parametrize("screen", [
    [f"{SHELL_LINE} git status", SHELL_LINE],
    [f"{SHELL_LINE} git sta"],
])
def test_셸_터미널에_이전_명령이나_입력_중인_글자가_있으면_어떤_터미널도_닫지_않고_지킨다(world, screen):
    # given
    wt = world.r1()
    handle = world.shell_handles(wt)[0]
    world.edit_terminal(handle, screen=screen, stream=screen)
    world.add_terminal({"handle": "term_idle", "worktreeId": wt["id"], "title": "zsh", "screen": [SHELL_LINE],
                        "stream": [SHELL_LINE]})
    # when
    world.end_turn()
    # then
    assert world.present(wt) and {handle, "term_idle"} <= world.terminals()
    assert "terminal" in world.reasons().values()


def test_작업_폴더에서_도는_프로세스나_열린_포트가_있으면_셸_터미널은_닫아도_워크트리는_지킨다(world):
    # given
    wt = world.r1()
    world.processes.append(subprocess.Popen(["sleep", "60"], cwd=wt["path"]))
    # when
    world.end_turn()
    # then
    assert world.present(wt) and world.shell_handles(wt) == []
    assert "process" in world.reasons().values()


def test_열린_포트가_있으면_워크트리를_지킨다(world):
    # given
    wt = world.r1()
    state = world.state()
    state["ports"] = [{"worktreeId": wt["id"], "port": 3000}]
    world.save_state(state)
    # when
    world.end_turn()
    # then
    assert world.present(wt) and "listener" in world.reasons().values()


def test_Orca가_실패하면_아무것도_닫거나_지우지_않고_훅은_제한_시간_안에_끝난다(world):
    # given
    wt = world.r1()
    before = set(world.shell_handles(wt))
    # when
    fired = world.fire("Stop", env={"FAKE_ORCA_FAIL": "1"})
    world.wait_run()
    # then
    assert fired.code == 0 and fired.seconds < 5
    assert world.present(wt) and set(world.shell_handles(wt)) == before


def test_git_fetch가_실패하거나_끝나지_않으면_아무것도_닫지_않고_훅은_제한_시간_안에_끝난다(world, tmp_path):
    # given
    wt = world.r1()
    real_git = shutil.which("git")
    stub = tmp_path / "stub-bin"
    stub.mkdir()
    (stub / "git").write_text(
        f'#!/bin/sh\ncase " $* " in *" fetch "*) exec sleep 30;; esac\nexec {real_git} "$@"\n', encoding="utf-8")
    (stub / "git").chmod(0o755)
    before = set(world.shell_handles(wt))
    # when
    fired = world.fire("Stop", env={"PATH": f"{stub}:{world.env['PATH']}", "HEI5ENBUG_CLEANUP_STEP_SECONDS": "1"})
    world.wait_run()
    # then
    assert fired.code == 0 and fired.seconds < 5
    assert world.present(wt) and set(world.shell_handles(wt)) == before
    assert world.reasons()["1"] == "git"


def test_git_fetch가_실패하면_워크트리를_지키고_터미널을_닫지_않는다(world):
    # given
    wt = world.r1()
    git(wt["path"], "remote", "set-url", "origin", "/nonexistent/origin.git")
    before = set(world.shell_handles(wt))
    # when
    world.end_turn()
    # then
    assert world.present(wt) and set(world.shell_handles(wt)) == before
    assert "fetch" in world.reasons().values()


def test_에이전트가_돌지_않은_워크트리와_다른_세션이_만든_워크트리는_푸시되어_깨끗해도_건드리지_않는다(world):
    # given
    other = world.create(name="ABC-125", branch="feature/ABC-125", record=False)
    git(other["path"], "push", "-q", "-u", "origin", "feature/ABC-125")
    state = world.state()
    next(item for item in state["worktrees"] if item["id"] == other["id"])["lineage"]["createdAt"] -= 3_600_000
    world.save_state(state)
    quiet = world.create(name="ABC-124", branch="feature/ABC-124")
    git(quiet["path"], "push", "-q", "-u", "origin", "feature/ABC-124")
    # when
    world.end_turn()
    # then
    assert world.present(quiet) and world.present(other)
    assert world.result()["entries"]["1"]["state"] == "left"


def test_제거한_브랜치에_같은_세션이_워크트리를_다시_만들면_이후_모든_이벤트에서_지켜진다(world):
    # given
    first = world.r1()
    world.end_turn()
    again = world.create(extra=f" --base-branch origin/{BRANCH}")
    world.work_in(again)
    # when
    world.end_turn()
    world.end_turn()
    world.fire("UserPromptSubmit")
    # then
    assert not world.present(first) or world.present(again)
    assert world.present(again) and "created-again" in world.reasons().values()


def test_주_클론과_세션이_일하는_워크트리와_자식이_있는_워크트리는_상태에_이름이_있어도_지워지지_않는다(world):
    # given
    own = world.r1()
    parent = world.create(name="ABC-130", branch="feature/ABC-130", record=False)
    child = world.create(name="ABC-131", branch="feature/ABC-131", record=False,
                         extra=f" --parent-worktree id:{parent['id']}")
    state = world.state()
    main = next(item for item in state["worktrees"] if item["repoId"] == "demo-b" and item["isMainWorktree"])
    for item in state["worktrees"]:
        if item["id"] == child["id"]:
            item["lineage"]["createdAt"] -= 3_600_000
    world.save_state(state)
    path = world.hook_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    creates = [{"seq": index, "repo": None, "agent": True, "worker": False, "start": 0, "end": 1}
               for index in (10, 11, 12)]
    path.write_text(json.dumps({"creates": creates, "agents": [], "seq": 12}), encoding="utf-8")
    seeded = {"entries": {"10": {"state": "pending", "worktree_id": main["id"]},
                          "11": {"state": "pending", "worktree_id": own["id"]},
                          "12": {"state": "pending", "worktree_id": parent["id"]}}, "notices": [], "removed": []}
    orca_cleanup_state.write_results(orca_cleanup_state.result_path(path), seeded)
    # when
    world.fire("Stop", cwd=own["path"])
    world.wait_run()
    # then
    assert world.present(own) and world.present(parent) and world.present(child)
    assert (world.repo.parent / "demo-b").is_dir()
    assert {key: world.reasons()[key] for key in ("10", "11", "12")} == {
        "10": "main-clone", "11": "own-worktree", "12": "has-children"}


def test_만든_워크트리가_없는_세션과_이전_실행이_아직_도는_세션은_프롬프트와_턴_끝에서_프로세스를_시작하지_않는다(world, monkeypatch):
    # given
    started = []
    monkeypatch.setattr(orca_cleanup_state.subprocess, "Popen", lambda *args, **kwargs: started.append(args))
    monkeypatch.setenv("XDG_STATE_HOME", str(world.state_dir))
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_demo_a")
    monkeypatch.setenv("ORCA_USER_DATA_PATH", str(world.state_dir / "orca-user-data"))
    state = orca_status_hook.State.load(SESSION)
    # when
    for name in ("UserPromptSubmit", "Stop"):
        orca_status_hook.cleanup_step(name, {"cwd": str(world.repo)}, state)
    state.creates = [{"seq": 1, "repo": None, "agent": True, "worker": False, "start": 0, "end": 1}]
    state.save()
    lock = orca_cleanup_state.lock_path(state.path)
    lock.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}), encoding="utf-8")
    for name in ("UserPromptSubmit", "Stop"):
        orca_status_hook.cleanup_step(name, {"cwd": str(world.repo)}, state)
    assert started == []
    lock.unlink()
    monkeypatch.delenv("ORCA_USER_DATA_PATH")
    orca_status_hook.cleanup_step("Stop", {"cwd": str(world.repo)}, state)
    ungated = len(started)
    monkeypatch.setenv("ORCA_USER_DATA_PATH", str(world.state_dir / "orca-user-data"))
    orca_status_hook.cleanup_step("Stop", {"cwd": str(world.repo)}, state)
    # then
    assert ungated == 0 and len(started) == 1


def test_한_명령에서_같은_저장소에_워크트리_둘을_만들었거나_명령_시간에_만든_것이_없으면_아무것도_기록하거나_지우지_않는다(world):
    # given
    first = world.create(name="ABC-140", branch="feature/ABC-140", record=False)
    second = world.create(name="ABC-141", branch="feature/ABC-141", record=False)
    both = (f"orca worktree create --repo id:demo-b --name ABC-140 && "
            f"orca worktree create --repo id:demo-b --name ABC-141")
    world.fire("PostToolUse", both)
    world.fire("PostToolUse", "orca worktree create --repo id:demo-a --name ABC-142 --branch feature/ABC-142")
    # when
    world.end_turn()
    # then
    assert world.present(first) and world.present(second)
    assert {entry["state"] for entry in world.result()["entries"].values()} == {"none"}


def test_출력을_다른_프로그램으로_넘긴_명령도_같은_방식으로_기록되어_제거된다(world):
    # given
    command = f"orca worktree create --repo id:demo-b --name ABC-123 --branch {BRANCH} --json | python3 -c pass"
    wt = world.orca(*command.split("|")[0].split()[1:])["result"]["worktree"]
    world.fire("PostToolUse", command)
    world.work_in(wt)
    # when
    world.end_turn()
    # then
    assert not world.present(wt)


def test_세션_터미널이_훅이_프로세스를_시작한_직후_닫혀도_정리는_끝까지_진행되어_워크트리가_제거된다(world):
    # given
    wt = world.r1()
    payload = json.dumps({"hook_event_name": "Stop", "session_id": SESSION, "cwd": str(world.repo)})
    terminal = subprocess.Popen(["sh", "-c", f'"{sys.executable}" -B "{HOOK}"; sleep 60'], stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, env={**os.environ, **world.env}, start_new_session=True,
                                text=True)
    terminal.stdin.write(payload)
    terminal.stdin.close()
    lock = orca_cleanup_state.lock_path(world.hook_state_path())
    deadline = time.monotonic() + 20
    while not (lock.exists() and (json.loads(lock.read_text() or "{}").get("pid"))):
        assert time.monotonic() < deadline
        time.sleep(0.02)
    # when
    os.killpg(terminal.pid, signal.SIGKILL)
    terminal.wait()
    world.wait_run()
    # then
    assert not world.present(wt)


def test_정리_실행이_셸_터미널을_닫은_직후_끝나도_워크트리는_온전하고_다음_실행이_마무리한다(world):
    # given
    wt = world.r1()
    state = world.state()
    state["kill_parent_on_close"] = True
    world.save_state(state)
    # when
    world.end_turn()
    halted = (world.present(wt), world.shell_handles(wt))
    world.end_turn()
    # then
    assert halted == (True, [])
    assert not world.present(wt)


def test_기록은_worktree_create와_worker_start와_terminal_create를_읽고_변수가_든_선택자와_현재_워크트리는_버린다():
    # given
    commands = [
        "orca worktree create --repo id:demo-b --name a --agent claude",
        "orca orchestration worker-start --worktree new-child --repo id:demo-b --agent codex --spec x",
        "orca orchestration worker-start --worktree id:r::/p --agent claude --spec x",
        "orca terminal create --worktree id:r::/p --command 'cd /p && claude'",
        "orca terminal create --worktree id:r::/p --command 'npm test'",
        "orca orchestration worker-start --worktree current --agent claude --spec x",
        "orca worktree create --repo $REPO --name a",
        "orca orchestration worker-start --worktree $WT --agent claude --spec x",
    ]
    # when
    parsed = [orca_cleanup_state.parse_command(command) for command in commands]
    # then
    assert parsed[0] == ([{"repo": "id:demo-b", "agent": True, "worker": False}], [])
    assert parsed[1] == ([{"repo": "id:demo-b", "agent": True, "worker": True}], [])
    assert parsed[2] == ([], [{"selector": "id:r::/p", "worker": True}])
    assert parsed[3] == ([], [{"selector": "id:r::/p", "worker": False}])
    assert parsed[4] == ([], [])
    assert parsed[5] == ([], [])
    assert parsed[6] == ([{"repo": None, "agent": False, "worker": False}], [])
    assert parsed[7] == ([], [])


def test_정리_실행은_Orca나_git이_멈춰도_정해진_시간_안에_스스로_끝나고_시작한_자식도_남기지_않는다(world, tmp_path):
    # given
    wt = world.r1()
    real_git = shutil.which("git")
    stub = tmp_path / "stub-bin"
    stub.mkdir()
    (stub / "git").write_text(
        f'#!/bin/sh\ncase " $* " in *" fetch "*) exec sleep 31.5;; esac\nexec {real_git} "$@"\n', encoding="utf-8")
    (stub / "git").chmod(0o755)
    bound = 2.0
    environment = {"PATH": f"{stub}:{world.env['PATH']}", "HEI5ENBUG_CLEANUP_STEP_SECONDS": "30",
                   "HEI5ENBUG_CLEANUP_RUN_SECONDS": str(bound)}
    lock = orca_cleanup_state.lock_path(world.hook_state_path())
    # when
    world.fire("Stop", env=environment)
    started = time.monotonic()
    deadline = started + bound + 4
    while lock.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    ended = time.monotonic() - started
    alive = subprocess.run(["pgrep", "-f", "sleep 31.5"], capture_output=True, text=True).stdout.split()
    # then
    assert not lock.exists() and ended < bound + 3
    assert alive == [] and world.present(wt)
