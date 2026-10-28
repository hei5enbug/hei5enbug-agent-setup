"""승인 정책의 세 층(조회, 세션 승인, 매번 승인)과 그 경계를 표로 열거해 확인한다."""
import json
import re
from pathlib import Path

import pytest

from test_approval_guard import bash_event, datagrip_guard, fake_bin, guard, state, state_mod  # noqa: F401
import guard_dispatch  # noqa: E402
import guard_tools  # noqa: E402

WRITE_KEY = state_mod.WRITE_KEY
SENSITIVE_KEY = state_mod.SENSITIVE_KEY
CODE = re.compile(r"(?:승인|approve) ([A-Z2-9]{6})")
STATE_NAME = "hei5enbug-agent-setup"


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def reason(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"] if output else ""


def asked(output, host):
    return decision(output) == ("ask" if host == "claude" else "deny")


def passed(output, host):
    return decision(output) == ("allow" if host == "claude" else None)


def mcp_event(tool, tool_input, tool_use_id="t1", name="PreToolUse", session="s1", **extra):
    return {"hook_event_name": name, "session_id": session, "tool_name": tool, "tool_input": tool_input,
            "tool_use_id": tool_use_id, **extra}


def approve_and_finish(event, host):
    """사용자가 각 호스트에서 승인하는 방식대로 승인하고 호출을 끝낸다. 첫 PreToolUse 출력을 돌려준다."""
    first = guard.handle(event, host)
    if host == "codex":
        code = CODE.search(reason(first))[1]
        guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": event["session_id"],
                      "prompt": "승인 " + code}, host)
        guard.handle(event, host)
    guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    return first


def with_id(event, tool_use_id):
    return {**event, "tool_use_id": tool_use_id}


# --- 매번 묻는 목록의 모든 행 ------------------------------------------------------------------------------------------

EVERY_TIME_COMMANDS = [
    # 파괴적 git과 gh
    "git push --force origin main", "git push --force-with-lease origin main", "git push --delete origin old",
    "git push --mirror", "git push --prune", "git push origin +main", "git push origin :old-branch",
    "git reset --hard", "git clean -fd", "git checkout -f main", "git checkout .", "git restore .",
    "git stash drop", "git stash clear", "gh repo delete owner/repo --yes", "gh api /x -X DELETE",
    # 보호·외부 경로 또는 미해결 대상의 재귀 삭제
    "rm -rf /usr/local/share/example-data", "rm -rf $UNKNOWN_TARGET/x", "rm -rf ~",
    # 파괴적 SQL
    'psql -c "delete from t"', 'psql -c "drop table t"', 'sqlcmd -Q "TRUNCATE TABLE t"',
    # 원격 인프라 삭제
    "kubectl delete pod x --context dev -n web", "oc delete pod x", "kubectl drain node1 --context dev",
    "kubectl apply -f a.yaml --force --context dev -n web", "kubectl apply -f a.yaml --prune -l app=x --context dev",
    "helm uninstall web --kube-context dev", "az group delete -n rg", "az rest -m DELETE --url https://management.azure.com/x",
    "aws s3 rm s3://b", "aws s3 sync . s3://b --delete", "gcloud compute instances delete x", "gsutil rm gs://b/x",
    "terraform destroy", "terraform apply -destroy", "terraform state rm x", "tofu destroy",
    "kubectl exec pod -- rm -rf /data", "oc exec pod -- rm -rf /data",
    # 패키지 배포
    "npm publish", "pnpm publish", "yarn publish", "uv publish", "poetry publish", "cargo publish",
    "twine upload dist/*", "gem push x.gem",
    # docker와 podman의 삭제
    "docker --context prod rm c1", "docker --context prod rmi img", "docker --host ssh://prod system prune",
    "docker --context prod volume rm v", "docker --context prod compose down -v",
    "podman --connection prod rm c1", "podman --connection prod system prune",
    "docker --context prod exec c1 rm -rf /data", "podman --connection prod exec c1 rm -rf /data",
    # curl의 파괴적 메서드
    "curl -X DELETE https://example.com/item/1",
    # 샌드박스 없는 Codex 실행
    "codex exec -s danger-full-access task", "codex exec --dangerously-bypass-approvals-and-sandbox task",
    # 분류 불가 호출 중 파괴 문구가 있는 것
    "eval kubectl delete pod x", "kubectl delete $RESOURCE x", "kubectl delete 'x",
    "python3 -c 'import boto3; boto3.client(\"s3\").delete_bucket(Bucket=\"x\")'",
]


