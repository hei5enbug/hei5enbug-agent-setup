"""Acceptance checks: approval asks the guard recorded where the agent made no mistake no longer ask, while the nearby risky
shape keeps today's outcome. A script a quoted heredoc writes earlier in the same command is classified by that body, an
`xargs` reader that cannot print file content is a read, `env | grep` over secret-named variables whose values cannot be
secrets is a read, and local Docker metadata reads are reads."""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402

NON_TEMPORARY_HOME = "/nonexistent-home"
NON_TEMPORARY_TMPDIR = "/nonexistent-tmpdir"
QUIET = ("read", "pass")
ASKS = ("write", "always", "sensitive", "secret", "forbidden")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", NON_TEMPORARY_HOME)
    monkeypatch.setenv("TMPDIR", NON_TEMPORARY_TMPDIR)
    for name in [name for name in os.environ if name.startswith(("GIT_", "DOCKER_", "CONTAINER_"))]:
        monkeypatch.delenv(name)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return tmp_path


def classify(command, cwd=REPO_ROOT):
    return guard.classify_text(command, str(cwd))


def heredoc_write(path, body, delimiter="'EOF'"):
    return f"cat > {path} <<{delimiter}\n{body}EOF\n"


READ_ONLY_BODY = "import re, sys\nfrom pathlib import Path\nprint(len(re.findall('a', Path(sys.argv[1]).read_text())))\n"


# --- A1. 같은 명령에서 인용된 heredoc으로 쓴 스크립트의 실행 -----------------------------------------------------------------

def test_인용된_heredoc으로_쓴_읽기_전용_스크립트의_실행은_묻지_않는다(home):
    # given
    command = (heredoc_write("/tmp/work/demo/scratchpad/linkcheck.py", READ_ONLY_BODY)
               + "python3 /tmp/work/demo/scratchpad/linkcheck.py .")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_변수로_지정한_경로의_스크립트를_쓰고_파이프로_이어_실행해도_묻지_않는다(home):
    # given
    body = "import json, sys\nfrom pathlib import Path\nfor p in Path('.').glob('*/metrics.json'):\n    print(json.dumps(json.loads(p.read_text())))\n"
    command = ("C=~/.local/state/demo-plugin/eval/closure\n" + heredoc_write("$C/collect.py", body)
               + "python3 $C/collect.py final | python3 -c \"import sys,json\nfor l in sys.stdin: print(json.loads(l)['task'])\"")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_앞선_파이프라인과_cd_뒤에_쓴_스크립트의_실행은_묻지_않는다(home):
    # given
    body = "import json\nwith open('/tmp/work/demo/scratchpad/files.txt') as f:\n    print(len(f.read().split()))\n"
    command = ("S=/tmp/work/demo/scratchpad; cd /home/test/projects; while read f; do du -k \"$f\"; done < $S/files.txt"
               " | sort -rn | head -5; cat > $S/survey.py <<'EOF'\n" + body + "EOF\npython3 $S/survey.py $S/files.txt")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_mkdir로_만든_폴더에_쓰고_cd한_뒤_상대_경로로_실행해도_묻지_않는다(home):
    # given
    body = "import collections, glob, json, os, re, sys, time\nprint(len(glob.glob('*')), sys.argv[1])\n"
    command = ("mkdir -p ~/.local/state/demo-plugin/eval/v12 && cat > ~/.local/state/demo-plugin/eval/v12/measure.py <<'EOF'\n"
               + body + "EOF\ncd ~/.local/state/demo-plugin/eval/v12 && python3 measure.py 14")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_임시_폴더에만_쓰는_스크립트와_이어서_실행한_다른_스크립트도_묻지_않는다(home):
    # given
    scratch = home / "scratchpad"
    (scratch / "preview").mkdir(parents=True)
    (scratch / "preview" / "convert.py").write_text(
        "import sys\nwith open(sys.argv[2]) as src, open(sys.argv[3], 'w') as out:\n    out.write(src.read())\n")
    body = (f"import re\nS = '{scratch}/blog'\nhtml = open(S + '/original.html').read()\n"
            "with open(S + '/assembled.html', 'w', encoding='utf-8') as out:\n    out.write(re.sub('a', 'b', html))\n")
    command = (f"S={scratch}/blog; cat > $S/build.py <<'EOF'\n{body}EOF\n"
               f"python3 $S/build.py && python3 {scratch}/preview/convert.py dark $S/assembled.html $S/converted.html; echo exit $?")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_cd한_폴더에서_sed_뒤에_여러_파일을_쓰고_상대_경로로_실행해도_묻지_않는다(home):
    # given
    scratch = home / "scratchpad"
    scratch.mkdir()
    page = "import re\nhtml = open('template.html').read()\nopen('page_pre.html', 'w').write(re.sub('a', 'b', html))\n"
    command = (f"S={scratch}; cd $S; sed -i 's/a/b/' template.html\ncat > fig.svg <<'EOF'\n<svg><text>a</text></svg>\nEOF\n"
               f"cat > build_page.py <<'EOF'\n{page}EOF\npython3 build_page.py")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_cat_뒤에_heredoc을_두는_쓰기_형태도_같은_결과다(home):
    # given
    command = ("cat <<'EOF' > /tmp/work/demo/scratchpad/linkcheck.py\n" + READ_ONLY_BODY
               + "EOF\npython3 /tmp/work/demo/scratchpad/linkcheck.py .")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_heredoc으로_쓴_스크립트는_같은_본문의_기존_파일과_묻는지_여부가_같다(home):
    # given
    scratch = home / "scratchpad"
    scratch.mkdir()
    bodies = [READ_ONLY_BODY, "import subprocess\nsubprocess.run(['ls'])\n"]
    for index, body in enumerate(bodies):
        existing = scratch / f"existing{index}.py"
        existing.write_text(body)
        # when
        written = classify(heredoc_write(f"{scratch}/new{index}.py", body) + f"python3 {scratch}/new{index}.py")
        stored = classify(f"python3 {existing}")
        # then
        assert (written.kind in QUIET) == (stored.kind in QUIET)


