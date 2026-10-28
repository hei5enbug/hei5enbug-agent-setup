"""Acceptance checks: disposable or recoverable local actions do not ask every time (variables, xargs, temporary roots,
local container engines, clean git trees, and provably read-only Python)."""
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402
import guard_cloud  # noqa: E402
import approval_state as state_mod  # noqa: E402

NON_TEMPORARY_HOME = "/nonexistent-home"
NON_TEMPORARY_TMPDIR = "/nonexistent-tmpdir"
PLUGIN_RUNNER = "/opt/plugin/scripts/role_runner.py"
ALLOW = state_mod.permission_allow()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", NON_TEMPORARY_HOME)
    monkeypatch.setenv("TMPDIR", NON_TEMPORARY_TMPDIR)
    for name in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr(guard_cloud, "PODMAN_SYSTEM_CONFIGS", (), raising=False)
    for name in ("KUBECONFIG", "AWS_PROFILE", "CLOUDSDK_CORE_PROJECT", "DOCKER_CONTEXT", "DOCKER_HOST", "CONTAINER_HOST",
                 "CONTAINER_CONNECTION", "CLAUDE_PROJECT_DIR", "DOCKER_CONFIG", "CONTAINERS_CONF", "XDG_CONFIG_HOME",
                 "HEI5ENBUG_PARENT_SESSION"):
        monkeypatch.delenv(name, raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("kubectl", "az"):
        (bin_dir / name).write_text("#!/bin/sh\necho fake\n")
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return tmp_path


def classify(command, cwd=REPO_ROOT):
    return guard.classify_text(command, str(cwd))


def permission(command, cwd=REPO_ROOT):
    event = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": command},
             "session_id": "s1", "cwd": str(cwd)}
    return guard.handle(event, "claude")


def pre_decision(command, cwd=REPO_ROOT):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "session_id": "s1", "cwd": str(cwd)}
    output = guard.handle(event, "claude")
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


# --- 1. 같은 명령 안에서 앞서 대입한 변수 --------------------------------------------------------------------------------

def test_앞서_대입한_옵션_변수는_공백으로_나뉘어_조회로_분류된다(home):
    # given
    command = "C=\"--context ctx -n ns\"; kubectl $C get pods -o wide | awk '{print $1}'"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "read"


def test_awk가_필드만_출력하면_조회_파이프의_끝이_될_수_있다(home):
    # given
    commands = ["kubectl get pods | awk '{print $1}'", "kubectl get pods | awk -F: '{print $1, $NF}'",
                "kubectl get pods | awk 'NR > 1 {print $2}'"]
    # when
    kinds = [classify(command).kind for command in commands]
    # then
    assert kinds == ["read", "read", "read"]


@pytest.mark.parametrize("command", [
    "kubectl get pods | awk '{system(\"x\")}'",
    "kubectl get pods | awk '{print $1 > \"out.txt\"}'",
    "kubectl get pods | awk '{print $1}' > out.txt",
    "kubectl get pods | awk '{print $1}' file.txt",
])
def test_필드_출력이_아닌_awk는_조회_파이프로_보지_않는다(home, command):
    # given
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "pass"


def test_for_반복문_본문은_앞서_대입한_변수로_역할_실행기_호출을_알아본다(home):
    # given
    command = (f"R={PLUGIN_RUNNER}; S={home}/scratch; for i in 1 2 3; do python3 $R scout --assignment $S/s$i.md "
               "--result $S/r$i.md & done; wait")
    literal = f"python3 {PLUGIN_RUNNER} scout --assignment {home}/scratch/s1.md --result {home}/scratch/r1.md"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == classify(literal).kind == "pass"


def test_mktemp_폴더를_대입한_변수의_삭제는_임시_삭제라_매번_묻지_않는다(home):
    # given
    command = "d=$(mktemp -d); cd $d && git init -q a; rm -rf $d"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.every_time is False


def test_정적이지_않은_값의_삭제는_해석할_수_없는_대상이라_매번_묻는다(home):
    # given
    command = 'W=$(cat file); rm -rf "$W"'
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True
    assert outcome.descriptions == ["Recursive removal with an unresolved target"]


def test_따옴표_없는_확장만_공백으로_나뉘고_따옴표_안의_확장은_한_단어다(home):
    # given
    split = classify('T="/tmp/x /home/other"; rm -rf $T')
    quoted = classify('T="/tmp/x /home/other"; rm -rf "$T"')
    # when
    kinds = (split.kind, quoted.kind)
    # then
    assert kinds == ("always", "pass")


@pytest.mark.parametrize("command", [
    "export K=get; kubectl $K pods",
    "K=get; (K=delete); kubectl $K pods",
    "K=get; K=$(cat f); kubectl $K pods",
    "K=get; for K in delete; do kubectl $K pods; done",
    "K=get; read K; kubectl $K pods",
    "true && K=get; kubectl $K pods",
    "K=get & kubectl $K pods",
    "K=get | cat; kubectl $K pods",
    "if true; then K=get; fi; kubectl $K pods",
    "f() { K=get; }; f; kubectl $K pods",
])
def test_고정되지_않은_대입은_변수를_치환하지_않아_분류_불가_쓰기로_남는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "write"


@pytest.mark.parametrize(("raw", "expected"), [
    ("$C", ["a", "b"]), ('"$C"', ["a b"]), ("x$C", ["xa", "b"]), ("$C.md", ["a", "b.md"]), ("${C}z", ["a", "bz"]),
    ("'$C'", None), ("$UNSET", None), ("\\$C", None), ('"x $C y"', ["x a b y"]),
])
def test_변수_확장은_sh처럼_따옴표_밖에서만_단어를_나눈다(raw, expected):
    # given
    statics = {"C": "a b"}
    # when
    result = guard._expand_raw_word(raw, statics)
    # then
    assert result == expected


def test_앞뒤_공백만_있는_값은_따옴표_밖에서_치환하지_않는다():
    # given
    statics = {"E": "  "}
    # when
    result = guard._expand_raw_word("$E", statics)
    # then
    assert result is None


# --- 2. xargs ----------------------------------------------------------------------------------------------------------

def test_xargs_뒤_단순_명령은_그_명령으로_분류하고_자리표시자는_모르는_피연산자다(home):
    # given
    command = ("git ls-tree -r --name-only upstream/main | grep X | xargs -I{} git show upstream/main:{} | grep -n Y")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "sensitive"
    assert outcome.keys == [state_mod.SENSITIVE_KEY]


@pytest.mark.parametrize("command", [
    "git ls-files | xargs grep -n X", "git ls-files | xargs -n1 -P4 grep -n X", "git ls-files -z | xargs -0 grep -n X",
    "git ls-files | xargs -i git show HEAD:{}", "git ls-files | xargs --replace=@ git show HEAD:@",
])
def test_xargs로_이어진_읽기_명령은_모르는_피연산자가_있어_민감_조회로_분류한다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "sensitive"


@pytest.mark.parametrize("command", ["git ls-files | xargs rm -rf", "git ls-files | xargs -I{} rm -rf {}",
                                     "ls | xargs -0 rm -r"])
def test_xargs로_이어진_재귀_삭제는_해석할_수_없는_대상이라_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True
    assert outcome.descriptions == ["Recursive removal with an unresolved target"]


@pytest.mark.parametrize("command", [
    "ls | xargs kubectl delete", "ls | xargs -I{} kubectl delete pod {} --context dev -n web",
    "ls | xargs docker --context prod rm",
])
def test_xargs_뒤_파괴적_명령은_그_명령처럼_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("command", [
    "ls | xargs sh -c 'kubectl get pods'", "ls | xargs bash -c 'git show {}'", "ls | xargs -I{} {} --version",
    "ls | xargs xargs git show", "ls | xargs eval git show", "ls | xargs --unknown-option git show",
    "ls | xargs",
])
def test_셸_eval_중첩_xargs_알_수_없는_옵션이_있는_xargs는_이전처럼_불투명하다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind != "read"


