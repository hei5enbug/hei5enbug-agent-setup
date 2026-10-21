"""Acceptance checks: Claude's PermissionRequest absorbs the host prompt once the session's write approval exists."""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402
import approval_state as state_mod  # noqa: E402

WRITE_KEY = state_mod.WRITE_KEY
APPLY = "kubectl apply -f a --context dev -n web"
ALLOW = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("HEI5ENBUG_RESPONSE_LANGUAGE", "English")
    state_mod.prompt_language.cache_clear()
    for name in ("HEI5ENBUG_PARENT_SESSION", "KUBECONFIG", "AWS_PROFILE", "HEI5ENBUG_LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "kubectl").write_text("#!/bin/sh\necho fake\n")
    (bin_dir / "kubectl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return root


def event(project, tool, tool_input, name="PermissionRequest", session="s1", tool_use_id=None):
    value = {"hook_event_name": name, "tool_name": tool, "tool_input": tool_input, "session_id": session,
             "cwd": str(project)}
    if tool_use_id:
        value["tool_use_id"] = tool_use_id
    return value


def edit(project, path, name="PermissionRequest", session="s1", tool_use_id=None):
    return event(project, "Edit", {"file_path": str(path), "old_string": "a", "new_string": "b"}, name, session,
                 tool_use_id)


def bash(project, command, name="PermissionRequest", session="s1"):
    return event(project, "Bash", {"command": command}, name, session)


def asked(session="s1"):
    return state_mod._load("claude", session)["asked"]


def approved(session="s1"):
    return state_mod._load("claude", session)["approved"]


def grant_by_edit(project, session="s1"):
    target = project / "seed.txt"
    guard.handle(edit(project, target, session=session), "claude")
    guard.handle(edit(project, target, "PostToolUse", session, "toolu-seed"), "claude")


def test_승인_전_편집은_결정을_내지_않고_pr_항목을_기록한다(project):
    # given
    target = project / "src" / "a.py"
    request = edit(project, target)
    digest = state_mod.permission_digest("Edit", request["tool_input"])
    # when
    output = guard.handle(request, "claude")
    # then
    assert output is None
    assert asked() == [{"id": f"pr:{digest}", "keys": [WRITE_KEY]}]
    assert approved() == []


def test_편집이_끝나면_tool_use_id가_다른_사후_이벤트로_쓰기_승인을_기록하고_항목을_지운다(project):
    # given
    target = project / "src" / "a.py"
    guard.handle(edit(project, target), "claude")
    # when
    guard.handle(edit(project, target, "PostToolUse", tool_use_id="toolu-77"), "claude")
    # then
    assert approved() == [WRITE_KEY]
    assert asked() == []


def test_같은_편집을_다시_요청해도_pr_항목은_하나다(project):
    # given
    request = edit(project, project / "a.py")
    # when
    guard.handle(request, "claude")
    guard.handle(request, "claude")
    # then
    assert len(asked()) == 1


def test_승인_뒤_편집은_허용한다(project):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(edit(project, project / "other.py"), "claude")
    # then
    assert output == ALLOW


@pytest.mark.parametrize("tool, key", [("Write", "file_path"), ("MultiEdit", "file_path"), ("NotebookEdit", "notebook_path")])
def test_승인_뒤_다른_편집_도구도_허용한다(project, tool, key):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(event(project, tool, {key: str(project / "x.ipynb")}), "claude")
    # then
    assert output == ALLOW


def test_상대_경로_편집도_프로젝트_안이면_허용한다(project):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(event(project, "Write", {"file_path": "docs/new.md", "content": "x"}), "claude")
    # then
    assert output == ALLOW


@pytest.mark.parametrize("relative", [
    ".git/config", ".claude/settings.json", ".env", ".env.local", "sub/.git/hooks/pre-commit", ".vscode/settings.json",
    ".idea/x.xml", ".husky/pre-commit", ".bashrc", ".zshrc", ".gitconfig", ".gitmodules", ".mcp.json", ".claude.json",
    ".ripgreprc", ".profile", ".bash_profile", ".zprofile",
])
def test_보호_경로_편집은_승인_뒤에도_결정을_내지_않고_항목을_남기지_않는다(project, relative):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(edit(project, project / relative), "claude")
    # then
    assert output is None
    assert asked() == []


def test_승인_전_보호_경로_편집은_항목을_남기지_않는다(project):
    # given
    request = edit(project, project / ".git" / "config")
    # when
    output = guard.handle(request, "claude")
    # then
    assert output is None
    assert asked() == []


def test_프로젝트_밖_편집은_결정을_내지_않고_항목을_남기지_않는다(project, tmp_path):
    # given
    grant_by_edit(project)
    outside = tmp_path / "elsewhere" / "a.py"
    # when
    output = guard.handle(edit(project, outside), "claude")
    # then
    assert output is None
    assert asked() == []


def test_상위_경로로_빠져나가는_편집은_프로젝트_밖으로_본다(project):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(edit(project, project / ".." / "escape.py"), "claude")
    # then
    assert output is None


def test_상태_폴더_편집은_결정을_내지_않는다(project, tmp_path):
    # given
    grant_by_edit(project)
    target = state_mod.state_dir() / "claude-s1.json"
    # when
    output = guard.handle(edit(project, target), "claude")
    # then
    assert output is None


def test_추가_디렉터리_설정이_있으면_그_안의_편집은_승인_뒤_허용한다(project, tmp_path):
    # given
    extra = tmp_path / "extra"
    extra.mkdir()
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"additionalDirectories": [str(extra)]}}))
    grant_by_edit(project)
    # when
    inside = guard.handle(edit(project, extra / "a.txt"), "claude")
    protected = guard.handle(edit(project, extra / ".git" / "config"), "claude")
    # then
    assert inside == ALLOW
    assert protected is None


