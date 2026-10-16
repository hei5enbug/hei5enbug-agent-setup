import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
GUARD_PATH = SCRIPTS / "approval_guard.py"
sys.path.insert(0, str(SCRIPTS))

import approval_guard as guard  # noqa: E402
import approval_state as state_mod  # noqa: E402
import datagrip_guard  # noqa: E402

PG_ID = "11111111-1111-4111-8111-111111111111"
MSSQL_ID = "22222222-2222-4222-8222-222222222222"
APPROVAL_ID = "33333333-3333-4333-8333-333333333333"
CODE_PATTERN = re.compile(r"승인 ([A-Z2-9]{6})")
SECRET_HELPER = "python3 /plugins/hei5enbug/scripts/secret_exec.py --secret DB=k8s:dev/web/db/password -- "
TOOL_BASH = "Bash"

READ_COMMANDS = [
    "kubectl get pods -n web",
    "kubectl describe pod x --context dev",
    "kubectl apply -f a.yaml --dry-run=server",
    "kubectl get secret db -o name",
    "kubectl config view",
    "kubectl rollout status deploy/x -n web",
    "kubectl --context dev -n web get pods",
    "kubectl -n web get pods",
    "helm list -A",
    "helm get notes rel",
    "helm repo list",
    "az vm list -o table",
    "az account show",
    "az keyvault secret list --vault-name v",
    "az version",
    "az --version",
    "terraform plan",
    "terraform fmt -check",
    "terraform state list",
    "terraform workspace show",
    "aws ec2 describe-instances",
    "aws s3 ls",
    "aws sts get-caller-identity",
    "aws ssm get-parameter --name x",
    "gcloud compute instances list",
    "gcloud config get-value project",
    "terraform output",
    "terraform output -no-color",
    "gsutil ls gs://b",
    "gsutil cat gs://b/x",
    "docker ps -a",
    "docker image ls",
    "docker compose ps",
    "kustomize build .",
    "psql -c \"select 1\"",
    "psql -c 'show all' -c 'select now()'",
    "sqlcmd -Q \"SELECT 1\"",
    "kubectl get pods | grep web",
    "kubectl get pods | jq .items",
    "kubectl get pods 2>&1 | head",
    "kubectl get pods > /dev/null",
    "helm list &>/dev/null",
    "sudo -u root kubectl get pods",
    "nice -n 5 kubectl get pods",
    "env -i FOO=1 kubectl get pods",
    "time -p kubectl get pods",
    "nohup kubectl get pods",
    "FOO=bar kubectl get pods",
    "/usr/local/bin/kubectl get pods",
    "(kubectl get pods)",
    "python3 /p/scripts/secret_exec.py --secret A=k8s:c/n/s/k -- kubectl get pods",
    "python3 /p/scripts/secret_exec.py --secret A=k8s:c/n/s/k -- sh -c 'kubectl get pods -n web'",
]

WRITE_COMMANDS = [
    ("kubectl apply -f a.yaml -n web --context dev", ["kubectl:apply@(default) dev/web"]),
    ("kubectl scale deploy/x --replicas=3 --context dev -n web", ["kubectl:scale deploy/x@(default) dev/web"]),
    ("kubectl foo --context dev -n web", ["kubectl:foo@(default) dev/web"]),
    ("helm upgrade rel chart --kube-context dev -n web", ["helm:upgrade rel chart@(default) dev/web"]),
    ("aws ec2 start-instances --profile p --region r --instance-ids i-1", ["aws:ec2 start-instances@p/r"]),
    ("az vm start -g rg --subscription sub", ["az:vm start@sub/rg"]),
    ("gcloud compute instances create x --project pj", ["gcloud:compute instances create x@pj"]),
    ("gsutil cp a gs://b --project p", ["gsutil:cp a gs://b@p"]),
    ("docker run --rm alpine", ["docker:run@(current)"]),
    ("docker compose up -d", ["docker:compose up@(current)"]),
    ("psql -h db -d app -c \"insert into t values (1)\"", ["psql:insert@db/app"]),
    ("psql -c \"select 1; update t set a=1\"", ["psql:select+update@(default)/(default)"]),
    ("sqlcmd -S srv -d db -Q \"UPDATE t SET a=1\"", ["sqlcmd:update@srv/db"]),
]

ALWAYS_COMMANDS = [
    "kubectl get pods -l app=$(cat f)",
    "echo $(kubectl delete ns x)",
    "kubectl delete pod x --context dev -n web",
    "kubectl apply -f a.yaml --force --context dev -n web",
    "kubectl apply -f a.yaml --prune -l app=x --context dev -n web",
    "kubectl drain node1 --context dev",
    "kubectl --context dev",
    "helm uninstall rel -n web",
    "helm get values rel",
    "helm get all rel",
    "helm get manifest rel",
    "terraform destroy",
    "terraform apply -destroy",
    "terraform state rm x",
    "terraform state show x",
    "terraform output -json",
    "terraform force-unlock 123",
    "aws s3 rm s3://b",
    "aws s3 sync . s3://b --delete",
    "aws ec2 terminate-instances --instance-ids i-1",
    "az group delete -n rg",
    "az keyvault secret purge --vault-name v -n s",
    "gcloud compute instances delete x",
    "gsutil rm gs://b/x",
    "gsutil rb gs://b",
    "docker rm x",
    "docker rmi img",
    "docker system prune",
    "docker compose down -v",
    "docker volume rm v",
    "psql -c \"delete from t\"",
    "psql -c \"drop table t\"",
    "psql -c \"truncate t\"",
    "psql -c \"with d as (delete from t returning 1) select 1\"",
    "sqlcmd -Q \"DELETE FROM t\"",
    "mysql -e 'select 1'",
    "mongosh --eval 'db.x.find()'",
    "redis-cli get x",
    "psql",
    "psql -f x.sql -c 'select 1'",
    "kubectl get pods; kubectl delete x --context dev -n web",
    "echo $(kubectl delete ns x)",
    "kubectl get pods | xargs kubectl delete",
    "bash -c 'kubectl delete x'",
    "kubectl get pods `date`",
    "eval kubectl delete x",
    "kubectl apply -f - <<EOF\nkind: x\nEOF",
]

SECRET_COMMANDS = [
    "kubectl get secret db -o json --context dev -n web",
    "kubectl get secrets -o yaml",
    "kubectl get secret/db -o jsonpath='{.data}'",
    "kubectl -o json get secret db",
    "kubectl get --raw /api/v1/namespaces/x/secrets",
    "kubectl config view --raw",
    "kubectl create token sa",
    "az keyvault secret show --vault-name v -n s",
    "az keyvault secret download --vault-name v -n s -f out",
    "az keyvault key download --vault-name v -n k -f out",
    "az storage account keys list -n a",
    "az account get-access-token",
    "az acr credential show -n r",
    "az webapp list-connection-strings -n w -g g",
    "aws secretsmanager get-secret-value --secret-id x",
    "aws ssm get-parameter --name p --with-decryption",
    "aws ssm get-parameters --names a --with-decryption",
    "aws kms decrypt --ciphertext-blob x",
    "aws ecr get-login-password",
    "aws sts assume-role --role-arn x",
    "aws sts get-session-token",
    "aws configure get aws_secret_access_key",
    "aws rds generate-db-auth-token",
    "gcloud secrets versions access latest --secret s",
    "gcloud auth print-access-token",
    "gcloud auth print-identity-token",
    "gcloud sql generate-login-token",
    SECRET_HELPER + "kubectl get secret s -o json",
]

