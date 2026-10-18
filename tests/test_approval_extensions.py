import json
import os
import re
import shlex
import subprocess
import sys

import pytest

from test_approval_guard import (
    GUARD_PATH, bash_event, fake_bin, guard, project, query_event, state, state_mod, datagrip_guard, PG_ID, MSSQL_ID,
)


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def approve(output, host="codex", session="s1"):
    code = re.search(r"승인 ([A-Z2-9]{6})", output["hookSpecificOutput"]["permissionDecisionReason"])[1]
    return guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": "승인 " + code}, host)


def request_command(*keys):
    return shlex.join(["python3", str(GUARD_PATH), "request", *(arg for key in keys for arg in ("--key", key)),
                       "--why", "Apply the requested deployment and issue update"])


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_request_bundle_records_every_key_only_after_user_approval(state, fake_bin, host):
    """사전 승인 묶음은 사용자 승인 뒤에만 공통 쓰기 키를 세션에 기록한다."""
    # given
    keys = ["kubectl:apply@(default) dev/web", "mcp:session"]
    event = bash_event(request_command(*keys))
    outcome = guard.classify_text(event["tool_input"]["command"], str(state))
    # when
    first = guard.handle(event, host)
    before = state_mod.is_approved(host, "s1", [state_mod.WRITE_KEY])
    if host == "claude":
        context = guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    else:
        context = approve(first)
    after = state_mod.is_approved(host, "s1", [state_mod.WRITE_KEY])
    retry = guard.handle(event, host)
    # then
    assert decision(first) == ("ask" if host == "claude" else "deny")
    assert all(key in first["hookSpecificOutput"]["permissionDecisionReason"] for key in keys)
    assert "issue update" in first["hookSpecificOutput"]["permissionDecisionReason"]
    assert not before
    assert outcome.kind == "request"
    assert outcome.keys == sorted(keys)
    assert after
    assert state_mod._load(host, "s1")["approved"] == [state_mod.WRITE_KEY]
    assert decision(retry) == ("allow" if host == "claude" else None)
    if host == "codex":
        assert "mcp:session" in context["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("key", [
    "kubectl:delete pod x@dev", "kubectl:apply --force@dev", "helm:get values app@dev",
    "terraform:state pull@directory", "docker:inspect container@dev", "kubectl:exec pod env@dev",
    "psql:delete@db", "sql:always:uuid:hash", "kubectl:unclassified@dev", "mcp:delete_item",
    "sensitive:config", "mysql:insert@db", "bad", "mcp:create_item", "curl:DELETE@https://example.test",
])
@pytest.mark.parametrize("host", ["claude", "codex"])
def test_request_rejects_keys_that_cannot_receive_session_approval(state, fake_bin, key, host):
    """항상 묻거나 분류할 수 없는 키의 사전 승인은 거부하고 기록하지 않는다."""
    # given
    event = bash_event(request_command(key))
    # when
    output = guard.handle(event, host)
    guard.handle({**event, "hook_event_name": "PostToolUse"}, host)
    # then
    assert decision(output) == "deny"
    assert not state_mod.is_approved(host, "s1", [key])
    assert not state_mod._load(host, "s1")["pending"]


def test_request_command_prints_keys_without_mutating_approval_state(state):
    """승인 요청 명령 자체는 키를 출력하고 상태를 직접 변경하지 않는다."""
    # given
    args = [sys.executable, str(GUARD_PATH), "request", "--key", "mcp:session", "--why", "Update issue"]
    # when
    completed = subprocess.run(args, capture_output=True, text=True)
    # then
    assert completed.returncode == 0
    assert "mcp:session" in completed.stdout
    assert not state_mod.state_dir().exists()


def test_custom_curl_write_methods_can_be_preapproved(state):
    """비파괴적인 사용자 지정 curl 메서드도 사전 승인할 수 있다."""
    # given
    command = request_command("curl:PROPFIND@https://example.test")
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "request"