@pytest.mark.parametrize("protected", [".claude", ".git", ".husky", ".vscode", ".idea"])
def test_보호_디렉터리를_추가_디렉터리로_지정해도_그_안의_편집은_허용하지_않는다(project, tmp_path, protected):
    # given
    root = project / protected
    root.mkdir()
    config = tmp_path / "claude-config"
    config.mkdir()
    (config / "settings.json").write_text(json.dumps({"permissions": {"additionalDirectories": [str(root)]}}))
    grant_by_edit(project)
    # when
    inside = guard.handle(edit(project, root / "settings.json"), "claude")
    nested = guard.handle(edit(project, root / "sub" / "a.txt"), "claude")
    ordinary = guard.handle(edit(project, project / "a.txt"), "claude")
    # then
    assert inside is None
    assert nested is None
    assert ordinary == ALLOW
    assert asked() == []


def test_요청_횟수를_다_쓴_편집은_네이티브_프롬프트_대신_거부한다(project):
    # given
    outputs = [guard.handle(edit(project, project / f"f{index}.py"), "claude") for index in range(state_mod.MAX_REQUESTS)]
    # when
    fourth = guard.handle(edit(project, project / "f3.py"), "claude")
    # then
    assert outputs == [None] * state_mod.MAX_REQUESTS
    assert fourth == {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {
        "behavior": "deny", "message": state_mod.stop_reason("claude")}}}
    assert len(asked()) == state_mod.MAX_REQUESTS


def test_완료된_편집은_요청_횟수를_되돌려_다시_물을_수_있다(project):
    # given
    for index in range(state_mod.MAX_REQUESTS - 1):
        guard.handle(edit(project, project / f"f{index}.py"), "claude")
    last = project / "last.py"
    guard.handle(edit(project, last), "claude")
    guard.handle(edit(project, last, "PostToolUse", tool_use_id="toolu-9"), "claude")
    # when
    output = guard.handle(edit(project, project / "after.py"), "claude")
    # then
    assert output == ALLOW


def test_사용자_설정의_추가_디렉터리도_읽는다(project, tmp_path):
    # given
    extra = tmp_path / "shared"
    extra.mkdir()
    config = tmp_path / "claude-config"
    config.mkdir()
    (config / "settings.json").write_text(json.dumps({"permissions": {"additionalDirectories": [str(extra)]}}))
    grant_by_edit(project)
    # when
    output = guard.handle(edit(project, extra / "a.txt"), "claude")
    # then
    assert output == ALLOW


def test_변수가_든_경로는_허용하지_않는다(project):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(event(project, "Write", {"file_path": "$HOME/a.txt", "content": "x"}), "claude")
    # then
    assert output is None


def test_경로가_없는_편집은_결정을_내지_않는다(project):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(event(project, "Edit", {"old_string": "a"}), "claude")
    # then
    assert output is None


def test_승인_전_가드_비대상_bash는_결정을_내지_않고_항목을_남기지_않는다(project):
    # given
    request = bash(project, "npm install")
    # when
    output = guard.handle(request, "claude")
    # then
    assert output is None
    assert asked() == []


def test_승인_뒤_가드_비대상_bash는_허용한다(project):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(bash(project, "mkdir -p build"), "claude")
    # then
    assert output == ALLOW


