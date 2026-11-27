"""Acceptance checks: this plugin's Codex hooks are re-trusted only from a clean official checkout."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import codex_hook_trust as trust  # noqa: E402

KEY = f"{trust.PLUGIN_ID}:hooks/hooks.json:pre_tool_use:0:0"
FAKE_APP_SERVER = """#!{python}
import json, os, sys
log = os.environ["FAKE_TRUST_LOG"]
hooks = json.loads(os.environ["FAKE_HOOKS"])
reject = os.environ.get("FAKE_REJECT_WRITE") == "1"
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        print(json.dumps({{"id": request["id"], "result": {{}}}}), flush=True)
    elif method == "config/value/write":
        with open(log, "a") as stream:
            stream.write(json.dumps(request["params"]) + "\\n")
        if reject:
            print(json.dumps({{"id": request["id"], "error": {{"message": "denied"}}}}), flush=True)
        else:
            print(json.dumps({{"id": request["id"], "result": {{"status": "ok"}}}}), flush=True)
    elif method == "hooks/list":
        written = set()
        if os.path.exists(log):
            written = {{json.loads(item)["keyPath"] for item in open(log)}}
        listed = [dict(hook, trustStatus="trusted") if 'hooks.state."' + hook["key"] + '"' in written else hook
                  for hook in hooks]
        print(json.dumps({{"id": request["id"], "result": {{"data": [{{"cwd": request["params"]["cwds"][0], "hooks": listed}}]}}}}),
              flush=True)