@pytest.mark.parametrize(("filename", "content", "invocation", "kind"), [
    ("task.sh", "kubectl get pods\n", "bash task.sh", "read"),
    ("task.sh", "kubectl get pods\n", "sh task.sh", "read"),
    ("task.sh", "kubectl get pods\n", "zsh task.sh", "read"),
    ("task.sh", "kubectl get pods\n", "./task.sh", "read"),
    ("task.sh", "kubectl get pods\n", "source task.sh", "read"),
    ("task.sh", "kubectl get pods\n", ". task.sh", "read"),
    ("task.sh", "echo starting\nkubectl apply -f a --context dev\n", "bash task.sh", "write"),
    ("task.sh", "kubectl delete pods x --context dev\n", "bash task.sh", "always"),
    ("task.sh", "kubectl get secret s -o json\n", "bash task.sh", "secret"),
    ("task.sh", "cat .env.production\n", "bash task.sh", "sensitive"),
    ("task.sh", "echo hello\n", "bash task.sh", "pass"),
    ("task.py", 'import subprocess\nsubprocess.run("kubectl get pods", shell=True)\n', "python3 task.py", "write"),
    ("task.py", 'import subprocess\nsubprocess.run(["kubectl", "apply", "-f", "a", "--context", "dev"])\n',
     "python task.py", "write"),
    ("task.py", 'import boto3\nboto3.client("s3").put_object()\n', "python3 task.py", "write"),
    ("task.py", 'from google.cloud import storage\n', "python3 task.py", "write"),
    ("task.py", 'print("hello")\n', "python3 task.py", "pass"),
    ("task.js", 'exec("kubectl get pods");', "node task.js", "pass"),
    ("task.mjs", 'spawn(["kubectl", "apply", "-f", "a", "--context", "dev"]);', "node task.mjs", "pass"),
    ("Makefile", "all: prepare\n\tkubectl get pods\nprepare:\n\tkubectl apply -f a --context dev\n",
     "make", "write"),
    ("Makefile", "all:\n\tkubectl delete pod x\nread:\n\tkubectl get pods\n", "make read", "read"),
    ("Makefile", ".PHONY: all\nall:\n\tkubectl get pods\n", "make", "read"),
    ("Makefile", "all:\n\techo hello\nother:\n\tkubectl delete pod x\n", "make", "pass"),
    ("package.json", '{"scripts":{"read":"kubectl get pods"}}', "npm run read", "read"),
    ("package.json", '{"scripts":{"write":"kubectl apply -f a --context dev"}}', "pnpm run write", "write"),
    ("package.json", '{"scripts":{"read":"kubectl get pods"}}', "yarn run read", "read"),
    ("package.json", '{"scripts":{"hello":"echo hi","other":"kubectl delete pod x"}}', "npm run hello", "pass"),
    ("package.json", '{"scripts":{"preread":"kubectl delete pod x","read":"kubectl get pods"}}',
     "npm run read", "always"),
])
def test_script_calls_classify_contents_relative_to_event_cwd(state, fake_bin, filename, content, invocation, kind):
    """스크립트 파일은 이벤트 작업 폴더에서 읽어 내부 호출의 성격을 합친다."""
    # given
    (state / filename).write_text(content)
    # when
    outcome = guard.classify_text(invocation, str(state))
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize("content", [None, "x" * (256 * 1024 + 1), "import boto3\n"])
def test_unreadable_large_or_unclassified_scripts_require_one_time_approval(state, fake_bin, content):
    """읽을 수 없거나 크거나 SDK를 호출하는 스크립트는 세션 쓰기 승인을 요구한다."""
    # given
    if content is not None:
        (state / "task.py").write_text(content)
    # when
    outcome = guard.classify_text("python3 task.py", str(state))
    # then
    assert outcome.kind == "write"
    assert re.fullmatch("script:[a-f0-9]{64}", outcome.keys[0])


def test_script_named_pipe_is_unclassified_without_waiting_for_input(state, fake_bin):
    """일반 파일이 아닌 스크립트 경로는 입력을 기다리지 않고 분류 불가로 처리한다."""
    # given
    os.mkfifo(state / "pipe.sh")
    # when
    outcome = guard.classify_text("bash pipe.sh", str(state))
    # then
    assert outcome.kind == "write"


def test_script_identity_includes_path_argv_environment_and_content(state, fake_bin, monkeypatch):
    """분류되지 않은 스크립트의 키는 경로·인자·환경·내용이 바뀌면 달라진다."""
    # given
    (state / "task.py").write_text("import boto3\n")
    (state / "other.py").write_text("import boto3\n")
    first = guard.classify_text("python3 task.py", str(state)).keys
    # when
    other_path = guard.classify_text("python3 other.py", str(state)).keys
    other_argv = guard.classify_text("python3 task.py extra", str(state)).keys
    monkeypatch.setenv("AWS_PROFILE", "other")
    other_env = guard.classify_text("python3 task.py", str(state)).keys
    (state / "task.py").write_text("import boto3\n# changed\n")
    other_content = guard.classify_text("python3 task.py", str(state)).keys
    # then
    assert all(keys != first for keys in (other_path, other_argv, other_env, other_content))