@pytest.mark.parametrize("body", [
    "import subprocess\nsubprocess.run(['ls', '-l'])\n",
    "import os\nos.system('ls')\n",
    "import subprocess\nsubprocess.run(['kubectl', 'delete', 'pod', 'demo'])\n",
    "import subprocess\nsubprocess.run(['gh', 'pr', 'merge', '1'])\n",
    "import subprocess\nsubprocess.run(['aws', 's3', 'rm', 's3://example-bucket/key'])\n",
])
def test_프로세스나_연동_CLI를_실행하는_본문은_계속_묻는다(home, body):
    # given
    command = heredoc_write("/tmp/work/demo/scratchpad/job.py", body) + "python3 /tmp/work/demo/scratchpad/job.py"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_인용하지_않은_구분자의_본문은_스크립트로_읽지_않는다(home):
    # given
    body = "import os\nprint(os.environ['HOME'], '$HOME')\n"
    command = heredoc_write("/tmp/work/demo/scratchpad/job.py", body, "EOF") + "python3 /tmp/work/demo/scratchpad/job.py"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_쓴_뒤_다른_명령이_파일을_바꾸면_계속_묻는다(home):
    # given
    command = (heredoc_write("/tmp/work/demo/scratchpad/job.py", READ_ONLY_BODY)
               + "cp /tmp/work/demo/other.py /tmp/work/demo/scratchpad/job.py\npython3 /tmp/work/demo/scratchpad/job.py .")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