@pytest.mark.parametrize("command", EVERY_TIME_COMMANDS)
def test_매번_묻는_목록의_행은_매번_묻는_작업으로_분류된다(state, fake_bin, command):
    """매번 묻는 목록의 모든 행은 분류 단계에서 매번 묻는 작업이고 세션 키를 만들지 않는다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True
    assert outcome.keys
    assert not set(outcome.keys) & state_mod.SESSION_KEYS
    assert state_mod.split_outcome(outcome)[0] == outcome.keys


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("command", EVERY_TIME_COMMANDS)
def test_매번_묻는_목록의_행은_승인한_뒤에도_호출마다_다시_묻는다(state, fake_bin, host, command):
    """매번 묻는 목록의 호출은 승인해도 같은 호출을 다시 하면 두 호스트 모두 다시 묻는다."""
    # given
    first = approve_and_finish(bash_event(command, cwd=state, tool_use_id="first"), host)
    # when
    again = guard.handle(bash_event(command, cwd=state, tool_use_id="second"), host)
    # then
    assert asked(first, host)
    assert asked(again, host)
    if host == "claude":
        assert reason(again).startswith("Asks every time:")
    else:
        assert CODE.search(reason(again))


EVERY_TIME_MCP = [
    ("mcp__demo__deleteItem", {}),
    ("mcp__demo__trash_message", {"id": 1}),
    ("mcp__demo__manage", {"action": "delete"}),
    ("mcp__db__run_query", {"query": "DROP TABLE orders"}),
    ("mcp__db__run_query", {"sql": "DELETE FROM orders"}),
]


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize(("tool", "tool_input"), EVERY_TIME_MCP)
def test_파괴적_mcp_호출은_매번_묻는_작업이다(state, fake_bin, host, tool, tool_input):
    """삭제 단어가 있는 MCP 도구 이름과 action, 파괴적 SQL 필드는 승인한 뒤에도 매번 묻는다."""
    # given
    outcome = guard.classify_mcp(tool, tool_input)
    approve_and_finish(mcp_event(tool, tool_input, "first"), host)
    # when
    again = guard.handle(mcp_event(tool, tool_input, "second"), host)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True
    assert asked(again, host)


def test_datagrip의_파괴적_문장은_매번_묻는_작업이다(state):
    """DataGrip의 파괴적 문장은 매번 묻는 작업으로 분류하고 세션 키를 만들지 않는다."""
    # given
    tool_input = {"projectPath": str(state), "connectionId": "c1", "queryText": "DROP TABLE t"}
    # when
    outcome = datagrip_guard.classify_query(tool_input)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True
    assert not set(outcome.keys) & state_mod.SESSION_KEYS


def test_tabularis의_파괴적_문장은_매번_묻는_작업이다(state, monkeypatch):
    """tabularis의 파괴적 문장은 매번 묻는 작업으로 분류한다."""
    # given
    directory = state / "tabularis"
    directory.mkdir()
    monkeypatch.setenv("HEI5ENBUG_TABULARIS_DIR", str(directory))
    (directory / "connections.json").write_text(json.dumps([
        {"id": "pg", "name": "demo", "params": {"driver": "postgresql"}}]))
    # when
    outcome = guard.classify_mcp("mcp__tabularis__run_query", {"connection_id": "pg", "query": "TRUNCATE t"})
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_스크립트_안의_분류_불가_파괴_문구는_매번_묻고_그_밖의_문구는_세션_쓰기다(state, fake_bin):
    """분류하지 못한 스크립트는 파괴 문구가 있을 때만 매번 묻고, 없으면 해시 키 대신 세션 쓰기로 분류한다."""
    # given
    (state / "danger.sh").write_text("echo kubectl delete pod x\n")
    (state / "calm.sh").write_text("echo kubectl get pods\n")
    # when
    danger = guard.classify_text("bash danger.sh", str(state))
    calm = guard.classify_text("bash calm.sh", str(state))
    # then
    assert danger.kind == "always"
    assert danger.every_time is True
    assert danger.keys[0].startswith("script:")
    assert calm.kind == "write"
    assert state_mod.split_outcome(calm) == ([], [WRITE_KEY])


def test_분류기_예외는_매번_묻는_작업이고_stderr에_한_줄을_남긴다(state, fake_bin, monkeypatch, capsys):
    """분류기가 예외를 던지면 매번 묻는 작업으로 처리하고 예외 종류를 stderr에 한 줄 적는다."""
    # given
    def fail(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(guard_dispatch, "classify_text", fail)
    # when
    output = guard.handle(bash_event("echo hi", cwd=state), "claude")
    # then
    assert decision(output) == "ask"
    assert reason(output).startswith("Asks every time:")
    assert capsys.readouterr().err == "approval_guard: classifier error: RuntimeError\n"


def test_mcp_분류기_예외도_stderr에_한_줄을_남긴다(state, monkeypatch, capsys):
    """MCP 분류기 예외도 같은 형식으로 stderr에 한 줄을 남긴다."""
    # given
    def fail(*args, **kwargs):
        raise KeyError("boom")
    monkeypatch.setattr(guard_tools, "classify_mcp", fail)
    # when
    output = guard.handle(mcp_event("mcp__demo__thing", {}), "claude")
    # then
    assert decision(output) == "ask"
    assert capsys.readouterr().err == "approval_guard: classifier error: KeyError\n"


def test_분류된_매번_작업은_모두_every_time_표시를_갖는다(state, fake_bin):
    """어떤 입력에서도 always 결과는 every_time 표시를 가지므로 재사용되는 always 층이 없다."""
    # given
    corpus = [*EVERY_TIME_COMMANDS, "kubectl apply -f a", "git tag -d v1", "helm get values w", "printenv", "npm run x",
              "kubectl config delete-context x", "helm repo remove r", "kubectl exec pod -- tool --force"]
    # when
    outcomes = [guard.classify_text(command, str(state)) for command in corpus]
    # then
    assert not hasattr(state_mod, "reusable")
    assert all(outcome.every_time for outcome in outcomes if outcome.kind == "always")


# --- 매번 목록에서 옮긴 항목 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "terraform state show x", "terraform state pull", "terraform output -json", "terraform output -raw name",
    "tofu state show x", "helm get values web", "helm get manifest web", "helm get all web",
])
def test_terraform_상태_출력과_helm_값_조회는_민감_조회다(state, fake_bin, command):
    """terraform 상태·출력과 helm 값 조회는 매번이 아니라 세션 1회 민감 조회로 분류한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "sensitive"
    assert outcome.keys == [SENSITIVE_KEY]
    assert outcome.every_time is False
    assert state_mod.split_outcome(outcome) == ([], [SENSITIVE_KEY])


@pytest.mark.parametrize("command", [
    "kubectl config delete-context old", "kubectl config use-context dev", "kubectl config set-context dev",
    "kubectl config unset users.x", "oc config delete-cluster old", "helm repo remove stable", "helm repo rm stable",
    "git tag -d v1", "git tag --delete v1", "git tag -f v1", "git tag --force v1",
    "kubectl exec pod -- tool --force", "kubectl run job --image=x -- sh -c 'a --prune'",
])
def test_로컬_설정_변경과_로컬_태그_삭제는_세션_쓰기다(state, fake_bin, command):
    """kubectl config, helm repo remove, 로컬 git tag 삭제와 `--` 뒤의 --force는 매번이 아니라 세션 쓰기다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "write"
    assert state_mod.split_outcome(outcome) == ([], [WRITE_KEY])


@pytest.mark.parametrize("command", ["kubectl config view", "kubectl config get-contexts", "kubectl config current-context"])
def test_kubectl_config_조회는_계속_읽기다(state, fake_bin, command):
    """kubectl config의 조회 하위 명령은 계속 읽기다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "read"