def test_script_writes_merge_keys_and_reuse_them_once_per_session(state, fake_bin):
    """스크립트 내부 쓰기는 중복 키를 합치고 같은 세션에서 한 번만 승인한다."""
    # given
    (state / "write.sh").write_text("kubectl apply -f a --context dev\nkubectl apply -f b --context dev\n")
    event = bash_event("bash write.sh", cwd=state)
    # when
    first = guard.handle(event, "codex")
    approve(first)
    second = guard.handle(event, "codex")
    keys = state_mod._load("codex", "s1")["approved"]
    # then
    assert decision(first) == "deny"
    assert second is None
    assert keys == [state_mod.WRITE_KEY]


@pytest.mark.parametrize(("path", "content", "command"), [
    ("guard.sh", "python3 /plugin/scripts/approval_state.py\n", "bash guard.sh"),
    ("guard.py", "import approval_state\n", "python3 guard.py"),
    ("guard.py", 'import subprocess\nsubprocess.run(["python3", "/p/scripts/approval_guard.py"])\n', "python3 guard.py"),
    ("guard.py", 'import subprocess\nGUARD = "/p/scripts/approval_guard.py"\ncmd = ["python3", GUARD]\n'
                 "subprocess.run(cmd)\n", "python3 guard.py"),
    ("guard.py", 'import os\nos.system("python3 /p/scripts/datagrip_guard.py < event.json")\n', "python3 guard.py"),
])
def test_scripts_cannot_bypass_the_self_approval_guard(state, fake_bin, path, content, command):
    """스크립트에 숨긴 승인 가드 실행도 자기 승인 거부를 우회하지 못한다."""
    # given
    (state / path).write_text(content)
    # when
    output = guard.handle(bash_event(command, cwd=state), "claude")
    # then
    assert decision(output) == "deny"


def test_a_script_that_only_lists_guard_files_as_data_is_not_self_approval(state, fake_bin):
    """가드 파일 이름을 점검 목록 같은 데이터로만 담고 다른 명령을 실행하는 스크립트는 자기 승인으로 막지 않는다."""
    # given
    (state / "refresh.py").write_text(
        'import subprocess\nREQUIRED = ("scripts/datagrip_guard.py", "scripts/approval_guard.py")\n'
        'missing = [p for p in REQUIRED if p]\nsubprocess.run(["git", "status"])\n'
    )
    # when
    output = guard.handle(bash_event("python3 refresh.py status", cwd=state), "claude")
    # then
    assert output is None or decision(output) != "deny"


def test_the_plugin_refresh_script_status_is_not_self_approval():
    """플러그인 자신의 orca_plugin_refresh.py 실행은 자기 승인으로 분류되지 않는다."""
    # given
    script = GUARD_PATH.parents[1] / "skills" / "orca-plugin-refresh" / "scripts" / "orca_plugin_refresh.py"
    # when
    outcome = guard.classify_text(f"python3 {script} status --run-id {'0' * 32} --json", str(GUARD_PATH.parents[1]))
    # then
    assert outcome.kind != "forbidden"


