import pytest

from test_approval_guard import bash_event, fake_bin, guard, state, state_mod


@pytest.mark.parametrize(("command", "kind"), [
    ("kubectl get pods $NAME", "read"),
    ("kubectl get pods ${NAME}", "read"),
    ("kubectl $VERB pods", "always"),
    ("kubectl ${VERB} pods", "always"),
    ("kubectl $(echo get) pods", "always"),
    ("kubectl `echo get` pods", "always"),
    ('echo "$(kubectl get secret $NAME -o json)"', "secret"),
    ("kubectl get secret ${NAME} -o json", "secret"),
    ("kubectl exec $NAME -- env", "sensitive"),
])
def test_only_an_unresolved_verb_fails_closed_after_sensitive_reads(state, fake_bin, command, kind):
    """동적으로 정해지는 동사만 항상 묻고 변수 인자의 조회와 비밀 판정은 유지한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == kind


def test_secret_substitution_with_variable_argument_is_denied(state, fake_bin):
    """변수 인자를 쓰는 명령 치환도 비밀을 출력하면 거부한다."""
    # given
    event = bash_event('echo "$(kubectl get secret $NAME -o json)"', cwd=state)
    # when
    output = guard.handle(event, "claude")
    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "secret value" in output["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize(("delimiter", "body", "kind"), [
    ("EOF", "$(kubectl delete pod x --context dev -n web)", "always"),
    ("EOF", "`kubectl delete pod x --context dev -n web`", "always"),
    ("'EOF'", "$(kubectl delete pod x --context dev -n web)", "pass"),
    ('"EOF"', "`kubectl delete pod x --context dev -n web`", "pass"),
    (r"\EOF", "$(kubectl delete pod x --context dev -n web)", "pass"),
    ("EOF", "kubectl delete pod x --context dev -n web", "pass"),
])
def test_unquoted_heredoc_expansions_are_not_discarded(state, fake_bin, delimiter, body, kind):
    """인용하지 않은 히어도큐먼트의 명령 치환은 실행으로 검사하고 인용한 본문은 데이터로 본다."""
    # given
    command = f"cat <<{delimiter}\n{body}\nEOF\n"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize("receiver", [
    "cat <<'EOF' | bash",
    "cat <<'EOF' |& bash",
    "timeout 5 bash <<'EOF'",
    "timeout 5 /bin/bash <<'EOF'",
    "env FOO=bar timeout 5 bash <<'EOF'",
    "timeout 5 kubectl apply -f - <<'EOF'",
    "timeout 5 source <<'EOF'",
    "timeout 5 . <<'EOF'",
])
def test_piped_and_wrapped_heredoc_runners_are_not_data(state, fake_bin, receiver):
    """파이프로 넘기거나 래퍼 뒤에서 실행하는 히어도큐먼트는 데이터로 건너뛰지 않는다."""
    # given
    command = f"{receiver}\nkubectl delete pod x --context dev -n web\nEOF\n"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("receiver", [
    "python3.11 - <<'EOF'",
    "/usr/bin/python3.11 - <<'EOF'",
    "timeout 5 python3.11 - <<'EOF'",
    "cat <<'EOF' | python3.11 -",
])
def test_versioned_python_heredoc_covered_calls_fail_closed(state, fake_bin, receiver):
    """버전이 붙은 파이썬이 히어도큐먼트로 실행하는 대상 명령도 항상 묻는다."""
    # given
    command = (f"{receiver}\nimport subprocess\n"
               'subprocess.run(["kubectl", "delete", "pod", "x", "--context", "dev", "-n", "web"])\nEOF\n')
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize(("command", "kind"), [
    ("(cd safe); bash run.sh", "always"),
    ("cd safe | bash run.sh", "always"),
    ("cd safe |& bash run.sh", "always"),
    ("cd safe || bash run.sh", "always"),
    ("cd safe & bash run.sh", "always"),
    ("cd safe && bash run.sh; true | cat", "pass"),
    ("true | cat; cd safe && bash run.sh", "pass"),
    ("cat x | cd safe; bash run.sh", "always"),
    ("cd safe && bash run.sh", "read"),
    ("cd safe; bash run.sh", "read"),
    ("cd safe\nbash run.sh", "read"),
])
def test_cd_tracking_requires_only_sequential_operators(state, fake_bin, command, kind):
    """cd는 자신의 구간에 파이프, 서브셸, 백그라운드, 실패 시 실행 연산자가 닿지 않을 때만 디렉터리를 바꾼다."""
    # given
    safe = state / "safe"
    safe.mkdir()
    (safe / "run.sh").write_text("kubectl get pods\n")
    (state / "run.sh").write_text("kubectl delete pod x --context dev -n web\n")
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize(("body", "kind"), [
    ("use \\`make\\` and \\$(date) here\nmake only the edits\n", "pass"),
    ("a real $(kubectl delete pod x --context dev -n web)\n", "always"),
    ("a real `kubectl delete pod x --context dev -n web`\n", "always"),
    ("escaped backslash then a real \\\\`kubectl delete pod x --context dev -n web`\n", "always"),
])
def test_unquoted_heredoc_data_is_scanned_only_when_the_shell_would_expand_it(state, fake_bin, body, kind):
    """따옴표 없는 heredoc 본문은 셸이 실제로 치환을 실행할 때만 명령으로 검사한다."""
    # given
    command = f"cat > {state}/note.md <<EOF\n{body}EOF\n"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize(("body", "kind"), [
    ("make only the edits\nbash and source One lines\nstamp $(date -u +%Y)\n", "pass"),
    ("make only the edits\nstamp $(kubectl delete pod x --context dev -n web)\n", "always"),
    ("don't stop at the quote $(kubectl delete pod x --context dev -n web)\n", "always"),
    ("nested $(echo $(kubectl delete pod x --context dev -n web))\n", "always"),
])
def test_unquoted_heredoc_prose_is_data_and_only_its_substitutions_are_classified(state, fake_bin, body, kind):
    """따옴표 없는 heredoc의 산문은 데이터이고 셸이 실행하는 치환만 분류한다."""
    # given
    command = f"cat > {state}/note.md <<EOF\n{body}EOF\n"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize(("command", "kind"), [
    ('S={danger}; S={safe} bash "$S/run.sh"', "always"),
    ('S={danger}; S={safe} true; bash "$S/run.sh"', "always"),
    ('S={safe} bash "$S/run.sh"', "always"),
    ('S={safe}\nbash $S/run.sh', "read"),
    ('S={safe}; bash $S/run.sh', "read"),
    ('S={safe} && bash $S/run.sh', "read"),
])
def test_only_standalone_assignments_persist_for_script_argument_expansion(state, fake_bin, command, kind):
    """스크립트 인자의 변수는 앞선 독립 대입문만 반영하고 명령 앞의 임시 대입은 반영하지 않는다."""
    # given
    danger, safe = state / "danger", state / "safe"
    danger.mkdir()
    safe.mkdir()
    (danger / "run.sh").write_text("kubectl delete pod x --context dev -n web\n")
    (safe / "run.sh").write_text("kubectl get pods\n")
    command = command.format(danger=danger, safe=safe)
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == kind


def test_argv_script_path_uses_the_previous_variable_value(state, fake_bin):
    """argv 분류도 명령 앞 임시 대입 대신 앞서 저장한 변수로 스크립트 경로를 확장한다."""
    # given
    (state / "run.sh").write_text("kubectl delete pod x --context dev -n web\n")
    words = ["S=/safe", "bash", "$S/run.sh"]
    # when
    outcome = guard._classify_argv(words, False, str(state), 0, " ".join(words), variables={"S": str(state)})
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize(("command", "kind"), [
    ("(true; cd safe; true); bash run.sh", "always"),
    ("(true; (true); cd safe; true); bash run.sh", "always"),
    ("false && cd safe; bash run.sh", "always"),
    ("true || cd safe; bash run.sh", "always"),
    ("cd safe && bash run.sh", "read"),
    ("cd safe; bash run.sh", "read"),
    ("cd .; cd safe\nbash run.sh", "read"),
])
def test_cd_must_be_unconditional_and_outside_parentheses(state, fake_bin, command, kind):
    """조건부 또는 괄호 안의 cd는 후속 스크립트 기준 경로를 바꾸지 않는다."""
    # given
    safe = state / "safe"
    safe.mkdir()
    (safe / "run.sh").write_text("kubectl get pods\n")
    (state / "run.sh").write_text("kubectl delete pod x --context dev -n web\n")
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize("body", [
    "$(printf ')'; kubectl delete pod x --context dev -n web)",
    '$(printf ")"; kubectl delete pod x --context dev -n web)',
    "$(printf ')'; kubectl delete pod x --context dev -n web",
    "`printf ')'; kubectl delete pod x --context dev -n web",
])
def test_heredoc_substitutions_keep_quoted_parentheses_and_unclosed_bodies(state, fake_bin, body):
    """히어도큐먼트 치환의 인용된 닫는 괄호와 닫히지 않은 나머지 본문도 검사한다."""
    # given
    command = f"cat <<EOF\n{body}\nEOF\n"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("receiver", [
    "dash", "ksh", "fish", "unknown-program", "./run.sh", "/tmp/run.sh", "bash", "python3.11",
])
def test_unknown_or_executing_heredoc_receivers_keep_commands_visible(state, fake_bin, receiver):
    """알려진 데이터 수신자가 아닌 명령의 히어도큐먼트는 실행 명령으로 검사한다."""
    # given
    command = f"{receiver} <<'EOF'\nkubectl delete pod x --context dev -n web\nEOF\n"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("receiver", [
    "cat > run.sh", "cat >> run.sh", "cat >| run.sh", "cat &> run.sh", "cat > run",
    "cat > note.md > run.sh", "cat > run.sh > note.md", "tee run.sh", "tee -a note.md run",
])
def test_heredoc_output_to_non_data_files_keeps_commands_visible(state, fake_bin, receiver):
    """출력 대상 중 하나라도 데이터 파일이 아니면 히어도큐먼트의 명령을 검사한다."""
    # given
    command = f"{receiver} <<'EOF'\nkubectl delete pod x --context dev -n web\nEOF\n"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


def test_heredoc_cannot_hide_a_script_overwrite_before_execution(state, fake_bin):
    """기존 스크립트가 조회만 하더라도 히어도큐먼트로 덮어쓸 삭제 명령은 항상 묻는다."""
    # given
    (state / "run.sh").write_text("kubectl get pods\n")
    command = "cat > run.sh <<'EOF'\nkubectl delete pod x --context dev -n web\nEOF\nbash run.sh"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "always"


@pytest.mark.parametrize("receiver", (
    "cat tee head tail wc sort uniq cut tr base64 xxd od grep egrep fgrep rg jq column fold fmt nl tac rev cmp diff git gh"
).split())
def test_known_data_receivers_ignore_quoted_heredoc_commands(state, fake_bin, receiver):
    """알려진 데이터 수신자는 인용된 히어도큐먼트 내용을 명령으로 실행하지 않는다."""
    # given
    command = f"{receiver} <<'EOF'\nkubectl delete pod x --context dev -n web\nEOF\n"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize("receiver", [
    "cat > note.md", "cat >> note.MARKDOWN", "cat >| note.txt", "cat &> note.json",
    "cat > /dev/null", "cat > /dev/stdout", "cat > /dev/stderr", "tee -a note.md note.jsonl",
    "cat > note.md > note.yaml", "git commit -F -",
])
def test_data_file_outputs_and_git_commit_prose_stay_data(state, fake_bin, receiver):
    """데이터 파일 출력과 git 커밋 메시지의 인용된 산문은 승인 없이 통과한다."""
    # given
    command = f"{receiver} <<'EOF'\nDon't execute kubectl delete pod x; this is prose.\nEOF\n"
    # when
    outcome = guard.classify_text(command, str(state))
    # then
    assert outcome.kind == "pass"


@pytest.mark.parametrize(("command", "kind"), [
    ("$(printf kubectl) delete pod x --context dev -n web", "always"),
    ("`printf kubectl` delete pod x --context dev -n web", "always"),
    ("${CLI} kubectl delete pod x --context dev -n web", "always"),
    ("$CLI kubectl delete pod x --context dev -n web", "always"),
    ("$EDITOR notes.md", "pass"),
    ("$HOME/bin/tool run", "pass"),
    ("echo kubectl; $EDITOR notes.md", "pass"),
])
def test_substituted_executables_with_covered_words_fail_closed(state, fake_bin, command, kind):
    """동적 실행 파일과 같은 구간에 대상 CLI가 있으면 항상 묻고 일반 편집기나 도구는 통과한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize(("command", "kind"), [
    ("az rest --method GET --url https://v.vault.azure.net/secrets/token?api-version=7.4", "secret"),
    ("az rest -m GET --uri https://v.vault.azure.net/KEYS/token", "secret"),
    ("az rest -m GET -u https://v.vault.azure.net/secrets", "secret"),
    ("az rest -m GET --url https://management.azure.com/subscriptions/x", "read"),
    ("az rest -m get --uri=https://management.azure.com/x", "read"),
    ("URL=https://management.azure.com/x; az rest -m GET -u $URL", "read"),
    ("URL=https://management.azure.com/x; az rest -m GET --url=${URL}", "read"),
    ("URL=https://management.azure.com/x; az --subscription sub rest -m GET --url $URL", "read"),
    ("URL=https://v.vault.azure.net/secrets/token; az rest -m GET --url $URL", "secret"),
    ("az rest -m GET --url https://example.test/x", "write"),
    ("az rest -m GET --url $UNKNOWN_URL", "write"),
    ("az rest -m GET --url https://management.azure.com/$UNKNOWN_PATH", "write"),
    ("az rest -m GET", "write"),
    ("az rest -m GET --url https://management.azure.com/x/SeCrEt", "write"),
    ("az rest -m GET --url https://management.azure.com/x/LISTKEYS", "write"),
    ("az rest -m GET --url https://management.azure.com/x/list-keys", "write"),
    ("az rest -m GET --url https://management.azure.com/x/connectionString", "write"),
    ("az rest -m GET --url https://management.azure.com/x/listCredentials", "write"),
    ("az rest -m DELETE --url https://management.azure.com/x", "always"),
])
def test_az_rest_reads_require_a_known_arm_url_and_vault_secret_gets_are_denied(state, fake_bin, command, kind):
    """Azure REST 조회는 확인된 ARM 주소만 허용하고 Key Vault 비밀 조회는 거부한다."""
    # given
    cwd = str(state)
    # when
    outcome = guard.classify_text(command, cwd)
    # then
    assert outcome.kind == kind