@pytest.mark.parametrize("command", [
    "kubectl apply --force -f a.yaml", "kubectl apply -f a.yaml --prune", "oc replace --force -f a.yaml",
    "kubectl --force apply -f a.yaml",
])
def test_force와_prune은_구분자_앞_옵션일_때만_매번_묻는다(state, fake_bin, command):
    """kubectl과 oc의 --force와 --prune은 `--` 앞에 있을 때만 매번 묻는 작업으로 센다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_민감_조회_승인은_세션의_모든_민감_조회를_허용하고_쓰기는_허용하지_않는다(state, fake_bin, host):
    """terraform 출력 민감 조회를 한 번 승인하면 다른 민감 조회는 허용하지만 쓰기는 따로 묻는다."""
    # given
    first = approve_and_finish(bash_event("terraform output -json", cwd=state, tool_use_id="first"), host)
    # when
    other = guard.handle(bash_event("helm get values web --kube-context dev", cwd=state, tool_use_id="second"), host)
    write = guard.handle(bash_event("kubectl apply -f a.yaml -n web --context dev", cwd=state, tool_use_id="third"), host)
    # then
    assert asked(first, host)
    assert passed(other, host)
    assert asked(write, host)
    assert state_mod._load(host, "s1")["approved"] == [SENSITIVE_KEY]


# --- C1-2 민감 조회 -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", ["cat .env", "printenv", "env", "docker inspect web", "kubectl exec pod -- env"])
def test_민감_조회는_세션_키_하나와_명령을_부르는_한_줄_설명을_낸다(state, fake_bin, command):
    """민감 조회는 sensitive:session 하나와 명령 이름이 든 한 줄 설명 하나를 낸다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "sensitive"
    assert outcome.keys == [SENSITIVE_KEY]
    assert outcome.descriptions == [command]


def test_민감_조회_설명은_60자_한_줄로_줄인다(state, fake_bin):
    """긴 명령이나 여러 줄 명령의 민감 조회 설명은 한 줄 60자 이내로 줄인다."""
    # given
    command = "cat .env\n" + "echo " + "x" * 80
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "sensitive"
    assert len(outcome.descriptions) == 1
    assert "\n" not in outcome.descriptions[0]
    assert len(outcome.descriptions[0]) <= 60
    assert outcome.descriptions[0].startswith("cat .env echo")


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_첫_민감_조회_승인은_다른_민감_조회를_세션_동안_허용한다(state, fake_bin, host):
    """첫 민감 조회를 승인하면 명령이 달라도 같은 세션의 민감 조회는 다시 묻지 않는다."""
    # given
    first = approve_and_finish(bash_event("cat .env", cwd=state, tool_use_id="first"), host)
    # when
    others = [guard.handle(bash_event(command, cwd=state, tool_use_id=f"next{index}"), host)
              for index, command in enumerate(["head .env", "printenv", "env", "docker inspect web"])]
    # then
    assert asked(first, host)
    assert all(passed(output, host) for output in others)


def test_옛_민감_digest_키는_새_세션_키를_대신하지_못한다(state, fake_bin):
    """상태 파일에 남은 옛 sensitive:<digest> 키는 해롭지 않고 새 민감 조회 승인을 대신하지도 않는다."""
    # given
    state_mod.record_approved("claude", "s1", ["sensitive:0123456789ab"])
    # when
    output = guard.handle(bash_event("cat .env", cwd=state), "claude")
    # then
    assert decision(output) == "ask"
    assert reason(output).startswith("Sensitive read: cat .env (may show a value). ")


ENVIRONMENT_NAME_READS = [
    "env | cut -d= -f1",
    "env | cut -d= -f1 | sort",
    "env | cut -d '=' -f 1 | grep -i token",
    "env | cut --delimiter== --fields=1",
    "printenv | cut -d= -f1",
    "env | grep -i token | cut -d= -f1",
    "env | grep CLAUDE_CODE_ | cut -d= -f1 | sort -u",
    "env | grep -o '^[A-Z_]*'",
    "env | grep -oE '^[A-Za-z_][A-Za-z0-9_]*'",
    "env | grep -o '^[^=]*' | sort",
    "env | grep -c TOKEN",
    "env | awk -F= '{print $1}'",
    "env | awk -F '=' '{ print $1 }' | sort",
    "env | sed -E 's/=.*/=<v>/'",
    "env | sed 's/=.*/=***/' | grep TOKEN",
    "env | sed -E 's/=.+/=masked/g'",
    "env | sed 's/^\\([^=]*\\)=.*/\\1=hidden/'",
]


@pytest.mark.parametrize("command", ENVIRONMENT_NAME_READS)
def test_이름만_출력하거나_값을_가린_환경_변수_파이프는_조회다(state, fake_bin, command):
    """환경 변수 이름만 출력하거나 `=` 뒤를 가리는 파이프는 민감 조회가 아니라 읽기다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "read"


@pytest.mark.parametrize("command", [
    "env | cut -d= -f2", "env | cut -d: -f1", "env | cut -f1", "env | cut -d= -f1,2", "env | grep -o 'token.*'",
    "env | grep -o '^.*'", "env | grep -o '^[A-Z_=]*'", "env | grep -o '^[A-Z_]*' .env",
    "env | grep -o 'a' -o '^[A-Z]*'", "env | awk -F= '{print $2}'", "env | awk '{print $1}'",
    "env | awk -F= '{print $1}' extra.txt", "env | sed 's/x/y/'", "env | sed -E 's/=.*/&/'",
    "env | sed -E 's/=.*/\\0/'", "env | sed 's/=.*/x/w out.txt'", "env | sed -n p", "env | cut -d= -f1 | tee out",
    "env | cut -d= -f1 > out.txt", "env | cut -d= -f1 | cut -f2", "env | cut -d= -f1 $(printenv TOKEN)",
])
def test_이름만_보이지_않는_환경_변수_파이프는_계속_민감_조회다(state, fake_bin, command):
    """값이 보일 수 있는 필터가 섞인 환경 변수 파이프는 계속 민감 조회나 쓰기로 분류한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind != "read"


# --- C1-3 실행형 MCP 입력 -----------------------------------------------------------------------------------------------

REPL = "mcp__aside__repl"


@pytest.mark.parametrize("tool_input", [
    {"code": "print(1)"}, {"language": "python", "code": "x = 1"}, {"language": "bash", "code": "ls -la"},
    {"code": "ls"}, {"code": "print('remove the old files')"}, {"code": "rm_count = 0  # drop nothing"},
    {"language": "python", "code": "def trash():\n    return 'delete later'"},
])
def test_코드_입력이_파괴적이지_않으면_실행형_mcp는_세션_쓰기다(state, tool_input):
    """코드 입력이 되돌릴 수 없는 호출이 아니면 파괴 단어가 문자열에 있어도 세션 쓰기이고 digest 키가 없다."""
    # given
    tool = REPL
    # when
    outcome = guard.classify_mcp(tool, tool_input, str(state))
    # then
    assert outcome.kind == "write"
    assert not any(key.startswith(f"mcp:{tool}:") for key in outcome.keys)
    assert state_mod.split_outcome(outcome) == ([], [WRITE_KEY])