# --- 3. 임시 루트 안에만 쓰는 명령 ------------------------------------------------------------------------------------

def test_임시_폴더_안에만_쓰는_명령_묶음은_통과이고_호스트_확인도_허용한다(home):
    # given
    scratch = home / "scratchpad"
    command = (f"S={scratch}; mkdir -p $S/verify && cp /some/app/bin $S/verify/bin && cat > $S/verify/a.py <<'EOF'\n"
               "import subprocess\nprint(1)\nEOF")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.exe == guard.TEMP_WRITE_EXE
    assert pre_decision(command) is None
    assert permission(command) == ALLOW


@pytest.mark.parametrize("command", [
    "echo hi > /tmp/work/a.txt", "echo hi >> /tmp/work/a.txt", "echo hi > /private/tmp/work/a.txt",
    "printf x > /var/folders/ab/cd/T/a.txt", f"echo hi > {NON_TEMPORARY_TMPDIR}/a.txt", "mkdir -p /tmp/work/a/b",
    "cp a.txt /tmp/work/", "cp -r src /tmp/work/dst", "cp -t /tmp/work a.txt b.txt", "mv /anywhere/a /tmp/work/b",
    "echo hi | tee /tmp/work/a.txt", "echo hi | tee -a /tmp/work/a /tmp/work/b", "touch /tmp/work/a",
    "echo hi > ~/.cache/work/a", "echo hi > ~/.claude/jobs/abc/tmp/a.txt",
    "mkdir -p ~/.claude/jobs/abc/tmp/x && cp a ~/.claude/jobs/abc/tmp/x",
])
def test_모든_대상이_임시_루트_안인_쓰기는_통과로_분류한다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.exe == guard.TEMP_WRITE_EXE
    assert permission(command) == ALLOW


@pytest.mark.parametrize("command", [
    "cat > ./README.md", "cat > README.md <<'EOF'\nx\nEOF", "echo hi >> /etc/hosts", "mkdir -p build",
    "mkdir -p /tmp/work ./build", "cp a.txt ./b.txt", "cp a.txt /tmp/work ./b.txt", "mv /tmp/a ./b",
    "echo hi | tee ./a.txt", "touch ./a", "echo hi > ~/.claude/jobs/abc/a.txt", "echo hi > ~/.claude/a.txt",
    "echo hi > $UNKNOWN/a", "echo hi > /tmp/*", "echo hi > /tmp/../etc/a",
    "npm install > /tmp/work/log", "git init /tmp/work/repo", "echo $(npm run x) > /tmp/work/a",
    "sudo mkdir -p /tmp/work", "./cat > /tmp/work/a", "echo hi > /tmp/work/a; npm install",
    "python3 - <<'PY' > /tmp/work/a\nprint(1)\nPY",
])
def test_임시_루트_밖에_쓰거나_판단할_수_없는_명령은_호스트_확인을_허용하지_않는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.exe != guard.TEMP_WRITE_EXE
    assert permission(command) is None


def test_임시_루트를_가리키는_심볼릭_링크가_밖을_향하면_임시_쓰기가_아니다(home):
    # given
    link = home / "link"
    link.symlink_to(REPO_ROOT)
    outside = classify(f"cat > {link}/README.md")
    # when
    kind = outside.exe
    # then
    assert kind != guard.TEMP_WRITE_EXE


# --- 4. Claude Code 작업 임시 폴더의 재귀 삭제 -----------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    f"rm -rf {NON_TEMPORARY_HOME}/.claude/jobs/abc/tmp/sw", f"rm -r {NON_TEMPORARY_HOME}/.claude/jobs/abc/tmp/a/b",
    f"rm -rf {NON_TEMPORARY_HOME}/.claude/jobs/abc/tmp/*", "rm -rf ~/.claude/jobs/abc/tmp/sw",
    f"rm -rf {NON_TEMPORARY_HOME}/.claude/jobs/abc/tmp",
])
def test_작업_임시_폴더_안의_재귀_삭제는_임시_삭제라_매번_묻지_않는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "pass"
    assert outcome.every_time is False


@pytest.mark.parametrize("command", [
    f"rm -rf {NON_TEMPORARY_HOME}/.claude/jobs/abc",
    f"rm -rf {NON_TEMPORARY_HOME}/.claude/jobs", f"rm -rf {NON_TEMPORARY_HOME}/.claude",
    f"rm -rf {NON_TEMPORARY_HOME}", f"rm -rf {NON_TEMPORARY_HOME}/.claude/jobs/abc/tmp/sw/.git",
    f"rm -rf {NON_TEMPORARY_HOME}/.claude/jobs/abc/other/sw", "rm -rf /", "rm -rf $UNKNOWN_TARGET/x",
    f"rm -rf {NON_TEMPORARY_HOME}/.claude/jobs/abc/tmp/../sw",
])
def test_작업_임시_폴더_밖과_보호_경로의_재귀_삭제는_계속_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


# --- 5. 로컬 컨테이너 엔진의 삭제 ------------------------------------------------------------------------------------

LOCAL_DOCKER = [
    "docker rm c1", "docker rm -f c1", "docker rmi img", "docker container rm c1", "docker image rm img",
    "docker image prune -f", "docker volume rm v", "docker volume prune -f", "docker network rm n",
    "docker network prune -f", "docker system prune -af", "docker compose down", "docker compose down -v",
    "docker compose down --volumes", "docker run --rm alpine", "podman rm c1", "podman system prune -f",
    "podman compose down -v", "DOCKER_HOST=unix:///var/run/docker.sock docker rm c1",
    "DOCKER_CONTEXT=default docker rm c1", "DOCKER_HOST=localhost:2375 docker rm c1",
]
REMOTE_DOCKER = [
    "docker --context prod rm c1", "docker -c prod rm c1", "docker --context=prod rmi img", "docker -H tcp://h:2375 rm c1",
    "docker --host ssh://h system prune -f", "docker -Hssh://h rm c1", "DOCKER_CONTEXT=prod docker rm c1",
    "DOCKER_HOST=ssh://h docker rm c1", "DOCKER_HOST=tcp://10.0.0.5:2375 docker system prune -f",
    "DOCKER_HOST=tcp://localhost:2375 docker rm c1", "docker --context prod compose down -v",
    "podman --connection prod rm c1", "podman --remote rm c1", "CONTAINER_HOST=ssh://h podman rm c1",
    "docker --context prod volume rm v",
]


@pytest.mark.parametrize("command", LOCAL_DOCKER)
def test_로컬_엔진의_도커_삭제와_정리는_세션_쓰기다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False
    assert state_mod.split_outcome(outcome) == ([], [state_mod.WRITE_KEY])


@pytest.mark.parametrize("command", REMOTE_DOCKER)
def test_원격_엔진의_도커_삭제는_계속_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_도커_옵션_값에_든_h는_원격_옵션으로_오인하지_않는다(home):
    # given
    command = "docker exec c1 grep -Hn x /etc/hosts"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False


@pytest.mark.parametrize("command", ["docker exec c1 rm -rf /data", "podman exec c1 rm -rf /data",
                                     "docker exec c1 sh -c 'rm -rf /data'", "docker exec -it -u root c1 rm /x"])
def test_로컬_컨테이너_안의_삭제_명령은_세션_쓰기다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False