PASS_COMMANDS = [
    "git tag v1",
    "ls -la",
    "command -v kubectl",
    "echo \"$(date)\"; command -v kubectl",
    "command -V helm",
    "echo x; command -v kubectl",
    "",
    "echo hi",
    "cat <<EOF\nhello\nEOF",
    "echo $(date)",
    "kubectl get pods | sh",
    "kubectl get pods > out.txt",
    "kubectl get pods; rm -rf x",
    "kubectl get pods >&2",
    "helm list > out",
]


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    for name in ("CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD", "HEI5ENBUG_APPROVAL_GUARD", "PLUGIN_ROOT", "AWS_PROFILE", "AWS_REGION",
                 "CLOUDSDK_CORE_PROJECT", "DOCKER_CONTEXT", "DOCKER_HOST", "TF_WORKSPACE", "KUBECONFIG", "MARK"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.fixture
def fake_bin(state, monkeypatch):
    """Fake kubectl and az on an otherwise empty PATH so target lookups never reach a real cloud CLI."""
    bin_dir = state / "bin"
    bin_dir.mkdir()
    mark = 'if [ -n "$MARK" ]; then echo {name} >> "$MARK"; fi\n'
    kubectl_script = (
        "#!/bin/sh\n" + mark.format(name="kubectl") +
        'prev=""\n'
        'for arg in "$@"; do\n'
        '  case "$arg" in\n'
        '    --kubeconfig=*) path="${arg#--kubeconfig=}"; echo "ctx-${path##*/}"; exit 0;;\n'
        '  esac\n'
        '  if [ "$prev" = "--kubeconfig" ]; then echo "ctx-${arg##*/}"; exit 0; fi\n'
        '  prev="$arg"\n'
        'done\n'
        'if [ -n "$KUBECONFIG" ]; then echo "ctx-env-${KUBECONFIG##*/}"; exit 0; fi\n'
        "echo fake-ctx\n"
    )
    (bin_dir / "kubectl").write_text(kubectl_script)
    (bin_dir / "az").write_text("#!/bin/sh\n" + mark.format(name="az") + "echo fake-sub\n")
    for name in ("kubectl", "az"):
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


def classify(command, cwd=None):
    return guard.classify_text(command, str(cwd or Path.cwd()))


def bash_event(command, name="PreToolUse", session="s1", cwd=None, **extra):
    event = {"hook_event_name": name, "tool_name": TOOL_BASH, "tool_input": {"command": command}, "session_id": session}
    if cwd is not None:
        event["cwd"] = str(cwd)
    return {**event, **extra}


def mcp_event(tool, name="PreToolUse", session="s1"):
    return {"hook_event_name": name, "tool_name": tool, "tool_input": {}, "session_id": session}


def reason_of(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def decision_of(output):
    return output["hookSpecificOutput"]["permissionDecision"]


def code_of(output):
    return CODE_PATTERN.search(reason_of(output)).group(1)


# --- classification of Bash commands ---------------------------------------------------------------------------------

@pytest.mark.parametrize("command", READ_COMMANDS)
def test_읽기_명령은_키_없이_read로_분류된다(state, fake_bin, command):
    # given
    expected = "read"
    # when
    outcome = classify(command, state)
    # then
    assert (outcome.kind, outcome.keys) == (expected, [])


@pytest.mark.parametrize(("command", "keys"), WRITE_COMMANDS)
def test_쓰기_명령은_cli와_종류와_대상으로_키를_만든다(state, fake_bin, command, keys):
    # given
    expected_kind = "write"
    # when
    outcome = classify(command, state)
    # then
    assert (outcome.kind, outcome.keys) == (expected_kind, keys)
    assert len(outcome.descriptions) == 1


@pytest.mark.parametrize("command", ALWAYS_COMMANDS)
def test_파괴적이거나_분류할_수_없는_명령은_항상_묻는_always로_분류된다(state, fake_bin, command):
    # given
    expected = "always"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected
    assert outcome.keys


@pytest.mark.parametrize("command", SECRET_COMMANDS)
def test_값을_출력하는_명령은_secret으로_거부된다(state, fake_bin, command):
    # given
    expected = "secret"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("command", PASS_COMMANDS)
def test_커버되지_않거나_필터로_이어지지_않은_명령은_pass로_분류된다(state, fake_bin, command):
    # given
    expected = "pass"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize(
    ("command", "keys"),
    [
        ("kubectl apply -f a --context dev -n web && helm upgrade rel c --kube-context dev -n web",
         ["helm:upgrade rel c@(default) dev/web", "kubectl:apply@(default) dev/web"]),
        ("kubectl get pods --context dev -n web | grep x", []),
        ("kubectl get pods 2>&1 | grep x", []),
    ],
)
def test_여러_하위_명령은_모든_쓰기_키를_모으고_필터만_이어진_읽기는_읽기로_본다(state, fake_bin, command, keys):
    # given
    expected = "write" if keys else "read"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected
    assert outcome.keys == keys


def test_쓰기와_삭제가_섞이면_삭제가_이겨_항상_묻는다(state, fake_bin):
    # given
    command = "kubectl apply -f a --context dev -n web && kubectl delete x --context dev -n web"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "always"
    assert outcome.keys == ["kubectl:delete x@(default) dev/web"]


def test_비밀_출력이_섞이면_쓰기가_있어도_secret이_이긴다(state, fake_bin):
    # given
    command = "kubectl apply -f a --context dev -n web && kubectl get secret s -o json --context dev -n web"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "secret"


@pytest.mark.parametrize(("command", "kind"), [
    ("helm list 2>/dev/null", "read"),
    ("helm list 2>&1", "read"),
    ("helm list > /tmp/x", "pass"),
    ("helm list >> /tmp/x", "pass"),
    ("helm list 2>/tmp/err", "pass"),
    ("helm list &> /tmp/x", "pass"),
    ("helm list <input.txt", "read"),
])
def test_리다이렉션은_2_대_1과_dev_null만_읽기를_허용한다(state, fake_bin, command, kind):
    # given
    expected = kind
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("command", [
    "kubectl get pods | jq .items | sort | uniq",
    "kubectl get pods | tr a b | column",
])
def test_뒤따르는_필터_명령들은_읽기를_유지한다(state, fake_bin, command):
    # given
    expected = "read"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("command", [
    "sudo kubectl delete x --context dev -n web",
    "nice -n 5 kubectl delete x --context dev -n web",
    "env -i FOO=1 kubectl delete x --context dev -n web",
    "time -p kubectl delete x --context dev -n web",
    "sudo -u root -- kubectl delete x --context dev -n web",
    "nohup env A=1 kubectl delete x --context dev -n web",
    "/usr/bin/env kubectl delete x --context dev -n web",
    "{ kubectl delete x --context dev -n web; }",
    "(kubectl delete x --context dev -n web)",
    "if true; then kubectl delete x --context dev -n web; fi",
])
def test_래퍼와_그_옵션과_값은_벗기고_실행_파일로_분류한다(state, fake_bin, command):
    # given
    expected = ["kubectl:delete x@(default) dev/web"]
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "always"
    assert outcome.keys == expected


@pytest.mark.parametrize("command", [
    "kubectl apply -f a --context dev -n web; rm -rf x",
    "kubectl apply -f a --context dev -n web && echo done",
    "kubectl apply -f a --context dev -n web > out.txt",
    "kubectl apply -f a --context dev -n web | sh",
])
def test_승인_가능한_쓰기에_검증되지_않은_명령이나_파일_출력이_섞이면_항상_묻는다(state, fake_bin, command):
    # given
    expected_keys = ["kubectl:apply@(default) dev/web"]
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "always"
    assert outcome.keys == expected_keys


def test_쓰기에_필터가_이어지면_쓰기로_남는다(state, fake_bin):
    # given
    command = "kubectl apply -f a --context dev -n web 2>&1 | grep created"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "write"
    assert outcome.keys == ["kubectl:apply@(default) dev/web"]


def test_승인된_쓰기에_알_수_없는_명령이_붙으면_claude는_허용하지_않고_묻는다(state, fake_bin):
    # given
    command = "kubectl apply -f a --context dev -n web && rm -rf x"
    guard.handle(bash_event(command, "PostToolUse", cwd=state), "claude")
    guard.handle(bash_event("kubectl apply -f a --context dev -n web", "PostToolUse", cwd=state), "claude")
    # when
    output = guard.handle(bash_event(command, cwd=state), "claude")
    # then
    assert decision_of(output) == "ask"


def test_하위_셸_안의_커버된_명령은_셸_텍스트를_따로_분류한다(state, fake_bin):
    # given
    command = SECRET_HELPER + "sh -c 'kubectl delete x --context dev -n web'"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "always"
    assert outcome.keys == ["kubectl:delete x@(default) dev/web"]


def test_secret_helper에_구분자가_없으면_분류할_수_없어_항상_묻는다(state, fake_bin):
    # given
    command = "python3 /plugins/hei5enbug/scripts/secret_exec.py --secret DB=k8s:dev/web/db/password"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "always"
    assert outcome.keys == [f"secret_exec:unclassified:{guard._digest(command)}"]


def test_커버된_명령이_없는_heredoc은_그대로_pass다(state, fake_bin):
    # given
    command = "cat <<EOF\nhello\nEOF"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "pass"


def test_닫히지_않은_따옴표가_커버된_명령을_숨기면_항상_묻는다(state, fake_bin):
    # given
    command = "kubectl get pods 'x"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "always"
    assert outcome.keys[0].startswith("kubectl:unclassified:")


def test_닫히지_않은_따옴표라도_커버된_명령이_없으면_pass다(state, fake_bin):
    # given
    command = "echo 'x"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "pass"


def test_kustomize는_모든_호출이_읽기다(state, fake_bin):
    # given
    command = "kustomize edit set image x=y"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "read"


def test_대상_이름은__context와__n이_있으면_그대로_쓰고_없으면_현재_값을_조회한다(state, fake_bin):
    # given
    command = "kubectl apply -f a.yaml"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.keys == ["kubectl:apply@(default) fake-ctx/(default)"]


def test_대상_조회는_쓰기와_삭제에서만_실행되고_읽기에서는_실행되지_않는다(state, fake_bin, monkeypatch):
    # given
    mark = state / "mark.txt"
    monkeypatch.setenv("MARK", str(mark))
    # when
    classify("kubectl get pods", state)
    read_calls = mark.exists()
    classify("kubectl apply -f a.yaml", state)
    # then
    assert read_calls is False
    assert mark.read_text().splitlines() == ["kubectl"]


def test_대상_조회가_실패하면_현재_값_자리에_괄호_표기를_쓴다(state, monkeypatch, tmp_path):
    # given
    empty_bin = tmp_path / "empty"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    # when
    outcome = classify("kubectl apply -f a.yaml", state)
    # then
    assert outcome.keys == ["kubectl:apply@(default) (current)/(default)"]


def test_az_대상은_구독과_리소스_그룹을_쓴다(state, fake_bin):
    # given
    command = "az vm start -g rg"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.keys == ["az:vm start@fake-sub/rg"]


def test_terraform_대상은_작업_디렉터리와_워크스페이스_파일을_쓴다(state, fake_bin):
    # given
    (state / ".terraform").mkdir()
    (state / ".terraform" / "environment").write_text("staging\n")
    # when
    outcome = classify("terraform apply", state)
    # then
    assert outcome.keys == [f"terraform:apply@{state}:staging"]


def test_terraform_대상은_TF_WORKSPACE와_chdir를_따른다(state, fake_bin, monkeypatch):
    # given
    monkeypatch.setenv("TF_WORKSPACE", "prod")
    # when
    outcome = classify("terraform -chdir=infra apply", state)
    # then
    assert outcome.keys == [f"terraform:apply@{state / 'infra'}:prod"]


def test_인라인_환경_변수는_대상_값을_정한다(state, fake_bin):
    # given
    command = "DOCKER_CONTEXT=remote docker run alpine"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.keys == ["docker:run alpine@remote"]


def test_aws_대상은_프로파일과_리전을_쓰고_없으면_기본값을_쓴다(state, fake_bin):
    # given
    command = "aws ec2 start-instances --instance-ids i-1"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.keys == ["aws:ec2 start-instances@(default)/(default)"]


def test_kubectl_leading_옵션_뒤의_하위_명령도_분류한다(state, fake_bin):
    # given
    command = "kubectl -n web delete pod x --context dev"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "always"
    assert outcome.keys == ["kubectl:delete pod x@(default) dev/web"]


# --- psql and sqlcmd --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("command", "kind"), [
    ("psql -c \"select 1\"", "read"),
    ("psql -c \"select 1\" -c \"insert into t values (1)\"", "write"),
    ("psql -c \"select 1\" -f x.sql", "always"),
    ("psql -c \"insert into t values (1)\" -c \"delete from t\"", "always"),
    ("psql -c \"select 'unterminated\"", "always"),
    ("psql --command \"select 1\"", "read"),
    ("sqlcmd -Q \"SELECT 1\" -i x.sql", "always"),
    ("sqlcmd -Q \"SELECT 1\"", "read"),
    ("sqlcmd -Q \"UPDATE t SET a=1\"", "write"),
    ("sqlcmd -Q \"DROP TABLE t\"", "always"),
])
def test_psql과_sqlcmd는_읽기_쓰기_파괴를_나눈다(state, fake_bin, command, kind):
    # given
    expected = kind
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