@pytest.mark.parametrize("change", [
    "sed -i 's/a/b/' /tmp/work/demo/scratchpad/job.py",
    "echo x > /tmp/work/demo/scratchpad/job.py",
    "mv /tmp/work/demo/other.py /tmp/work/demo/scratchpad/job.py",
    "python3 /tmp/work/demo/other.py",
    "$(cp /tmp/work/demo/other.py /tmp/work/demo/scratchpad/job.py)",
])
def test_쓴_뒤_파일을_바꿀_수_있는_어떤_명령_뒤에도_계속_묻는다(home, change):
    # given
    command = (heredoc_write("/tmp/work/demo/scratchpad/job.py", READ_ONLY_BODY)
               + change + "\npython3 /tmp/work/demo/scratchpad/job.py .")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_조건부로_쓰는_heredoc의_스크립트는_계속_묻는다(home):
    # given
    command = ("test -f /tmp/work/demo/flag && cat > /tmp/work/demo/scratchpad/job.py <<'EOF'\n" + READ_ONLY_BODY
               + "EOF\npython3 /tmp/work/demo/scratchpad/job.py .")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_임시_폴더와_세션_폴더_밖에_쓰는_본문은_계속_묻는다(home):
    # given
    body = "open('/home/test/projects/report.txt', 'w').write('x')\n"
    command = heredoc_write("/tmp/work/demo/scratchpad/job.py", body) + "python3 /tmp/work/demo/scratchpad/job.py"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


@pytest.mark.parametrize("body", [
    "import pathlib\npathlib.Path('/home/test/projects/report.txt').write_text('x')\n",
    "import shutil\nshutil.rmtree('/home/test/projects/cache')\n",
    "import os\nos.remove('/home/test/projects/report.txt')\n",
])
def test_다른_방식으로_파일을_바꾸는_본문도_계속_묻는다(home, body):
    # given
    command = heredoc_write("/tmp/work/demo/scratchpad/job.py", body) + "python3 /tmp/work/demo/scratchpad/job.py"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_셸_스크립트의_본문이_연동_CLI를_부르면_계속_묻는다(home):
    # given
    command = (heredoc_write("/tmp/work/demo/scratchpad/job.sh", "kubectl delete pod demo\n")
               + "bash /tmp/work/demo/scratchpad/job.sh")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_인용된_heredoc으로_쓴_읽기_전용_셸_스크립트의_실행은_묻지_않는다(home):
    # given
    command = (heredoc_write("/tmp/work/demo/scratchpad/job.sh", "ls -la /tmp/work/demo\nwc -l /tmp/work/demo/a.txt\n")
               + "bash /tmp/work/demo/scratchpad/job.sh")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_쓴_적_없는_스크립트의_실행은_계속_묻는다(home):
    # given
    command = "python3 /tmp/work/demo/scratchpad/never_written.py ."
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "write"


def test_이전_명령의_heredoc_기록은_다음_분류로_넘어가지_않는다(home):
    # given
    first = heredoc_write("/tmp/work/demo/scratchpad/job.py", READ_ONLY_BODY) + "python3 /tmp/work/demo/scratchpad/job.py ."
    # when
    classify(first)
    outcome = classify("python3 /tmp/work/demo/scratchpad/job.py .")
    # then
    assert outcome.kind == "write"


# --- A2. 파일 내용을 출력할 수 없는 xargs 판독기 ---------------------------------------------------------------------------

def test_xargs_wc와_ls_stat_du는_이름과_크기만_출력하므로_읽기다(home):
    # given
    commands = [
        "find /tmp/work/demo -type f | xargs wc -c",
        "find /tmp/work/demo -type f | xargs wc -l",
        "find /tmp/work/demo -type f | xargs wc -w",
        "find /tmp/work/demo -type f | xargs wc -m",
        "find /tmp/work/demo -type f | xargs ls -la",
        "find /tmp/work/demo -type f | xargs stat",
        "find /tmp/work/demo -type f | xargs du -k",
    ]
    for command in commands:
        # when
        outcome = classify(command)
        # then
        assert outcome.kind in QUIET, command


def test_xargs_grep은_이름이나_개수만_내는_옵션일_때_읽기다(home):
    # given
    commands = [
        "find /tmp/work/demo -type f | xargs grep -l demo",
        "find /tmp/work/demo -type f | xargs grep -L demo",
        "find /tmp/work/demo -type f | xargs grep -c demo",
        "find /tmp/work/demo -type f | xargs grep -q demo",
        "find /tmp/work/demo -type f | xargs grep -il demo",
        "find /tmp/work/demo -type f | xargs grep --files-with-matches demo",
        "find /tmp/work/demo -type f | xargs rg -l demo",
        "find /tmp/work/demo -type f | xargs rg --count demo",
    ]
    for command in commands:
        # when
        outcome = classify(command)
        # then
        assert outcome.kind in QUIET, command


