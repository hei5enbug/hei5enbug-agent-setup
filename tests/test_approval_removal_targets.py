"""Acceptance checks: a recursive removal resolves the variables it names across `if`, `case`, loops, and groups, and a
target that Git can restore or that Git ignores is a session write instead of an every-time ask."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402

NON_TEMPORARY_HOME = "/nonexistent-home"
NON_TEMPORARY_TMPDIR = "/nonexistent-tmpdir"
UNRESOLVED = "Recursive removal with an unresolved target"
PROTECTED = "Recursive removal of a protected or external path"
TRACKED = "Recursive removal of tracked files"
IGNORED = "Recursive removal of ignored files"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", NON_TEMPORARY_HOME)
    monkeypatch.setenv("TMPDIR", NON_TEMPORARY_TMPDIR)
    for name in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return tmp_path


def classify(command, cwd=REPO_ROOT):
    return guard.classify_text(command, str(cwd))


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", "-C", str(root), *args],
                   check=True, capture_output=True)


@pytest.fixture
def work_tree(home, monkeypatch):
    """A Git work tree outside every temporary root, with the session folder elsewhere."""
    monkeypatch.setattr(guard, "TEMPORARY_ROOTS", ("/nonexistent-temp-root",))
    session = home / "session"
    session.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(session))
    root = home / "demo"
    for name, text in (("tracked/a.txt", "a"), ("dirty/b.txt", "b"), (".gitignore", "build/\n")):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    (root / "dirty" / "b.txt").write_text("changed")
    (root / "build").mkdir()
    (root / "build" / "out.bin").write_text("out")
    (root / "scratch").mkdir()
    (root / "scratch" / "new.txt").write_text("new")
    return root


# --- 1. 앞서 대입한 변수의 해석 -------------------------------------------------------------------------------------------

def test_임시_폴더를_리터럴로_대입한_변수의_삭제는_묻지_않는다(home):
    # given
    command = 'V=/tmp/work/demo; rm -rf "$V/x"'
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.every_time is False


def test_홈과_임시_폴더_변수는_환경_값으로_해석한다(home, monkeypatch):
    # given
    monkeypatch.setenv("TMPDIR", "/tmp/work/scratch")
    commands = ['S=$TMPDIR/mrg; rm -rf "$S"', 'S=${TMPDIR:-/tmp/work/other}/mrg; rm -rf "$S"',
                'S=${TMPDIR}/mrg; rm -rf "$S"']
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert [outcome.kind for outcome in outcomes] == ["pass", "pass", "pass"]


def test_임시_폴더_변수가_없으면_기본값으로_해석한다(home, monkeypatch):
    # given
    monkeypatch.delenv("TMPDIR")
    command = 'S=${TMPDIR:-/tmp/work/other}/mrg; rm -rf "$S"'
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"


def test_홈_아래를_가리키는_변수의_삭제는_보호_경로라_매번_묻는다(home):
    # given
    commands = ['C=$HOME/x; rm -rf "$C"', 'C=~/x; rm -rf "$C"', 'C=${HOME}; rm -rf "$C/x"']
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert all(outcome.kind == "always" and outcome.every_time for outcome in outcomes)
    assert all(outcome.descriptions == [PROTECTED] for outcome in outcomes)


def test_이미_해석한_변수로_만든_변수도_해석한다(home):
    # given
    command = 'A=/tmp/work; B="$A/demo"; rm -rf "$B/x"'
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"


def test_for_반복문_변수는_글롭_단어까지_해석해_임시_폴더_삭제로_본다(home):
    # given
    command = 'V=/tmp/work/demo; for d in "$V"/*/repo; do rm -rf "$d"; done'
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.every_time is False


def test_for_반복문_값_하나라도_외부_경로면_가장_엄격한_결과로_묻는다(home):
    # given
    command = "for d in /tmp/work/a /home/test/b; do rm -rf \"$d\"; done"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.descriptions == [PROTECTED]


def test_case의_모든_갈래가_대입한_변수는_해석한다(home):
    # given
    command = 'case "$1" in a) V=/tmp/work/a;; b) V=/tmp/work/b;; *) V=/tmp/work/c;; esac; rm -rf "$V/x"'
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"


def test_case_갈래_하나가_외부_경로면_그_값으로도_분류한다(home):
    # given
    command = 'case "$1" in a) V=/tmp/work/a;; *) V=/home/test/b;; esac; rm -rf "$V/x"'
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.descriptions == [PROTECTED]


def test_if와_else가_모두_대입한_변수는_해석한다(home):
    # given
    command = 'if [ -d x ]; then V=/tmp/work/a; else V=/tmp/work/b; fi; rm -rf "$V/x"'
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("command", [
    'if [ -d x ]; then V=/tmp/work/a; fi; rm -rf "$V/x"',
    'case "$1" in a) V=/tmp/work/a;; b) V=/tmp/work/b;; esac; rm -rf "$V/x"',
    'case "$1" in a) V=/tmp/work/a;; *) :;; esac; rm -rf "$V/x"',
    '(V=/tmp/work/a); rm -rf "$V/x"',
    'V=/tmp/work/a & rm -rf "$V/x"',
    'for i in 1 2; do rm -rf "$V/x"; V=/tmp/work/a; done',
    'for i in 1 2; do V=/tmp/work/a; done; rm -rf "$V/x"',
])
def test_일부_경로에서만_대입한_변수는_해석하지_못해_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [UNRESOLVED]


@pytest.mark.parametrize("command", [
    'W=$(cat list); rm -rf "$W"',
    'W=`cat list`; rm -rf "$W"',
    'read W; rm -rf "$W"',
    'W=$((1 + 2)); rm -rf "/tmp/work/$W/$X"',
    'rm -rf "$NO_SUCH_VARIABLE/x"',
    'V=/tmp/work/a; unset V; rm -rf "$V/x"',
    'V=/tmp/work/a; eval "V=/home/test"; rm -rf "$V/x"',
    'while read d; do rm -rf "$d"; done < list',
    'for d in $(ls); do rm -rf "$d"; done',
    'f() { V=/tmp/work/a; }; rm -rf "$V/x"',
])
def test_명령_치환이나_읽기_산술_알_수_없는_변수는_해석하지_못해_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [UNRESOLVED]


def test_변수로_가리킨_보호_경로는_그대로_매번_묻는다(home):
    # given
    commands = ['V=/; rm -rf "$V"', 'V=/tmp/work/demo/.git; rm -rf "$V"', "V=/home/test/other; rm -rf \"$V\""]
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert all(outcome.kind == "always" and outcome.descriptions == [PROTECTED] for outcome in outcomes)


# --- 2. Git이 복구하거나 무시하는 작업 트리 삭제 -------------------------------------------------------------------------

def test_변경이_없는_추적_파일_삭제는_세션_쓰기다(work_tree):
    # given
    command = "rm -rf tracked"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False
    assert outcome.descriptions == [TRACKED]


def test_변경한_추적_파일_삭제는_매번_묻는다(work_tree):
    # given
    command = "rm -rf dirty"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [PROTECTED]


def test_무시된_빌드_폴더_삭제는_세션_쓰기다(work_tree):
    # given
    command = "rm -rf build"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "write"
    assert outcome.descriptions == [IGNORED]


def test_추적도_무시도_안_된_폴더_삭제는_매번_묻는다(work_tree):
    # given
    command = "rm -rf scratch"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [PROTECTED]


@pytest.mark.parametrize("command", ["rm -rf .", "rm -rf ./", "rm -rf .git", "rm -rf .git/objects", "rm -rf nothing"])
def test_작업_트리_루트와_git_폴더와_없는_경로는_매번_묻는다(work_tree, command):
    # given
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [PROTECTED]


def test_추적_파일과_무시된_폴더를_함께_지우면_두_설명을_모두_남긴다(work_tree):
    # given
    command = "rm -rf tracked build"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "write"
    assert outcome.descriptions == [TRACKED, IGNORED]


def test_복구할_수_없는_대상이_하나라도_섞이면_매번_묻는다(work_tree):
    # given
    command = "rm -rf tracked scratch"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_변수로_가리킨_추적_대상도_같은_규칙으로_분류한다(work_tree):
    # given
    named = ['V=build; rm -rf "$V"', 'V=tracked; [ -d "$V" ] && rm -rf "$V"', 'V=scratch; rm -rf "$V"']
    # when
    outcomes = [classify(command, work_tree) for command in named]
    # then
    assert [outcome.kind for outcome in outcomes] == ["write", "write", "always"]


def test_반복문_안에서는_다음_반복에서_파일이_바뀔_수_있어_Git_규칙을_적용하지_않는다(work_tree):
    # given
    command = 'for d in tracked build; do rm -rf "$d"; done'
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_다른_저장소의_추적_대상과_Git이_아닌_폴더는_매번_묻는다(work_tree):
    # given
    other = work_tree.parent / "other"
    (other / "x").mkdir(parents=True)
    (other / "x" / "a.txt").write_text("a")
    git(other, "init", "-q")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "base")
    plain = work_tree.parent / "plain"
    (plain / "1").mkdir(parents=True)
    commands = [f"rm -rf {other}/x", f'cd {plain} && for v in 1 2; do [ -d "$v" ] && rm -r "$v"; done']
    # when
    outcomes = [classify(command, work_tree) for command in commands]
    # then
    assert all(outcome.kind == "always" and outcome.descriptions == [PROTECTED] for outcome in outcomes)


def test_추적_폴더_안의_글롭_삭제도_폴더_상태로_판단한다(work_tree):
    # given
    commands = ["rm -rf tracked/*.txt", "rm -rf scratch/*.txt"]
    # when
    outcomes = [classify(command, work_tree) for command in commands]
    # then
    assert [outcome.kind for outcome in outcomes] == ["write", "always"]


def test_작업_트리_밖_경로는_Git_규칙을_적용하지_않는다(work_tree):
    # given
    outside = work_tree.parent / "elsewhere"
    outside.mkdir()
    command = f"rm -rf {outside}"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.descriptions == [PROTECTED]


def test_심볼릭_링크를_지우는_명령은_Git_규칙을_적용하지_않는다(work_tree):
    # given
    (work_tree / "link").symlink_to(work_tree / "tracked")
    command = "rm -rf link"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.descriptions == [PROTECTED]


def test_앞선_명령이_파일을_바꿀_수_있으면_Git_규칙을_적용하지_않는다(work_tree):
    # given
    command = "touch scratch/x; rm -rf tracked"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_Git이_없으면_추적_대상도_매번_묻는다(work_tree, monkeypatch):
    # given
    monkeypatch.setenv("PATH", "/nonexistent-bin")
    command = "rm -rf tracked"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_Git이_시간을_넘기면_추적_대상도_매번_묻는다(work_tree, monkeypatch):
    # given
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 3)

    monkeypatch.setattr(guard.subprocess, "run", slow)
    command = "rm -rf tracked"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_저장소를_바꾸는_Git_환경_변수가_있으면_매번_묻는다(work_tree, monkeypatch):
    # given
    monkeypatch.setenv("GIT_DIR", str(work_tree / ".git"))
    command = "rm -rf tracked"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_세션_폴더_안_삭제와_임시_폴더_삭제는_그대로_통과한다(work_tree):
    # given
    session = work_tree.parent / "session"
    (session / "out").mkdir()
    commands = ["rm -rf out", f"rm -rf {session}/out"]
    # when
    outcomes = [classify(command, session) for command in commands]
    # then
    assert [outcome.kind for outcome in outcomes] == ["pass", "pass"]


# --- 3. cd, 연산자, 리다이렉션을 지나도 해석을 유지한다 ------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    'V=/tmp/work/a; cd /tmp && rm -rf "$V/x"',
    'V=/tmp/work/a && cd /tmp && ls; rm -rf "$V/x" 2>/dev/null',
    'V=/tmp/work/a || true; rm -rf "$V/x"',
    'V=/tmp/work/a; ls | head -1; rm -rf "$V/x"',
    'V=/tmp/work/a; echo hi > /tmp/work/log; rm -rf "$V/x"',
    'V=/tmp/work/a; cd /; rm -rf "$V/x"',
    'A=/tmp/work/a && B=/tmp/work/b; rm -rf "$B/x"',
])
def test_리터럴_대입_뒤의_cd와_연산자와_리다이렉션은_해석을_유지한다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.every_time is False


def test_앞선_명령에_달린_조건부_대입은_목록_뒤에서_이전_값과_빈_값의_합집합으로_본다(home, monkeypatch):
    # given
    monkeypatch.setenv("DEMO_DIR", "/tmp/work/env")
    unset = ['cd /tmp && D=/tmp/work/a; rm -rf "$D/y"', '[ -d x ] || D=/tmp/work/a; rm -rf "$D/y"',
             '{ cd /tmp && D=/tmp/work/a; }; rm -rf "$D/y"']
    previous = ['D=/home/test/old; cd /tmp && D=/tmp/work/new; rm -rf "$D/y"']
    before_and_after = ['D=/tmp/work/old; [ -d x ] && D=/tmp/work/new; rm -rf "$D/y"',
                        'cd /tmp && DEMO_DIR=/tmp/work/a; rm -rf "$DEMO_DIR/y"']
    # when
    outcomes = [classify(command) for command in (*unset, *previous, *before_and_after)]
    # then
    assert [outcome.kind for outcome in outcomes] == ["always"] * 4 + ["pass"] * 2
    assert all(outcome.descriptions == [PROTECTED] for outcome in outcomes[:4])


def test_같은_목록에서_대입_뒤에_이어진_명령은_새_값만_본다(home):
    # given
    commands = ['cd /tmp && D=/tmp/work/a && rm -rf "$D/y"', 'A=/tmp/work/a && B=/tmp/work/b && rm -rf "$B/y"',
                'cd /tmp && cd / && D=/tmp/work/a && rm -rf "$D/y"']
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert [outcome.kind for outcome in outcomes] == ["pass", "pass", "pass"]


def test_따옴표_없이_빈_값으로_풀리는_대상은_빼고_따옴표_친_빈_대상은_아무것도_지우지_않는다(home):
    # given
    commands = ['cd /tmp && D=/tmp/work/a; rm -rf $D', 'cd /tmp && D=/tmp/work/a; rm -rf "$D"',
                'D=""; rm -rf $D', 'D=""; rm -rf "$D"', 'rm -rf ""', 'cd /tmp && D=/tmp/work/a; rm -rf $D /tmp/work/z']
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert all(outcome.kind == "pass" and outcome.every_time is False for outcome in outcomes)


def test_빈_값이_대상을_루트나_밖의_경로로_바꾸면_매번_묻는다(home):
    # given
    commands = ['cd /tmp && D=/tmp/work/a; rm -rf "$D/y"', 'cd /tmp && D=/tmp/work/a; rm -rf $D/y',
                'cd /tmp && D=/tmp/work/a; rm -rf "$D/"', 'cd /tmp && D=/tmp/work/a; rm -rf /tmp/work/z $D/y']
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert all(outcome.kind == "always" and outcome.every_time for outcome in outcomes)
    assert all(outcome.descriptions == [PROTECTED] for outcome in outcomes)


def test_조건부_대입_뒤_임시_폴더_변수는_빈_값을_빼고_해석한다(home, monkeypatch):
    # given
    monkeypatch.setenv("TMPDIR", "/tmp/work/scratch")
    with_variable = "cd /tmp && S=$TMPDIR/mrg; rm -rf $S; mkdir -p $S"
    with_default = "cd /tmp && S=${TMPDIR:-/tmp/work/other}/mrg; rm -rf $S; mkdir -p $S"
    # when
    outcomes = [classify(command) for command in (with_variable, with_default)]
    # then
    assert [outcome.kind for outcome in outcomes] == ["pass", "pass"]


def test_뒤따르는_cd는_상대_대상의_기준만_바꾼다(home):
    # given
    commands = ['V=x; cd /tmp; rm -rf "$V"', 'V=etc; cd /; rm -rf "$V"']
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert outcomes[0].kind == "pass"
    assert outcomes[1].kind == "always" and outcomes[1].descriptions == [PROTECTED]


# --- 4. 스크립트의 위치 관용구와 위치 인자 ------------------------------------------------------------------------------

def run_script(home, body, call):
    script = home / "harness" / "setup.sh"
    script.parent.mkdir(exist_ok=True)
    script.write_text("#!/bin/bash\n" + body + "\n")
    return classify(f"bash {script} {call}")


@pytest.mark.parametrize("body", [
    'EV=$(dirname "$0"); d=$EV/$1-$2; rm -rf $d; mkdir -p $d/repo',
    'EV=$(cd "$(dirname "$0")" && pwd); c=$1; v=$2; d=$EV/$c-$v; rm -rf $d; mkdir -p $d/repo',
    'EV=${BASH_SOURCE[0]%/*}; d=$EV/$1-$2; rm -rf $d',
    'd=$(dirname "$0")/$1-$2; rm -rf "$d"',
    'd=${0%/*}/$1-$2; rm -rf "$d"',
    'set -e; d=$1; rm -rf $d/x',
])
def test_스크립트_폴더와_위치_인자로_만든_삭제_대상은_해석한다(home, body):
    # given
    call = "c1 old" if "set -e" not in body else "/tmp/work/a"
    # when
    outcome = run_script(home, body, call)
    # then
    assert outcome.kind == "pass"


def test_반복문_변수를_스크립트_인자로_넘기면_가능한_값마다_해석한다(home):
    # given
    script = home / "harness" / "setup.sh"
    script.parent.mkdir()
    script.write_text('#!/bin/bash\nd=$(dirname "$0")/$1-$2\nrm -rf "$d"\n')
    safe = f"for v in old new; do bash {script} c1 $v; done"
    unsafe = f"for v in /tmp/work/a /home/test/b; do bash {script} $v x; done"
    script.write_text('#!/bin/bash\nrm -rf "$1/$2"\n')
    # when
    outcomes = [classify(safe), classify(unsafe)]
    # then
    assert outcomes[0].kind == "pass"
    assert outcomes[1].kind == "always" and outcomes[1].descriptions == [PROTECTED]


@pytest.mark.parametrize("body, call, description", [
    ('rm -rf "$1"', "/home/test/x", PROTECTED),
    ('rm -rf "$3/x"', "c1 old", PROTECTED),
    ('rm -rf "$1"', '"$(cat list)"', UNRESOLVED),
    ('rm -rf "$1"', '"$UNSET_VARIABLE"', UNRESOLVED),
    ('set -- /home/test; rm -rf "$1"', "/tmp/work/a", UNRESOLVED),
    ('while true; do shift; rm -rf "$1"; done', "/tmp/work/a /tmp/work/b", UNRESOLVED),
    ('d=$(cat "$1"); rm -rf "$d"', "list", UNRESOLVED),
])
def test_스크립트_인자를_알_수_없거나_보호_경로면_그대로_매번_묻는다(home, body, call, description):
    # given
    # when
    outcome = run_script(home, body, call)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert description in outcome.descriptions


def test_스크립트_밖의_위치_인자와_스크립트_폴더_관용구는_해석하지_않는다(home):
    # given
    commands = ['rm -rf "$1/x"', 'rm -rf "$(dirname "$0")/x"']
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert all(outcome.kind == "always" and outcome.descriptions == [UNRESOLVED] for outcome in outcomes)


def test_루프_머리는_파일이_바뀔_수_있다고_보지만_단순_검사_명령은_아니다(home):
    # given
    clean = home / "clean"
    clean.mkdir()
    (clean / "a.txt").write_text("a")
    git(clean, "init", "-q")
    git(clean, "add", "-A")
    git(clean, "commit", "-q", "-m", "base")
    plain = classify("git reset --hard", clean)
    guarded = classify("[ -d . ] && git reset --hard", clean)
    looped = classify("while true; do git reset --hard; done", clean)
    for_looped = classify("for d in a b; do git reset --hard; done", clean)
    # when
    every_time = [plain.every_time, guarded.every_time, looped.every_time, for_looped.every_time]
    # then
    assert every_time == [False, False, True, True]


# --- 5. 검토에서 나온 결함: 혼합 조건 목록, 필드 분리, 스크립트 링크, Git 설정 ----------------------------------------------

@pytest.mark.parametrize("command", [
    'D=/home/test/data; true || D=$TMPDIR/cache && rm -rf "$D"',
    'D=/home/test/data; true || D=$TMPDIR/cache; rm -rf "$D"',
    'D=/home/test/data; true && false || D=$TMPDIR/cache && rm -rf "$D"',
    'D=/home/test/data; [ -d x ] && D=$TMPDIR/cache || rm -rf "$D"',
    'D=/home/test/data; [ -d x ] || D=$TMPDIR/cache && D=$TMPDIR/other && rm -rf "$D"',
])
def test_또는이_낀_조건_목록에서는_뒤따르는_명령도_이전_값을_본다(home, monkeypatch, command):
    # given
    monkeypatch.setenv("TMPDIR", "/tmp/work")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [PROTECTED]


@pytest.mark.parametrize("command", [
    'D=/tmp/work/old; true && D=$TMPDIR/cache && rm -rf "$D"',
    'D=/home/test/data; cd /tmp && D=$TMPDIR/cache && D=$TMPDIR/other && rm -rf "$D"',
])
def test_와만_이어진_목록에서는_대입_뒤_명령이_새_값만_본다(home, monkeypatch, command):
    # given
    monkeypatch.setenv("TMPDIR", "/tmp/work")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("command", [
    'D="/tmp/work/a /home/test/x"; rm -rf $D',
    "D='/tmp/work/a /home/test/x'; rm -rf $D",
    'D=/tmp/work/a; E="$D /home/test/x"; rm -rf $E',
    'for d in "/tmp/work/a /home/test/x"; do rm -rf $d; done',
    'IFS=/; D=/tmp/work/a; rm -rf $D',
])
def test_따옴표_없는_참조는_공백에서_나뉘거나_풀지_못해_밖의_대상을_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_따옴표_친_참조는_공백이_있어도_한_대상으로_본다(home):
    # given
    folder = "/tmp/work/a b"
    commands = [f'D="{folder}"; rm -rf "$D"', f'D="{folder}"; rm -rf "$D/x"']
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert [outcome.kind for outcome in outcomes] == ["pass", "pass"]


@pytest.mark.parametrize("argument", ["'/tmp/work/cache /home/test/data'", "'/tmp/work/a*b /home/test/data'",
                                      "$'/tmp/work/a\\t/home/test/data'"])
def test_스크립트_인자의_공백은_따옴표_없는_참조에서_여러_대상이_된다(home, argument):
    # given
    # when
    outcome = run_script(home, 'rm -rf $1', argument)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_스크립트_인자의_따옴표_친_참조와_공백_없는_값은_그대로_통과한다(home):
    # given
    # when
    outcomes = [run_script(home, 'rm -rf "$1"', "'/tmp/work/a b'"), run_script(home, 'rm -rf $1', "/tmp/work/a")]
    # then
    assert [outcome.kind for outcome in outcomes] == ["pass", "pass"]


@pytest.fixture
def linked_script(home, monkeypatch):
    """A script whose real folder is a temporary root and whose link folder is not."""
    real = home / "temp"
    real.mkdir()
    monkeypatch.setattr(guard, "TEMPORARY_ROOTS", (str(real),))
    (real / "cleanup.sh").write_text('#!/bin/bash\nD=$(dirname "$0"); rm -rf "$D/cache"\n')
    tools = home / "tools"
    tools.mkdir()
    (tools / "cleanup.sh").symlink_to(real / "cleanup.sh")
    session = home / "session"
    session.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(session))
    return real, tools


def test_링크로_부른_스크립트의_폴더는_링크_경로를_따라_임시_루트_밖이면_묻는다(linked_script):
    # given
    real, tools = linked_script
    # when
    outcomes = [classify(f"bash {tools}/cleanup.sh", real), classify(f"bash {real}/cleanup.sh", real)]
    # then
    assert outcomes[0].kind == "always" and outcomes[0].descriptions == [PROTECTED]
    assert outcomes[1].kind == "pass"


def test_상대_경로로_링크를_불러도_링크의_폴더를_기준으로_한다(linked_script):
    # given
    real, tools = linked_script
    # when
    outcome = classify("bash ./cleanup.sh", tools)
    # then
    assert outcome.kind == "always" and outcome.descriptions == [PROTECTED]


def test_저장소_설정이_추적되지_않은_파일을_숨겨도_매번_묻는다(work_tree):
    # given
    git(work_tree, "config", "status.showUntrackedFiles", "no")
    (work_tree / "tracked" / "notes.txt").write_text("notes")
    command = "rm -rf tracked"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [PROTECTED]


def test_사용자_제외_파일이_추적되지_않은_파일을_가려도_무시된_파일로_보지_않는다(work_tree):
    # given
    excludes = work_tree.parent / "excludes"
    excludes.write_text("scratch/\n")
    git(work_tree, "config", "core.excludesFile", str(excludes))
    command = "rm -rf scratch"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_변경을_가정하지_않음으로_표시한_추적_파일은_매번_묻는다(work_tree):
    # given
    git(work_tree, "update-index", "--assume-unchanged", "dirty/b.txt")
    command = "rm -rf dirty"
    # when
    outcome = classify(command, work_tree)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