@pytest.mark.parametrize("command", [
    "docker --context prod exec c1 rm -rf /data", "docker exec c1 psql -c 'delete from t'",
    "docker exec c1 git reset --hard", "docker exec c1 kubectl delete pod x", "docker exec c1 git push --force",
    "kubectl exec pod -- rm -rf /data",
])
def test_원격_엔진이거나_원격_파괴가_섞인_exec는_계속_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("command", [
    "eval docker rm c1", "bash -c 'docker rm c1'", "cleanup() { docker rm -f c1; docker network rm n; }; cleanup",
    "D='docker rm c1'; $D", "docker rm c1; rm -rf /tmp/work/a",
])
def test_로컬_도커_삭제만_담은_함수_변수_간접_호출은_세션_쓰기다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False


@pytest.mark.parametrize("command", [
    "eval docker --context prod rm c1", "eval 'docker rm c1; kubectl delete pod x'",
    "bash -c 'docker -H tcp://h rm c1'", "f() { docker --context prod rm -f c1; }; f",
    "D='docker --context prod rm c1'; $D", "DOCKER_HOST=ssh://h eval docker rm c1",
    "eval docker rm c1 && psql -c 'delete from t'",
])
def test_원격_엔진이나_다른_파괴가_섞인_간접_호출은_계속_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


# --- 6. 커밋하지 않은 추적 파일 변경이 없을 때의 git 폐기 ------------------------------------------------------------------

def git(directory, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                    "-C", str(directory), *args], check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})


@pytest.fixture
def repo(home):
    directory = home / "repo"
    directory.mkdir()
    git(directory, "init", "-q")
    (directory / "a.txt").write_text("one\n")
    git(directory, "add", "a.txt")
    git(directory, "commit", "-q", "-m", "first")
    return directory


DISCARDS = ["git reset --hard", "git reset --hard HEAD~0", "git checkout -f", "git checkout -f main", "git checkout .",
            "git checkout -- .", "git restore .", "git restore :/", "git restore --worktree .", "git restore -SW ."]


@pytest.mark.parametrize("command", DISCARDS)
def test_추적_파일_변경이_없는_저장소의_폐기는_세션_쓰기다(repo, command):
    # given
    # when
    outcome = classify(command, repo)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False


def test_c_옵션이_가리키는_저장소가_깨끗하면_다른_폴더에서도_세션_쓰기다(repo, home):
    # given
    command = f"git -C {repo} reset --hard"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False


def test_추적되지_않는_파일만_있어도_세션_쓰기다(repo):
    # given
    (repo / "new.txt").write_text("untracked\n")
    # when
    outcome = classify("git reset --hard", repo)
    # then
    assert outcome.kind == "write"


def test_c_옵션이_더러운_저장소를_가리키면_매번_묻는다(repo, home):
    # given
    (repo / "a.txt").write_text("changed\n")
    # when
    outcome = classify(f"git -C {repo} reset --hard", home)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("command", DISCARDS)
def test_추적_파일을_수정했으면_폐기는_계속_매번_묻는다(repo, command):
    # given
    (repo / "a.txt").write_text("changed\n")
    # when
    outcome = classify(command, repo)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_스테이징만_한_변경도_커밋하지_않은_변경이라_매번_묻는다(repo):
    # given
    (repo / "b.txt").write_text("two\n")
    git(repo, "add", "b.txt")
    # when
    outcome = classify("git reset --hard", repo)
    # then
    assert outcome.kind == "always"


def test_저장소가_아니면_매번_묻는다(home):
    # given
    folder = home / "plain"
    folder.mkdir()
    # when
    outcome = classify("git reset --hard", folder)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_git_dir_옵션이나_환경변수로_저장소를_바꾸면_매번_묻는다(repo, home, monkeypatch):
    # given
    option = classify(f"git --git-dir={repo}/.git --work-tree={repo} reset --hard", home)
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    # when
    environment = classify("git reset --hard", repo)
    # then
    assert option.every_time is True
    assert environment.every_time is True


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("git", 3), OSError("no git"), ValueError("bad")])
def test_상태_조회가_실패하거나_시간이_초과되면_매번_묻는다(repo, monkeypatch, failure):
    # given
    def broken(*args, **kwargs):
        raise failure
    monkeypatch.setattr(guard.subprocess, "run", broken)
    # when
    outcome = classify("git reset --hard", repo)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_상태_조회는_짧은_제한_시간과_추적_파일_전용_옵션으로_실행한다(repo, monkeypatch):
    # given
    seen = {}
    real = subprocess.run

    def spy(argv, **kwargs):
        seen["argv"], seen["timeout"] = argv, kwargs.get("timeout")
        return real(argv, **kwargs)
    monkeypatch.setattr(guard.subprocess, "run", spy)
    # when
    classify("git reset --hard", repo)
    # then
    assert seen["argv"][-3:] == ["status", "--porcelain", "--untracked-files=no"]
    assert seen["timeout"] == guard.LOOKUP_TIMEOUT_SECONDS


@pytest.mark.parametrize("command", [
    "git clean -fd", "git clean -f", "git stash drop", "git stash clear", "git push --force origin main",
    "git push --force-with-lease origin main", "git push --force-if-includes origin main",
    "git push --delete origin old", "git push --mirror origin", "git push --prune origin", "git push origin +main",
    "git push -f origin main", "git push origin :old",
])
def test_정리와_스태시_삭제와_위험한_푸시는_깨끗한_저장소에서도_매번_묻는다(repo, command):
    # given
    # when
    outcome = classify(command, repo)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("command", ["git restore --staged .", "git reset --soft HEAD~1", "git checkout main"])
def test_파괴적이지_않은_git_호출의_분류는_그대로다(repo, command):
    # given
    (repo / "a.txt").write_text("changed\n")
    # when
    outcome = classify(command, repo)
    # then
    assert outcome.every_time is False


# --- 7. 읽기 전용임이 증명된 Python ---------------------------------------------------------------------------------