@pytest.mark.parametrize("tool_input", [
    {"language": "python", "code": "import subprocess\nsubprocess.run(['kubectl', 'delete', 'pod', 'x'])"},
    {"code": "import os\nos.system('git push --force origin main')"},
    {"language": "bash", "code": "kubectl delete pod x --context dev -n web"},
    {"language": "sh", "code": "git push --force"},
    {"code": "docker --context prod rm c1"},
    {"language": "python", "code": "import boto3\nboto3.client('s3').delete_bucket(Bucket='x')"},
])
def test_코드_입력에_매번_묻는_호출이_있으면_실행형_mcp도_매번_묻는다(state, fake_bin, tool_input):
    """실행형 MCP의 코드 입력을 기존 분류기로 분류해 매번 표시가 있으면 매번 묻는다."""
    # given
    tool = REPL
    # when
    outcome = guard.classify_mcp(tool, tool_input, str(state))
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True
    assert not any(key.startswith(f"mcp:{tool}:") for key in outcome.keys)


@pytest.mark.parametrize(("tool_input", "kind"), [
    ({"language": "bash", "code": "kubectl get secret db -o json"}, "secret"),
    ({"code": "kubectl get secret db -o json"}, "secret"),
    ({"language": "python", "code": "import subprocess\nsubprocess.run(['kubectl', 'get', 'secret', 'db', '-o', 'json'])"},
     "secret"),
    ({"language": "python", "code": "import approval_state"}, "forbidden"),
])
def test_실행형_mcp의_secret과_forbidden_분류는_그대로_보존한다(state, fake_bin, tool_input, kind):
    """코드 입력이 secret이나 forbidden으로 분류되면 같은 결과로 거부한다."""
    # given
    tool = REPL
    # when
    outcome = guard.classify_mcp(tool, tool_input, str(state))
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_실행형_mcp의_forbidden_분류는_두_호스트에서_거부된다(state, host):
    """가드를 실행하는 코드를 실행형 MCP로 보내면 Claude는 거부하고 Codex도 거부한다."""
    # given
    event = mcp_event(REPL, {"language": "python", "code": "import approval_guard"})
    # when
    output = guard.handle(event, host)
    # then
    assert decision(output) == "deny"
    assert state_mod.SESSION_KEYS.isdisjoint(state_mod._load(host, "s1")["approved"])


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_실행형_mcp의_일반_코드는_세션_쓰기_승인_한_번으로_이어서_실행된다(state, host):
    """실행형 MCP의 코드는 입력이 달라도 한 번의 세션 쓰기 승인으로 계속 실행된다."""
    # given
    first = approve_and_finish(mcp_event(REPL, {"code": "print(1)"}, "first"), host)
    # when
    other = guard.handle(mcp_event(REPL, {"code": "print(2)"}, "second"), host)
    # then
    assert asked(first, host)
    assert passed(other, host)
    assert state_mod._load(host, "s1")["approved"] == [WRITE_KEY]


def test_코드가_없는_실행형_mcp는_세션_쓰기다(state):
    """코드 문자열이 없는 실행형 MCP 호출도 세션 쓰기로 분류한다."""
    # given
    tool_input = {"timeout": 5}
    # when
    outcome = guard.classify_mcp(REPL, tool_input, str(state))
    # then
    assert outcome.kind == "write"


# --- C1-4 ParseError 폴백 ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "grep -n \"az call\" README.md; echo 'x",
    "echo \"kubectl delete x\" 'unterminated",
    "cat <<EOF\nkubectl get pods\nEOF\necho 'oops",
    "echo 'git' \"gh\" 'x",
])
def test_파싱에_실패해도_heredoc과_문자열_안의_단어는_가드_대상이_아니다(state, fake_bin, command):
    """따옴표가 닫히지 않아도 heredoc 본문과 닫힌 따옴표 문자열 안의 단어만 있으면 pass다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("command", ["kubectl get pods 'x", "echo 'a' ; az vm list 'y", "git status \"x"])
def test_파싱에_실패해도_문자열_밖의_커버된_단어는_분류_불가로_본다(state, fake_bin, command):
    """파싱에 실패했을 때 문자열 밖에 커버된 단어가 남으면 분류하지 못한 명령으로 세션 쓰기를 요구한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "write"
    assert outcome.keys[0].startswith(("kubectl:unclassified:", "az:unclassified:", "git:unclassified:"))


def test_분류하지_못한_명령의_설명은_앞_60자_한_줄이다(state, fake_bin):
    """분류하지 못한 명령의 설명은 `Unclassified command:` 뒤에 앞 60자를 한 줄로 이어 붙인다."""
    # given
    command = "kubectl get pods 'x\n" + "y" * 100
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.descriptions == ["Unclassified command: " + " ".join(command.split())[:60]]
    assert "\n" not in outcome.descriptions[0]