@pytest.mark.parametrize(("command", "kind"), [
    ("kubectl get pods -l app=$(cat f)", "pass"),
    ("kubectl get pods `date`", "pass"),
    ('echo "`kubectl get pods`"', "read"),
    ('R=`kubectl apply -f a --context dev`; echo "$R"', "write"),
    ('echo "$(echo "$(kubectl get pods)")"', "read"),
    ('echo "$(kubectl get pods --field-selector \'name=)\')"', "read"),
    ('echo "`kubectl get secret s -o json`"', "secret"),
    ('echo "$(echo "$(kubectl get secret s -o json)")"', "secret"),
    ('echo "`kubectl $VERB pods`"', "write"),
    ('R=$(kubectl apply -f a --context dev); rm -rf local', "write"),
    ('echo "$(kubectl apply -f a --context dev)" > output', "write"),
    ("echo '$(kubectl delete pod x)'", "pass"),
    ('echo "$(kubectl get pods)" "$(kubectl delete pod x --context dev)"', "always"),
    ("eval kubectl get pods", "write"),
    ("xargs kubectl get pods", "write"),
    ("bash -c 'kubectl get pods'", "pass"),
    ("az rest --method=GeT --url https://example.test", "write"),
    ("az rest -mDeLeTe --url https://example.test", "always"),
    ("az rest --url https://example.test", "write"),
    ("az rest --method HEAD --url https://example.test", "write"),
])
def test_substitutions_merge_classifications_and_preserve_opaque_regions(state, fake_bin, command, kind):
    """치환은 내부 호출의 분류를 합치고 다른 간접 실행의 보수적인 분류는 유지한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize(("command", "kind"), [
    ('S={directory} && bash $S/run.sh', "read"),
    ('S={directory}; cd ${{S}} && bash run.sh', "read"),
    ('S={directory}; W=$S; cd $W && bash run.sh', "read"),
    ('S={directory} bash $S/run.sh', "write"),
    ('S={directory}; R=$(bash $S/run.sh); echo $R', "read"),
    ('cd tools && cd nested && bash run.sh', "write"),
    ('cd $UNASSIGNED; bash tools/nested/run.sh', "read"),
    ('cd missing-directory; bash tools/nested/run.sh', "read"),
])
def test_assignments_and_cd_resolve_script_paths_in_sequence(state, fake_bin, command, kind):
    """앞선 대입과 디렉터리 변경을 순서대로 반영해 스크립트 경로를 찾는다."""
    # given
    directory = state / "tools" / "nested"
    directory.mkdir(parents=True)
    (directory / "run.sh").write_text("kubectl get pods\n")
    command = command.format(directory=directory)
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == kind


def test_script_path_does_not_expand_an_unassigned_environment_variable(state, fake_bin, monkeypatch):
    """현재 명령에서 대입하지 않은 환경 변수로는 스크립트 경로를 확정하지 않는다."""
    # given
    (state / "run.sh").write_text("echo hello\n")
    monkeypatch.setenv("UNASSIGNED", str(state))
    # when
    outcome = guard.classify_text("bash $UNASSIGNED/run.sh", str(state))
    # then
    assert outcome.kind == "write"


@pytest.mark.parametrize(("command", "kind"), [
    ("cat <<'EOF'\nbash 'unterminated\n$(kubectl delete pod x)\nEOF\n", "pass"),
    ("cat <<-EOF\n\tkubectl delete pod x\n\tEOF\nkubectl get pods\n", "pass"),
    ("cat <<A <<'B'\nsource missing.sh\nA\nkubectl delete pod x\nB\n", "pass"),
    ("env FOO=bar bash <<EOF\nkubectl delete pod x\nEOF\n", "always"),
    ("python3 <<EOF\nkubectl delete pod x\nEOF\n", "pass"),
    ("kubectl apply -f - <<EOF\necho hi\nEOF\n", "write"),
    ("cat <<EOF\necho hello\nEOF\nkubectl delete pod x\n", "always"),
])
def test_heredoc_data_is_ignored_only_for_non_executing_receivers(state, fake_bin, command, kind):
    """데이터 수신 명령의 히어도큐먼트만 건너뛰고 실행 수신 명령과 뒤따르는 명령은 검사한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == kind


def test_shell_script_heredoc_data_does_not_trigger_approval(state, fake_bin):
    """셸 스크립트 안에서도 데이터 히어도큐먼트에 적힌 명령은 실행으로 분류하지 않는다."""
    # given
    (state / "run.sh").write_text("cat <<'EOF'\nbash missing.sh\nkubectl delete pod x\nEOF\n")
    # when
    outcome = guard.classify_text("bash run.sh", str(state))
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("command", [
    "echo $(python3 /plugin/scripts/approval_state.py)",
    "echo `python3 /plugin/scripts/approval_state.py`",
])
def test_substitutions_preserve_self_approval_denials(state, fake_bin, command):
    """명령 치환 안의 승인 상태 실행도 기존 자기 승인 거부를 유지한다."""
    # given
    event = bash_event(command, cwd=state)
    # when
    output = guard.handle(event, "claude")
    # then
    assert decision(output) == "deny"
    assert "Approvals come only from the user" in output["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"])
