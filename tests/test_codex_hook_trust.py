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

OFFICIAL = "https://github.com/hei5enbug/hei5enbug-agent-setup.git"
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
def installed(tmp_path):
    origin = tmp_path / "origin"
    (origin / "hooks").mkdir(parents=True)
    (origin / "hooks" / "hooks.json").write_text('{"hooks": {}}\n')
    (origin / ".gitignore").write_text("*.log\n")
    git(origin, "init", "-q", "-b", "main")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "release")
    git(origin, "tag", "v1.0.0")
    root = tmp_path / "codex-home" / "plugins" / "cache" / "hei5enbug" / "hei5enbug-agent-setup" / "1.0.0"
    root.parent.mkdir(parents=True)
    git(tmp_path, "clone", "-q", str(origin), str(root))
    git(root, "remote", "set-url", "origin", OFFICIAL)
    (root / trust.INSTALL_MARKER).write_text(json.dumps({"source_type": "git", "source": OFFICIAL}))
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


def test_main_원격_참조가_없어도_릴리스_태그의_커밋이면_통과하고_둘_다_없으면_실패한다(installed):
    # given
    git(installed, "update-ref", "-d", trust.MAIN_REF)
    git(installed, "update-ref", "-d", "refs/remotes/origin/HEAD")
    tagged = trust.verify_checkout(installed)
    git(installed, "tag", "-d", "v1.0.0")
    # when / then
    assert tagged is None
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