# --- 예외 원인 수정 ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("command", "key"), [
    ("curl -X POST http://localhost:abc/x -d y", "curl:POST@http://localhost"),
    ("curl -X POST http://localhost:99999999/x -d y", "curl:POST@http://localhost"),
    ("curl -X POST 'http://[::1/x' -d y", "curl:POST@http://[::1]"),
    ("curl -X POST 'http://user@[::1/x' -d y", "curl:POST@http://[::1]"),
    ("curl -X POST 'HTTP://[::1]:8080/x' -d y", "curl:POST@http://[::1]:8080"),
    ("curl -X POST https://example.com:8443/x -d y", "curl:POST@https://example.com:8443"),
])
def test_curl은_잘못된_포트와_ipv6_괄호에서도_예외_없이_호스트로_분류한다(state, command, key):
    """잘못된 포트나 닫히지 않은 IPv6 괄호가 있는 curl도 예외 없이 scheme과 host로 쓰기 키를 만든다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "write"
    assert outcome.keys == [key]


def test_잘못된_주소의_curl_삭제는_예외_없이_매번_묻는다(state):
    """잘못된 포트의 curl DELETE도 예외 대신 호스트로 분류해 매번 묻는다."""
    # given
    command = "curl -X DELETE http://localhost:abc/x"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"
    assert outcome.keys == ["curl:DELETE@http://localhost"]


# --- C1-5 승인 기록 -------------------------------------------------------------------------------------------------

def write_script(directory, body):
    path = directory / "getver.py"
    path.write_text(body, encoding="utf-8")
    return path


SCRIPT_WRITE = "import subprocess\nsubprocess.run(['kubectl', 'apply', '-f', 'x.yaml'])\n"


def test_permission_digest는_입력_순서와_무관한_16자리_16진수다():
    """승인 요청과 완료 이벤트가 같은 digest를 쓰도록 입력 키 순서와 무관한 16자리 16진수를 만든다."""
    # given
    first = state_mod.permission_digest("Bash", {"command": "ls", "description": "d"})
    second = state_mod.permission_digest("Bash", {"description": "d", "command": "ls"})
    other = state_mod.permission_digest("Bash", {"command": "pwd"})
    # then
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{16}", first)
    assert first != other


def test_승인_뒤_재분류가_달라도_세션_쓰기가_기록되고_asked가_비워진다(state, fake_bin):
    """승인 기록 유실 재현: 스크립트 쓰기를 승인한 뒤 내용이 바뀌어 재분류가 달라져도 write:session을 기록한다."""
    # given
    script = write_script(state, SCRIPT_WRITE)
    event = bash_event(f"python3 {script}", cwd=state, tool_use_id="toolu_1")
    first = guard.handle(event, "claude")
    before = state_mod._load("claude", "s1")["asked"]
    script.write_text("print('changed')\n")
    # when
    guard.handle({**event, "hook_event_name": "PostToolUse"}, "claude")
    # then
    assert decision(first) == "ask"
    assert before == [{"id": "toolu_1", "keys": [WRITE_KEY]}]
    data = state_mod._load("claude", "s1")
    assert data["approved"] == [WRITE_KEY]
    assert data["asked"] == []


def test_승인_뒤_재분류가_예외를_던져도_세션_쓰기가_기록된다(state, fake_bin, monkeypatch):
    """PostToolUse의 재분류가 예외를 던져도 PreToolUse에서 기록한 asked 항목으로 write:session을 기록한다."""
    # given
    script = write_script(state, SCRIPT_WRITE)
    event = bash_event(f"python3 {script}", cwd=state, tool_use_id="toolu_1")
    guard.handle(event, "claude")
    assert state_mod._load("claude", "s1")["asked"] == [{"id": "toolu_1", "keys": [WRITE_KEY]}]
    monkeypatch.setattr(guard_dispatch, "classify_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("slow")))
    # when
    guard.handle({**event, "hook_event_name": "PostToolUse"}, "claude")
    # then
    data = state_mod._load("claude", "s1")
    assert data["approved"] == [WRITE_KEY]
    assert data["asked"] == []


def test_승인_뒤_재분류가_읽기가_되어도_asked_항목의_키를_기록한다(state, fake_bin):
    """PostToolUse의 재분류가 키를 만들지 않아도 같은 tool_use_id의 asked 항목은 그대로 기록한다."""
    # given
    command = "kubectl apply -f a.yaml -n web --context dev"
    guard.handle(bash_event(command, cwd=state, tool_use_id="toolu_1"), "claude")
    # when
    guard.handle(bash_event("kubectl get pods", "PostToolUse", cwd=state, tool_use_id="toolu_1"), "claude")
    # then
    data = state_mod._load("claude", "s1")
    assert data["approved"] == [WRITE_KEY]
    assert data["asked"] == []


def test_tool_use_id가_없어도_pr_digest로_asked_항목을_찾아_기록한다(state, fake_bin):
    """tool_use_id가 맞지 않으면 tool_name과 tool_input의 pr digest가 같은 asked 항목을 찾아 재분류 없이 기록한다."""
    # given
    tool_input = {"command": "python3 tool.py --execute", "description": "run it"}
    digest = "pr:" + state_mod.permission_digest("Bash", tool_input)
    assert state_mod.request_ask("claude", "s1", [], [WRITE_KEY], digest, [WRITE_KEY])
    event = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash", "tool_input": tool_input,
             "tool_use_id": "toolu_other", "cwd": str(state)}
    # when
    guard.handle(event, "claude")
    # then
    data = state_mod._load("claude", "s1")
    assert data["approved"] == [WRITE_KEY]
    assert data["asked"] == []


def test_두_식별자가_모두_맞지_않으면_asked_항목을_건드리지_않는다(state, fake_bin):
    """tool_use_id도 digest도 맞지 않는 완료 이벤트는 다른 호출의 asked 항목을 승인으로 기록하지 않는다."""
    # given
    assert state_mod.request_ask("claude", "s1", [], [WRITE_KEY], "pr:" + "0" * 16, [WRITE_KEY])
    event = bash_event("kubectl apply -f a.yaml -n web --context dev", "PostToolUse", cwd=state, tool_use_id="other")
    # when
    guard.handle(event, "claude")
    # then
    data = state_mod._load("claude", "s1")
    assert data["approved"] == []
    assert data["asked"] == [{"id": "pr:" + "0" * 16, "keys": [WRITE_KEY]}]


def test_매번_묻는_호출은_asked_항목을_남기지_않고_승인_뒤에도_세션_키를_늘리지_않는다(state, fake_bin):
    """매번 묻는 호출은 ask 때 asked 항목을 만들지 않아 완료돼도 승인 키가 생기지 않는다."""
    # given
    command = "git push --force origin main"
    event = bash_event(command, cwd=state, tool_use_id="toolu_1")
    # when
    guard.handle(event, "claude")
    guard.handle({**event, "hook_event_name": "PostToolUse"}, "claude")
    # then
    data = state_mod._load("claude", "s1")
    assert data["approved"] == []
    assert data["asked"] == []


def test_매번_묻는_호출과_쓰기가_섞이면_쓰기_키만_기록한다(state, fake_bin):
    """쓰기와 매번 묻는 호출이 섞인 호출은 승인 뒤 write:session만 기록하고 매번 키는 남기지 않는다."""
    # given
    command = "kubectl apply -f a.yaml -n web --context dev && git push --force origin main"
    event = bash_event(command, cwd=state, tool_use_id="toolu_1")
    # when
    first = guard.handle(event, "claude")
    guard.handle({**event, "hook_event_name": "PostToolUse"}, "claude")
    # then
    assert reason(first).startswith("Asks every time:")
    assert state_mod._load("claude", "s1")["approved"] == [WRITE_KEY]
    assert state_mod._load("claude", "s1")["asked"] == []


# --- C1-6 MCP 이름 조회 판정 -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tool", [
    "mcp__atlassian__getjiraissue", "mcp__atlassian__searchjiraissuesusingjql", "mcp__atlassian__getconfluencepage",
    "mcp__atlassian__lookupjiraaccountid", "mcp__x__listdatabases", "mcp__x__describetable", "mcp__x__checkstatus",
    "mcp__x__countitems", "mcp__x__findusers", "mcp__x__showlogs", "mcp__x__readfile", "mcp__x__fetchdata",
    "mcp__x__getJiraIssue", "mcp__codex_apps__atlassian_rovo__legacy__atlassian_rovo_legacy_getjiraissue",
])
def test_단어로_나뉘지_않는_조회형_mcp_이름은_조회다(state, tool):
    """getjiraissue처럼 한 덩어리 소문자 이름이라도 조회 동사로 시작하고 쓰기 단어가 없으면 조회다."""
    # given
    tool_input = {"issueIdOrKey": "A-1"}
    # when
    outcome = guard.classify_mcp(tool, tool_input, str(state))
    # then
    assert outcome.kind == "read"


@pytest.mark.parametrize("tool", [
    "mcp__x__getandupdatepage", "mcp__x__getaddress", "mcp__x__listanddelete", "mcp__x__sendmessage",
    "mcp__x__createjiraissue", "mcp__x__deletejiraissue", "mcp__x__unknownthing", "mcp__x__gettrashcan",
])
def test_쓰기_단어가_있거나_조회_동사가_없는_한_덩어리_이름은_쓰기다(state, tool):
    """한 덩어리 이름에 쓰기·삭제 단어가 뒤따르거나 조회 동사로 시작하지 않으면 기본값인 쓰기다."""
    # given
    tool_input = {}
    # when
    outcome = guard.classify_mcp(tool, tool_input, str(state))
    # then
    assert outcome.kind == "write"
    assert state_mod.split_outcome(outcome) == ([], [WRITE_KEY])


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_getjiraissue_호출은_두_호스트에서_승인_없이_통과한다(state, host):
    """조회로 분류한 getjiraissue는 Claude에서는 허용하고 Codex에서는 권한 요청에서 허용한다."""
    # given
    event = mcp_event("mcp__atlassian__getjiraissue", {"issueIdOrKey": "A-1"})
    # when
    output = guard.handle(event, host)
    permission = guard.handle({**event, "hook_event_name": "PermissionRequest"}, host)
    # then
    assert (decision(output) == "allow") if host == "claude" else output is None
    assert (permission is None) if host == "claude" else permission["hookSpecificOutput"]["decision"]["behavior"] == "allow"


# --- C1-7 플러그인 스크립트 ---------------------------------------------------------------------------------------------

ROOT = Path(guard.__file__).resolve().parents[1]
HOST_SETTINGS = ROOT / "scripts" / "host_settings.py"


@pytest.mark.parametrize("arguments", ["check", "check --json", "check --host codex"])
def test_host_settings_check는_읽기다(state, arguments):
    """플러그인 루트의 host_settings.py check는 스크립트가 없어도 읽기로 분류한다."""
    # given
    command = f"python3 {HOST_SETTINGS} {arguments}"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "read"


@pytest.mark.parametrize("arguments", ["apply", "apply --host claude"])
def test_host_settings_apply는_세션_쓰기다(state, arguments):
    """플러그인 루트의 host_settings.py apply는 세션 쓰기로 분류한다."""
    # given
    command = f"python3 {HOST_SETTINGS} {arguments}"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "write"
    assert state_mod.split_outcome(outcome) == ([], [WRITE_KEY])
    assert outcome.descriptions == ["Apply plugin host settings"]


@pytest.mark.parametrize("command", [
    f"python3 -I {HOST_SETTINGS} check",
    f"python3 -B {HOST_SETTINGS} apply",
    "python3 /elsewhere/scripts/host_settings.py check",
    f"python3 {HOST_SETTINGS} frobnicate",
    f"python3 {HOST_SETTINGS}",
    f"cat {HOST_SETTINGS} | python3 - check",
])
def test_host_settings의_다른_호출은_읽기_예외를_받지_않는다(state, command):
    """인터프리터 옵션이 앞서거나 다른 루트이거나 알 수 없는 하위 명령이면 읽기 예외를 받지 않는다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind != "read"