@pytest.mark.parametrize("directory", ["approvals", "heartbeats"])
@pytest.mark.parametrize("host", ["claude", "codex"])
def test_file_tools_cannot_edit_guard_state(state, tool, directory, host):
    """파일 편집 도구로 승인이나 heartbeat 상태를 고칠 수 없다."""
    # given
    path = state_mod.state_dir().parent / directory / "codex-s1.json"
    tool_input = {"file_path": str(path), "notebook_path": str(path),
                  "command": f"*** Begin Patch\n*** Add File: {path}\n+fake\n*** End Patch"}
    event = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": tool, "tool_input": tool_input}
    # when
    output = guard.handle(event, host)
    # then
    assert decision(output) == "deny"
    assert "Approvals come only from the user" in output["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("path", [
    "~/.kube/config", "~/.aws/credentials", "~/.aws/config", "~/.azure/token.json",
    "~/.config/gcloud/credentials.db", "~/.pgpass", "~/.docker/config.json", "~/.netrc", ".env", ".env.local",
])
@pytest.mark.parametrize("tool", ["Read", "Bash"])
def test_protected_file_reads_warn_and_always_ask(state, fake_bin, path, tool):
    """보호 파일을 읽으면 비밀 전달 도우미를 권하고 매번 승인을 받는다."""
    # given
    tool_input = {"file_path": path} if tool == "Read" else {"command": "cat " + path}
    event = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": tool, "tool_input": tool_input}
    # when
    first = guard.handle(event, "codex")
    context = approve(first)
    once = guard.handle(event, "codex")
    guard.handle({**event, "hook_event_name": "PostToolUse"}, "codex")
    again = guard.handle(event, "codex")
    claude = guard.handle(event, "claude")
    # then
    assert decision(first) == decision(again) == "deny"
    assert decision(once) is None
    assert decision(claude) == "ask"
    assert "This may expose a protected value; prefer secret_exec.py" in first["hookSpecificOutput"]["permissionDecisionReason"]
    assert "protected value" in context["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("command", ["less .env", "head .env", "tail .env", "grep TOKEN .env", "rg TOKEN .env", "cat < .env",
    "printenv", "env", "env -u TOKEN", "kubectl exec pod -- env", "kubectl exec pod -- printenv", "docker inspect id",
    "docker container inspect id", "docker exec id env", "bash -c 'cat .env'", "echo $(printenv)"])
