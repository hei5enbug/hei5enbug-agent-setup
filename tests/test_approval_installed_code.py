"""Writes into installed plugin code, which are denied as self-modification, while reads of that code stay allowed."""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402
import approval_state as state_mod  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    custom = tmp_path / "custom-config"
    caches = {
        "claude": home / ".claude" / "plugins" / "cache" / "market" / "demo" / "1.0.0",
        "codex": home / ".codex" / "plugins" / "cache" / "market" / "demo" / "1.0.0",
        "custom": custom / "plugins" / "cache" / "market" / "demo" / "1.0.0",
    }
    for cache in caches.values():
        (cache / "scripts").mkdir(parents=True)
        (cache / "scripts" / "tool.py").write_text("print('x')\n")
    project = home / "work" / "project"
    project.mkdir(parents=True)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(custom))
    monkeypatch.setenv("HEI5ENBUG_RESPONSE_LANGUAGE", "English")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    state_mod.prompt_language.cache_clear()
    for name in [name for name in os.environ if name.startswith("GIT_")] + ["KUBECONFIG", "CODEX_HOME"]:
        monkeypatch.delenv(name, raising=False)
    return {"home": home, "project": project, "tmp": tmp_path, "scratch": scratch, **caches}


def verdict(world, command, cwd=None, session="s1"):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "session_id": session, "cwd": str(cwd or world["project"])}
    output = guard.handle(event, "claude")
    if not output:
        return None, ""
    details = output["hookSpecificOutput"]
    return details["permissionDecision"], details.get("permissionDecisionReason", "")


def denied(world, command, cwd=None):
    return verdict(world, command, cwd)[0] == "deny"


def fill(world, template):
    values = {name: str(path) for name, path in world.items() if isinstance(path, Path)}
    values["root"] = str(REPO_ROOT)
    return template.format(**values)


SHELL_WRITES = [
    "sed -i 's/a/b/' {claude}/scripts/tool.py",
    "sed -i.bak -e 's/a/b/' {claude}/scripts/tool.py",
    "sed --in-place 's/a/b/' {codex}/scripts/tool.py",
    "sed -ni 's/a/b/p' {custom}/scripts/tool.py",
    "cp {scratch}/new.py {claude}/scripts/tool.py",
    "cp -r {scratch}/dir {claude}/scripts/",
    "cp -t {claude}/scripts {scratch}/new.py",
    "mv {scratch}/new.py {codex}/scripts/tool.py",
    "mv {claude}/scripts/tool.py {scratch}/gone.py",
    "install -m 644 {scratch}/new.py {custom}/scripts/tool.py",
    "rsync -a {scratch}/dir/ {claude}/scripts/",
    "printf x | tee {claude}/scripts/tool.py",
    "echo x | tee -a {codex}/scripts/tool.py",
    "echo x > {claude}/scripts/tool.py",
    "echo x >> {custom}/scripts/tool.py",
    "echo x >| {claude}/scripts/tool.py",
    "echo x &> {claude}/scripts/tool.py",
    "cat > {claude}/scripts/new.py <<'EOF'\nprint(1)\nEOF",
    "cp {scratch}/new.py {claude}/scripts/../scripts//tool.py",
    "cp {scratch}/new.py {home}/.claude/plugins/cache/market/demo/1.0.0/scripts/tool.py",
    "cp {scratch}/new.py ~/.claude/plugins/cache/market/demo/1.0.0/scripts/tool.py",
    "cp {scratch}/new.py $HOME/.codex/plugins/cache/market/demo/1.0.0/scripts/tool.py",
    "cp {scratch}/new.py ${{CLAUDE_CONFIG_DIR}}/plugins/cache/market/demo/1.0.0/scripts/tool.py",
    "D={claude}/scripts; cp {scratch}/new.py $D/tool.py",
    "bash -c 'cp {scratch}/new.py {claude}/scripts/tool.py'",
    "echo x > {root}/scripts/guard_extra.py",
    "sed -i 's/a/b/' {root}/README.md",
    "cp {scratch}/new.py {root}/scripts/",
]


@pytest.mark.parametrize("template", SHELL_WRITES)
def test_설치된_플러그인_코드로의_셸_쓰기는_자기_수정으로_거부한다(world, template):
    # given
    command = fill(world, template)
    # when
    result = verdict(world, command)
    # then
    assert result[0] == "deny", command


def test_작업_폴더가_플러그인_캐시_안이어도_상대_경로_쓰기는_거부한다(world):
    # given
    command = "sed -i 's/a/b/' scripts/tool.py"
    # when
    result = denied(world, command, world["claude"])
    # then
    assert result


def test_심볼릭_링크와_cd를_거친_쓰기도_거부한다(world):
    # given
    link = world["scratch"] / "link"
    link.symlink_to(world["claude"] / "scripts")
    commands = [f"cp {world['scratch']}/new.py {link}/tool.py", f"echo x > {link}/tool.py",
                f"cd {world['claude']} && echo x > scripts/tool.py"]
    # when
    results = [denied(world, command) for command in commands]
    # then
    assert results == [True, True, True]


def test_거부_사유는_설치된_코드_수정_금지를_알려_준다(world):
    # given
    command = fill(world, "echo x > {claude}/scripts/tool.py")
    # when
    decision, reason = verdict(world, command)
    # then
    assert decision == "deny" and "installed" in reason.lower() and "plugin" in reason