@pytest.mark.parametrize("kind", ["always", "sensitive"])
@pytest.mark.parametrize("writes", [[], ["write-a"]])
def test_claude_every_time_prompt_discloses_session_write_approval(state, kind, writes):
    """Claude의 매번 승인 질문은 일반 쓰기의 세션 승인도 함께 부여하는 경우 이를 명시한다."""
    # given
    action = state_mod.Outcome(kind, ["once-key"], ["Requested action"], writes=writes)
    expected = "Asks every time: Requested action."
    if writes:
        expected += " It also approves non-destructive writes for the rest of this session."
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert output["hookSpecificOutput"]["permissionDecisionReason"] == expected


@pytest.mark.parametrize(("kind", "writes", "session_scope"), [
    ("write", [], True), ("request", [], True), ("always", ["write-a"], True),
    ("sensitive", ["write-a"], True), ("always", [], False), ("sensitive", [], False),
])
def test_codex_prompt_discloses_every_session_write_grant(state, kind, writes, session_scope):
    """Codex 승인 코드 안내는 세션 쓰기 승인을 부여하는 모든 호출에서 그 범위를 명시한다."""
    # given
    action = state_mod.Outcome(kind, ["original-key"], ["Requested action"], writes=writes)
    prefix = "Approval required: Requested action. "
    if session_scope:
        prefix += "Approving also allows non-destructive writes for the rest of this session. "
    # when
    output = state_mod.pre_decision("codex", "s1", action)
    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert output["hookSpecificOutput"]["permissionDecisionReason"].startswith(prefix + "Ask the user to reply `승인 ")
    assert output["hookSpecificOutput"]["permissionDecisionReason"].endswith(state_mod.RETRY_INSTRUCTION)
