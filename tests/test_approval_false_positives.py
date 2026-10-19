"""Acceptance checks for the approval guard's classification accuracy (benign calls must not ask)."""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402

ADF_QUERY = (
    "az datafactory {resource} query-by-factory --factory-name f -g rg "
    "--last-updated-after 2026-01-01T00:00:00Z --last-updated-before 2026-01-02T00:00:00Z"
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    for name in ("KUBECONFIG", "AWS_PROFILE", "CLOUDSDK_CORE_PROJECT", "DOCKER_CONTEXT", "S", "W", "UNSET_DIR"):
        monkeypatch.delenv(name, raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "az").write_text("#!/bin/sh\necho fake-sub\n")
    (bin_dir / "kubectl").write_text("#!/bin/sh\necho fake-ctx\n")
    for name in ("az", "kubectl"):
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return tmp_path


def classify(command, cwd):
    return guard.classify_text(command, str(cwd))


@pytest.mark.parametrize("resource", ["pipeline-run", "trigger-run"])
def test_az_datafactory_query_by_factory는_조회다(home, resource):
    assert classify(ADF_QUERY.format(resource=resource), home).kind == "read"


def test_az_rest_get은_조회다(home):
    outcome = classify("az rest --method get --url https://management.azure.com/subscriptions/x?api-version=2021-04-01", home)
    assert outcome.kind == "read"


def test_az_rest_짧은_옵션_get도_조회다(home):
    assert classify("az rest -m GET --url https://management.azure.com/x", home).kind == "read"


def test_az_rest_post는_쓰기다(home):
    outcome = classify("az rest --method post --url https://management.azure.com/x/start", home)
    assert outcome.kind == "write"


def test_az_rest_delete는_항상_묻는다(home):
    assert classify("az rest --method delete --url https://management.azure.com/x", home).kind == "always"


def test_명령_치환_안의_조회는_조회로_본다(home):
    command = "R=$(az datafactory pipeline-run show --factory-name f -g rg --run-id abc --query status -o tsv); echo $R"
    assert classify(command, home).kind == "read"


def test_명령_치환_안의_쓰기는_쓰기로_본다(home):
    command = ("R=$(az datafactory pipeline create-run --factory-name f -g rg -n p --query runId -o tsv); echo $R")
    outcome = classify(command, home)
    assert outcome.kind == "write"
    assert any("pipeline create-run" in key for key in outcome.keys)


def test_명령_치환_안의_삭제는_항상_묻는다(home):
    assert classify("X=$(kubectl delete pod x --context dev -n web); echo $X", home).kind == "always"


def test_covered_명령이_없는_치환은_통과다(home):
    assert classify('echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)"', home).kind == "pass"


def test_변수로_채운_치환은_세션_쓰기로_분류한다(home):
    # given
    command = "X=$(kubectl $VERB pods); echo $X"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "write"


def _script(tmp_path, name, body):
    path = tmp_path / "tools" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(body)
    return path


def test_cd_뒤의_상대_스크립트는_그_디렉터리에서_읽는다(home, tmp_path):
    _script(home, "run.sh", "echo hello\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outcome = classify(f"cd {home / 'tools'} && bash run.sh", elsewhere)
    assert outcome.kind == "pass"


def test_cd_뒤의_파이썬_프로세스_실행은_세션_쓰기로_분류한다(home, tmp_path):
    # given
    _script(home, "tool.py", 'import subprocess\nsubprocess.run(["kubectl", "get", "pods"])\n')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # when
    outcome = classify(f"cd {home / 'tools'} && python3 tool.py", elsewhere)
    # then
    assert outcome.kind == "write"


def test_같은_명령의_변수_대입으로_스크립트_경로를_푼다(home, tmp_path):
    _script(home, "run.sh", "echo hello\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outcome = classify(f"S={home / 'tools'}; bash $S/run.sh", elsewhere)
    assert outcome.kind == "pass"


def test_중괄호_변수도_푼다(home, tmp_path):
    _script(home, "run.sh", "kubectl get pods\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outcome = classify(f"W={home / 'tools'}\nbash ${{W}}/run.sh", elsewhere)
    assert outcome.kind == "read"


def test_명령_앞에_붙인_대입은_그_명령의_인자를_풀지_않는다(home, tmp_path):
    # given
    _script(home, "run.sh", "kubectl get pods\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # when
    outcome = classify(f"W={home / 'tools'} bash ${{W}}/run.sh", elsewhere)
    # then
    assert outcome.kind == "write"


def test_변수로_푼_스크립트의_쓰기는_쓰기로_본다(home, tmp_path):
    _script(home, "run.sh", "kubectl apply -f x.yaml --context dev -n web\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outcome = classify(f"S={home / 'tools'}; bash $S/run.sh", elsewhere)
    assert outcome.kind == "write"


def test_풀_수_없는_변수의_스크립트는_세션_쓰기로_분류한다(home):
    # given
    command = "bash $UNSET_DIR/run.sh"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "write"


def test_없는_스크립트는_세션_쓰기로_분류한다(home):
    # given
    command = f"bash {home}/missing.sh"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "write"


def test_cd가_없으면_이벤트_cwd가_기준이다(home):
    _script(home, "run.sh", "kubectl delete pod x --context dev -n web\n")
    assert classify("bash tools/run.sh", home).kind == "always"


def test_cat으로_파일에_쓰는_heredoc_본문은_데이터다(home):
    command = (
        f"cat > {home}/note.md <<'EOF'\n"
        "source One of the options\n"
        "bash Insert here\n"
        ". Another line\n"
        "kubectl delete pod x\n"
        "EOF\n"
    )
    assert classify(command, home).kind == "pass"


def test_tee로_파일에_쓰는_heredoc_본문도_데이터다(home):
    command = f"tee {home}/note.md <<'EOF'\nkubectl delete pod x\nEOF\n"
    assert classify(command, home).kind == "pass"


def test_bash에_먹이는_heredoc은_본문을_실행으로_본다(home):
    command = "bash <<'EOF'\nkubectl delete pod x --context dev -n web\nEOF\n"
    assert classify(command, home).kind != "pass"


@pytest.mark.parametrize("separator", [";", "&&", "||", "\n"])
@pytest.mark.parametrize(("before", "pipeline", "after"), [
    ("cat /x/a.md | head -120; echo", 'env | grep -E "CLAUDE_CODE_(SUBAGENT|EFFORT|MAX_CONC)"',
     'grep -h -E "maxEffortLevel" ~/.claude/settings.json 2>/dev/null'),
    ("echo before", "env | grep CLAUDE_CODE_X", "echo ok"),
    ("echo before", "printenv | rg CLAUDE_CODE_X | head -10", "echo ok"),
])
def test_filtered_environment_in_lists_keeps_standalone_aggregation(home, separator, before, pipeline, after):
    """명령 목록의 환경 변수 필터는 각 요소를 단독 분류해 합친 결과를 유지한다."""
    # given
    command = f"{before} {separator} {pipeline} {separator} {after}"
    parts = [classify(part, home) for part in (before, pipeline, after)]
    expected = guard._aggregate(parts, guard.tokenize(command))
    # when
    outcome = classify(command, home)
    # then
    assert outcome == expected
    assert outcome.kind != "sensitive"


@pytest.mark.parametrize("pipeline", ["env", "env | grep CLAUDE_CODE_X", "env | grep -P CLAUDE_CODE_X"])
def test_unfiltered_or_secret_environment_in_lists_stays_sensitive(home, monkeypatch, pipeline):
    """필터가 없거나 비밀 이름과 일치하거나 확인할 수 없는 환경 변수 조회는 목록에서도 민감 호출이다."""
    # given
    monkeypatch.setenv("CLAUDE_CODE_X_TOKEN", "test-placeholder")
    command = f"echo a; {pipeline}"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "sensitive"


def test_sensitive_environment_filter_in_a_list_keeps_its_standalone_keys(home, monkeypatch):
    """목록 안에서 비밀 이름과 일치한 환경 변수 필터는 단독 실행과 같은 민감 분류 키를 유지한다."""
    # given
    monkeypatch.setenv("CLAUDE_CODE_X_TOKEN", "test-placeholder")
    pipeline = "env | grep CLAUDE_CODE_X"
    expected = classify(pipeline, home)
    command = f"echo before; {pipeline} ; echo after"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == expected.kind == "sensitive"
    assert outcome.keys == expected.keys


def test_filtered_environment_does_not_hide_a_write_in_the_list(home):
    """환경 변수 필터를 포함한 명령 목록에서도 다른 요소의 쓰기 종류와 키가 유지된다."""
    # given
    write = "curl -X POST https://example.com/api"
    expected = classify(write, home)
    command = f"env | grep CLAUDE_CODE_X; {write}"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == expected.kind == "write"
    assert outcome.keys == expected.keys


@pytest.mark.parametrize("script_path", ["absolute", "relative", "symlink"])
def test_plugin_refresh_status_at_the_guard_root_is_a_read(home, script_path):
    """가드 플러그인 경로로 해석되는 새로고침 스크립트의 status는 읽기다."""
    # given
    script = REPO_ROOT / "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py"
    cwd = REPO_ROOT
    if script_path == "relative":
        script = script.relative_to(REPO_ROOT)
    elif script_path == "symlink":
        link = home / "refresh.py"
        link.symlink_to(script)
        script = link
    command = f"python3 {script} status --run-id {'0' * 32} --json"
    # when
    outcome = classify(command, cwd)
    # then
    assert outcome.kind == "read"


@pytest.mark.parametrize(("options", "subcommand"), [
    ("", "apply"), ("", "plan"), ("", "update"), ("", "apply-installed"), ("", "self-apply"),
    ("-B ", "status"), ("-I ", "status"), ("-- ", "status"),
])
def test_other_plugin_refresh_invocations_keep_the_existing_verdict(home, options, subcommand):
    """status 이외의 하위 명령이나 인터프리터 옵션이 있는 호출은 기존 쓰기 분류를 유지한다."""
    # given
    script = REPO_ROOT / "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py"
    command = f"python3 {options}{script} {subcommand} --run-id {'0' * 32} --json"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "write"


def test_same_named_refresh_script_outside_the_guard_root_keeps_its_verdict(home):
    """플러그인 밖에 있는 동명의 스크립트는 status라도 기존 쓰기 분류를 유지한다."""
    # given
    original = REPO_ROOT / "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py"
    script = home / "orca_plugin_refresh.py"
    script.write_text(original.read_text())
    # when
    outcome = classify(f"python3 {script} status --run-id {'0' * 32} --json", home)
    # then
    assert outcome.kind == "write"


def test_plugin_refresh_status_does_not_hide_another_write(home):
    """플러그인 status와 쓰기를 함께 실행하면 쓰기의 종류와 키가 유지된다."""
    # given
    script = REPO_ROOT / "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py"
    write = "curl -X POST https://example.com/api"
    expected = classify(write, home)
    command = f"python3 {script} status --run-id {'0' * 32} --json; {write}"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == expected.kind == "write"
    assert outcome.keys == expected.keys


@pytest.mark.parametrize("before", [
    'export REVIEW_NEW_TOKEN="$AWS_SECRET_ACCESS_KEY"', "REVIEW_NEW_TOKEN=x", "source ./env.sh", ". ./env.sh",
    "set -a", "eval true", "declare -x REVIEW_NEW_TOKEN=x", "f() { true; }",
])
def test_environment_filter_after_an_environment_change_stays_sensitive(home, before):
    """앞선 목록 요소가 환경을 바꿀 수 있으면 뒤의 환경 변수 필터를 읽기로 단축하지 않는다."""
    # given
    command = f"{before}; env | grep '^REVIEW_NEW_TOKEN='"
    # when
    outcome = classify(command, home)
    # then
    assert outcome.kind == "sensitive"