"""


def git(root, *args):
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", "-c", "commit.gpgsign=false",
                           "-c", "tag.gpgsign=false", "-C", str(root), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


@pytest.fixture
def official(tmp_path, monkeypatch):
    origin = tmp_path / "origin"
    (origin / "hooks").mkdir(parents=True)
    (origin / "hooks" / "hooks.json").write_text('{"hooks": {}}\n')
    (origin / ".gitignore").write_text("*.log\n")
    git(origin, "init", "-q", "-b", "main")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "release")
    git(origin, "tag", "v1.0.0")
    monkeypatch.setattr(trust, "OFFICIAL_URL", origin.as_uri(), raising=False)
    monkeypatch.setattr(trust, "OFFICIAL_REMOTES", frozenset({origin.as_uri()}))
    return origin


@pytest.fixture
def installed(tmp_path, official):
    root = tmp_path / "codex-home" / "plugins" / "cache" / "hei5enbug" / "hei5enbug-agent-setup" / "1.0.0"
    root.parent.mkdir(parents=True)
    git(tmp_path, "clone", "-q", official.as_uri(), str(root))
    (root / trust.INSTALL_MARKER).write_text(json.dumps({"source_type": "git", "source": official.as_uri()}))
    return root


def hook(root, status="modified", plugin=trust.PLUGIN_ID, key=KEY):
    return {"key": key, "pluginId": plugin, "trustStatus": status, "currentHash": "sha256:abc",
            "sourcePath": str(root / "hooks" / "hooks.json"), "eventName": "preToolUse"}


def fake_server(tmp_path, hooks, reject=False):
    script = tmp_path / "fake_app_server"
    script.write_text(FAKE_APP_SERVER.format(python=sys.executable))
    script.chmod(0o755)
    log = tmp_path / "writes.jsonl"
    env = dict(os.environ, FAKE_TRUST_LOG=str(log), FAKE_HOOKS=json.dumps(hooks), FAKE_REJECT_WRITE="1" if reject else "0")
    return [str(script)], env, log


def pin_marketplace(codex_home, ref):
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text(f'[marketplaces.{trust.MARKETPLACE}]\nref = "{ref}"\n', encoding="utf-8")


def test_공식_저장소의_깨끗한_설치본은_검증을_통과한다(installed):
    # given
    root = installed
    # when
    trust.verify_checkout(root)
    # then
    assert (root / trust.INSTALL_MARKER).is_file()


@pytest.mark.parametrize("change", ["edited", "untracked", "ignored", "staged", "remote", "local_commit"])
def test_로컬에서_바뀐_설치본은_검증에_실패한다(installed, change):
    # given
    if change == "edited":
        (installed / "hooks" / "hooks.json").write_text('{"hooks": {"PreToolUse": []}}\n')
    elif change == "untracked":
        (installed / "hooks" / "extra.json").write_text("{}\n")
    elif change == "ignored":
        (installed / "debug.log").write_text("x\n")
    elif change == "staged":
        (installed / "new.txt").write_text("x\n")
        git(installed, "add", "new.txt")
    elif change == "remote":
        git(installed, "remote", "set-url", "origin", "https://example.com/fork/hei5enbug-agent-setup.git")
    else:
        (installed / "hooks" / "hooks.json").write_text('{"hooks": {"Stop": []}}\n')
        git(installed, "commit", "-q", "-am", "local")
    # when / then
    with pytest.raises(trust.TrustError):
        trust.verify_checkout(installed)


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_색인_플래그로_수정을_숨긴_설치본도_검증에_실패한다(installed, flag):
    # given
    git(installed, "update-index", flag, "hooks/hooks.json")
    (installed / "hooks" / "hooks.json").write_text('{"hooks": {"PreToolUse": []}}\n')
    assert git(installed, "status", "--porcelain") == "?? .codex-marketplace-install.json"
    # when / then
    with pytest.raises(trust.TrustError):
        trust.verify_checkout(installed)


def test_로컬_커밋에_로컬_v_태그와_위조한_origin_main을_붙여도_검증에_실패한다(installed):
    # given
    (installed / "hooks" / "hooks.json").write_text('{"hooks": {"PreToolUse": []}}\n')
    git(installed, "commit", "-q", "-am", "local")
    git(installed, "tag", "v-local")
    git(installed, "tag", "v9.9.9")
    git(installed, "update-ref", "refs/remotes/origin/main", "HEAD")
    # when / then
    with pytest.raises(trust.TrustError):
        trust.verify_checkout(installed)


def test_공식_원격이_지금_광고하는_릴리스_태그의_커밋이면_main에_없어도_통과한다(installed, official):
    # given
    git(official, "checkout", "-q", "-b", "hotfix")
    (official / "hooks" / "hooks.json").write_text('{"hooks": {"Stop": []}}\n')
    git(official, "commit", "-q", "-am", "hotfix")
    git(official, "tag", "-a", "v1.0.1", "-m", "hotfix")
    git(official, "checkout", "-q", "main")
    git(installed, "fetch", "-q", "origin", "tag", "v1.0.1")
    git(installed, "checkout", "-q", "--detach", "v1.0.1")
    git(installed, "update-ref", "-d", "refs/remotes/origin/main")
    # when
    result = trust.verify_checkout(installed)
    # then
    assert result is None


def test_공식_main이_앞서_나가도_그_조상이면_통과하고_설치본의_git에는_쓰지_않는다(installed, official):
    # given
    (official / "README.md").write_text("next\n")
    git(official, "add", "README.md")
    git(official, "commit", "-q", "-m", "next")
    git(installed, "update-ref", "-d", "refs/remotes/origin/main")
    refs_before = git(installed, "for-each-ref")
    # when
    result = trust.verify_checkout(installed)
    # then
    assert result is None
    assert git(installed, "for-each-ref") == refs_before


def test_공식_원격에_닿지_못하면_거부한다(installed, tmp_path, monkeypatch):
    # given
    missing = (tmp_path / "missing").as_uri()
    monkeypatch.setattr(trust, "OFFICIAL_URL", missing, raising=False)
    monkeypatch.setattr(trust, "OFFICIAL_REMOTES", frozenset({missing}))
    git(installed, "remote", "set-url", "origin", missing)
    # when / then
    with pytest.raises(trust.TrustError):
        trust.verify_checkout(installed)


def test_대상은_이_플러그인의_신뢰되지_않은_훅뿐이다(installed):
    # given
    hooks = [hook(installed), hook(installed, status="untrusted", key=f"{trust.PLUGIN_ID}:hooks/codex-hooks.json:stop:0:0"),
             hook(installed, status="trusted", key=f"{trust.PLUGIN_ID}:hooks/hooks.json:stop:0:0"),
             hook(installed, plugin="other@market", key="other@market:hooks/hooks.json:stop:0:0"),
             hook(installed, key=f'{trust.PLUGIN_ID}:hooks/hooks.json:"x"')]
    # when
    targets = trust.candidates(hooks)
    # then
    assert [item["key"] for item in targets] == [KEY, f"{trust.PLUGIN_ID}:hooks/codex-hooks.json:stop:0:0"]


def test_검증된_설치본의_훅은_현재_해시로_신뢰를_기록하고_hooks_list로_확인한다(installed, tmp_path):
    # given
    hooks = [hook(installed), hook(installed, plugin="other@market", key="other@market:hooks/hooks.json:stop:0:0")]
    command, env, log = fake_server(tmp_path, hooks)
    # when
    after = trust.heal(hooks, command, env, str(tmp_path), 20)
    # then
    writes = [json.loads(line) for line in log.read_text().splitlines()]
    assert writes == [{"keyPath": f'hooks.state."{KEY}"', "value": {"trusted_hash": "sha256:abc"}, "mergeStrategy": "replace"}]
    assert {item["key"]: item["trustStatus"] for item in after}[KEY] == "trusted"


@pytest.mark.parametrize("case", ["edited", "reject", "other_plugin"])
def test_수정된_설치본이나_실패한_쓰기나_다른_플러그인은_신뢰하지_않는다(installed, tmp_path, case):
    # given
    hooks = [hook(installed, plugin="other@market", key="other@market:x")] if case == "other_plugin" else [hook(installed)]
    if case == "edited":
        (installed / "hooks" / "hooks.json").write_text('{"hooks": {"PreToolUse": []}}\n')
    command, env, log = fake_server(tmp_path, hooks, reject=case == "reject")
    # when / then
    with pytest.raises(trust.TrustError):
        trust.heal(hooks, command, env, str(tmp_path), 20)
    assert log.exists() == (case == "reject")


@pytest.mark.parametrize(("current", "expected"), [
    ("sha256:hookpart/sha256:contentpart", {"trusted_hash": "sha256:hookpart", "trusted_content_hash": "sha256:contentpart"}),
    ("sha256:onepart", {"trusted_hash": "sha256:onepart"}),
])
def test_두_부분_해시는_훅_부분과_내용_부분으로_나누어_쓰고_한_부분_해시는_trusted_hash만_쓴다(installed, tmp_path, current, expected):
    """두 부분 해시는 trusted_hash에 훅 부분, trusted_content_hash에 내용 부분을 쓰고, 한 부분 해시는 trusted_hash만 쓴다."""
    # given
    hooks = [{**hook(installed), "currentHash": current}]
    command, env, log = fake_server(tmp_path, hooks)
    # when
    trust.heal(hooks, command, env, str(tmp_path), 20)
    # then
    writes = [json.loads(line) for line in log.read_text().splitlines()]
    assert writes == [{"keyPath": f'hooks.state."{KEY}"', "value": expected, "mergeStrategy": "replace"}]


@pytest.fixture
def retrust_env(installed, tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    pin_marketplace(tmp_path / "codex-home", "a" * 40)
    return installed


def test_재신뢰는_성공하면_훅을_신뢰하고_설치_폴더를_기록해_같은_폴더는_다시_하지_않는다(retrust_env, tmp_path):
    """재신뢰가 성공하면 훅을 신뢰하고 설치 폴더를 기록해 같은 폴더에서는 다시 필요하다고 보지 않는다."""
    # given
    command, env, log = fake_server(tmp_path, [hook(retrust_env)])
    # when
    reason = trust.retrust(command=command, env=env)
    # then
    assert reason is None
    assert len(log.read_text().splitlines()) == 1
    assert trust.retrust_due(trust.install_folder(), trust.state_folder() / trust.STAMP_FILE, 0.0) is False


def test_기록한_뒤_설치_폴더가_다시_설치되면_재신뢰가_필요하다고_본다(retrust_env):
    """기록한 설치 폴더가 같은 버전으로 다시 설치되어 교체되면 재신뢰가 필요하다고 본다."""
    # given
    folder, stamp = trust.install_folder(), trust.state_folder() / trust.STAMP_FILE
    stamp.parent.mkdir(parents=True)
    trust.write_stamp(stamp, trust.install_identity(folder), True, 0.0)
    unchanged = trust.retrust_due(folder, stamp, 1.0)
    # when
    (retrust_env.parent / "scratch").mkdir()
    retrust_env.rename(retrust_env.parent / "old")
    (retrust_env.parent / "scratch").rename(retrust_env)
    # then
    assert unchanged is False
    assert trust.retrust_due(folder, stamp, 1.0) is True


def test_검증에_실패한_재신뢰는_신뢰를_쓰지_않고_사유를_돌려주며_지연_안에는_같은_폴더를_다시_시도하지_않는다(retrust_env, tmp_path):
    """수정된 설치본은 신뢰 쓰기 없이 사유를 돌려주고, 같은 폴더의 재시도는 지연 시간이 지난 뒤에만 허용한다."""
    # given
    (retrust_env / "hooks" / "hooks.json").write_text('{"hooks": {"PreToolUse": []}}\n')
    command, env, log = fake_server(tmp_path, [hook(retrust_env)])
    stamp = trust.state_folder() / trust.STAMP_FILE
    folder = trust.install_folder()
    # when
    reason = trust.retrust(command=command, env=env)
    saved = json.loads(stamp.read_text())
    # then
    assert reason and "local changes" in reason
    assert not log.exists()
    assert saved["ok"] is False
    assert trust.retrust_due(folder, stamp, saved["at"] + 1) is False
    assert trust.retrust_due(folder, stamp, saved["at"] + trust.RETRUST_RETRY_SECONDS) is True


def test_다른_재신뢰가_잠금을_잡고_있으면_아무것도_하지_않는다(retrust_env, tmp_path):
    """다른 재신뢰가 잠금을 잡고 있으면 Codex 서버를 시작하지 않고 신뢰도 쓰지 않는다."""
    # given
    import fcntl
    command, env, log = fake_server(tmp_path, [hook(retrust_env)])
    state = trust.state_folder()
    state.mkdir(parents=True)
    with open(state / trust.LOCK_FILE, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # when
        reason = trust.retrust(command=command, env=env)
    # then
    assert reason == "another re-trust is running"
    assert not log.exists()
    assert not (state / trust.STAMP_FILE).exists()


@pytest.mark.parametrize("ref", ["v1.0.0", "a" * 39, "A" * 40, None])
def test_마켓플레이스_ref가_전체_커밋이_아니면_재신뢰는_Codex를_시작하지_않는다(retrust_env, tmp_path, ref):
    """마켓플레이스 ref가 태그 이름이거나 40자리 커밋이 아니면 프롬프트 재신뢰는 시작도 실행도 하지 않는다."""
    # given
    codex_home = tmp_path / "codex-home"
    if ref is None:
        (codex_home / "config.toml").write_text("", encoding="utf-8")
    else:
        pin_marketplace(codex_home, ref)
    command, env, log = fake_server(tmp_path, [hook(retrust_env)])
    # when
    started = trust.start_retrust_if_due(script=tmp_path / "missing.py")
    reason = trust.retrust(command=command, env=env)
    # then
    assert started is False
    assert reason
    assert not log.exists()
    assert not (trust.state_folder() / trust.STAMP_FILE).exists()


def test_공식_원격_조회는_확인_중인_저장소의_로컬_url_재작성에_영향받지_않는다(installed, official, tmp_path):
    """확인 대상 저장소의 로컬 url insteadOf 설정이 있어도 공식 원격이 광고하는 ref를 그대로 읽는다."""
    # given
    decoy = tmp_path / "decoy"
    (decoy / "hooks").mkdir(parents=True)
    (decoy / "hooks" / "hooks.json").write_text('{"decoy": true}\n')
    git(decoy, "init", "-q", "-b", "main")
    git(decoy, "add", ".")
    git(decoy, "commit", "-q", "-m", "decoy")
    git(installed, "config", f"url.{decoy.as_uri()}.insteadOf", official.as_uri())
    expected = git(official, "rev-parse", "refs/heads/main")
    # when
    main, released = trust.advertised()
    # then
    assert main == expected
    assert git(decoy, "rev-parse", "refs/heads/main") != expected
    assert released == {git(official, "rev-parse", "v1.0.0")}


def test_재신뢰는_목록을_읽기_전의_설치_신원을_기록해_도중에_바뀌면_성공을_기록하지_않는다(retrust_env, tmp_path, monkeypatch):
    """훅 목록을 읽는 사이 설치 폴더가 바뀌면 성공 기록을 남기지 않아 다음 프롬프트가 다시 확인한다."""
    # given
    command, env, log = fake_server(tmp_path, [hook(retrust_env)])
    folder, stamp = trust.install_folder(), trust.state_folder() / trust.STAMP_FILE
    real_calls = trust.app_server_calls
    swapped = []

    def swapping(*arguments):
        result = real_calls(*arguments)
        if not swapped:
            swapped.append((folder / "2.0.0").mkdir())
        return result

    monkeypatch.setattr(trust, "app_server_calls", swapping)
    # when
    reason = trust.retrust(command=command, env=env)
    # then
    assert reason is None
    assert not stamp.exists()
    assert trust.retrust_due(folder, stamp, 0.0) is True


def test_프롬프트_확인은_설치_마커의_내용을_읽지_않고_손상되거나_읽을_수_없어도_예외_없이_판단한다(retrust_env, monkeypatch):
    """프롬프트 시점 확인은 마커의 메타데이터만 보므로 내용이 손상돼도 변경을 감지하고, 마커나 폴더를 못 읽어도 예외 없이 시작하지 않는다."""
    # given
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    marker = retrust_env / trust.INSTALL_MARKER
    folder, stamp = trust.install_folder(), trust.state_folder() / trust.STAMP_FILE
    stamp.parent.mkdir(parents=True)
    trust.write_stamp(stamp, trust.install_identity(folder), True, 0.0)
    marker.write_bytes(b"\xff\xfe\x00broken-marker-with-new-size")
    reads = []
    real_read_text = Path.read_text

    def tracked(self, *arguments, **options):
        reads.append(self.name)
        return real_read_text(self, *arguments, **options)

    monkeypatch.setattr(Path, "read_text", tracked)
    # when
    changed = trust.retrust_due(folder, stamp, 1.0)
    retrust_env.chmod(0)
    try:
        unreadable_version = trust.retrust_due(folder, stamp, 1.0)
    finally:
        retrust_env.chmod(0o755)
    folder.chmod(0)
    try:
        unreadable_folder = trust.retrust_due(folder, stamp, 1.0)
    finally:
        folder.chmod(0o755)
    # then
    assert changed is True
    assert trust.INSTALL_MARKER not in reads
    assert unreadable_folder is False
    assert unreadable_version in {True, False}


def test_잠금을_얻은_뒤_이미_다른_재신뢰가_성공했으면_다시_시작하지_않는다(retrust_env, tmp_path, monkeypatch):
    """두 프롬프트가 같은 설치를 보고 하나가 먼저 재신뢰를 끝내면, 잠금을 얻은 나머지는 기록을 다시 확인해 시작하지 않는다."""
    # given
    folder, stamp = trust.install_folder(), trust.state_folder() / trust.STAMP_FILE
    real_due = trust.retrust_due
    calls = []

    def stale_then_real(*arguments):
        calls.append(1)
        if len(calls) == 1:
            return True
        return real_due(*arguments)

    monkeypatch.setattr(trust, "retrust_due", stale_then_real)
    stamp.parent.mkdir(parents=True)
    trust.write_stamp(stamp, trust.install_identity(folder), True, 0.0)
    starts = []
    monkeypatch.setattr(trust.subprocess, "Popen", lambda *arguments, **options: starts.append(arguments))
    # when
    started = trust.start_retrust_if_due(script=tmp_path / "heal.py")
    # then
    assert started is False
    assert starts == []
