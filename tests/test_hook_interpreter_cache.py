import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PYTHON = os.path.realpath(sys.executable)
EVENT = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/tmp/work",
                    "tool_input": {"command": "git push origin demo-a"}})


@pytest.fixture
def box(tmp_path):
    scripts = tmp_path / "plugin" / "scripts"
    shutil.copytree(REPO_ROOT / "scripts", scripts, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "state").mkdir()
    return tmp_path


def shim(directory, marker, resolver_marker=None, delay=2, resolves=True, root_only=False):
    """A python3 stand-in that sleeps, records each run, and runs the real interpreter; the resolver call is told apart.

    With `root_only`, the resolver call answers only when it runs from the root folder, as a version manager's shim
    answers with the user's default there and with a project's version elsewhere.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "python3"
    resolver = resolver_marker or marker
    answer = f'exec "{REAL_PYTHON}" "$@"' if resolves else "exit 1"
    if root_only:
        answer = f'if [ "$(pwd)" = / ]; then {answer}; else exit 1; fi'
    path.write_text(
        f'#!/bin/sh\nsleep {delay}\nif [ "$1" = "-E" ]; then echo x >> "{resolver}"; {answer}; fi\n'
        f'echo x >> "{marker}"\nexec "{REAL_PYTHON}" "$@"\n', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def run_hook(box, bin_dir, script="required_checks_hook.py", event=EVENT, state=True, **env):
    environment = {"PATH": f"{bin_dir}:/usr/bin:/bin", **env}
    if state:
        environment["XDG_STATE_HOME"] = str(box / "state")
    start = time.monotonic()
    result = subprocess.run(["sh", str(box / "plugin" / "scripts" / "hook_python.sh"), script], input=event,
                            text=True, capture_output=True, env=environment, timeout=60, cwd=box)
    return result, time.monotonic() - start


def cache_dir(box):
    return box / "state" / "hei5enbug-agent-setup" / "interpreter"


def wait_resolved(box, timeout=20):
    deadline = time.monotonic() + timeout
    folder = cache_dir(box)
    while time.monotonic() < deadline:
        settled = (folder / "cache").exists() and (folder / "verified").exists() or (folder / "failed").exists()
        if folder.is_dir() and not (folder / "lock").exists() and settled:
            return
        time.sleep(0.1)
    raise AssertionError("the background resolution did not finish")


def count(path):
    return len(path.read_text().splitlines()) if path.exists() else 0


def test_캐시가_없으면_첫_훅은_캐시된_실행과_같은_속도로_python3으로_실행되고_해결이_끝난_뒤의_세_번은_shim을_거치지_않는다(box):
    # given
    marker = box / "marker"
    bin_dir = box / "bin"
    shim(bin_dir, marker, delay=1)
    uncached, uncached_seconds = run_hook(box, bin_dir, state=False)
    marker.unlink()
    # when
    first, first_seconds = run_hook(box, bin_dir)
    wait_resolved(box)
    after_resolution = count(marker)
    later = [run_hook(box, bin_dir) for _ in range(3)]
    # then
    assert first.stdout == uncached.stdout != "" and first.returncode == 0
    assert first_seconds <= uncached_seconds + 0.5
    cache = (cache_dir(box) / "cache").read_text().splitlines()
    assert cache == [str(bin_dir / "python3"), REAL_PYTHON]
    assert after_resolution >= 1
    assert count(marker) == after_resolution
    assert all(result.stdout == uncached.stdout and seconds < 1.5 for result, seconds in later)


def test_다른_python3이_PATH_앞에_오거나_캐시가_지워지면_다시_해결한다(box):
    # given
    marker = box / "marker"
    first_bin, second_bin = box / "bin1", box / "bin2"
    shim(first_bin, marker, delay=0.2)
    shim(second_bin, marker, delay=0.2)
    run_hook(box, first_bin)
    wait_resolved(box)
    # when
    run_hook(box, second_bin)
    wait_resolved(box, 20)
    switched = (cache_dir(box) / "cache").read_text().splitlines()[0]
    (cache_dir(box) / "cache").unlink()
    run_hook(box, second_bin)
    wait_resolved(box)
    # then
    assert switched == str(second_bin / "python3")
    assert (cache_dir(box) / "cache").read_text().splitlines()[0] == str(second_bin / "python3")


def test_해결이_실패하면_훅은_PATH의_python3으로_실행되고_캐시는_쓰지_않으며_재시도는_분당_한_번이다(box):
    # given
    marker, resolver = box / "marker", box / "resolver"
    bin_dir = box / "bin"
    shim(bin_dir, marker, resolver, delay=0.1, resolves=False)
    # when
    first, _ = run_hook(box, bin_dir)
    wait_resolved(box)
    attempts_after_first = count(resolver)
    second, _ = run_hook(box, bin_dir)
    time.sleep(1.0)
    attempts_after_second = count(resolver)
    old = time.time() - 120
    os.utime(cache_dir(box) / "failed", (old, old))
    run_hook(box, bin_dir)
    deadline = time.monotonic() + 15
    while count(resolver) < 2 and time.monotonic() < deadline:
        time.sleep(0.1)
    # then
    assert first.returncode == second.returncode == 0 and first.stdout == second.stdout != ""
    assert not (cache_dir(box) / "cache").exists()
    assert attempts_after_first == attempts_after_second == 1
    assert count(resolver) == 2


def test_잠금을_쥔_프로세스가_살아_있으면_해결을_시작하지_않고_죽었으면_잠금을_넘겨받는다(box):
    # given
    marker, resolver = box / "marker", box / "resolver"
    bin_dir = box / "bin"
    shim(bin_dir, marker, resolver, delay=0.1)
    cache_dir(box).mkdir(parents=True)
    lock = cache_dir(box) / "lock"
    old = time.time() - 600
    lock.write_text(f"{os.getpid()}\n")
    os.utime(lock, (old, old))
    # when
    run_hook(box, bin_dir)
    time.sleep(1.0)
    held = count(resolver)
    finished = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    lock.write_text(finished.stdout)
    run_hook(box, bin_dir)
    wait_resolved(box)
    # then
    assert held == 0
    assert (cache_dir(box) / "cache").exists() and count(resolver) == 1
    assert not lock.exists()


def test_캐시가_해결기가_쓴_뒤_다시_쓰였거나_확인_파일이_없으면_실행하지_않고_다시_해결한다(box):
    # given
    marker, resolver = box / "marker", box / "resolver"
    bin_dir = box / "bin"
    shim(bin_dir, marker, resolver, delay=0.1)
    run_hook(box, bin_dir)
    wait_resolved(box)
    folder = cache_dir(box)
    trap = box / "ran"
    stub = box / "stub"
    stub.write_text(f'#!/bin/sh\necho x >> "{trap}"\nexec "{REAL_PYTHON}" "$@"\n', encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    past = time.time() - 30
    os.utime(folder / "verified", (past, past))
    (folder / "cache").write_text(f"{bin_dir / 'python3'}\n{stub}\n")
    resolved_before = count(resolver)
    # when
    rewritten, _ = run_hook(box, bin_dir)
    wait_resolved(box)
    os.utime(folder / "verified", (past, past))
    (folder / "cache").write_text(f"{bin_dir / 'python3'}\n{stub}\n")
    (folder / "verified").unlink()
    unmarked, _ = run_hook(box, bin_dir)
    wait_resolved(box)
    # then
    assert not trap.exists()
    assert rewritten.stdout != "" and unmarked.stdout != ""
    assert count(resolver) == resolved_before + 2


def test_프로젝트의_버전_파일이_있는_폴더에서_시작해도_해결은_루트_폴더에서_기본_인터프리터로_한다(box):
    # given
    marker, resolver = box / "marker", box / "resolver"
    bin_dir = box / "bin"
    shim(bin_dir, marker, resolver, delay=0.1, root_only=True)
    (box / ".python-version").write_text("3.11\n")
    # when
    result, _ = run_hook(box, bin_dir)
    wait_resolved(box)
    # then
    assert result.returncode == 0 and result.stdout != ""
    assert (cache_dir(box) / "cache").read_text().splitlines() == [str(bin_dir / "python3"), REAL_PYTHON]


def test_실패_표시가_신선하면_동시에_시작한_두_해결기_중_하나만_해결을_시도한다(box):
    # given
    marker, resolver = box / "marker", box / "resolver"
    bin_dir = box / "bin"
    shim(bin_dir, marker, resolver, delay=0.3, resolves=False)
    # when
    results = [run_hook(box, bin_dir)[0] for _ in range(3)]
    wait_resolved(box)
    time.sleep(1.0)
    # then
    assert all(result.returncode == 0 and result.stdout != "" for result in results)
    assert count(resolver) == 1


def test_설정된_인터프리터가_유효하면_캐시를_보지도_만들지도_않는다(box):
    # given
    marker = box / "marker"
    bin_dir = box / "bin"
    shim(bin_dir, marker, delay=0.1)
    # when
    result, _ = run_hook(box, bin_dir, HEI5ENBUG_PYTHON=REAL_PYTHON)
    time.sleep(0.5)
    # then
    assert result.returncode == 0 and result.stdout != ""
    assert not cache_dir(box).exists() and not marker.exists()


def test_캐시_파일이_그룹이나_다른_사용자에게_쓰기_가능하면_훅이_시작할_때_지운다(box):
    # given
    marker = box / "marker"
    bin_dir = box / "bin"
    shim(bin_dir, marker, delay=0.1)
    run_hook(box, bin_dir)
    wait_resolved(box)
    cache = cache_dir(box) / "cache"
    cache.chmod(0o666)
    # when
    run_hook(box, bin_dir)
    # then
    assert not cache.exists() or cache.stat().st_mode & 0o022 == 0


def test_느린_shim과_차가운_캐시에서도_orca_배치_훅은_절반_시간_안에_돌아온다(box):
    # given
    marker = box / "marker"
    bin_dir = box / "bin"
    shim(bin_dir, marker, delay=2)
    orca = bin_dir / "orca"
    orca.write_text('#!/bin/sh\necho \'{"ok": true, "result": {"worktrees": []}}\'\n', encoding="utf-8")
    orca.chmod(orca.stat().st_mode | stat.S_IXUSR)
    event = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(box),
                        "tool_input": {"command": "orca worktree set --worktree demo-a --display-name demo-title"}})
    # when
    result, seconds = run_hook(box, bin_dir, "orca_placement_hook.py", event)
    # then
    assert result.returncode == 0
    assert seconds < 2.5 + 1.0


def test_런처는_빈_PATH_항목이나_상대_PATH_항목이_앞서면_캐시를_쓰지_않는다(box):
    # given
    marker = box / "marker"
    bin_dir = box / "bin"
    shim(bin_dir, marker, delay=0.1)
    # when
    result = subprocess.run(
        ["sh", str(box / "plugin" / "scripts" / "hook_python.sh"), "required_checks_hook.py"], input=EVENT,
        text=True, capture_output=True, timeout=60, cwd=box,
        env={"PATH": f"relative:{bin_dir}:/usr/bin:/bin", "XDG_STATE_HOME": str(box / "state")})
    time.sleep(0.5)
    # then
    assert result.returncode == 0 and result.stdout != ""
    assert not cache_dir(box).exists()


def test_인터프리터_도우미는_POSIX_sh_문법이고_런처_옆에_있다():
    # given
    helper = REPO_ROOT / "scripts" / "hook_interpreter.sh"
    # when
    syntax = subprocess.run(["sh", "-n", str(helper)], capture_output=True, text=True, timeout=30)
    # then
    assert helper.is_file() and syntax.returncode == 0, syntax.stderr


@pytest.mark.parametrize("remove_helper", [False, True])
def test_런처가_실행하지_못할_때의_메시지는_플러그인과_런처와_다음_단계를_밝힌다(box, remove_helper):
    # given
    scripts = box / "plugin" / "scripts"
    if remove_helper:
        (scripts / "hook_interpreter.sh").unlink()
    # when
    result = subprocess.run(["sh", str(scripts / "hook_python.sh"), "../escape.py"], capture_output=True, text=True,
                            timeout=30, env={"PATH": "/usr/bin:/bin"})
    # then
    assert result.returncode == 1 and result.stdout == ""
    assert "hei5enbug-agent-setup" in result.stderr and "hook_python.sh" in result.stderr
    assert ("Reinstall the plugin" if remove_helper else "Fix the hook command") in result.stderr