def test_기록된_xargs_wc_명령은_묻지_않는다(home):
    # given
    command = ("B=/tmp/work/demo/scratchpad/backup/docs; find $B -type f | xargs wc -c; echo; ls -la /home/test/demo/docs/; "
               "wc -c /home/test/demo/docs/*")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_기록된_xargs_grep_l_반복문은_묻지_않는다(home):
    # given
    command = ("cd /home/test/projects; R=/tmp/work/demo/ref; find . -name '*.jsonl' -newer $R | grep -v -e eval-runs > "
               "/tmp/work/demo/files.txt; for p in 'a b' 'c'; do printf '%s: ' \"$p\"; xargs -I{} grep -l -- \"$p\" {} < "
               "/tmp/work/demo/files.txt | wc -l; done")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


@pytest.mark.parametrize("command", [
    "find . -type f | xargs cat",
    "find . -type f | xargs grep TOKEN",
    "find . -type f | xargs grep -n TOKEN",
    "find . -type f | xargs head -5",
    "find . -type f | xargs tail -5",
    "find . -type f | xargs grep -o TOKEN",
    "find . -type f | xargs rg TOKEN",
    "find . -type f | xargs rg -L TOKEN",
    "find . -type f | xargs rg -l --json TOKEN",
    "find . -type f | xargs sed -n 1p",
    "find . -type f | xargs strings",
])
def test_파일_내용을_출력할_수_있는_xargs_판독기는_계속_민감하다(home, command):
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "sensitive"


# --- A3. 값이 비밀일 수 없는 비밀 이름 환경 변수 -------------------------------------------------------------------------------

@pytest.fixture
def git_config_env(home, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.interactive")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "credential.guiPrompt")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "false")
    return home


def test_기록된_env_grep_묶음은_묻지_않는다(git_config_env):
    # given
    command = ("cd /home/test/repo; env | grep -c '^GIT_CONFIG' ; env -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u "
               "GIT_CONFIG_VALUE_0 python3 -m pytest -q -p no:cacheprovider tests/test_demo.py -k clean 2>&1 | grep -E "
               "'Error|assert' | head -15; env | grep '^GIT' | cut -c1-60")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_기록된_env_grep_i_뒤에_GIT_CONFIG를_지정해_실행하는_명령은_묻지_않는다(git_config_env):
    # given
    command = ("env | grep -i GIT_CONFIG; GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=credential.interactive "
               "GIT_CONFIG_VALUE_0=false GIT_CONFIG_KEY_1=credential.guiPrompt GIT_CONFIG_VALUE_1=false python3 -m pytest "
               "tests/test_demo.py -q -x 2>&1 | tail -30")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


@pytest.mark.parametrize("command", ["env | grep GIT_CONFIG", "env | grep -i git_config", "env | grep '^GIT'"])
def test_값이_거짓이나_설정_이름인_GIT_CONFIG_변수만_맞으면_읽기다(git_config_env, command):
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "read"


@pytest.mark.parametrize("value", ["", "true", "false", "0", "1", "yes", "no", "on", "off", "never", "always", "auto", "FALSE", "Yes"])
def test_값이_비어_있거나_불리언_같은_비밀_이름_변수는_읽기다(home, monkeypatch, value):
    # given
    monkeypatch.setenv("DEMO_API_TOKEN", value)
    # when
    outcome = classify("env | grep DEMO_API_TOKEN")
    # then
    assert outcome.kind == "read"


def test_GIT_CONFIG_COUNT는_숫자_값이면_읽기다(home, monkeypatch):
    # given
    monkeypatch.setenv("GIT_CONFIG_COUNT", "3")
    # when
    outcome = classify("env | grep GIT_CONFIG_COUNT")
    # then
    assert outcome.kind == "read"


def test_http_extraHeader를_설정하는_GIT_CONFIG는_계속_민감하다(home, monkeypatch):
    # given
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "http.extraHeader")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "Authorization: Bearer abc123")
    # when
    outcome = classify("env | grep GIT_CONFIG")
    # then
    assert outcome.kind == "sensitive"