READ_ONLY_SCRIPTS = [
    'import sys\nwith open(sys.argv[1]) as handle:\n    print(handle.read())\n',
    'print(open("data.txt").read())', 'print(open("data.txt", "rb").read())', 'print(open("data.txt", mode="rt").read())',
    'import json, os\nprint(json.dumps(sorted(os.listdir("."))))',
    'from pathlib import Path\nprint(Path("a").read_text())\nfor item in Path(".").iterdir():\n    print(item)',
    'import re\nprint(re.compile("a+").findall("caab"))',
    'import csv, sys\nfor row in csv.reader(open("a.csv", newline="")):\n    print(row)',
    'import os\nfor root, folders, files in os.walk("."):\n    print(root, len(files))',
    'import shutil\nprint(shutil.which("git"))', 'from collections import Counter\nprint(Counter("abca"))',
    'import argparse\nparser = argparse.ArgumentParser()\nparser.add_argument("path")\nprint(parser.parse_args().path)',
    'class A:\n    def __init__(self):\n        super().__init__()\n    def __str__(self):\n        return "a"\nprint(A())',
    'print(1)', 'if __name__ == "__main__":\n    print(sys.argv)\nimport sys',
    's="kubectl delete pod x"\nprint(s)',
]
NOT_READ_ONLY_SCRIPTS = [
    'open("a.txt", "w").write("x")', 'open("a.txt", "a")', 'open("a.txt", "r+")', 'open("a.txt", "wb")',
    'mode = "w"\nopen("a.txt", mode)', 'open("a.txt", **{"mode": "w"})', 'open("a.txt", "r", opener=print)',
    'import io\nio.open("a.txt", "w")', 'import os\nos.open("a.txt", os.O_WRONLY)', 'from pathlib import Path\nPath("a").open("w")',
    'from pathlib import Path\nPath("a").write_text("x")', 'from pathlib import Path\nPath("a").write_bytes(b"x")',
    'from pathlib import Path\nPath("a").touch()', 'from pathlib import Path\nPath("a").mkdir()',
    'from pathlib import Path\nPath("a").unlink()', 'from pathlib import Path\nPath("a").rename("b")',
    'from pathlib import Path\nPath("a").replace("b")', 'from pathlib import Path\nPath("a").symlink_to("b")',
    'from pathlib import Path\nPath("a").chmod(0o700)', 'import os\nos.remove("a")', 'import os\nos.unlink("a")',
    'import os\nos.rmdir("a")', 'import os\nos.removedirs("a")', 'import os\nos.makedirs("a")', 'import os\nos.mkdir("a")',
    'import os\nos.rename("a", "b")', 'import os\nos.replace("a", "b")', 'import os\nos.chmod("a", 0o700)',
    'import os\nos.chown("a", 0, 0)', 'import os\nos.truncate("a", 0)', 'import os\nos.system("ls")',
    'import os\nos.popen("ls")', 'import os\nos.spawnl(os.P_WAIT, "ls")', 'import os\nos.execv("ls", ["ls"])',
    'import os\nos.kill(1, 0)', 'from os import remove\nremove("a")', 'from os import system as run\nrun("ls")',
    'import subprocess\nsubprocess.run(["ls"])', 'import subprocess', 'import socket', 'import requests', 'import httpx',
    'import urllib.request', 'from urllib import request', 'from urllib.request import urlopen', 'import http.client',
    'from http import client', 'import ftplib', 'import smtplib', 'import paramiko', 'import multiprocessing',
    'import ctypes', 'import shutil\nshutil.rmtree("a")', 'import shutil\nshutil.copy("a", "b")',
    'import shutil as sh\nsh.move("a", "b")', 'from shutil import copyfile\ncopyfile("a", "b")',
    'import shutil\nx = shutil', 'import boto3', 'import kubernetes', 'import redis', 'import tempfile',
    'import importlib\nimportlib.import_module("os")', 'eval("1")', 'exec("print(1)")', 'compile("1", "f", "eval")',
    '__import__("os")', 'import os\ngetattr(os, name)', 'import os\ngetattr(os, "system")("ls")', 'setattr(object, "a", 1)',
    'import os\nprint(os.environ)', 'import os\nprint(os.getenv("HOME"))', 'from os import environ\nprint(environ)',
    'print(().__class__.__bases__)', 'print(globals())', 'print(vars())', 'open', 'f = open\nf("a", "w")',
    'print(list(map(open, ["a"])))', 'import sys\nprint(sys.modules)', 'from . import x', 'from os import *',
    'import yaml', 'import os, sqlite3', 'print("a".replace("a", "b"))', 'items = []\nitems.remove(1)',
    'print(open(".env").read())', 'print(open("/home/u/.aws/credentials").read())', 'print("token")',
    'import argparse\nargparse.ArgumentParser().add_argument("f", type=argparse.FileType("w"))',
    'async def run():\n    pass', 'def broken(:', 'help(print)',
    'import xml.etree.ElementTree as ET\nET.ElementTree().write("a.xml")',
]


@pytest.mark.parametrize("body", READ_ONLY_SCRIPTS)
@pytest.mark.parametrize("mode", ["script", "heredoc"])
def test_읽기_전용임이_증명된_파이썬_스크립트는_조회다(home, body, mode):
    # given
    script = home / "tool.py"
    script.write_text(body)
    command = f"python3 {script}" if mode == "script" else "python3 - <<'PY'\n" + body + "\nPY"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "read"
    assert outcome.keys == []


@pytest.mark.parametrize("body", NOT_READ_ONLY_SCRIPTS)
@pytest.mark.parametrize("mode", ["script", "heredoc"])
def test_읽기_전용임을_증명할_수_없는_파이썬은_조회가_되지_않는다(home, body, mode):
    # given
    script = home / "tool.py"
    script.write_text(body)
    command = f"python3 {script}" if mode == "script" else "python3 - <<'PY'\n" + body + "\nPY"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind != "read"


def test_읽기_전용_파이썬_조회는_파이프_필터와_함께도_조회이고_호스트_결정은_허용이다(home):
    # given
    script = home / "tool.py"
    script.write_text('print(open("data.txt").read())')
    command = f"python3 {script} | head -5"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "read"
    assert pre_decision(command, home) == "allow"


def test_읽지_못하는_스크립트는_이전_분류를_유지한다(home):
    # given
    command = f"python3 {home}/missing.py"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "write"


@pytest.mark.parametrize("command", ["python3 {script} .env", "python3 {script} ~/.aws/credentials",
                                     "python3 {script} /tmp/.env.production"])
def test_보호된_파일을_인자로_받는_스크립트는_조회로_올리지_않는다(home, command):
    # given
    script = home / "tool.py"
    script.write_text("import sys\nprint(open(sys.argv[1]).read())")
    # when
    outcome = classify(command.format(script=script), home)
    # then
    assert outcome.kind == "pass"


def test_execute_인자가_있으면_읽기_전용_스크립트도_쓰기다(home):
    # given
    script = home / "tool.py"
    script.write_text("print(1)")
    # when
    outcome = classify(f"python3 {script} --execute", home)
    # then
    assert outcome.kind == "write"


def test_python_c_인라인_코드는_이전처럼_통과다(home):
    # given
    command = "python3 -c 'print(1)'"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "pass"


def test_읽기_전용_스크립트의_stdin_인자도_수정_스크립트와_구분한다(home):
    # given
    command = "python3 - arg <<'PY'\nprint(1)\nPY"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "pass"


# --- 8. 유지되는 규칙 ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "kubectl delete pod x --context dev -n web", "terraform destroy", "npm publish", "curl -X DELETE https://example.com/x",
    "psql -h db.example.com -c 'delete from t'", "gh repo delete owner/repo --yes",
    "codex exec -s danger-full-access task",
])
def test_원격_인프라와_배포_파괴는_그대로_매번_묻는다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_비밀을_출력하는_호출은_그대로_거부된다(home):
    # given
    command = "kubectl get secret s -o json"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "secret"


@pytest.mark.parametrize("command", ["env", "printenv", "cat .env", "docker inspect web"])
def test_민감_조회는_그대로_세션_민감_승인이다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "sensitive"


# --- 최종 검토 보완 -----------------------------------------------------------------------------------------------------

INLINE_DESTRUCTIVE = ("import subprocess; subprocess.run(['kubectl','delete','pod','x','--context','dev','-n','web'])")


@pytest.mark.parametrize("flags", ["-c", "-Ic", "-Bc", "-IBc"])
@pytest.mark.parametrize("attached", [True, False])
def test_파이썬_인라인_코드는_어떤_표기든_heredoc이_아니라_그_코드를_분류한다(home, flags, attached):
    # given
    code = shlex.quote(INLINE_DESTRUCTIVE)
    invocation = f"python3 {flags}{code}" if attached and flags == "-c" else f"python3 {flags} {code}"
    command = invocation + " <<'PY'\nprint(1)\nPY"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("invocation", ["python3 -c'print(1)'", "python3 -Ic 'print(1)'", "python3 -Bc'print(1)'"])
def test_파이썬_인라인_코드가_있으면_heredoc이_읽기_전용이어도_조회로_올리지_않는다(home, invocation):
    # given
    command = invocation + " <<'PY'\nprint(2)\nPY"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind != "read"