# --- MCP tools --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tool", [
    "mcp__claude_ai_Gmail__get_thread",
    "mcp__claude_ai_Google_Drive__search_files",
    "mcp__datagrip__preview_table_data",
    "mcp__tool__fetch_page",
])
def test_읽기_동사로_시작하는_mcp_도구는_읽기다(tool):
    # given
    expected = "read"
    # when
    outcome = guard.classify_mcp(tool)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("tool", [
    "mcp__claude_ai_Slack__slack_send_message",
    "mcp__claude_ai_Atlassian__createJiraIssue",
    "mcp__tool__rename_item",
    "mcp__tool__create_get",
    "mcp__tool__do_something_else",
])
def test_쓰기_단어가_있거나_동사가_없는_mcp_도구는_한_세션_쓰기_키로_묶인다(tool):
    # given
    expected = ["mcp:session"]
    # when
    outcome = guard.classify_mcp(tool)
    # then
    assert (outcome.kind, outcome.keys) == ("write", expected)


@pytest.mark.parametrize(("tool", "expected"), [
    ("mcp__claude_ai_Slack__slack_read_channel", "read"),
    ("mcp__claude_ai_Slack__slack_search_public", "read"),
    ("mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql", "read"),
    ("mcp__claude_ai_Atlassian__getConfluencePage", "read"),
    ("mcp__tool__get_and_update_item", "write"),
    ("mcp__claude_ai_Atlassian__getTransitionsForJiraIssue", "read"),
    ("mcp__tool__update_get_status", "write"),
])
def test_쓰기_단어_없이_읽기_동사만_있는_mcp_도구만_읽기다(tool, expected):
    # given
    kind = expected
    # when
    outcome = guard.classify_mcp(tool)
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize("tool", [
    "mcp__claude_ai_Gmail__trash_message",
    "mcp__claude_ai_Google_Drive__trash_file",
    "mcp__tool__removeMember",
    "mcp__tool__revoke_token",
    "mcp__tool__get_and_delete_item",
])
def test_삭제_계열_mcp_도구는_도구_이름으로_항상_묻는다(tool):
    # given
    expected = [f"mcp:{tool}"]
    # when
    outcome = guard.classify_mcp(tool)
    # then
    assert (outcome.kind, outcome.keys) == ("always", expected)


@pytest.mark.parametrize("tool", ["mcp__broken", "mcp__only__"])
def test_이름이_모자란_mcp_도구는_분류할_수_없어_항상_묻는다(tool):
    # given
    expected = f"mcp:{tool}"
    # when
    outcome = guard.classify_mcp(tool)
    # then
    assert outcome.kind == "always"
    assert outcome.keys == [expected]