SHELL_QUIET = [
    "cat {claude}/scripts/tool.py",
    "cp {claude}/scripts/tool.py {scratch}/copy.py",
    "cp -r {codex}/scripts {scratch}/scripts-copy",
    "rsync -a {custom}/scripts/ {scratch}/out/",
    "sed -n 1,5p {claude}/scripts/tool.py",
    "diff {claude}/scripts/tool.py {codex}/scripts/tool.py",
    "grep -rn print {claude}/scripts",
    "ls -la {claude}/scripts",
    "echo x > {scratch}/note.txt",
    "echo x | tee {scratch}/note.txt",
    "sed -i 's/a/b/' {scratch}/note.txt",
    "mv {scratch}/a.txt {scratch}/b.txt",
    "install -m 644 {scratch}/a.txt {scratch}/b.txt",
    "echo x > {home}/.claude/plugins/installed_plugins.json.demo",
    "echo x > {home}/.claude/plugins/cache-notes.txt",
    "echo x > {home}/.claude/plugins/cachex/file",
    "cp {scratch}/a.txt {project}/a.txt",
    "cmd 2>&1 > /dev/null",
]


@pytest.mark.parametrize("template", SHELL_QUIET)
def test_설치된_코드를_읽거나_다른_곳에_쓰는_셸_명령은_거부하지_않는다(world, template):
    # given
    command = fill(world, template)
    # when
    result = verdict(world, command)
    # then
    assert result[0] != "deny", command


def test_작업_폴더가_플러그인_캐시_안이어도_임시_폴더로_쓰는_명령은_거부하지_않는다(world):
    # given
    command = f"sed -i 's/a/b/' {world['scratch']}/note.txt"
    # when
    result = denied(world, command, world["claude"])
    # then
    assert not result


PYTHON_WRITES = [
    "open('{claude}/scripts/tool.py', 'w').write('x')",
    "from pathlib import Path\nPath('{codex}/scripts/tool.py').write_text('x')",
    "import shutil\nshutil.copy('{scratch}/new.py', '{custom}/scripts/tool.py')",
    "import os\nos.replace('{scratch}/new.py', '{claude}/scripts/tool.py')",
    "import os\nos.remove('{claude}/scripts/tool.py')",
    "import shutil\nshutil.rmtree('{claude}/scripts')",
    "from pathlib import Path\n(Path.home() / '.claude' / 'plugins' / 'cache' / 'market' / 'demo' / '1.0.0' / 'x.py')"
    ".write_text('x')",
    "import os\nbase = os.path.expanduser('~/.codex/plugins/cache')\nopen(os.path.join(base, 'x.py'), 'a').write('x')",
    "from pathlib import Path\nPath('{claude}/scripts/tool.py').open('w').write('x')",
    "with open('{claude}/scripts/../scripts//tool.py', 'a') as f:\n    f.write('x')",
    "open('{root}/scripts/guard_extra.py', 'w').write('x')",
]


@pytest.mark.parametrize("template", PYTHON_WRITES)
@pytest.mark.parametrize("shape", ["heredoc", "inline", "script"])
def test_설치된_플러그인_코드로의_파이썬_쓰기는_자기_수정으로_거부한다(world, template, shape):
    # given
    body = fill(world, template)
    script = world["scratch"] / "edit.py"
    script.write_text(body + "\n")
    command = {"heredoc": f"python3 - <<'EOF'\n{body}\nEOF", "inline": "python3 -c '" + body.replace("'", "'\"'\"'") + "'",
               "script": f"python3 {script}"}[shape]
    # when
    result = verdict(world, command)
    # then
    assert result[0] == "deny", (template, shape)


PYTHON_QUIET = [
    "print(open('{claude}/scripts/tool.py').read())",
    "from pathlib import Path\nprint(Path('{codex}/scripts/tool.py').read_text())",
    "import json\nopen('{scratch}/out.json', 'w').write(json.dumps({{'a': 1}}))",
    "from pathlib import Path\nPath('{project}/notes.txt').write_text('x')",
    "import os\nprint(os.listdir('{claude}/scripts'))",
]


@pytest.mark.parametrize("template", PYTHON_QUIET)
@pytest.mark.parametrize("shape", ["heredoc", "inline"])
def test_설치된_코드를_읽거나_다른_곳에_쓰는_파이썬은_거부하지_않는다(world, template, shape):
    # given
    body = fill(world, template)
    command = {"heredoc": f"python3 - <<'EOF'\n{body}\nEOF", "inline": "python3 -c '" + body.replace("'", "'\"'\"'") + "'"}[shape]
    # when
    result = verdict(world, command)
    # then
    assert result[0] not in ("deny", "ask"), (template, shape)


def test_설치된_코드를_다른_곳으로_복사하는_인라인_파이썬은_거부하지_않는다(world):
    # given
    body = fill(world, "import shutil\nshutil.copy('{custom}/scripts/tool.py', '{scratch}/copy.py')")
    # when
    result = verdict(world, "python3 -c '" + body.replace("'", "'\"'\"'") + "'")
    # then
    assert result[0] not in ("deny", "ask")