def test_exposure_commands_are_sensitive(state, fake_bin, command):
    """환경 출력과 보호 파일 조회 등 새 노출 경로는 민감 호출로 분류한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == "sensitive"


def test_kubeconfig_environment_path_is_sensitive(state, fake_bin, monkeypatch):
    """KUBECONFIG에 지정한 모든 파일도 보호 파일로 취급한다."""
    # given
    monkeypatch.setenv("KUBECONFIG", str(state / "first") + ":" + str(state / "second"))
    # when
    outcome = guard.classify_text("cat second", str(state))
    # then
    assert outcome.kind == "sensitive"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_children_reuse_parent_approved_keys_without_writing_parent_state(state, fake_bin, monkeypatch, host):
    """자식 세션은 부모 승인 키를 읽어서 쓰되 부모 상태를 변경하지 않는다."""
    # given
    command = "kubectl apply -f a --context dev"
    _, keys = state_mod.split_outcome(guard.classify_text(command, str(state)))
    state_mod.record_approved("codex", "main", keys)
    parent = state_mod._path("codex", "main")
    before = parent.read_bytes()
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "codex:main")
    # when
    output = guard.handle(bash_event(command), host)
    guard.handle(bash_event(command, name="PostToolUse"), host)
    # then
    assert decision(output) == ("allow" if host == "claude" else None)
    assert parent.read_bytes() == before
    assert not state_mod._path(host, "s1").exists()


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("command", ["kubectl apply -f a --context other", "kubectl delete pod x", request_command("mcp:session")])
def test_children_route_new_approvals_to_main_session(state, fake_bin, monkeypatch, host, command):
    """자식 세션의 새 승인과 사전 승인 요청은 주 세션으로 돌려보낸다."""
    # given
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "claude:main")
    # when
    output = guard.handle(bash_event(command), host)
    # then
    assert decision(output) == "deny"
    assert "Approval is needed in the main session: run approval_guard.py request" in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert not state_mod._load(host, "s1")["pending"]


def test_child_prompt_cannot_approve_pending_code(state, monkeypatch):
    """자식 세션의 사용자 프롬프트로는 승인 코드를 기록하지 않는다."""
    # given
    code = state_mod.request_code("codex", "s1", [], ["mcp:session"])
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "codex:main")
    # when
    output = guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "승인 " + code}, "codex")
    # then
    assert output["hookSpecificOutput"]["additionalContext"] == state_mod.HOOKS_WARNING
    assert not state_mod.is_approved("codex", "s1", ["mcp:session"])
    assert code in state_mod._load("codex", "s1")["pending"]


@pytest.mark.parametrize("value", ["../bad", "codex:../bad", "codex:s1:other", "other:s1", "claude:"])
def test_malformed_parent_session_is_ignored(state, monkeypatch, value):
    """잘못된 부모 세션 값은 무시한다."""
    # given
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", value)
    # when
    parent = state_mod.parent_session()
    # then
    assert parent is None


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_approval_prompt_context_names_the_approval_and_instructs_immediate_retry(state, fake_bin, host):
    """승인 프롬프트 결과는 승인한 호출과 즉시 재시도 지침을 제공한다."""
    # given
    code = state_mod.request_code(host, "s1", [], ["mcp:session"], ["Update issue"])
    # when
    output = guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "승인 " + code}, host)
    # then
    assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "Update issue" in output["hookSpecificOutput"]["additionalContext"]
    assert output["hookSpecificOutput"]["additionalContext"].endswith(state_mod.RETRY_INSTRUCTION)


def test_heartbeat_is_written_even_with_guard_toggle_off(state, monkeypatch):
    """승인 가드를 꺼도 이벤트의 heartbeat는 기록한다."""
    # given
    monkeypatch.setenv("HEI5ENBUG_APPROVAL_GUARD", "false")
    monkeypatch.setenv("PLUGIN_ROOT", str(GUARD_PATH.parents[1]))
    event = {"hook_event_name": "UserPromptSubmit", "session_id": "off", "prompt": "hello"}
    # when
    completed = subprocess.run([sys.executable, str(GUARD_PATH)], input=json.dumps(event), capture_output=True, text=True)
    # then
    assert completed.returncode == 0
    assert completed.stdout == ""
    assert (state_mod.state_dir().parent / "heartbeats/codex-off").exists()


def test_datagrip_heartbeat_is_written_even_when_its_toggle_is_off(state, monkeypatch):
    """DataGrip 가드를 꺼도 이벤트의 heartbeat는 기록한다."""
    # given
    monkeypatch.setenv("HEI5ENBUG_DATAGRIP_GUARD", "false")
    monkeypatch.setenv("PLUGIN_ROOT", str(GUARD_PATH.parents[1]))
    event = {"hook_event_name": "PreToolUse", "session_id": "off-db", "tool_name": datagrip_guard.TOOL_NAME}
    # when
    completed = subprocess.run([sys.executable, str(GUARD_PATH.with_name("datagrip_guard.py"))],
                               input=json.dumps(event), capture_output=True, text=True)
    # then
    assert completed.returncode == 0
    assert completed.stdout == ""
    assert (state_mod.state_dir().parent / "heartbeats/codex-off-db").exists()


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_classifier_errors_fail_closed_with_the_failure_reason(state, fake_bin, monkeypatch, host):
    """분류기 예외가 나면 실패 이유를 알리고 매번 승인을 요구한다."""
    # given
    def broken(*args, **kwargs):
        raise RuntimeError("broken")
    monkeypatch.setattr(guard, "classify_text", broken)
    # when
    output = guard.handle(bash_event("kubectl get pods"), host)
    # then
    assert decision(output) == ("ask" if host == "claude" else "deny")
    assert guard.FAILURE_REASON in output["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_datagrip_classifier_errors_fail_closed(state, project, monkeypatch, host):
    """DataGrip 분류기 예외도 양쪽 호스트에서 실패 이유와 함께 승인을 요구한다."""
    # given
    def broken(*args, **kwargs):
        raise RuntimeError("broken")
    monkeypatch.setattr(datagrip_guard, "detect_host", lambda: host)
    monkeypatch.setattr(datagrip_guard, "decide", broken)
    monkeypatch.setattr(datagrip_guard, "codex_pre_tool_use", broken)
    # when
    output = datagrip_guard.handle(query_event(project, PG_ID, "select 1"))
    # then
    assert decision(output) == ("ask" if host == "claude" else "deny")
    assert guard.FAILURE_REASON in output["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize(("tool", "arguments", "kind"), [
    ("search_channels", {"query": "dev", "limit": 3}, "read"),
    ("search_logs", {"query": "error delete failed"}, "read"),
    ("find_items", {"query": "/* note */ update t set a = 1"}, "write"),
    ("get_query", {"query": "  (select 1)"}, "read"),
])
def test_mcp_query_field_is_sql_only_when_its_text_starts_like_sql(tool, arguments, kind):
    """일반 검색어 query는 SQL로 보지 않고, SQL 문장처럼 시작하는 query만 SQL로 판정한다."""
    # given
    name = "mcp__provider__" + tool
    # when
    outcome = guard.classify_mcp(name, arguments)
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize(("tool", "arguments", "kind"), [
    ("get_query", {"query": "select 1"}, "read"),
    ("execute_sql", {"sql": "select 1"}, "read"),
    ("get_query", {"statement": "update t set x=1"}, "write"),
    ("read_query", {"queryText": "delete from t"}, "always"),
    ("read_query", {"query": "select 'drop'"}, "always"),
    ("get_repl", {"code": "print(1)"}, "write"),
    ("get_exec", {"command": "kubectl get pods"}, "write"),
    ("read_run", {"script": "kubectl delete pod x"}, "always"),
    ("get_code", {"code": "x=1"}, "write"),
    ("read_eval", {"text": "1+1"}, "write"),
])
def test_mcp_sql_and_execution_inputs_override_name_only_reads(tool, arguments, kind):
    """MCP의 SQL과 실행 입력도 확인해 이름만으로 읽기를 허용하지 않는다."""
    # given
    name = "mcp__provider__" + tool
    # when
    outcome = guard.classify_mcp(name, arguments)
    # then
    assert outcome.kind == kind
    if kind == "write":
        assert outcome.keys == ["mcp:session"]


def test_datagrip_non_destructive_writes_share_the_mcp_session_key(state, project):
    """DataGrip의 일반 쓰기는 DB와 문장 종류가 달라도 세션 쓰기 승인을 공유한다."""
    # given
    state_mod.record_approved("claude", "s1", [state_mod.WRITE_KEY])
    inputs = [query_event(project, source, sql)["tool_input"] for source, sql in (
        (PG_ID, "insert into t values (1)"), (MSSQL_ID, "update t set a=1"),
    )]
    # when
    outputs = [datagrip_guard.decide(value, "s1") for value in inputs]
    # then
    assert all(decision(output) == "allow" for output in outputs)


def test_database_reads_enforce_a_sixty_second_statement_timeout(state, fake_bin, project):
    """PostgreSQL 조회는 CLI와 DataGrip 모두 60초 문장 제한을 적용한다."""
    # given
    cli = bash_event("psql -c 'select 1'")
    tool_input = query_event(project, PG_ID, "select 1")["tool_input"]
    # when
    cli_output = guard.handle(cli, "claude")
    query_output = datagrip_guard.decide(tool_input)
    # then
    assert "-c statement_timeout=60000" in cli_output["hookSpecificOutput"]["updatedInput"]["command"]
    assert "SET LOCAL statement_timeout = '60s';" in query_output["hookSpecificOutput"]["updatedInput"]["queryText"]


@pytest.mark.parametrize(("command", "kind", "keys"), [
    ("curl https://example.test/path", "read", []),
    ("curl -I https://example.test", "read", []),
    ("curl -X HEAD https://example.test", "read", []),
    ("curl --request=GET https://example.test", "read", []),
    ("curl -X PATCH https://example.test/path?q=1", "write", ["curl:PATCH@https://example.test"]),
    ("curl -X DELETE https://example.test/path", "always", ["curl:DELETE@https://example.test"]),
    ("curl -d body https://example.test/path", "write", ["curl:POST@https://example.test"]),
    ("curl -d https://body.test -x https://proxy.test https://example.test/path", "write", ["curl:POST@https://example.test"]),
    ("curl --data-binary=@body https://example.test", "write", ["curl:POST@https://example.test"]),
    ("curl -F file=@body https://example.test", "write", ["curl:POST@https://example.test"]),
    ("curl -T body https://example.test", "write", ["curl:PUT@https://example.test"]),
    ("curl --json '{}' https://example.test", "write", ["curl:POST@https://example.test"]),
    ("curl -X GET -d body https://example.test", "write", ["curl:GET@https://example.test"]),
    ("curl --request PUT --url=https://example.test:8443/path", "write", ["curl:PUT@https://example.test:8443"]),
    ("curl -u name:password https://example.test", "sensitive", None),
    ("curl --user=name:password https://example.test", "sensitive", None),
    ("curl -H 'Authorization: Bearer value' https://example.test", "sensitive", None),
    ("curl --header='authorization: value' https://example.test", "sensitive", None),
])
def test_curl_classifies_method_origin_and_credential_exposure(state, command, kind, keys):
    """curl은 메서드와 서버 주소로 쓰기를 구분하고 자격 증명 인자는 매번 묻는다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == kind
    if keys is not None:
        assert outcome.keys == keys