@pytest.mark.parametrize(("name", "words"), [
    ("createJiraIssue", ["create", "jira", "issue"]),
    ("slack_send_message", ["slack", "send", "message"]),
    ("merge-pull-request", ["merge", "pull", "request"]),
    ("HTTPRequest", ["http", "request"]),
    ("getOrDeleteThing", ["get", "or", "delete", "thing"]),
])
def test_도구_이름은_밑줄_하이픈_camelCase_경계에서_나뉜다(name, words):
    # given
    part = name
    # when
    result = guard.tool_words(part)
    # then
    assert result == words


@pytest.mark.parametrize(("tool", "part"), [
    ("mcp__claude_ai_Slack__slack_send_message", "slack_send_message"),
    ("mcp__a__b__c", "b__c"),
    ("mcp__broken", None),
])
def test_mcp_도구_부분은_두_번째_밑줄_쌍_뒤에서_잡힌다(tool, part):
    # given
    expected = part
    # when
    result = guard.mcp_tool_part(tool)
    # then
    assert result == expected


# --- host decisions: Claude Code ---------------------------------------------------------------------------------------

def test_claude는_읽기를_허용하고_이유를_붙인다(state, fake_bin):
    # given
    event = bash_event("kubectl get pods -n web", cwd=state)
    # when
    output = guard.handle(event, "claude")
    # then
    assert decision_of(output) == "allow"
    assert reason_of(output) == guard.READ_REASON


def test_claude는_쓰기를_처음_묻고_이유에_대상과_세션_안내를_넣는다(state, fake_bin):
    # given
    event = bash_event("kubectl apply -f a --context dev -n web", cwd=state)
    # when
    output = guard.handle(event, "claude")
    # then
    assert decision_of(output) == "ask"
    assert "kubectl apply on (default) dev/web" in reason_of(output)
    assert "rest of this session" in reason_of(output)


def test_claude는_후_처리로_기록한_쓰기_키를_같은_세션에서_허용한다(state, fake_bin):
    # given
    command = "kubectl apply -f a --context dev -n web"
    guard.handle(bash_event(command, "PostToolUse", cwd=state), "claude")
    # when
    output = guard.handle(bash_event(command, cwd=state), "claude")
    # then
    assert decision_of(output) == "allow"
    assert "Approved earlier in this session" in reason_of(output)


def test_claude의_쓰기_기록은_다른_세션에는_옮겨가지_않는다(state, fake_bin):
    # given
    command = "kubectl apply -f a --context dev -n web"
    guard.handle(bash_event(command, "PostToolUse", session="s1", cwd=state), "claude")
    # when
    output = guard.handle(bash_event(command, session="s2", cwd=state), "claude")
    # then
    assert decision_of(output) == "ask"


def test_claude는_항상_묻는_명령을_매번_묻고_기록하지_않는다(state, fake_bin):
    # given
    command = "kubectl delete x --context dev -n web"
    # when
    guard.handle(bash_event(command, "PostToolUse", cwd=state), "claude")
    output = guard.handle(bash_event(command, cwd=state), "claude")
    # then
    assert decision_of(output) == "ask"
    assert reason_of(output).endswith("This action asks every time.")
    assert state_mod._load("claude", "s1")["approved"] == []


def test_claude_후_처리는_읽기와_pass를_기록하지_않는다(state, fake_bin):
    # given
    commands = ["kubectl get pods", "git tag v1"]
    # when
    for command in commands:
        guard.handle(bash_event(command, "PostToolUse", cwd=state), "claude")
    # then
    assert not (state / "xdg" / "hei5enbug-agent-setup" / "approvals" / "claude-s1.json").exists()


def test_claude는_pass와_권한_요청에_출력하지_않는다(state, fake_bin):
    # given
    pass_event = bash_event("git tag v1", cwd=state)
    permission = bash_event("kubectl apply -f a --context dev -n web", "PermissionRequest", cwd=state)
    # when
    results = [guard.handle(pass_event, "claude"), guard.handle(permission, "claude")]
    # then
    assert results == [None, None]


def test_세션_아이디가_없으면_claude도_쓰기를_묻고_상태를_남기지_않는다(state, fake_bin):
    # given
    event = bash_event("kubectl apply -f a --context dev -n web", session=None, cwd=state)
    guard.handle({**event, "hook_event_name": "PostToolUse"}, "claude")
    # when
    output = guard.handle(event, "claude")
    # then
    assert decision_of(output) == "ask"
    assert not (state / "xdg").exists() or not any((state / "xdg").rglob("*.json"))


# --- host decisions: Codex -------------------------------------------------------------------------------------------

def test_codex는_읽기에_출력하지_않고_권한_요청에서만_허용한다(state, fake_bin):
    # given
    pre = bash_event("kubectl get pods -n web", cwd=state)
    permission = bash_event("kubectl get pods -n web", "PermissionRequest", cwd=state)
    # when
    pre_output = guard.handle(pre, "codex")
    permission_output = guard.handle(permission, "codex")
    # then
    assert pre_output is None
    assert permission_output == {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}


def test_codex는_쓰기를_승인_코드와_함께_거부하고_같은_키는_같은_코드를_받는다(state, fake_bin):
    # given
    event = bash_event("kubectl apply -f a --context dev -n web", cwd=state)
    # when
    first = guard.handle(event, "codex")
    second = guard.handle(event, "codex")
    # then
    assert decision_of(first) == "deny"
    assert "Ask the user to reply `승인" in reason_of(first)
    assert code_of(first) == code_of(second)
    assert len(code_of(first)) == 6


def test_codex는_승인_문장을_받으면_쓰기를_허용하고_권한_요청도_허용한다(state, fake_bin):
    # given
    command = "kubectl apply -f a --context dev -n web"
    code = code_of(guard.handle(bash_event(command, cwd=state), "codex"))
    # when
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"승인 {code}"}, "codex")
    pre = guard.handle(bash_event(command, cwd=state), "codex")
    permission = guard.handle(bash_event(command, "PermissionRequest", cwd=state), "codex")
    # then
    assert pre is None
    assert permission["hookSpecificOutput"]["decision"] == {"behavior": "allow"}


@pytest.mark.parametrize("prompt_template", ["approve {code}", "APPROVE {code}", "approve {lower}"])
def test_codex는_영문_approve_문장도_받고_대소문자를_구분하지_않는다(state, fake_bin, prompt_template):
    # given
    command = "kubectl apply -f a --context dev -n web"
    code = code_of(guard.handle(bash_event(command, cwd=state), "codex"))
    prompt = prompt_template.format(code=code, lower=code.lower())
    # when
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": prompt}, "codex")
    # then
    assert guard.handle(bash_event(command, cwd=state), "codex") is None


def test_codex는_모르는_코드나_다른_세션의_코드로는_승인되지_않는다(state, fake_bin):
    # given
    command = "kubectl apply -f a --context dev -n web"
    code = code_of(guard.handle(bash_event(command, cwd=state), "codex"))
    # when
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "승인 ZZZZZZ"}, "codex")
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s2", "prompt": f"승인 {code}"}, "codex")
    output = guard.handle(bash_event(command, cwd=state), "codex")
    # then
    assert decision_of(output) == "deny"
    assert code_of(output) == code


def test_codex는_항상_묻는_명령을_once_코드로_거부하고_승인_뒤_한_번만_허용한다(state, fake_bin):
    # given
    command = "kubectl delete x --context dev -n web"
    code = code_of(guard.handle(bash_event(command, cwd=state), "codex"))
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"approve {code}"}, "codex")
    # when
    first = guard.handle(bash_event(command, cwd=state), "codex")
    guard.handle(bash_event(command, "PostToolUse", cwd=state), "codex")
    second = guard.handle(bash_event(command, cwd=state), "codex")
    # then
    assert first is None
    assert decision_of(second) == "deny"


