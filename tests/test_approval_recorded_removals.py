"""Acceptance checks: recorded approval asks where the agent made no mistake no longer ask (statically resolvable removal
targets, a glob that cannot reach `.git`, the plugin's evaluation workspace, a `git stash drop` that loses nothing, and
Claude Code's own dangerous-removal prompt), while the nearby risky shapes still ask."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402
import approval_state as state_mod  # noqa: E402

NON_TEMPORARY_HOME = "/nonexistent-home"
NON_TEMPORARY_TMPDIR = "/nonexistent-tmpdir"
UNRESOLVED = "Recursive removal with an unresolved target"
PROTECTED = "Recursive removal of a protected or external path"
ALLOW = state_mod.permission_allow()

SCRATCH = "/tmp/work/demo/scratchpad"

COPY_WORKTREE_PLAIN = (
    f'W={SCRATCH}/wt1 && git worktree add --detach "$W" HEAD >/dev/null 2>&1; '
    'G1="api/cmd/x api/internal/y docs/a.md"; for p in $G1; do rm -rf "${W:?}"/"${p:?}"; '
    'if [ -e "$p" ]; then mkdir -p "$(dirname "$W/$p")"; cp -R "$p" "$W/$p"; fi; done; '
    'cd "$W/api" && go build ./... 2>&1 | head -20'
)
BASH_C_LOOP = (
    "bash -c '\n"
    f"W={SCRATCH}/wt1\n"
    "for p in api/cmd/x api/internal/y docs/a.md; do\n"
    '  rm -rf "${W:?}/${p:?}"; mkdir -p "$(dirname "$W/$p")"; cp -R "$p" "$W/$p"\n'
    "done\n"
    'git -C "$W" status --short | wc -l\n'
    'cd "$W/api" && go build ./... 2>&1 | head -20\''
)
BASH_C_POSITIONAL = (
    f'S={SCRATCH}; bash -c \'shopt -s dotglob nullglob; rm -rf "$1"/*\' _ "$S"; ls -A "$S" | wc -l; du -sh "$S"; '
    "df -h / | tail -1"
)
UNQUOTED_LOOP = (
    f"W={SCRATCH}/wt1 && git worktree add --detach $W HEAD >/dev/null 2>&1 && "
    'G1="api/cmd/x docs/a.md" && for p in $G1; do rm -rf $W/$p; [ -e $p ] && mkdir -p $(dirname $W/$p) && '
    "cp -R $p $W/$p; done"
)
SIGNATURE_BACKUP = (
    "cd /home/test/repo/api/internal/x && cp a.go /tmp/sig.bak 2>/dev/null; B=$PWD/../../../scratch_bak; mkdir -p $B; "
    "cp a.go $B/; rm -rf $B /tmp/sig.bak"
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", NON_TEMPORARY_HOME)
    monkeypatch.setenv("TMPDIR", NON_TEMPORARY_TMPDIR)
    for name in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return tmp_path


@pytest.fixture
def outside_temp(home, monkeypatch):
    """The test folder is not a temporary root, so the folders under it get no temporary-root exemption."""
    monkeypatch.setattr(guard, "TEMPORARY_ROOTS", ("/nonexistent-temp-root",))
    return home


def classify(command, cwd=REPO_ROOT):
    return guard.classify_text(command, str(cwd))


def permission(command, cwd=REPO_ROOT, session="g2-session"):
    event = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": command},
             "session_id": session, "cwd": str(cwd)}
    return guard.handle(event, "claude")


def is_ask(outcome):
    return outcome.kind in ("always", "forbidden") or outcome.every_time


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", "-C", str(root), *args],
                   check=True, capture_output=True)


# --- A5. 정적으로 해석되는 삭제 대상 --------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    BASH_C_POSITIONAL,
    COPY_WORKTREE_PLAIN,
    BASH_C_LOOP,
    UNQUOTED_LOOP,
])
def test_기록된_정적_삭제_형태는_묻지_않는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.every_time is False


def test_변수가_필수인_확장은_그_변수_값으로_해석한다(home):
    # given
    commands = [f'W={SCRATCH}; rm -rf "${{W:?}}/x"', f'W={SCRATCH}; rm -rf "${{W:?missing}}/x"',
                f"W={SCRATCH}; rm -rf ${{W:?}}"]
    # when
    outcomes = [classify(command) for command in commands]
    # then
    assert [outcome.kind for outcome in outcomes] == ["pass", "pass", "pass"]


def test_for_반복문은_공백으로_나뉘는_변수의_각_단어를_선택지로_삼는다(home):
    # given
    inside = f'W={SCRATCH}; L="a b"; for p in $L; do rm -rf "$W/$p"; done'
    escaping = f'W={SCRATCH}; L="a /home/test/b"; for p in $L; do rm -rf "$p"; done'
    # when
    inside_outcome, escaping_outcome = classify(inside), classify(escaping)
    # then
    assert inside_outcome.kind == "pass"
    assert escaping_outcome.kind == "always" and escaping_outcome.every_time is True
    assert escaping_outcome.descriptions == [PROTECTED]


def test_bash_c의_위치_인자는_정적일_때만_스크립트_안에서_해석한다(home):
    # given
    inside = "bash -c 'rm -rf \"$1\"/x' _ /tmp/work/demo"
    zero = "bash -c 'rm -rf \"$0\"/x' /tmp/work/demo"
    escaping = "bash -c 'rm -rf \"$1\"/x' _ /home/test/demo"
    # when
    outcomes = [classify(command) for command in (inside, zero, escaping)]
    # then
    assert [outcome.kind for outcome in outcomes] == ["pass", "pass", "always"]
    assert outcomes[2].descriptions == [PROTECTED]


@pytest.mark.parametrize("command", [
    'for p in $(ls); do rm -rf "$W/$p"; done',
    f'W={SCRATCH}; for p in $(ls); do rm -rf "$W/$p"; done',
    f'W={SCRATCH}; for p in $UNSET; do rm -rf "$W/$p"; done',
    f'W={SCRATCH}; IFS=/; L="a b"; for p in $L; do rm -rf "$W/$p"; done',
    "bash -c 'rm -rf \"$1\"' _ \"$HOME\"",
    "bash -c 'rm -rf \"$1\"/x' _ \"$UNSET\"",
    'W=/; rm -rf "${W:?}"',
    'rm -rf "${W:?}/x"',
    'rm -rf "${W:?}"',
])
def test_해석되지_않거나_보호_경로인_삭제_대상은_계속_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions in ([UNRESOLVED], [PROTECTED])


def test_현재_폴더에서_만든_경로의_삭제는_계속_매번_묻는다(home):
    # given
    # when
    outcome = classify(SIGNATURE_BACKUP)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [UNRESOLVED]


# --- A6. .git을 가리킬 수 없는 글롭 -----------------------------------------------------------------------------------------

def test_git_항목이_없는_폴더의_점_글롭_삭제는_묻지_않는다(home):
    # given
    scratch = home / "scratchpad"
    (scratch / "keep").mkdir(parents=True)
    command = (f'S={scratch}; chmod -R u+w "$S" 2>/dev/null; rm -rf "$S"/* "$S"/.[!.]* 2>/dev/null; '
               'ls -A "$S" | wc -l')
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.every_time is False


@pytest.mark.parametrize("entry", ["dir", "file"])
def test_git_항목이_있는_폴더의_점_글롭_삭제는_보호_경로라_매번_묻는다(home, entry):
    # given
    scratch = home / "scratchpad"
    scratch.mkdir()
    if entry == "dir":
        (scratch / ".git").mkdir()
    else:
        (scratch / ".git").write_text("gitdir: /elsewhere")
    command = f'S={scratch}; rm -rf "$S"/* "$S"/.[!.]* 2>/dev/null; ls -A "$S" | wc -l'
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [PROTECTED]


def test_도커_이미지_정리가_이어진_기록된_복합_명령은_매번_묻지_않는다(home):
    # given
    scratch = home / "scratchpad"
    scratch.mkdir()
    command = (f'S={scratch}; chmod -R u+w "$S" 2>/dev/null; rm -rf "$S"/* "$S"/.[!.]* 2>/dev/null; '
               'ls -A "$S" | wc -l; docker rmi python:3.12-slim 2>&1 | tail -2; docker system df | sed -n \'1,2p\'; '
               "docker run --rm alpine:latest df -h / | tail -1")
    # when
    outcome = classify(command)
    # then
    assert not is_ask(outcome)


def test_이름에_git이_들어간_글롭은_git_항목이_없어도_계속_매번_묻는다(home):
    # given
    scratch = home / "scratchpad"
    scratch.mkdir()
    # when
    outcome = classify(f'cd {scratch} && rm -rf .git* .g?t')
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [PROTECTED]


# --- A9. unset과 export가 앞서 정한 고정 변수를 지우지 않는다 -----------------------------------------------------------------

@pytest.mark.parametrize("command", [
    'T=$(mktemp -d); unset DEMO_STORE; python3 -c "print(1)"; cd /; rm -rf "$T"',
    'T=$(mktemp -d); export DEMO_DATA_FILE=$T/data.json; python3 -c "print(1)"; rm -rf "$T"',
    'T=/tmp/work/demo; export DEMO_NAME; unset A B; rm -rf "$T/x"',
])
def test_이름만_다루는_unset과_export_뒤에도_고정_변수를_해석한다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.every_time is False


@pytest.mark.parametrize("command", [
    'T=$(mktemp -d); unset T; rm -rf "$T"',
    'T=$(mktemp -d); export T=/home/test/demo; rm -rf "$T"',
    'T=$(mktemp -d); eval "$X"; rm -rf "$T"',
    'T=$(mktemp -d); declare -x T=$X; rm -rf "$T"',
    'T=$(mktemp -d); set -- a; rm -rf "$T/x"',
    'T=$(mktemp -d); export -n DEMO; rm -rf "$T"',
    'T=$(mktemp -d); [ -d x ] && export T=/home/test/demo; rm -rf "$T"',
    'T=/tmp/work/demo; export T=/tmp/work/other; rm -rf "$T/x"',
])
def test_변수를_지우거나_바꾸거나_알_수_없게_하는_환경_명령_뒤의_삭제는_계속_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


# --- A7. 플러그인 평가 작업 공간 ---------------------------------------------------------------------------------------------

def eval_root():
    return state_mod.state_dir().parent / "harness-eval"


RECORDED_EVAL = [
    "C7={root}/deterministic/c7; mv $C7/cwd/after/*.debug.log $C7/after/ && rm -rf \"$C7/cwd/after\"; cd $C7 && "
    'python3 -c "print(1)"',
    "D={root}/deterministic/c6; rm -rf \"$D/final\"; mkdir \"$D/final\" && git ls-files -z | rsync -a --from0 "
    '--files-from=- ./ "$D/final/" && echo copied',
    'D={root}/deterministic/c6; ls $D/final.json 2>/dev/null; rm -rf "$D/final" && mkdir "$D/final"',
]


@pytest.mark.parametrize("template", RECORDED_EVAL)
def test_평가_작업_공간_안의_삭제는_묻지_않는다(outside_temp, template):
    # given
    command = template.format(root=eval_root())
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.every_time is False


@pytest.mark.parametrize("target", ["{root}/runs/demo", "{root}/deterministic/runs", "{root}/deterministic/runs/a/b",
                                    "{root}", "{root}/", "{state}", "{root}/.."])
def test_평가_작업_공간_자체와_실행_기록_폴더_바깥의_삭제는_계속_매번_묻는다(outside_temp, target):
    # given
    command = "rm -rf " + target.format(root=eval_root(), state=eval_root().parent)
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [PROTECTED]


def test_평가_작업_공간_안에서_밖으로_나가는_심볼릭_링크는_계속_매번_묻는다(outside_temp):
    # given
    outside = outside_temp / "elsewhere"
    (outside / "x").mkdir(parents=True)
    inside = eval_root() / "deterministic" / "c7"
    inside.mkdir(parents=True)
    (inside / "out").symlink_to(outside)
    # when
    outcome = classify(f'rm -rf "{inside}/out/x"')
    # then
    assert outcome.kind == "always" and outcome.every_time is True
    assert outcome.descriptions == [PROTECTED]


def test_평가_작업_공간_글롭은_그_폴더가_안쪽일_때만_묻지_않는다(outside_temp):
    # given
    inside = f"rm -rf {eval_root()}/deterministic/c7/*"
    covering_root = f"rm -rf {eval_root()}/*"
    # when
    inside_outcome, root_outcome = classify(inside), classify(covering_root)
    # then
    assert inside_outcome.kind == "pass"
    assert root_outcome.kind == "always" and root_outcome.every_time is True


def test_승인_상태_폴더_아래의_삭제는_평가_작업_공간_예외로_풀리지_않는다(outside_temp):
    # given
    command = f"rm -rf {state_mod.state_dir()}/s1"
    # when
    outcome = classify(command)
    # then
    assert is_ask(outcome)
    assert outcome.kind != "pass"


# --- A8. 잃는 것이 없는 git stash drop -----------------------------------------------------------------------------------------

@pytest.fixture
def stashed(home):
    """A repository whose first stash was applied back, so the work tree equals stash@{0} for tracked files."""
    root = home / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "a.py").write_text("print(1)\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    (root / "tests" / "a.py").write_text("print(2)\n")
    git(root, "stash", "-q")
    git(root, "stash", "apply", "-q")
    return root


DROP_RECORDED = "git stash drop -q; git status --short; ls tests/a.py"


@pytest.mark.parametrize("command", [DROP_RECORDED, "git stash drop", "git stash drop stash@{0}",
                                     "git stash drop -q 'stash@{0}'"])
def test_작업_트리가_스태시와_같은_stash_drop은_매번_묻지_않는다(stashed, command):
    # given
    # when
    outcome = classify(command, stashed)
    # then
    assert outcome.kind in ("pass", "write")
    assert outcome.every_time is False


def test_스태시와_작업_트리_내용이_다르면_stash_drop은_매번_묻는다(stashed):
    # given
    (stashed / "tests" / "a.py").write_text("print(3)\n")
    # when
    outcome = classify(DROP_RECORDED, stashed)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_스태시가_없으면_stash_drop은_매번_묻는다(home):
    # given
    root = home / "repo"
    root.mkdir()
    git(root, "init", "-q")
    # when
    outcome = classify("git stash drop", root)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


@pytest.mark.parametrize("command", ["git stash clear", "git stash drop stash@{1}", "git stash drop 0",
                                     "git stash drop stash@{0} stash@{1}", "git stash drop --unknown"])
def test_다른_스태시를_가리키거나_모두_지우는_명령은_매번_묻는다(stashed, command):
    # given
    (stashed / "tests" / "a.py").write_text("print(2)\n")
    git(stashed, "stash", "-q")
    git(stashed, "stash", "apply", "-q")
    # when
    outcome = classify(command, stashed)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_추적하지_않는_파일을_담은_스태시의_drop은_매번_묻는다(home):
    # given
    root = home / "repo"
    root.mkdir()
    (root / "a.py").write_text("print(1)\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    (root / "a.py").write_text("print(2)\n")
    (root / "new.txt").write_text("keep me\n")
    git(root, "stash", "push", "-u", "-q")
    git(root, "stash", "apply", "-q")
    # when
    outcome = classify("git stash drop", root)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


def test_앞선_명령이_파일을_바꿀_수_있으면_stash_drop은_매번_묻는다(stashed):
    # given
    command = "sed -i s/2/3/ tests/a.py; git stash drop"
    # when
    outcome = classify(command, stashed)
    # then
    assert outcome.kind == "always" and outcome.every_time is True


# --- C2. Claude Code의 위험한 삭제 확인 --------------------------------------------------------------------------------------

def test_임시_폴더_안쪽으로_정적으로_해석되는_삭제만_있으면_권한_요청을_허용한다(home):
    # given
    # when
    answers = [permission(command) for command in (UNQUOTED_LOOP, COPY_WORKTREE_PLAIN, BASH_C_POSITIONAL, BASH_C_LOOP)]
    # then
    assert answers == [ALLOW, ALLOW, ALLOW, ALLOW]


@pytest.mark.parametrize("command", [
    "rm -rf /tmp",
    "rm -rf /tmp/",
    "rm -rf /tmp/*",
    "rm -rf /tmp/work",
    "rm -rf /tmp/work/demo /tmp",
    'rm -rf "$NO_SUCH_VARIABLE/x"',
    'for p in $(ls); do rm -rf "/tmp/work/demo/$p"; done',
    "rm -rf /tmp/work/demo/x $UNSET",
    "rm -rf /var/folders/ab",
])
def test_임시_폴더_자체나_해석되지_않는_삭제는_권한_요청을_허용하지_않는다(home, command):
    # given
    # when
    answer = permission(command)
    # then
    assert answer is None


def test_임시_폴더_밖의_삭제는_권한_요청을_허용하지_않는다(outside_temp, monkeypatch):
    # given
    session = outside_temp / "session"
    session.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(session))
    command = f"rm -rf {session}/build"
    # when
    outcome = classify(command, session)
    answer = permission(command, session)
    # then
    assert outcome.kind == "pass"
    assert answer is None


def test_삭제가_없는_명령의_권한_요청은_그대로_둔다(home):
    # given
    # when
    answer = permission("ls /tmp/work")
    # then
    assert answer is None


def test_삭제가_아닌_부분이_묻는_명령은_권한_요청을_허용하지_않는다(home):
    # given
    command = f"rm -rf {SCRATCH}/x; git reset --hard"
    # when
    answer = permission(command)
    # then
    assert answer is None