def test_짝이_없거나_숫자가_아닌_GIT_CONFIG_변수는_계속_민감하다(home, monkeypatch):
    # given
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.interactive")
    # when
    outcome = classify("env | grep GIT_CONFIG_KEY_0")
    # then
    assert outcome.kind == "sensitive"


def test_비밀_값을_가진_이름이_맞으면_계속_민감하다(home, monkeypatch):
    # given
    monkeypatch.setenv("DEMO_API_TOKEN", "abc123")
    # when
    outcomes = [classify("env | grep TOKEN"), classify("env | grep DEMO_API_TOKEN"), classify("env")]
    # then
    assert [outcome.kind for outcome in outcomes] == ["sensitive"] * 3


# --- A4. 로컬 Docker 메타데이터 읽기 --------------------------------------------------------------------------------------------

def test_로컬_docker_system_df와_volume_ls는_읽기다(home):
    # given
    commands = ["docker system df", "docker system df -v", "docker volume ls", "docker volume ls -f dangling=true -q"]
    for command in commands:
        # when
        outcome = classify(command)
        # then
        assert outcome.kind == "read", command


@pytest.mark.parametrize("command", [
    "docker volume inspect -f '{{json .Labels}}' demo",
    "docker volume inspect --format '{{.Name}} {{.Driver}} {{.Mountpoint}} {{.CreatedAt}}' demo",
    "docker volume inspect --format={{.Labels}} demo",
    "docker volume inspect -f '{{index .Labels \"com.example.demo\"}}' demo",
    "docker image inspect -f '{{.Id}} {{json .RepoTags}} {{.Size}}' demo:latest",
    "docker network inspect -f '{{.Name}} {{.Driver}}' demo",
])
def test_로컬_docker의_이름과_라벨_같은_메타데이터_형식은_읽기다(home, command):
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "read"


def test_기록된_docker_정리_후보_조회는_묻지_않는다(home):
    # given
    command = ("docker system df -v 2>/dev/null | sed -n '/Local Volumes space usage/,/Build cache/p' | awk 'NR<=3 "
               "|| $2==0' | head -45; echo; for v in $(docker volume ls -f dangling=true -q); do echo \"$v $(docker volume "
               "inspect -f '{{json .Labels}}' $v | cut -c1-120)\"; done")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


@pytest.mark.parametrize("command", [
    "docker inspect demo",
    "docker container inspect demo",
    "docker container inspect -f '{{.Name}}' demo",
    "docker inspect -f '{{.Name}}' demo",
    "docker volume inspect demo",
    "docker volume inspect -f '{{json .Options}}' demo",
    "docker volume inspect -f '{{json .}}' demo",
    "docker volume inspect -f '{{.Name}} {{.Options}}' demo",
    "docker volume inspect -f json demo",
    "docker image inspect -f '{{.Config.Env}}' demo:latest",
    "docker image inspect -f '{{json .Config}}' demo:latest",
    "docker network inspect -f '{{json .Containers}}' demo",
    "docker volume inspect -f '{{range .Labels}}{{.}}{{end}}' demo",
])
def test_이름과_라벨이_아닌_것을_드러낼_수_있는_docker_inspect는_계속_민감하다(home, command):
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "sensitive"


@pytest.mark.parametrize("command", [
    "DOCKER_HOST=tcp://example.com:2376 docker system df",
    "DOCKER_HOST=tcp://example.com:2376 docker volume inspect -f '{{json .Labels}}' demo",
    "docker --host tcp://example.com:2376 volume inspect -f '{{json .Labels}}' demo",
    "docker -H tcp://example.com:2376 system df",
])
def test_원격_엔진에_대한_docker_조회는_로컬과_같이_읽기로_보지_않는다(home, command):
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ("write", "sensitive")