def test_codex의_once_키는_미완료_호출에서_한_번_재사용하고_그다음은_거부한다(state, fake_bin):
    """사전 검사에서 소비한 일회 승인은 완료 전 한 번 재사용하고 다음 호출에는 새 승인을 요구한다."""
    # given
    command = "kubectl delete x --context dev -n web"
    code = code_of(guard.handle(bash_event(command, cwd=state), "codex"))
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"승인 {code}"}, "codex")
    # when
    pre = guard.handle(bash_event(command, cwd=state), "codex")
    permission = guard.handle(bash_event(command, "PermissionRequest", cwd=state), "codex")
    pre_again = guard.handle(bash_event(command, cwd=state), "codex")
    after_retry = guard.handle(bash_event(command, cwd=state), "codex")
    # then
    assert pre is None
    assert permission["hookSpecificOutput"]["decision"] == {"behavior": "allow"}
    assert pre_again is None
    assert decision_of(after_retry) == "deny"


def test_codex는_secret을_거부하고_코드를_만들지_않는다(state, fake_bin):
    # given
    event = bash_event("kubectl get secret db -o json --context dev -n web", cwd=state)
    # when
    output = guard.handle(event, "codex")
    # then
    assert decision_of(output) == "deny"
    assert "secret_exec.py" in reason_of(output)
    assert "승인" not in reason_of(output)


def test_claude와_codex는_secret을_같은_사유로_거부한다(state, fake_bin):
    # given
    event = bash_event("kubectl get secret db -o json --context dev -n web", cwd=state)
    # when
    claude = guard.handle(event, "claude")
    codex = guard.handle(event, "codex")
    # then
    assert decision_of(claude) == decision_of(codex) == "deny"
    assert reason_of(claude) == reason_of(codex)
    assert "--secret VAR=<source> -- <command>" in reason_of(claude)


def test_codex_세션_아이디가_없으면_코드를_만들지_않고_세션을_알_수_없다고_거부한다(state, fake_bin):
    # given
    event = bash_event("kubectl apply -f a --context dev -n web", session=None, cwd=state)
    # when
    output = guard.handle(event, "codex")
    # then
    assert decision_of(output) == "deny"
    assert "the session is unknown" in reason_of(output)
    assert "승인 " not in reason_of(output)


def test_codex_후_처리는_승인된_쓰기_키를_건드리지_않는다(state, fake_bin):
    # given
    command = "kubectl apply -f a --context dev -n web"
    # when
    output = guard.handle(bash_event(command, "PostToolUse", cwd=state), "codex")
    # then
    assert output is None


# --- self-approval guard and toggle -----------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "cat ~/.local/state/hei5enbug-agent-setup/approvals/codex-s1.json",
    "python3 -c 'import approval_state'",
    "python3 -c 'from approval_state import approve_text'",
    "python3 -c '__import__(\"approval_state\")'",
    "python3 scripts/approval_state.py",
    "/usr/bin/python3 -I /plugins/hei5enbug/scripts/approval_state.py",
    "python3 -m approval_state",
    "python3 -m scripts.approval_state",
    "python3 -c \"import subprocess; subprocess.run(['cat', 'scripts/approval_state.py'])\"",
    "sed -i 's/x/y/' $XDG_STATE_HOME/hei5enbug-agent-setup/approvals/x.json",
])
@pytest.mark.parametrize("host", ["claude", "codex"])
def test_승인_상태를_건드리는_bash_명령은_두_호스트_모두_거부한다(state, fake_bin, command, host):
    # given
    event = bash_event(command, cwd=state)
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == "deny"
    assert "Approvals come only from the user" in reason_of(output)