# --- C1-8 자기 승인 검사 -----------------------------------------------------------------------------------------------

def state_text(directory="approvals"):
    return f"{STATE_NAME}/{directory}"


ALLOWED_STATE_READS = [
    'ls "$HOME/.local/state/{name}/approvals"',
    "ls $HOME/.local/state/{name}/approvals",
    "cat ${{HOME}}/.local/state/{name}/approvals/claude-s1.json",
    "ls $XDG_STATE_HOME/{name}/approvals",
    'ls "${{XDG_STATE_HOME}}/{name}/heartbeats"',
    "ls $HOME/.local/state/{name}/pycache",
    'ls "${{XDG_STATE_HOME:-/home/user/.local/state}}/{name}/approvals"',
    'ls -la "$HOME/.local/state/{name}/approvals" | head',
    'find "$HOME/.local/state/{name}/approvals" -type f',
    "stat $HOME/.local/state/{name}/heartbeats ; ls $HOME/.local/state/{name}/approvals",
]


@pytest.mark.parametrize("command", ALLOWED_STATE_READS)
def test_경로_접두_변수가_붙은_상태_조회는_자기_승인으로_거부하지_않는다(state, fake_bin, command):
    """$HOME과 $XDG_STATE_HOME 등 허용한 변수가 단어 맨 앞 경로 접두일 때 상태 읽기를 거부하지 않는다."""
    # given
    text = command.format(name=STATE_NAME)
    # when
    output = guard.handle(bash_event(text, cwd=state), "claude")
    # then
    assert not guard._self_approval(text)
    assert decision(output) != "deny"