@pytest.mark.parametrize(("kind", "writes", "once_keys", "session_keys"), [
    ("write", [], [], ["write:session"]),
    ("request", [], [], ["write:session"]),
    ("always", [], ["original-key"], []),
    ("sensitive", [], ["original-key"], []),
    ("always", ["write-a", "write-b"], ["original-key"], ["write:session"]),
    ("sensitive", ["write-a", "write-b"], ["original-key"], ["write:session"]),
    ("read", [], [], []),
    ("pass", [], [], []),
    ("secret", [], [], []),
    ("forbidden", [], [], []),
])
def test_session_approval_mapping_preserves_classification_keys(kind, writes, once_keys, session_keys):
    """세션 승인 키를 하나로 바꿔도 원래 분류 키와 쓰기 키는 보존한다."""
    # given
    action = state_mod.Outcome(kind, ["original-key"], ["Requested action"], writes=writes)
    # when
    split = state_mod.split_outcome(action)
    # then
    assert split == (once_keys, session_keys)
    assert action.keys == ["original-key"]
    assert action.writes == writes


@pytest.mark.parametrize("kind", ["write", "request", "always", "sensitive"])
def test_claude_approval_prompt_uses_the_exact_short_wording(state, kind):
    """Claude 승인 질문은 쓰기 종류에 맞는 짧은 문구를 사용한다."""
    # given
    action = state_mod.Outcome(kind, ["original-key"], ["Requested action"])
    expected = (
        "Asks every time: Requested action." if kind in ("always", "sensitive") else
        "Write: Requested action. Approve once; writes then run without asking for 12 hours in this session."
    )
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    assert decision(output) == "ask"
    assert output["hookSpecificOutput"]["permissionDecisionReason"] == expected