def test_원격_엔진_환경에서_docker_inspect_형식도_계속_민감하다(home, monkeypatch):
    # given
    monkeypatch.setenv("DOCKER_HOST", "tcp://example.com:2376")
    # when
    outcome = classify("docker volume inspect -f '{{json .Labels}}' demo")
    # then
    assert outcome.kind == "sensitive"


# --- 보강: 우회하기 쉬운 형태 ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "find . -type f | xargs grep -ec TOKEN",
    "find . -type f | xargs grep -e -c TOKEN",
    "find . -type f | xargs grep -A2 TOKEN",
    "find . -type f | xargs grep -n -- -l",
])
def test_옵션_값이_이름_옵션처럼_보이는_xargs_grep은_계속_민감하다(home, command):
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "sensitive"


def test_cut_문자_범위는_앞선_필터가_보여_주는_것만_줄인다(home, monkeypatch):
    # given
    monkeypatch.setenv("DEMO_API_TOKEN", "abc123")
    # when
    outcomes = [classify("env | cut -c1-60"), classify("env | grep DEMO_API_TOKEN | cut -c1-60")]
    # then
    assert [outcome.kind for outcome in outcomes] == ["sensitive"] * 2


def test_같은_명령에서_환경을_바꾼_뒤의_env_grep은_계속_민감하다(home):
    # given
    command = "export DEMO_API_TOKEN=abc123; env | grep DEMO_API_TOKEN"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "sensitive"


def test_chmod_뒤_상대_실행_파일_형태도_본문으로_분류한다(home):
    # given
    command = (heredoc_write("/tmp/work/demo/scratchpad/run.py", "#!/usr/bin/env python3\n" + READ_ONLY_BODY)
               + "chmod +x /tmp/work/demo/scratchpad/run.py\n/tmp/work/demo/scratchpad/run.py .")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


def test_반복문_안에서_실행하는_스크립트는_계속_묻는다(home):
    # given
    command = (heredoc_write("/tmp/work/demo/scratchpad/job.py", READ_ONLY_BODY)
               + "for i in 1 2; do python3 /tmp/work/demo/scratchpad/job.py .; cp /tmp/work/demo/other.py "
               "/tmp/work/demo/scratchpad/job.py; done")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_sort의_출력_파일_옵션은_스크립트를_바꿀_수_있으므로_계속_묻는다(home):
    # given
    command = (heredoc_write("/tmp/work/demo/scratchpad/job.py", READ_ONLY_BODY)
               + "sort -o /tmp/work/demo/scratchpad/job.py /tmp/work/demo/other.py\npython3 /tmp/work/demo/scratchpad/job.py .")
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_작업_폴더를_바꾸는_본문은_상대_경로_쓰기를_믿지_않고_계속_묻는다(home):
    # given
    body = "import os\nos.chdir('/home/test/projects')\nopen('out.txt', 'w').write('x')\n"
    command = heredoc_write("/tmp/work/demo/scratchpad/job.py", body) + "python3 /tmp/work/demo/scratchpad/job.py"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


# --- F2. 한 번 실행한 heredoc 스크립트 본문은 다시 믿지 않는다 ---------------------------------------------------------------

JOB = "/tmp/work/demo/scratchpad/job.py"
SELF_REWRITE_BODY = (
    "import os\nopen('/tmp/work/demo/scratchpad/job.py', 'w').write(\"import os; os.system('rm -rf /home/test/project')\")\n"
)


def test_본문이_자기_경로를_덮어쓰는_스크립트를_두_번_실행하면_묻는다(home):
    # given
    command = heredoc_write(JOB, SELF_REWRITE_BODY) + f"python3 {JOB}\npython3 {JOB}"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_본문이_자기_경로를_쓰는_스크립트는_한_번만_실행해도_묻는다(home):
    # given
    command = heredoc_write(JOB, SELF_REWRITE_BODY) + f"python3 {JOB}"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