DENIED_STATE_COMMANDS = [
    ('find "{state}" ${{FLAGS:--delete}}', "${"),
    ('cat "$X" {state}/f', "$"),
    ('cat "{state}/$FILE"', "$"),
    ("echo $(ls {state})", "$("),
    ("echo `ls {state}`", "`"),
    ("cat <(ls {state})", "<("),
    ("cat {state}/f >(/bin/cat)", ">("),
    ("ls {state}/{{a,b}}", "{"),
    ("{{ ls {state}; }}", "{"),
    ("ls --path=$HOME/.local/state/{name}/approvals", "$"),
    ("ls x$HOME/.local/state/{name}/approvals", "$"),
    ("ls $OTHER/.local/state/{name}/approvals", "$"),
    ("ls $HOME/.local/state/{name}/approvals/$FILE", "$"),
    ("ls ${{HOME:-/x}}/.local/state/{name}/approvals", "${"),
    ("ls ${{XDG_STATE_HOME:-$HOME/.local}}/{name}/approvals", "${"),
]


@pytest.mark.parametrize(("command", "trigger"), DENIED_STATE_COMMANDS)
def test_허용하지_않은_변수와_치환은_거부하고_사유에_원인을_적는다(state, fake_bin, command, trigger):
    """허용한 경로 접두 변수 밖의 `$`, 치환, 백틱, 프로세스 치환, 중괄호는 거부하고 원인을 사유에 적는다."""
    # given
    text = command.format(state=state_mod.state_dir(), name=STATE_NAME)
    # when
    output = guard.handle(bash_event(text, cwd=state), "claude")
    # then
    assert decision(output) == "deny"
    assert reason(output).startswith(guard.SELF_APPROVAL_REASON)
    assert f'"{trigger}"' in reason(output)


@pytest.mark.parametrize("command", [
    "X=1 ls $HOME/.local/state/{name}/approvals",
    "python3 -c \"open('$HOME/.local/state/{name}/approvals/f', 'w')\"",
    "echo x > $HOME/.local/state/{name}/approvals/f",
    "echo x >$HOME/.local/state/{name}/approvals/f",
    "rm $HOME/.local/state/{name}/approvals/f",
    "touch ${{XDG_STATE_HOME}}/{name}/approvals/f",
    "cat $HOME/.local/state/{name}/approvals/f > /tmp/x",
    "find $HOME/.local/state/{name}/approvals -delete",
    "find $HOME/.local/state/{name}/approvals -exec cat {{}} ;",
    "sed -i s/a/b/ $XDG_STATE_HOME/{name}/approvals/f",
])
def test_허용한_변수를_써도_상태_쓰기와_다른_명령은_계속_거부한다(state, fake_bin, command):
    """경로 접두 변수를 풀어도 허용 목록 밖 명령, 대입, 쓰기, 리다이렉션, find 동작은 거부한다."""
    # given
    text = command.format(name=STATE_NAME)
    # when
    output = guard.handle(bash_event(text, cwd=state), "claude")
    # then
    assert decision(output) == "deny"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_접두_변수_상태_조회는_두_호스트_모두_거부하지_않는다(state, fake_bin, host):
    """상태 조회 명령의 허용은 호스트와 무관하다."""
    # given
    text = 'ls "$HOME/.local/state/hei5enbug-agent-setup/approvals"'
    # when
    output = guard.handle(bash_event(text, cwd=state), host)
    # then
    assert decision(output) != "deny"


# --- C6 워커 자식 --------------------------------------------------------------------------------------------------------

@pytest.fixture
def child(state, monkeypatch):
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "claude:parent")
    return state


def child_event(command, cwd, name="PreToolUse"):
    return bash_event(command, name, session="child", cwd=cwd, tool_use_id="toolu_child")


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_워커_자식의_조회는_부모_승인_요구로_거부되지_않는다(child, fake_bin, host):
    """워커 조회 거부 재현: 워커의 git show, rg 조회 묶음은 부모 승인 요구로 거부되지 않는다."""
    # given
    command = 'git show abc1234 --stat && git show abc1234 -- a.py | head -30 && rg -n "API_BASE_URL" src'
    # when
    output = guard.handle(child_event(command, child), host)
    # then
    assert guard.classify_text(command, str(child)).kind == "read"
    assert "Approval is needed in the main session" not in reason(output)
    assert decision(output) != "deny"


PROTECTED_READ = (
    'git show abc1234 --stat && git show abc1234 -- tools/dev/services.json | head -30 '
    '&& rg -n "API_BASE_URL" manifests/overlays/dev/.env.backend'
)


def test_워커의_보호_파일_조회는_쓰기가_아니라_민감_조회로_분류된다(child, fake_bin):
    """워커 조회 거부 사례의 실제 명령은 .env.backend를 읽으므로 쓰기가 아니라 세션 1회 민감 조회로 분류된다."""
    # given
    command = PROTECTED_READ
    # when
    outcome = guard.classify_text(command, str(child))
    # then
    assert outcome.kind == "sensitive"
    assert state_mod.split_outcome(outcome) == ([], [SENSITIVE_KEY])


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_워커의_민감_조회는_부모가_승인하기_전에는_부모_승인_요구로_거부된다(child, fake_bin, host):
    """부모가 민감 조회를 승인하기 전에는 자식의 민감 조회를 PARENT_REASON으로 거부한다."""
    # given
    event = child_event(PROTECTED_READ, child)
    # when
    output = guard.handle(event, host)
    # then
    assert decision(output) == "deny"
    assert reason(output) == state_mod.PARENT_REASON


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_부모가_승인한_민감_조회는_워커_자식이_이어서_실행한다(child, fake_bin, host):
    """부모의 sensitive:session 승인은 자식이 그대로 쓰므로 자식의 민감 조회를 허용한다."""
    # given
    state_mod.record_approved("claude", "parent", [SENSITIVE_KEY])
    event = child_event(PROTECTED_READ, child)
    # when
    output = guard.handle(event, host)
    # then
    assert passed(output, host)
    if host == "claude":
        assert reason(output).startswith("Approved in the main session:")


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_부모가_쓰기를_승인하면_워커_자식의_쓰기도_허용한다(child, fake_bin, host):
    """부모의 write:session 승인은 자식의 일반 쓰기를 허용한다."""
    # given
    state_mod.record_approved("claude", "parent", [WRITE_KEY])
    # when
    output = guard.handle(child_event("kubectl apply -f a.yaml -n web --context dev", child), host)
    # then
    assert passed(output, host)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_부모가_승인하지_않은_세션_키가_하나라도_있으면_자식은_거부된다(child, fake_bin, host):
    """쓰기와 민감 조회가 함께 필요한 자식 호출은 둘 중 하나라도 부모가 승인하지 않았으면 거부한다."""
    # given
    state_mod.record_approved("claude", "parent", [SENSITIVE_KEY])
    command = "kubectl apply -f a.yaml -n web --context dev && cat .env"
    # when
    output = guard.handle(child_event(command, child), host)
    # then
    assert decision(output) == "deny"
    assert reason(output) == state_mod.PARENT_REASON


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("command", ["git push --force origin main", "kubectl delete pod x --context dev -n web",
                                     "docker --context prod rm c1", "npm publish"])