@pytest.mark.parametrize("command", [
    "git show HEAD:list.txt | xargs kubectl get -o json", "git show HEAD:list.txt | xargs oc get",
    "git ls-files | xargs git show", "git ls-files | xargs -I{} git cat-file -p {}", "git ls-files | xargs cat",
    "git ls-files | xargs head -1", "git ls-files | xargs grep -n X", "git ls-files | xargs -I{} kubectl get {} -o yaml",
])
def test_xargs의_모르는_피연산자가_비밀을_가리킬_수_있으면_조회가_아니라_민감_조회다(home, command):
    # given
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "sensitive"


@pytest.mark.parametrize("command", ["git ls-files | xargs rm", "git ls-files | xargs echo", "git ls-files | xargs mkdir"])
def test_xargs_뒤_파일을_읽지_않는_명령은_민감_조회가_되지_않는다(home, command):
    # given
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("body", [
    'from io import open as f\nf("a.txt", "w")', 'import io\nx = io.open\nx("a.txt", "w")',
    'import io\nio.open("r", "w")', 'import io\nopener = getattr(io, "open")\nopener("a", "w")',
    'from io import open as f\nopener = f\nopener("a", "w")', 'import io as i\ni.open("a", "w")',
    'import io\nio.open("a", mode="w")', 'from pathlib import Path\nPath("a").open("r", 1, "w")',
    'import os\nos.fdopen(1, "w")', 'import os as o\no.open("a", 1)', 'from io import open as f\nlist(map(f, ["a"]))',
])
def test_열기_함수에_묶인_모든_이름은_쓰기_모드를_검사해_읽기_전용으로_보지_않는다(home, body):
    # given
    script = home / "tool.py"
    script.write_text(body)
    # when
    outcome = classify(f"python3 {script}", home)
    # then
    assert outcome.kind != "read"


@pytest.mark.parametrize("body", [
    'from io import open as f\nprint(f("a.txt").read())', 'import io\nprint(io.open("a.txt", "rb").read())',
    'from pathlib import Path\nprint(Path("a").open("r").read())', 'from pathlib import Path\nprint(Path("a").open().read())',
])
def test_읽기_모드로_묶인_열기_이름은_계속_조회다(home, body):
    # given
    script = home / "tool.py"
    script.write_text(body)
    # when
    outcome = classify(f"python3 {script}", home)
    # then
    assert outcome.kind == "read"


@pytest.mark.parametrize("arguments", ["--file=.env", "--file .env", "-f.env", "--path=~/.aws/credentials",
                                       "--out=x --file=/tmp/.env.production"])
@pytest.mark.parametrize("mode", ["script", "heredoc"])
def test_옵션_값에_든_보호된_파일도_파이썬_스크립트를_조회로_올리지_않는다(home, arguments, mode):
    # given
    body = "import sys\nprint(open(sys.argv[-1]).read())"
    script = home / "reader.py"
    script.write_text(body)
    command = f"python3 {script} {arguments}" if mode == "script" else f"python3 - {arguments} <<'PY'\n{body}\nPY"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "pass"


def docker_config(home, monkeypatch, text):
    folder = home / "docker-config"
    folder.mkdir(exist_ok=True)
    (folder / "config.json").write_text(text)
    monkeypatch.setenv("DOCKER_CONFIG", str(folder))


@pytest.mark.parametrize("text", ['{"currentContext": "prod"}', '{"currentContext": "remote-ssh", "auths": {}}',
                                  "{not json", "[]", '{"currentContext": 5}'])
def test_도커_설정에_저장된_현재_컨텍스트가_있거나_읽을_수_없으면_원격으로_본다(home, monkeypatch, text):
    # given
    docker_config(home, monkeypatch, text)
    # when
    outcome = classify("docker rm c1", home)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("text", ['{}', '{"currentContext": ""}', '{"currentContext": "default"}', '{"auths": {}}'])
def test_도커_설정의_현재_컨텍스트가_비었거나_default면_로컬이다(home, monkeypatch, text):
    # given
    docker_config(home, monkeypatch, text)
    # when
    outcome = classify("docker rm c1", home)
    # then
    assert outcome.kind == "write"


def test_도커_설정_폴더가_없으면_로컬이다(home, monkeypatch):
    # given
    monkeypatch.setenv("DOCKER_CONFIG", str(home / "missing"))
    # when
    outcome = classify("docker rm c1", home)
    # then
    assert outcome.kind == "write"


def test_도커_설정은_홈의_docker_폴더에서도_읽고_config_옵션이_대신한다(home, monkeypatch):
    # given
    monkeypatch.setenv("HOME", str(home / "userhome"))
    (home / "userhome" / ".docker").mkdir(parents=True)
    (home / "userhome" / ".docker" / "config.json").write_text('{"currentContext": "prod"}')
    other = home / "other"
    other.mkdir()
    (other / "config.json").write_text("{}")
    # when
    persisted = classify("docker rm c1", home)
    overridden = classify(f"docker --config {other} rm c1", home)
    # then
    assert persisted.kind == "always"
    assert overridden.kind == "write"


@pytest.mark.parametrize("text", ['[engine]\nactive_service = "prod"\n', '[engine]\nremote = true\n',
                                  '[engine]\nremote=true', '[engine]\nactive_service="x"\n'])
def test_podman_설정이_기본_원격_연결을_정하면_원격으로_본다(home, monkeypatch, text):
    # given
    config = home / "containers.conf"
    config.write_text(text)
    monkeypatch.setenv("CONTAINERS_CONF", str(config))
    # when
    outcome = classify("podman rm c1", home)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_podman_설정이_원격을_정하지_않으면_로컬이다(home, monkeypatch):
    # given
    config = home / "containers.conf"
    config.write_text('[engine]\n# active_service = "prod"\nremote = false\n[network]\ndefault_network = "x"\n')
    monkeypatch.setenv("CONTAINERS_CONF", str(config))
    # when
    outcome = classify("podman rm c1", home)
    # then
    assert outcome.kind == "write"


def test_podman_설정을_읽을_수_없으면_원격으로_본다(home, monkeypatch):
    # given
    config = home / "containers.conf"
    config.mkdir()
    monkeypatch.setenv("CONTAINERS_CONF", str(config))
    # when
    outcome = classify("podman rm c1", home)
    # then
    assert outcome.kind == "always"


def test_podman_시스템_연결의_기본값이_있으면_원격으로_본다(home, monkeypatch):
    # given
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg-config"))
    folder = home / "xdg-config" / "containers"
    folder.mkdir(parents=True)
    (folder / "podman-connections.json").write_text('{"Connection": {"Default": "prod", "Connections": {}}}')
    # when
    outcome = classify("podman rm c1", home)
    # then
    assert outcome.kind == "always"


def test_시스템_수준_podman_설정도_원격_기본값이면_원격이다(home, monkeypatch):
    # given
    system = home / "system.conf"
    system.write_text('[engine]\nactive_service = "prod"\n')
    monkeypatch.setattr(guard_cloud, "PODMAN_SYSTEM_CONFIGS", (str(system),))
    # when
    outcome = classify("podman rm c1", home)
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("command", [
    "docker -cprod rm c1", "docker -c=prod rm c1", "docker -Htcp://h:2375 rm c1", "docker -H=ssh://h rm c1",
    "podman --remote=true rm c1", "podman --remote=false rm c1", "podman --remote rm c1", "podman -r rm c1",
    "podman -cprod rm c1", "docker --context=prod rm c1", "docker --host=ssh://h rm c1", "podman --url=ssh://h rm c1",
    "podman --connection=prod rm c1", "podman --identity=key --url ssh://h rm c1",
])
def test_붙여_쓴_원격_옵션_표기도_원격으로_본다(home, command):
    # given
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("command", [
    "DOCKER_HOST=ssh://prod xargs docker rm < ids.txt", "DOCKER_CONTEXT=prod xargs docker rm < ids.txt",
    "DOCKER_HOST=ssh://prod xargs -I{} docker rm {}", "CONTAINER_HOST=ssh://prod xargs podman rm",
])
def test_xargs_앞의_접두_대입은_풀어낸_명령에_적용된다(home, command):
    # given
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_xargs_접두_대입이_없으면_로컬_도커_삭제는_세션_쓰기다(home):
    # given
    command = "xargs docker rm < ids.txt"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "write"


