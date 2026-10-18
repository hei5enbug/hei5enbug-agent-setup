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