@pytest.mark.parametrize("kind", ["always", "sensitive"])
def test_codex_mixed_calls_keep_only_the_shared_write_approval_after_completion(state, kind):
    """Codex 복합 호출이 완료돼도 위험 부분은 새 승인을 요구하고 일반 쓰기 승인만 유지한다."""
    # given
    action = state_mod.Outcome(kind, ["once-key"], ["Requested action"], writes=["write-a", "write-b"])
    denied = state_mod.pre_decision("codex", "s1", action, "first")
    approve(denied)
    state_mod.pre_decision("codex", "s1", action, "first")
    state_mod.after_call("codex", "s1", action, "first")
    # when
    output = state_mod.pre_decision("codex", "s1", action, "second")
    # then
    assert decision(output) == "deny"
    assert state_mod._load("codex", "s1")["approved"] == [state_mod.WRITE_KEY]
    assert state_mod._load("codex", "s1")["once"] == []
    assert state_mod._load("codex", "s1")["inflight"] == []
    assert list(state_mod._load("codex", "s1")["pending"].values())[0]["once_keys"] == ["once-key"]
    assert list(state_mod._load("codex", "s1")["pending"].values())[0]["session_keys"] == []


@pytest.mark.parametrize(("arguments", "description"), [
    ({"title": "t"}, "MCP write: mcp__provider__update_record"),
    ({"query": "UPDATE t SET a=1"}, "MCP SQL write via mcp__provider__update_record"),
])
def test_mcp_write_descriptions_name_the_tool(arguments, description):
    """MCP 일반 쓰기와 SQL 쓰기의 설명에는 도구 이름이 들어간다."""
    # given
    tool = "mcp__provider__update_record"
    # when
    action = guard.classify_mcp(tool, arguments)
    # then
    assert action.kind == "write"
    assert action.keys == ["mcp:session"]
    assert action.descriptions == [description]