@pytest.mark.parametrize("command", [
    "docker exec c1 git reset --hard", "podman exec c1 git reset --hard", "kubectl exec pod -- git reset --hard",
    "oc exec pod -- git checkout -f", "docker exec c1 sh -c 'git reset --hard'", "docker exec c1 git restore .",
    "kubectl exec pod -- sh -c 'git checkout .'",
])
def test_깨끗한_호스트_저장소여도_컨테이너_exec_안의_git_폐기는_매번_묻는다(repo, command):
    # given
    # when
    outcome = classify(command, repo)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("command", [
    "git -c core.hooksPath=x reset --hard", "git -c user.name=a reset --hard", "git --config-env=a=B reset --hard",
    "git --namespace=n reset --hard", "git --bare reset --hard", "git --no-pager -c a=b reset --hard",
    "GIT_DIR=. git reset --hard", "GIT_WORK_TREE=. git reset --hard", "GIT_INDEX_FILE=x git reset --hard",
    "GIT_CONFIG_GLOBAL=/dev/null git reset --hard", "GIT_CONFIG_COUNT=0 git reset --hard",
    "GIT_CEILING_DIRECTORIES=/ git reset --hard", "GIT_OBJECT_DIRECTORY=x git checkout -f",
])
def test_git_전역_옵션이나_환경이_대상을_바꿀_수_있으면_깨끗해도_매번_묻는다(repo, command):
    # given
    # when
    outcome = classify(command, repo)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("name", ["GIT_CONFIG_GLOBAL", "GIT_CEILING_DIRECTORIES", "GIT_WORK_TREE", "GIT_CONFIG_COUNT"])
def test_프로세스_환경의_git_변수도_깨끗한_저장소_예외를_막는다(repo, monkeypatch, name):
    # given
    monkeypatch.setenv(name, "x")
    # when
    outcome = classify("git reset --hard", repo)
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("command", [
    "printf x >> a.txt; git reset --hard", "touch x && git reset --hard", "echo hi; git reset --hard",
    "rm -f a.txt && git checkout -f", "sed -i s/one/two/ a.txt; git checkout .", "git stash pop; git reset --hard",
    "git commit -q -m x && git reset --hard", "echo hi > /tmp/work/a && git reset --hard",
    "mkdir -p /tmp/work/a && git restore .", "git reset --hard $(touch x)", "eval 'touch x'; git reset --hard",
    "touch x; eval 'git reset --hard'", "touch x; bash -c 'git reset --hard'", "python3 -c 'print(1)'; git reset --hard",
    "npm install; git reset --hard", "git status | tee out.txt; git reset --hard",
])
def test_앞선_세그먼트가_파일을_바꿀_수_있으면_깨끗한_저장소_예외를_쓰지_않는다(repo, command):
    # given
    # when
    outcome = classify(command, repo)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("command", [
    "git status && git reset --hard", "git status; git diff; git reset --hard", "cd . && git reset --hard",
    "X=1; git reset --hard", "git log -1 > /dev/null; git reset --hard", "git reset --hard && touch x",
])
def test_앞선_세그먼트가_모두_조회이면_깨끗한_저장소_예외를_쓴다(repo, command):
    # given
    # when
    outcome = classify(command, repo)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False


@pytest.mark.parametrize("command", [
    "P=./notes.txt; true || {\n  P=/tmp/x\n}; printf y > \"$P\"", "P=./notes.txt; true || { P=/tmp/x; }; printf y > \"$P\"",
    "P=./notes.txt; { P=/tmp/x; }; printf y > $P", "P=./notes.txt\n{\n  P=/tmp/x\n}\nprintf y > $P",
    "P=./notes.txt; if true; then\n  P=/tmp/x\nfi; printf y > $P",
    "P=./notes.txt; while false; do\n  P=/tmp/x\ndone; printf y > $P", "P=./notes.txt; false || P=/tmp/x; printf y > $P",
    "P=./notes.txt; true && P=/tmp/x; printf y > $P", "P=./notes.txt; cd . && P=/tmp/x; printf y > $P",
    "P=./notes.txt; true || {\n  P=/tmp/x\n}\nmkdir -p $P",
])
def test_블록과_조건_안의_대입은_변수를_알_수_없게_만들어_임시_쓰기로_보지_않는다(home, command):
    # given
    # when
    outcome = classify(command, REPO_ROOT)
    # then
    assert outcome.exe != guard.TEMP_WRITE_EXE
    assert permission(command, REPO_ROOT) is None


def test_앞선_대입만_있는_왼쪽_뒤의_and_대입은_고정으로_본다(home):
    # given
    command = "A=/tmp/a && B=/tmp/b; printf y > $B"
    # when
    outcome = classify(command, REPO_ROOT)
    # then
    assert outcome.exe == guard.TEMP_WRITE_EXE


@pytest.mark.parametrize("variant", ["cp", "mv", "cp -t"])
def test_임시_폴더_안의_기존_심볼릭_링크가_밖을_가리키면_cp와_mv_대상이_임시가_아니다(home, variant):
    # given
    folder = home / "folder"
    folder.mkdir()
    (folder / "README.md").symlink_to(REPO_ROOT / "README.md")
    command = {"cp": f"cp /some/src/README.md {folder}/", "mv": f"mv /some/src/README.md {folder}",
               "cp -t": f"cp -t {folder} /some/src/README.md"}[variant]
    # when
    outcome = classify(command, home)
    # then
    assert outcome.exe != guard.TEMP_WRITE_EXE
    assert permission(command, home) is None


def test_임시_폴더_안의_기존_폴더에_복사하면_원본_이름으로_이어진_경로를_본다(home):
    # given
    folder = home / "folder"
    folder.mkdir()
    # when
    outcome = classify(f"cp /some/src/a.txt /some/src/b.txt {folder}/", home)
    # then
    assert outcome.exe == guard.TEMP_WRITE_EXE


def test_원본_이름을_알_수_없는_복사_대상_폴더는_임시_쓰기가_아니다(home):
    # given
    folder = home / "folder"
    folder.mkdir()
    # when
    glob = classify(f"cp /some/src/*.md {folder}/", home)
    unknown = classify(f"cp $UNKNOWN {folder}/", home)
    # then
    assert glob.exe != guard.TEMP_WRITE_EXE
    assert unknown.exe != guard.TEMP_WRITE_EXE


@pytest.mark.parametrize("command", [
    "echo x > {link}", "echo x >> {link}", "echo x | tee {link}", "touch {link}", "echo x > {folder}/dir/f",
])
def test_임시_폴더_안의_기존_링크로_가는_리다이렉션_tee_touch는_임시_쓰기가_아니다(home, command):
    # given
    folder = home / "folder"
    folder.mkdir()
    link = folder / "link"
    link.symlink_to(REPO_ROOT / "README.md")
    (folder / "dir").symlink_to(REPO_ROOT)
    # when
    outcome = classify(command.format(link=link, folder=folder), home)
    # then
    assert outcome.exe != guard.TEMP_WRITE_EXE


def test_임시_폴더_안의_링크로_가는_mkdir은_임시_쓰기가_아니다(home):
    # given
    folder = home / "folder"
    folder.mkdir()
    (folder / "dir").symlink_to(REPO_ROOT)
    # when
    outcome = classify(f"mkdir -p {folder}/dir/new", home)
    # then
    assert outcome.exe != guard.TEMP_WRITE_EXE