@pytest.mark.parametrize("command", [
    "ls approvals",
    "echo '{}' > /tmp/x/approvals/claude-s1.json; echo hei5enbug-agent-setup",
    "rg approval_state scripts/",
    "cat scripts/approval_state.py",
    "rg 'import approval_state' scripts/",
    "python3 -c 'print(open(\"scripts/approval_state.py\").read())'",
    "python3 scripts/session_context.py",
])
def test_승인_상태를_언급만_하거나_다른_경로인_명령은_자기_승인_거부에_걸리지_않는다(state, fake_bin, command):
    # given
    event = bash_event(command, cwd=state)
    # when
    output = guard.handle(event, "claude")
    # then
    assert output is None or output["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_토글이_꺼지면_아무것도_출력하지_않는다(state, fake_bin, monkeypatch):
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD", "false")
    stdin = json.dumps(bash_event("kubectl delete x --context dev -n web"))
    # when
    completed = run_guard(stdin, state, host="claude", extra={"CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD": "false"})
    # then
    assert completed.returncode == 0
    assert completed.stdout == b""


def run_guard(stdin, state, host="claude", extra=None):
    env = {
        "PATH": os.defpath,
        "HOME": str(state),
        "XDG_STATE_HOME": str(state / "xdg"),
    }
    if host == "codex":
        env["PLUGIN_ROOT"] = str(REPO_ROOT)
    env.update(extra or {})
    data = stdin if isinstance(stdin, bytes) else stdin.encode("utf-8")
    return subprocess.run([sys.executable, str(GUARD_PATH)], input=data, capture_output=True, env=env, timeout=60)


def test_스크립트는_읽기를_claude_허용_json으로_출력한다(state, fake_bin):
    # given
    stdin = json.dumps(bash_event("kubectl get pods -n web", cwd=state))
    # when
    completed = run_guard(stdin, state, extra={"CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD": "true", "PATH": str(fake_bin)})
    # then
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_스크립트는_잘못된_입력에서도_출력_없이_0으로_끝난다(state, fake_bin):
    # given
    stdin = "not json"
    # when
    completed = run_guard(stdin, state)
    # then
    assert completed.returncode == 0
    assert completed.stdout == b""


def test_스크립트는_codex_host에서_승인_코드를_출력한다(state, fake_bin):
    # given
    stdin = json.dumps(bash_event("kubectl apply -f a --context dev -n web", cwd=state))
    # when
    completed = run_guard(stdin, state, host="codex", extra={"HEI5ENBUG_APPROVAL_GUARD": "true", "PATH": str(fake_bin)})
    # then
    assert completed.returncode == 0
    output = json.loads(completed.stdout)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- approval state -----------------------------------------------------------------------------------------------------

def test_세션_아이디는_안전한_문자열만_쓴다():
    # given
    values = ["s1", "abc.def-1_2", "../x", "a/b", "", None, 5, "x" * 129]
    # when
    results = [state_mod.session_key(value) for value in values]
    # then
    assert results == ["s1", "abc.def-1_2", None, None, None, None, None, None]


def test_승인_코드는_여섯_자리_영대문자와_숫자이고_같은_키는_같은_코드를_재사용한다(state):
    # given
    keys = ["kubectl:apply@dev/web"]
    # when
    first = state_mod.request_code("claude", "s1", [], keys)
    again = state_mod.request_code("claude", "s1", [], keys)
    other = state_mod.request_code("claude", "s1", [], ["helm:upgrade@x"])
    # then
    assert re.fullmatch(r"[A-Z2-9]{6}", first)
    assert first == again
    assert other != first


def test_같은_키라도_once_여부가_다르면_다른_코드를_만든다(state):
    # given
    keys = ["kubectl:delete x@dev/web"]
    # when
    write_code = state_mod.request_code("codex", "s1", [], keys)
    once_code = state_mod.request_code("codex", "s1", keys, [])
    # then
    assert write_code != once_code


def test_승인_문장은_세션_승인_또는_한_번_키로_옮기고_코드를_지운다(state):
    # given
    write_code = state_mod.request_code("codex", "s1", [], ["kubectl:apply@a"])
    once_code = state_mod.request_code("codex", "s1", ["kubectl:delete@a"], [])
    # when
    approved = state_mod.approve_text("codex", "s1", f"승인 {write_code} and approve {once_code.lower()}")
    # then
    assert approved == ["kubectl:apply@a", "kubectl:delete@a"]
    assert state_mod.is_approved("codex", "s1", ["kubectl:apply@a"])
    assert state_mod.approve_text("codex", "s1", f"승인 {write_code}") == []


def test_한_번_키는_중단된_호출에서_한_번_재사용된다(state):
    """일회 키는 처음 소비한 호출이 미완료이면 한 번만 추가로 재사용된다."""
    # given
    keys = ["kubectl:delete@a"]
    code = state_mod.request_code("codex", "s1", keys, [])
    state_mod.approve_text("codex", "s1", f"승인 {code}")
    # when
    first = state_mod.take_once("codex", "s1", keys, [], "toolu-1")
    second = state_mod.take_once("codex", "s1", keys, [], "toolu-2")
    third = state_mod.take_once("codex", "s1", keys, [], "toolu-3")
    # then
    assert (first, second, third) == (True, True, False)


def test_여러_키를_한_코드로_승인하면_모두_기록되고_하나만_소비하면_실패한다(state):
    # given
    keys = ["kubectl:apply@a", "helm:upgrade@a"]
    code = state_mod.request_code("claude", "s1", [], keys)
    state_mod.approve_text("claude", "s1", f"승인 {code}")
    # when
    partial = state_mod.is_approved("claude", "s1", ["kubectl:apply@a", "missing"])
    complete = state_mod.is_approved("claude", "s1", keys)
    # then
    assert (partial, complete) == (False, True)


def test_알_수_없는_세션은_상태를_읽거나_쓰지_않는다(state):
    # given
    # when
    result = state_mod.approve_text("codex", None, "승인 ABCDEF")
    state_mod.record_approved("claude", None, ["k"])
    # then
    assert result == []
    assert not (state / "xdg").exists()


def test_손상된_상태_파일은_빈_상태로_읽고_다음_쓰기에서_고친다(state):
    # given
    path = state_mod._path("claude", "s1")
    path.parent.mkdir(parents=True)
    path.write_text("{broken")
    # when
    before = state_mod.is_approved("claude", "s1", ["k"])
    state_mod.record_approved("claude", "s1", ["k"])
    # then
    assert before is False
    assert state_mod.is_approved("claude", "s1", ["k"])


def test_호스트와_세션마다_상태_파일이_따로_있다(state):
    # given
    state_mod.record_approved("claude", "s1", ["k"])
    # when
    other_host = state_mod.is_approved("codex", "s1", ["k"])
    other_session = state_mod.is_approved("claude", "s2", ["k"])
    # then
    assert (other_host, other_session) == (False, False)
    assert (state / "xdg" / "hei5enbug-agent-setup" / "approvals" / "claude-s1.json").exists()


def test_쓰기마다_7일_지난_상태_파일을_지우고_최근_파일은_남긴다(state):
    # given
    directory = state_mod.state_dir()
    directory.mkdir(parents=True)
    old = directory / "claude-old.json"
    recent = directory / "claude-recent.json"
    old.write_text("{}")
    recent.write_text("{}")
    eight_days = time.time() - 8 * 24 * 60 * 60
    os.utime(old, (eight_days, eight_days))
    # when
    state_mod.record_approved("claude", "s1", ["k"])
    # then
    assert not old.exists()
    assert recent.exists()


def test_쓰기는_잠금을_잡고_임시_파일을_남기지_않는다(state, monkeypatch):
    # given
    calls = []
    real_flock = state_mod.fcntl.flock

    def spy(handle, operation):
        calls.append(operation)
        return real_flock(handle, operation)

    monkeypatch.setattr(state_mod.fcntl, "flock", spy)
    # when
    state_mod.record_approved("claude", "s1", ["k"])
    # then
    assert state_mod.fcntl.LOCK_EX in calls
    assert calls[-1] == state_mod.fcntl.LOCK_UN
    leftovers = [path.name for path in state_mod.state_dir().iterdir() if path.name.endswith(".tmp")]
    assert leftovers == []


# --- DataGrip writes ----------------------------------------------------------------------------------------------------

def make_project(root):
    project = root / "project"
    (project / ".idea").mkdir(parents=True)
    (project / ".idea" / "dataSources.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<project version="4">\n'
        '  <component name="DataSourceManagerImpl" format="xml" multifile-model="true">\n'
        f'    <data-source source="LOCAL" name="demo-postgres" uuid="{PG_ID}"><driver-ref>postgresql</driver-ref></data-source>\n'
        f'    <data-source source="LOCAL" name="demo-mssql" uuid="{MSSQL_ID}"><driver-ref>sqlserver</driver-ref></data-source>\n'
        f'    <data-source source="LOCAL" name="prod 승인" uuid="{APPROVAL_ID}"><driver-ref>postgresql</driver-ref></data-source>\n'
        "  </component>\n</project>\n",
        encoding="utf-8",
    )
    return project


def query_event(project, connection_id, sql, name="PreToolUse", session="s1"):
    return {
        "hook_event_name": name,
        "tool_name": datagrip_guard.TOOL_NAME,
        "tool_input": {"projectPath": str(project), "connectionId": connection_id, "queryText": sql},
        "session_id": session,
    }


@pytest.fixture
def project(state):
    return make_project(state)


@pytest.mark.parametrize(("connection_id", "sql", "keys"), [
    (PG_ID, "INSERT INTO t VALUES (1)", ["mcp:session"]),
    (PG_ID, "INSERT INTO t VALUES (1); UPDATE t SET a = 1", ["mcp:session"]),
    (MSSQL_ID, "UPDATE dbo.T SET a = 1", ["mcp:session"]),
])
def test_datagrip_쓰기는_키승인_대상으로_묻는다(state, project, connection_id, sql, keys):
    # given
    event = query_event(project, connection_id, sql)
    # when
    outcome = datagrip_guard.classify_query(event["tool_input"])
    # then
    assert outcome.kind == "write"
    assert outcome.keys == keys


@pytest.mark.parametrize("sql", [
    "DELETE FROM t",
    "DROP TABLE t",
    "TRUNCATE t",
    "WITH d AS (DELETE FROM t RETURNING 1) SELECT 1",
    "SELECT 1; DELETE FROM t",
    "SELECT 'unterminated",
    "",
])
def test_datagrip_파괴_문장과_해석_불가_텍스트는_항상_묻는다(state, project, sql):
    # given
    event = query_event(project, PG_ID, sql)
    # when
    outcome = datagrip_guard.classify_query(event["tool_input"])
    # then
    assert outcome.kind == "always"
    assert outcome.keys[0].startswith("sql:always:")


def test_datagrip_승인_데이터_소스의_모든_쿼리는_항상_묻는다(state, project):
    # given
    event = query_event(project, APPROVAL_ID, "SELECT 1")
    # when
    outcome = datagrip_guard.classify_query(event["tool_input"])
    # then
    assert outcome.kind == "always"


def test_datagrip_claude는_쓰기를_처음_묻고_승인_뒤_프롤로그_없이_허용한다(state, project, monkeypatch):
    # given
    event = query_event(project, PG_ID, "INSERT INTO t VALUES (1)")
    # when
    first = datagrip_guard.handle(event)
    guard.handle({**event, "hook_event_name": "PostToolUse", "tool_response": {}}, "claude")
    second = datagrip_guard.handle(event)
    # then
    assert first["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert "DataGrip write (insert) on demo-postgres" in first["hookSpecificOutput"]["permissionDecisionReason"]
    assert second["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "updatedInput" not in second["hookSpecificOutput"]


def test_datagrip_claude는_파괴_문장을_매번_묻는다(state, project):
    # given
    event = query_event(project, PG_ID, "DELETE FROM t")
    # when
    first = datagrip_guard.handle(event)
    guard.handle({**event, "hook_event_name": "PostToolUse"}, "claude")
    second = datagrip_guard.handle(event)
    # then
    assert first["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert second["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_datagrip_codex는_쓰기를_거부하고_승인_뒤_출력_없이_실행하게_한다(state, project, monkeypatch):
    # given
    monkeypatch.setenv("PLUGIN_ROOT", str(REPO_ROOT))
    event = query_event(project, PG_ID, "INSERT INTO t VALUES (1)")
    # when
    denied = datagrip_guard.handle({**event, "hook_event_name": "PreToolUse"})
    code = code_of(denied)
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"승인 {code}"}, "codex")
    allowed = datagrip_guard.handle(event)
    permission = datagrip_guard.handle({**event, "hook_event_name": "PermissionRequest"})
    # then
    assert decision_of(denied) == "deny"
    assert allowed is None
    assert permission["hookSpecificOutput"]["decision"] == {"behavior": "allow"}


def test_datagrip_codex는_파괴_문장을_한_번_코드로만_허용한다(state, project, monkeypatch):
    # given
    monkeypatch.setenv("PLUGIN_ROOT", str(REPO_ROOT))
    event = query_event(project, PG_ID, "DROP TABLE t")
    code = code_of(datagrip_guard.handle(event))
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"승인 {code}"}, "codex")
    # when
    first = datagrip_guard.handle(event)
    guard.handle({**event, "hook_event_name": "PostToolUse"}, "codex")
    second = datagrip_guard.handle(event)
    # then
    assert first is None
    assert decision_of(second) == "deny"