def test_매번_묻는_호출은_부모가_모든_세션_키를_승인해도_자식에서_거부된다(child, fake_bin, host, command):
    """매번 묻는 호출은 부모의 세션 승인으로 열리지 않고 자식에서 계속 거부되어 메인 세션이 직접 실행한다."""
    # given
    state_mod.record_approved("claude", "parent", [WRITE_KEY, SENSITIVE_KEY])
    # when
    output = guard.handle(child_event(command, child), host)
    # then
    assert decision(output) == "deny"
    assert reason(output) == state_mod.PARENT_REASON


# --- D6 rm -r의 임시 경로 치환 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    'rm -rf "$(mktemp -d)"', "rm -rf `mktemp -d`", 'rm -rf "$(mktemp -d -t work.XXXX)"',
    'rm -rf "$(mktemp -d /tmp/work.XXXXXX)"', 'rm -rf "$(mktemp -d -p /tmp)"',
    'rm -rf "${TMPDIR:-/tmp}/work"', 'rm -r "${TMPDIR:-/tmp}"/work/x',
    'cd /tmp && rm -rf "$(mktemp -d)"',
])
def test_임시_치환과_TMPDIR_기본값_꼴의_재귀_삭제는_통과한다(state, fake_bin, monkeypatch, command):
    """`$(mktemp -d)`와 `${TMPDIR:-/tmp}` 접두 대상의 재귀 삭제는 임시 경로로 풀어 승인 없이 통과한다."""
    # given
    monkeypatch.delenv("TMPDIR", raising=False)
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind in ("pass", "read")


def test_TMPDIR가_설정되면_그_값으로_기본값_꼴을_푼다(state, fake_bin, monkeypatch):
    """TMPDIR 환경 변수가 있으면 `${TMPDIR:-literal}`을 그 값으로 풀고 임시 루트 검사를 한다."""
    # given
    root = state / "scratch"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    # when
    inside = guard.classify_text('rm -rf "${TMPDIR:-/home/other}/work"', str(state))
    # then
    assert inside.kind == "pass"


@pytest.mark.parametrize("command", [
    'rm -rf "${TMPDIR:-/home/other}/work"',
    'rm -rf "$(mktemp -d /home/other/x.XXXX)"',
    'rm -rf "$(mktemp -d -p /usr/local)"',
    'rm -rf "$(mktemp -d)"/../..',
    'rm -rf "$(mktemp)"',
    'rm -rf "$(mktemp -d)" ~',
    'rm -rf "$(mktemp -d)" $HOME',
    'rm -rf "$(mktemp -d)" "$(pwd)"',
    'rm -rf "${TMPDIR:-$HOME}/x"',
    'rm -rf "$(echo /tmp/x)"',
    'rm -rf "$(mktemp -d $(pwd)/x.XXXX)"',
])
def test_풀어도_보호_경로나_외부_경로가_되는_삭제는_계속_매번_묻는다(state, fake_bin, monkeypatch, command):
    """치환이나 기본값을 풀었을 때 홈, 외부 경로, 미해결 대상이 되는 재귀 삭제는 계속 매번 묻는다."""
    # given
    monkeypatch.delenv("TMPDIR", raising=False)
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "always"
    assert outcome.every_time is True


def test_세션_폴더와_git_삭제_차단은_임시_치환으로_풀리지_않는다(state, fake_bin, monkeypatch):
    """TMPDIR가 세션 폴더 위를 가리켜도 세션 폴더 자체나 .git 삭제는 계속 차단한다."""
    # given
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(state))
    monkeypatch.setenv("TMPDIR", str(state))
    # when
    session = guard.classify_text('rm -rf "${TMPDIR:-/tmp}"', str(state))
    git = guard.classify_text('rm -rf "${TMPDIR:-/tmp}/.git"', str(state))
    # then
    assert session.kind == "always"
    assert git.kind == "always"


# --- 두 호스트의 코드 흐름 --------------------------------------------------------------------------------------------

def test_codex에서_매번_묻는_호출은_호출마다_코드가_필요하고_세션_키는_코드_한_번이면_된다(state, fake_bin):
    """Codex에서 매번 묻는 호출은 호출마다 새 코드를 요구하고, 세션 쓰기는 코드 한 번으로 이어서 실행된다."""
    # given
    every_time = bash_event("git push --force origin main", cwd=state)
    write = bash_event("kubectl apply -f a.yaml -n web --context dev", cwd=state, tool_use_id="w1")
    first = guard.handle(every_time, "codex")
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "승인 " + CODE.search(reason(first))[1]},
                 "codex")
    allowed = guard.handle(every_time, "codex")
    guard.handle({**every_time, "hook_event_name": "PostToolUse"}, "codex")
    second = guard.handle(every_time, "codex")
    write_first = guard.handle(write, "codex")
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                  "prompt": "승인 " + CODE.search(reason(write_first))[1]}, "codex")
    guard.handle(write, "codex")
    guard.handle({**write, "hook_event_name": "PostToolUse"}, "codex")
    other_write = guard.handle(bash_event("helm upgrade rel chart --kube-context dev -n web", cwd=state, tool_use_id="w2"),
                               "codex")
    # then
    assert decision(first) == "deny" and CODE.search(reason(first))
    assert allowed is None
    assert decision(second) == "deny" and CODE.search(reason(second))
    assert decision(write_first) == "deny"
    assert other_write is None
    assert state_mod._load("codex", "s1")["approved"] == [WRITE_KEY]