# --- 이름 있는 도커 컨텍스트와 무해한 git 환경 변수 -------------------------------------------------------------------------

def context_meta(config_dir, name, content):
    folder = config_dir / "contexts" / "meta" / hashlib.sha256(name.encode()).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(content if isinstance(content, str) else json.dumps(content))


def docker_endpoint(host):
    return {"Name": "ctx", "Endpoints": {"docker": {"Host": host, "SkipTLSVerify": False}}}


@pytest.fixture
def docker_dir(home, monkeypatch):
    folder = home / "docker-config"
    folder.mkdir()
    monkeypatch.setenv("DOCKER_CONFIG", str(folder))
    return folder


@pytest.mark.parametrize("host", [f"unix://{NON_TEMPORARY_HOME}/.docker/run/docker.sock", "unix:///var/run/docker.sock",
                                  "npipe:////./pipe/docker_engine"])
def test_메타_파일의_호스트가_유닉스_소켓이면_저장된_현재_컨텍스트도_로컬이다(home, docker_dir, host):
    # given
    (docker_dir / "config.json").write_text('{"currentContext": "desktop-linux"}')
    context_meta(docker_dir, "desktop-linux", docker_endpoint(host))
    # when
    outcome = classify("docker rm c1", home)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False


def test_context_옵션과_환경변수가_고른_이름_있는_컨텍스트도_메타_파일로_판단한다(home, docker_dir):
    # given
    context_meta(docker_dir, "local-sock", docker_endpoint("unix:///var/run/docker.sock"))
    context_meta(docker_dir, "prod-ssh", docker_endpoint("ssh://deploy@prod.example.com"))
    # when
    kinds = [classify(command, home).kind for command in (
        "docker --context local-sock rm c1", "docker --context=local-sock rm c1", "docker -c local-sock rm c1",
        "docker -clocal-sock rm c1", "DOCKER_CONTEXT=local-sock docker rm c1", "docker --context prod-ssh rm c1",
        "DOCKER_CONTEXT=prod-ssh docker rm c1", "docker -cprod-ssh rm c1")]
    # then
    assert kinds == ["write"] * 5 + ["always"] * 3


def test_옵션이_환경변수와_설정보다_앞서_컨텍스트를_정한다(home, docker_dir, monkeypatch):
    # given
    (docker_dir / "config.json").write_text('{"currentContext": "prod-ssh"}')
    context_meta(docker_dir, "local-sock", docker_endpoint("unix:///var/run/docker.sock"))
    context_meta(docker_dir, "prod-ssh", docker_endpoint("ssh://prod"))
    monkeypatch.setenv("DOCKER_CONTEXT", "prod-ssh")
    # when
    outcome = classify("docker --context local-sock rm c1", home)
    # then
    assert outcome.kind == "write"


@pytest.mark.parametrize("host", ["ssh://deploy@prod", "tcp://10.0.0.5:2375", "tcp://localhost:2375", "http://x",
                                  "/var/run/docker.sock", "", "UNIX://x"])
def test_메타_파일의_호스트가_유닉스_소켓이_아니면_원격이다(home, docker_dir, host):
    # given
    (docker_dir / "config.json").write_text('{"currentContext": "named"}')
    context_meta(docker_dir, "named", docker_endpoint(host))
    # when
    outcome = classify("docker rm c1", home)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("meta", [
    "{not json", "[]", "null", {"Endpoints": {}}, {"Endpoints": {"docker": {}}}, {"Endpoints": {"docker": {"Host": 5}}},
    {"Endpoints": {"docker": "unix:///x"}}, {"Endpoints": []}, {"Name": "named"},
])
def test_메타_파일이_깨졌거나_호스트가_없으면_원격이다(home, docker_dir, meta):
    # given
    (docker_dir / "config.json").write_text('{"currentContext": "named"}')
    context_meta(docker_dir, "named", meta)
    # when
    outcome = classify("docker rm c1", home)
    # then
    assert outcome.kind == "always"


def test_메타_파일이_없거나_다른_이름의_것이면_원격이다(home, docker_dir):
    # given
    (docker_dir / "config.json").write_text('{"currentContext": "named"}')
    context_meta(docker_dir, "other", docker_endpoint("unix:///var/run/docker.sock"))
    # when
    missing = classify("docker rm c1", home)
    unreadable_dir = docker_dir / "contexts" / "meta" / hashlib.sha256(b"named").hexdigest() / "meta.json"
    unreadable_dir.mkdir(parents=True)
    unreadable = classify("docker rm c1", home)
    # then
    assert missing.kind == "always"
    assert unreadable.kind == "always"


def test_default_컨텍스트는_도커_호스트가_없으면_로컬이고_있으면_그_호스트를_따른다(home, docker_dir):
    # given
    (docker_dir / "config.json").write_text('{"currentContext": "default"}')
    # when
    plain = classify("docker --context default rm c1", home)
    remote = classify("DOCKER_HOST=ssh://prod docker --context default rm c1", home)
    # then
    assert plain.kind == "write"
    assert remote.kind == "always"


def test_config_옵션이_가리킨_폴더의_메타_파일을_읽는다(home, docker_dir):
    # given
    other = home / "other-docker"
    other.mkdir()
    (other / "config.json").write_text('{"currentContext": "named"}')
    context_meta(other, "named", docker_endpoint("unix:///var/run/docker.sock"))
    # when
    outcome = classify(f"docker --config {other} rm c1", home)
    # then
    assert outcome.kind == "write"


def test_도커_컨텍스트가_유닉스_소켓이어도_podman_연결_옵션은_원격이다(home, docker_dir):
    # given
    context_meta(docker_dir, "local-sock", docker_endpoint("unix:///var/run/docker.sock"))
    # when
    outcome = classify("podman --connection local-sock rm c1", home)
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("name", [
    "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_PAGER", "GIT_TERMINAL_PROMPT", "GIT_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND",
    "GIT_TRACE", "GIT_TRACE_PACKET", "GIT_TRACE2_EVENT", "GIT_PROGRESS_DELAY", "GIT_FLUSH", "GIT_MERGE_AUTOEDIT",
])
def test_저장소를_바꿀_수_없는_git_환경변수는_깨끗한_저장소_예외를_막지_않는다(repo, monkeypatch, name):
    # given
    monkeypatch.setenv(name, "true")
    # when
    outcome = classify("git reset --hard", repo)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False


@pytest.mark.parametrize("name", [
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_CEILING_DIRECTORIES",
    "GIT_COMMON_DIR", "GIT_EDITOR_EXTRA", "GIT_SOMETHING_NEW",
])
def test_그_밖의_git_환경변수는_계속_깨끗한_저장소_예외를_막는다(repo, monkeypatch, name):
    # given
    monkeypatch.setenv(name, "x")
    monkeypatch.setenv("GIT_EDITOR", "true")
    # when
    outcome = classify("git reset --hard", repo)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_접두_대입으로_준_무해한_git_변수는_허용하고_위험한_변수는_막는다(repo):
    # given
    harmless = classify("GIT_EDITOR=true GIT_PAGER=cat git reset --hard", repo)
    redirecting = classify("GIT_EDITOR=true GIT_DIR=. git reset --hard", repo)
    # then
    assert harmless.kind == "write"
    assert redirecting.kind == "always"


# --- 리스 보호된 force push -----------------------------------------------------------------------------------------------

@pytest.fixture
def pushing(repo):
    git(repo, "remote", "add", "origin", "https://example.com/team/repo.git")
    git(repo, "remote", "add", "upstream", "https://example.com/org/repo.git")
    return repo