def test_datagrip_쓰기_키는_approval_guard가_꺼지면_이전_동작을_유지한다(state, project, monkeypatch):
    # given
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD", "false")
    event = query_event(project, PG_ID, "INSERT INTO t VALUES (1)")
    # when
    output = datagrip_guard.handle(event)
    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert output["hookSpecificOutput"]["permissionDecisionReason"] == datagrip_guard.ASK_REASON


def test_datagrip_읽기는_승인_가드와_무관하게_기존대로_허용한다(state, project):
    # given
    event = query_event(project, PG_ID, "SELECT 1")
    # when
    output = datagrip_guard.handle(event)
    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_approval_guard는_datagrip_도구의_사전_검사를_맡지_않는다(state, project):
    # given
    event = query_event(project, PG_ID, "INSERT INTO t VALUES (1)")
    # when
    output = guard.handle(event, "claude")
    # then
    assert output is None


def test_datagrip_키의_키워드는_정렬되고_중복이_없다():
    # given
    sql = "UPDATE t SET a = 1; insert into u values (1); UPDATE v SET b = 2"
    # when
    keywords, destructive = datagrip_guard.query_facts(sql, True)
    # then
    assert sorted(keywords) == ["insert", "update"]
    assert destructive is False


# --- registration -------------------------------------------------------------------------------------------------------

def test_hooks_json은_승인_가드를_bash와_mcp_호출의_각_이벤트에_등록한다():
    # given
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    command = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/approval_guard.py"'
    expected_matcher = "^(Bash|Read|Edit|Write|MultiEdit|NotebookEdit|apply_patch|mcp__.*)$"
    # when
    entries = {
        event: [(group.get("matcher"), handler["command"], handler["timeout"], handler.get("async", False))
                for group in hooks[event] for handler in group["hooks"] if handler["command"] == command]
        for event in ("PreToolUse", "PermissionRequest", "PostToolUse", "UserPromptSubmit")
    }
    # then
    assert entries["PreToolUse"] == [(expected_matcher, command, 10, False)]
    assert entries["PermissionRequest"] == [(expected_matcher, command, 10, False)]
    assert entries["PostToolUse"] == [(expected_matcher, command, 10, False)]
    assert entries["UserPromptSubmit"] == [(None, command, 5, False)]


def test_plugin_manifest는_approval_guard_토글을_기본_켜짐으로_선언한다():
    # given
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    # when
    option = manifest["userConfig"]["approval_guard"]
    # then
    assert option["type"] == "boolean"
    assert option["default"] is True


# --- independent review findings -------------------------------------------------------------------------------------

def test_codex_once_키는_이전_미완료_호출에서_다음_호출로_한_번_옮긴다(state, fake_bin):
    """미완료 일회 승인을 다음 호출에 넘기면 이전 호출은 그 승인을 더 이상 사용할 수 없다."""
    # given
    command = "kubectl delete x --context dev -n web"
    code = code_of(guard.handle(bash_event(command, cwd=state, tool_use_id="toolu-1"), "codex"))
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"승인 {code}"}, "codex")
    action = classify(command, state)
    # when
    first = guard.handle(bash_event(command, cwd=state, tool_use_id="toolu-1"), "codex")
    second = guard.handle(bash_event(command, cwd=state, tool_use_id="toolu-2"), "codex")
    # then
    assert first is None
    assert second is None
    assert not state_mod.permission_allowed("codex", "s1", action, "toolu-1")
    assert state_mod.permission_allowed("codex", "s1", action, "toolu-2")


def test_codex_permission_request는_진행_중인_키만_허용하고_같은_호출의_post가_지운다(state, fake_bin):
    # given
    command = "kubectl delete x --context dev -n web"
    code = code_of(guard.handle(bash_event(command, cwd=state, tool_use_id="toolu-1"), "codex"))
    guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": f"승인 {code}"}, "codex")
    guard.handle(bash_event(command, cwd=state, tool_use_id="toolu-1"), "codex")
    # when
    own = guard.handle(bash_event(command, "PermissionRequest", cwd=state, tool_use_id="toolu-1"), "codex")
    other = guard.handle(bash_event(command, "PermissionRequest", cwd=state, tool_use_id="toolu-9"), "codex")
    guard.handle(bash_event(command, "PostToolUse", cwd=state, tool_use_id="toolu-9"), "codex")
    still = guard.handle(bash_event(command, "PermissionRequest", cwd=state, tool_use_id="toolu-1"), "codex")
    guard.handle(bash_event(command, "PostToolUse", cwd=state, tool_use_id="toolu-1"), "codex")
    after = guard.handle(bash_event(command, "PermissionRequest", cwd=state, tool_use_id="toolu-1"), "codex")
    # then
    assert own["hookSpecificOutput"]["decision"] == {"behavior": "allow"}
    assert other is None
    assert still["hookSpecificOutput"]["decision"] == {"behavior": "allow"}
    assert after is None


def test_datagrip_always_키는_데이터_소스_uuid를_포함해_다른_소스로_재사용되지_않는다(state, project):
    # given
    pg = query_event(project, PG_ID, "DELETE FROM t")["tool_input"]
    mssql = query_event(project, MSSQL_ID, "DELETE FROM t")["tool_input"]
    # when
    pg_outcome = datagrip_guard.classify_query(pg)
    mssql_outcome = datagrip_guard.classify_query(mssql)
    # then
    assert pg_outcome.kind == mssql_outcome.kind == "always"
    assert pg_outcome.keys[0].startswith(f"sql:always:{PG_ID}:")
    assert pg_outcome.keys != mssql_outcome.keys


def test_복합_명령의_항상_키와_쓰기_키는_하나의_코드로_함께_승인된다(state, fake_bin):
    # given
    command = "kubectl delete x --context dev -n web && kubectl apply -f a --context prod -n web"
    # when
    outcome = classify(command, state)
    denied = guard.handle(bash_event(command, cwd=state, tool_use_id="toolu-1"), "codex")
    approved = state_mod.approve_text("codex", "s1", f"승인 {code_of(denied)}")
    allowed = guard.handle(bash_event(command, cwd=state, tool_use_id="toolu-2"), "codex")
    # then
    assert outcome.kind == "always"
    assert outcome.keys == ["kubectl:delete x@(default) dev/web"]
    assert outcome.writes == ["kubectl:apply@(default) prod/web"]
    assert decision_of(denied) == "deny"
    assert set(approved) == {"kubectl:delete x@(default) dev/web", "kubectl:apply@(default) prod/web"}
    assert allowed is None