@pytest.mark.parametrize("command", [
    "ssh host ls",
    "scp a host:/tmp/a",
    "rsync -a a host:/tmp/a",
    "sudo mkdir /opt/x",
    "env FOO=1 sudo mkdir /opt/x",
    "su -c ls",
    "doas ls",
    "rm -rf /tmp/x/../..",
    "rm -rf ..",
    "dd if=/dev/zero of=/tmp/x",
    "mkfs.ext4 /dev/sdb1",
    "echo hi | ssh host cat",
])
def test_위험하거나_원격인_bash는_승인_뒤에도_결정을_내지_않는다(project, command):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(bash(project, command), "claude")
    # then
    assert output is None
    assert asked() == []


@pytest.mark.parametrize("command", ["rm -fr build", "rm --recursive build", "mkdir x && rm -rf x", 'rm -rf "$(mktemp -d)"'])
def test_가드가_안전하다고_본_재귀_삭제는_승인_뒤_권한_요청에서_허용한다(project, command):
    """작업 폴더 안이나 임시 폴더의 재귀 삭제는 가드가 경로를 검사해 통과시켰으므로 세션 쓰기 승인 뒤 묻지 않는다."""
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(bash(project, command), "claude")
    # then
    assert output == ALLOW


def test_플러그인_자신의_파일_읽기는_작업_폴더_밖이어도_허용한다(project):
    """플러그인 지침 파일처럼 플러그인 루트 안의 파일 읽기는 승인 없이 허용하고, 그 밖의 바깥 파일은 호스트에 맡긴다."""
    # given
    root = guard.Path(guard.__file__).resolve().parents[1]
    inside = {"hook_event_name": "PermissionRequest", "session_id": "s1", "cwd": str(project), "tool_name": "Read",
              "tool_input": {"file_path": str(root / "instructions" / "services.md")}}
    outside = {**inside, "tool_input": {"file_path": str(guard.Path.home() / ".ssh" / "config")}}
    # when
    outputs = [guard.handle(inside, "claude"), guard.handle(outside, "claude")]
    # then
    assert outputs == [ALLOW, None]


def test_강제_푸시_문구가_든_bash는_결정을_내지_않는다(project):
    # given
    grant_by_edit(project)
    # when
    outputs = [guard.handle(bash(project, command), "claude")
               for command in ("git push --force origin main", "git push -f origin main", "git push origin +main")]
    # then
    assert outputs == [None, None, None]


def test_조회_결과는_권한_요청에서_결정을_내지_않는다(project):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(bash(project, "kubectl get pods -n web --context dev"), "claude")
    # then
    assert output is None


def test_승인_뒤_가드가_분류한_쓰기는_권한_요청에서_허용한다(project):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(bash(project, APPLY), "claude")
    # then
    assert output == ALLOW


def test_승인_전_가드가_분류한_쓰기는_권한_요청에서_결정을_내지_않는다(project):
    # given
    request = bash(project, APPLY)
    # when
    output = guard.handle(request, "claude")
    # then
    assert output is None


def test_매번_묻는_호출은_승인_뒤에도_권한_요청에서_결정을_내지_않는다(project):
    # given
    grant_by_edit(project)
    # when
    output = guard.handle(bash(project, "git push --force origin main"), "claude")
    # then
    assert output is None


def test_첫_편집을_승인하면_뒤따르는_kubectl_쓰기는_다시_묻지_않는다(project):
    # given
    target = project / "a.py"
    first = guard.handle(edit(project, target), "claude")
    guard.handle(edit(project, target, "PostToolUse", tool_use_id="toolu-1"), "claude")
    # when
    pre = guard.handle(bash(project, APPLY, "PreToolUse"), "claude")
    permission = guard.handle(bash(project, APPLY), "claude")
    # then
    assert first is None
    assert pre["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert permission == ALLOW


def test_부모가_승인한_세션의_하위_에이전트_편집은_허용한다(project, monkeypatch):
    # given
    grant_by_edit(project, session="parent")
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "claude:parent")
    # when
    output = guard.handle(edit(project, project / "a.py", session="child"), "claude")
    # then
    assert output == ALLOW


def test_부모가_승인하지_않으면_하위_에이전트는_허용도_항목_기록도_하지_않는다(project, monkeypatch):
    # given
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "claude:parent")
    # when
    edit_output = guard.handle(edit(project, project / "a.py", session="child"), "claude")
    bash_output = guard.handle(bash(project, "npm install", session="child"), "claude")
    # then
    assert edit_output is None
    assert bash_output is None
    assert asked("child") == []


def test_세션_아이디가_없으면_편집은_결정을_내지_않고_상태를_남기지_않는다(project):
    # given
    request = {**edit(project, project / "a.py"), "session_id": None}
    # when
    output = guard.handle(request, "claude")
    # then
    assert output is None
    assert not (project.parent / "xdg").exists() or not any((project.parent / "xdg").rglob("*.json"))