LEASE_WRITES = [
    "git push --force-with-lease origin feature/ABC-1",
    "git push --force-with-lease=feature/ABC-1:abc123 origin feature/ABC-1",
    "git push --force-with-lease=feature/ABC-1 origin feature/ABC-1",
    "git push --force-if-includes --force-with-lease origin feature/x",
    "git push --force-if-includes origin feature/x",
    "git push -u --force-with-lease origin feature/x", "git push -uv --force-with-lease origin feature/x",
    "git push --force-with-lease origin HEAD:feature/x", "git push --force-with-lease origin local:feature/x",
    "git push --force-with-lease origin refs/heads/feature/x", "git push --force-with-lease origin HEAD:refs/heads/feature/x",
    "git push origin feature/x --force-with-lease", "git push --force-with-lease --no-verify origin feature/x",
    "git push --force-with-lease origin feature/a feature/b", "git push --dry-run --force-with-lease origin feature/x",
    "touch x && git push --force-with-lease origin feature/x", "GIT_EDITOR=true git push --force-with-lease origin feature/x",
    "git commit -q --allow-empty -m x && git push --force-with-lease origin feature/x",
]


@pytest.mark.parametrize("command", LEASE_WRITES)
def test_기능_브랜치로_가는_리스_보호_force_push는_세션_쓰기다(pushing, command):
    # given
    # when
    outcome = classify(command, pushing)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False
    assert state_mod.split_outcome(outcome) == ([], [state_mod.WRITE_KEY])


def test_c_옵션이_가리키는_저장소의_리스_push도_세션_쓰기다(pushing, home):
    # given
    command = f"git -C {pushing} push --force-with-lease origin feature/ABC-1"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "write"


LEASE_EVERY_TIME = [
    # 기본 브랜치
    "git push --force-with-lease origin main", "git push --force-with-lease origin master",
    "git push --force-with-lease origin develop", "git push --force-with-lease origin trunk",
    "git push --force-with-lease origin HEAD:main", "git push --force-with-lease origin feature/x:main",
    "git push --force-with-lease origin refs/heads/main", "git push --force-with-lease origin feature/x main",
    "git push --force-with-lease=main:abc origin feature/x", "git push --force-with-lease=refs/heads/main origin feature/x",
    # 원격
    "git push --force-with-lease upstream feature/x", "git push --force-with-lease origin",
    "git push --force-with-lease", "git push --force-with-lease=feature/x:abc",
    "git push --force-with-lease https://example.com/team/repo.git feature/x",
    "git push --force-with-lease git@example.com:team/repo.git feature/x", "git push --force-with-lease ../other feature/x",
    "git push --force-with-lease nope feature/x", "git push --force-with-lease -- origin feature/x",
    # 목적지가 명시되지 않거나 삭제·확장
    "git push --force-with-lease origin HEAD", "git push --force-with-lease origin @",
    "git push --force-with-lease origin HEAD:", "git push --force-with-lease origin feature/x:",
    "git push --force-with-lease origin +feature/x", "git push --force-with-lease origin feature/x:+feature/y",
    "git push --force-with-lease origin :feature/x", "git push --force-with-lease origin refs/tags/v1",
    "git push --force-with-lease origin feature/*", "git push --force-with-lease origin refs/for/x",
    "git push --force-with-lease origin refs/heads/*:refs/heads/*",
    # 다른 force 계열과 확장 옵션
    "git push --force origin feature/x", "git push -f origin feature/x", "git push -fu origin feature/x",
    "git push -uf origin feature/x", "git push --force --force-with-lease origin feature/x",
    "git push --force-with-lease -f origin feature/x", "git push --delete origin feature/x", "git push -d origin feature/x",
    "git push --force-with-lease --delete origin feature/x", "git push --force-with-lease --mirror origin",
    "git push --force-with-lease --prune origin feature/x", "git push --force-with-lease --all origin",
    "git push --force-with-lease --tags origin feature/x", "git push --force-with-lease -o ci.skip origin feature/x",
    "git push --force-with-lease --push-option=x origin feature/x", "git push --force-with-lease --receive-pack=x origin f",
    "git push --force-with-lease --repo=x origin feature/x", "git push --force-with-lease --unknown origin feature/x",
    # 전역 옵션과 환경
    "git -c core.sshCommand=x push --force-with-lease origin feature/x",
    "git --git-dir=.git push --force-with-lease origin feature/x", "git --work-tree=. push --force-with-lease origin feature/x",
    "git --namespace=n push --force-with-lease origin feature/x", "git --bare push --force-with-lease origin feature/x",
    "GIT_DIR=.git git push --force-with-lease origin feature/x",
    "GIT_CONFIG_GLOBAL=/dev/null git push --force-with-lease origin feature/x",
    # 컨테이너 래퍼
    "docker exec c1 git push --force-with-lease origin feature/x",
    "kubectl exec pod -- git push --force-with-lease origin feature/x",
    "docker exec c1 sh -c 'git push --force-with-lease origin feature/x'",
]


@pytest.mark.parametrize("command", LEASE_EVERY_TIME)
def test_그_밖의_force_push는_계속_매번_묻는다(pushing, command):
    # given
    # when
    outcome = classify(command, pushing)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_원격의_head_브랜치도_기본_브랜치로_보고_읽을_수_없으면_이_검사만_건너뛴다(pushing):
    # given
    git(pushing, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/release")
    # when
    default = classify("git push --force-with-lease origin release", pushing)
    default_lease = classify("git push --force-with-lease=release:abc origin feature/x", pushing)
    other = classify("git push --force-with-lease origin feature/x", pushing)
    # then
    assert default.kind == "always"
    assert default_lease.kind == "always"
    assert other.kind == "write"


def test_원격_head를_읽을_수_없어도_기능_브랜치는_세션_쓰기다(pushing):
    # given
    # when
    outcome = classify("git push --force-with-lease origin feature/x", pushing)
    # then
    assert outcome.kind == "write"


def test_저장소가_아니거나_원격을_읽을_수_없으면_매번_묻는다(home, pushing, monkeypatch):
    # given
    plain = home / "plain"
    plain.mkdir()
    not_repository = classify("git push --force-with-lease origin feature/x", plain)

    def broken(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 3)
    monkeypatch.setattr(guard.subprocess, "run", broken)
    # when
    timeout = classify("git push --force-with-lease origin feature/x", pushing)
    # then
    assert not_repository.kind == "always"
    assert timeout.kind == "always"


@pytest.mark.parametrize("name", ["GIT_EDITOR", "GIT_PAGER", "GIT_SSH_COMMAND", "GIT_TRACE"])
def test_무해한_git_환경변수가_있어도_리스_push_예외는_유지된다(pushing, monkeypatch, name):
    # given
    monkeypatch.setenv(name, "true")
    # when
    outcome = classify("git push --force-with-lease origin feature/x", pushing)
    # then
    assert outcome.kind == "write"


@pytest.mark.parametrize("name", ["GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_COUNT", "GIT_CEILING_DIRECTORIES"])
def test_저장소를_바꿀_수_있는_git_환경변수가_있으면_리스_push는_매번_묻는다(pushing, monkeypatch, name):
    # given
    monkeypatch.setenv(name, "x")
    # when
    outcome = classify("git push --force-with-lease origin feature/x", pushing)
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("command", ["git push origin feature/x", "git push origin main", "git push -u origin feature/x",
                                     "git push"])
def test_force가_없는_push는_계속_세션_쓰기다(pushing, command):
    # given
    # when
    outcome = classify(command, pushing)
    # then
    assert outcome.kind == "write"
    assert outcome.every_time is False