def test_claude는_복합_명령의_모든_설명을_묻고_쓰기_키만_기록한다(state, fake_bin):
    # given
    command = "kubectl delete x --context dev -n web && kubectl apply -f a --context prod -n web"
    # when
    output = guard.handle(bash_event(command, cwd=state), "claude")
    guard.handle(bash_event(command, "PostToolUse", cwd=state), "claude")
    plain_apply = guard.handle(bash_event("kubectl apply -f a --context prod -n web", cwd=state), "claude")
    plain_delete = guard.handle(bash_event("kubectl delete x --context dev -n web", cwd=state), "claude")
    # then
    assert decision_of(output) == "ask"
    assert "kubectl delete x on (default) dev/web" in reason_of(output)
    assert "kubectl apply on (default) prod/web" in reason_of(output)
    assert decision_of(plain_apply) == "allow"
    assert decision_of(plain_delete) == "ask"


def test_kubectl_대상은_kubeconfig_옵션과_그_컨텍스트를_따른다(state, fake_bin):
    # given
    command = "kubectl apply -f a -n web --kubeconfig /dev.yaml"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.keys == ["kubectl:apply@/dev.yaml ctx-dev.yaml/web"]


def test_kubectl_대상은_환경_변수_KUBECONFIG를_따른다(state, fake_bin):
    # given
    command = "KUBECONFIG=/prod.yaml kubectl apply -f a -n web"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.keys == ["kubectl:apply@/prod.yaml ctx-env-prod.yaml/web"]


def test_kubeconfig가_다르면_같은_명령도_다른_키가_된다(state, fake_bin):
    # given
    dev = "kubectl apply -f a -n web --kubeconfig /dev.yaml"
    prod = "kubectl apply -f a -n web --kubeconfig /prod.yaml"
    # when
    dev_keys = classify(dev, state).keys
    prod_keys = classify(prod, state).keys
    # then
    assert dev_keys != prod_keys


def test_helm은_컨텍스트를_지정하지_않으면_kubectl과_같은_방식으로_조회한다(state, fake_bin):
    # given
    command = "KUBECONFIG=/dev.yaml helm upgrade rel c -n web"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.keys == ["helm:upgrade rel c@/dev.yaml ctx-env-dev.yaml/web"]


def test_psql_읽기는_읽기_전용_PGOPTIONS를_붙여_두_호스트_모두_허용한다(state, fake_bin):
    # given
    command = "psql -c \"select 1\""
    event = bash_event(command, cwd=state)
    # when
    outputs = {host: guard.handle(event, host) for host in ("claude", "codex")}
    # then
    for output in outputs.values():
        assert decision_of(output) == "allow"
        assert output["hookSpecificOutput"]["updatedInput"]["command"] == guard.read_only_command(command)


def test_psql_함수_호출은_읽기로_분류돼도_서버가_읽기_전용을_강제하도록_다시_쓴다(state, fake_bin):
    # given
    command = "psql -c \"select public.mutate_data()\""
    # when
    outcome = classify(command, state)
    output = guard.handle(bash_event(command, cwd=state), "claude")
    # then
    assert outcome.kind == "read"
    assert output["hookSpecificOutput"]["updatedInput"]["command"] == guard.read_only_command(command)


def test_psql_읽기를_다시_쓸_수_없으면_이전처럼_허용만_한다(state, fake_bin):
    # given
    outcome = state_mod.Outcome("read", [], [], "psql")
    # when
    claude = guard._read_decision("claude", outcome, None)
    codex = guard._read_decision("codex", outcome, None)
    # then
    assert decision_of(claude) == "allow"
    assert "updatedInput" not in claude["hookSpecificOutput"]
    assert codex is None


@pytest.mark.parametrize("command", [
    "psql -c \"select 'delete'\"",
    "psql -c \"select 1 -- drop\"",
    "psql -c \"DO $$ BEGIN DELETE FROM t; END; $$\"",
    "sqlcmd -Q \"EXEC(N'DELETE FROM dbo.t')\"",
])
def test_원문에_delete_drop_truncate나_DO_EXEC가_있으면_읽기가_아니다(state, fake_bin, command):
    # given
    expected = "always"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize(("command", "kind"), [
    ("gcloud compute instances create list --project prod --zone us-central1-a", "write"),
    ("gcloud compute instances list --project prod", "read"),
    ("gcloud config get-value project", "read"),
    ("gsutil cp a gs://b", "write"),
    ("gsutil ls gs://b", "read"),
])
def test_gcloud와_gsutil은_명령_경로에서_처음_나온_동사로_읽기와_쓰기를_나눈다(state, fake_bin, command, kind):
    # given
    expected = kind
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize(("command", "kind"), [
    ("aws ssm get-parameters-by-path --path /prod --recursive --with-decryption", "secret"),
    ("aws secretsmanager batch-get-secret-value --secret-id-list a", "secret"),
    ("aws ssm get-parameters-by-path --path /prod --recursive", "read"),
])
def test_aws_복호화_경로_조회와_일괄_비밀_조회는_비밀로_거부한다(state, fake_bin, command, kind):
    # given
    expected = kind
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("command", [
    SECRET_HELPER + "bash -lc 'kubectl apply -f a --context dev -n web'",
    SECRET_HELPER + "sh -ec 'kubectl apply -f a --context dev -n web'",
    SECRET_HELPER + "bash --login -c 'kubectl apply -f a --context dev -n web'",
])
def test_셸_c_플래그_묶음은_안의_명령을_분류한다(state, fake_bin, command):
    # given
    expected = ["kubectl:apply@(default) dev/web"]
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == "write"
    assert outcome.keys == expected


@pytest.mark.parametrize("command", [
    "sh -c 'kubectl get secret s -o json --context dev -n web'",
    "echo $(kubectl get secret s -o json --context dev -n web)",
    "sh -c 'kubectl get secret s -o json --context dev -n web; echo'",
    "bash -lc 'echo $(kubectl get secret s -o json --context dev -n web)'",
])
def test_간접_실행_영역이_비밀을_출력하면_명령_전체가_secret이다(state, fake_bin, command):
    # given
    expected = "secret"
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize(("command", "kind"), [
    ("kubectl \\\n  get pods -n web", "read"),
    ("kubectl get pods \\\n  --context dev -n web", "read"),
    ("kubectl\\\nget pods -n web", "pass"),
])
def test_셸처럼_줄_이어쓰기를_지우고_나눈다(state, fake_bin, command, kind):
    # given
    expected = kind
    # when
    outcome = classify(command, state)
    # then
    assert outcome.kind == expected


@pytest.mark.parametrize("command", [
    "scripts/approval_guard.py",
    "python3 scripts/approval_guard.py",
    "printf '{}' | python3 scripts/approval_guard.py",
    "./scripts/approval_guard.py",
    "python3 -c 'import datagrip_guard'",
    "python3 -m datagrip_guard",
    "sh -c 'python3 scripts/datagrip_guard.py'",
    "env PYTHONPATH=x python3 scripts/approval_state.py",
])
@pytest.mark.parametrize("host", ["claude", "codex"])
def test_승인_가드_스크립트를_실행하는_명령은_두_호스트_모두_거부한다(state, fake_bin, command, host):
    # given
    event = bash_event(command, cwd=state)
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == "deny"


@pytest.mark.parametrize("command", [
    "cat scripts/approval_guard.py",
    "rg approval_guard scripts/",
    "sed -n 1,20p scripts/approval_state.py",
    "python3 -c \"print(open('scripts/datagrip_guard.py').read())\"",
])
def test_승인_가드_파일을_읽기만_하는_명령은_거부하지_않는다(state, fake_bin, command):
    # given
    event = bash_event(command, cwd=state)
    # when
    output = guard.handle(event, "codex")
    # then
    assert output is None


@pytest.mark.parametrize("sql", [
    "DO $$ BEGIN PERFORM 1; END $$",
    "SELECT 1; CALL public.refresh_all()",
])
def test_datagrip_do_나_call로_시작하는_문장은_항상_묻는다(state, project, sql):
    # given
    tool_input = query_event(project, PG_ID, sql)["tool_input"]
    # when
    outcome = datagrip_guard.classify_query(tool_input)
    # then
    assert outcome.kind == "always"