@pytest.mark.parametrize("body", [
    "import sys\nopen(sys.argv[1], 'w').write('x')\n",
    "import sys\nopen('/tmp/work/demo/scratchpad/' + sys.argv[1], 'w').write('x')\n",
    "import sys\nopen('/tmp/work/demo/scratchpad/out.txt', sys.argv[1]).write('x')\n",
])
def test_본문이_쓰는_위치를_알_수_없으면_그_스크립트의_본문을_믿지_않고_묻는다(home, body):
    # given
    command = heredoc_write(JOB, body) + f"python3 {JOB} x"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_읽기_전용_본문의_스크립트도_같은_명령에서_두_번째_실행은_묻는다(home):
    # given
    command = heredoc_write(JOB, READ_ONLY_BODY) + f"python3 {JOB} .\npython3 {JOB} ."
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in ASKS


def test_읽기_전용_본문의_스크립트는_첫_실행만_묻지_않는다(home):
    # given
    command = heredoc_write(JOB, READ_ONLY_BODY) + f"python3 {JOB} ."
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET


# --- F3. xargs 입력이 옵션처럼 보이는 단어를 낼 수 있으면 grep과 rg는 민감하다 ----------------------------------------------

def test_파일에서_읽은_입력을_받는_xargs_rg는_옵션_구분자가_없으면_민감하다(home):
    # given
    command = "xargs rg -l demo < /tmp/work/arguments.txt"
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "sensitive"


@pytest.mark.parametrize("command", [
    "xargs rg -l demo -- < /tmp/work/arguments.txt",
    "xargs grep -l -- demo < /tmp/work/arguments.txt",
    "xargs -I{} grep -l -- demo {} < /tmp/work/arguments.txt",
    "find /tmp/work/demo -type f -print0 | xargs -0 rg -l demo",
    "find . -name '*.md' | xargs grep -c demo",
    "echo a.txt b.txt | xargs grep -l demo",
    "printf '%s\\n' a.txt b.txt | xargs rg -l demo",
    "xargs wc -l < /tmp/work/arguments.txt",
    "xargs ls -la < /tmp/work/arguments.txt",
    "xargs stat < /tmp/work/arguments.txt",
    "xargs du -k < /tmp/work/arguments.txt",
])
def test_입력이_옵션처럼_보이는_단어를_낼_수_없거나_옵션_구분자가_앞서면_xargs_판독기는_읽기다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind in QUIET, command


@pytest.mark.parametrize("command", [
    "xargs grep -l demo < /tmp/work/arguments.txt",
    "cat /tmp/work/arguments.txt | xargs rg -l demo",
    "find -- -x -type f | xargs rg -l demo",
    "find /tmp/work/demo -printf '%p\\n' | xargs rg -l demo",
    "find /tmp/work/demo -exec echo --pre=x {} + | xargs rg -l demo",
    'find "$UNSET_ROOT" -type f | xargs rg -l demo',
    "echo --pre=x a.txt | xargs rg -l demo",
    "echo 'a.txt -x' | xargs rg -l demo",
    "echo *.txt | xargs rg -l demo",
    "ls /tmp/work/demo | xargs rg -l demo",
    "xargs -a /tmp/work/arguments.txt rg -l demo",
])
def test_입력이_옵션처럼_보이는_단어를_낼_수_있으면_옵션_구분자가_없는_xargs_판독기는_민감하다(home, command):
    # given
    # when
    outcome = classify(command)
    # then
    assert outcome.kind == "sensitive", command


# --- F5. 값이 거짓이어도 이름 자체가 비밀일 수 있는 GIT_CONFIG_KEY ---------------------------------------------------------

@pytest.mark.parametrize("key", [
    "http.https://demo:secret@example.com/.sslVerify",
    "http.extraHeader",
    "url.https://demo:secret@example.com/.insteadOf",
])
def test_값이_거짓이어도_허용_목록에_없는_GIT_CONFIG_키는_민감하다(home, monkeypatch, key):
    # given
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", key)
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    # when
    outcome = classify("env | grep GIT_CONFIG")
    # then
    assert outcome.kind == "sensitive"


def test_허용_목록의_자격_증명_키는_대소문자와_관계없이_읽기다(home, monkeypatch):
    # given
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.Interactive")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "credential.GUIPROMPT")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "false")
    # when
    outcome = classify("env | grep GIT_CONFIG")
    # then
    assert outcome.kind == "read"
