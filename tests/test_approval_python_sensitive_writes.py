"""Python writes to security-sensitive locations ask every time; ordinary Python writes stay silent."""
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
    project = home / "work" / "project"
    (project / ".git" / "hooks").mkdir(parents=True)
    (project / ".claude").mkdir()
    (project / "out").mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("HEI5ENBUG_RESPONSE_LANGUAGE", "English")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    state_mod.prompt_language.cache_clear()
    for name in [name for name in os.environ if name.startswith("GIT_")] + ["KUBECONFIG", "CODEX_HOME"]:
        monkeypatch.delenv(name, raising=False)
    return {"home": home, "project": project, "scratch": scratch}


def verdict(world, command, session="s1"):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "session_id": session, "cwd": str(world["project"])}
    output = guard.handle(event, "claude")
    if not output:
        return None, ""
    details = output["hookSpecificOutput"]
    return details["permissionDecision"], details.get("permissionDecisionReason", "")


def shapes(world, body):
    script = world["scratch"] / "job.py"
    script.write_text(body + "\n")
    return {"heredoc": f"python3 - <<'EOF'\n{body}\nEOF", "inline": "python3 -c '" + body.replace("'", "'\"'\"'") + "'",
            "script": f"python3 {script}"}


SENSITIVE_WRITES = [
    ("ssh authorized keys", "open('{home}/.ssh/authorized_keys', 'a').write('ssh-ed25519 AAAA demo')"),
    ("ssh config", "from pathlib import Path\nPath('{home}/.ssh/config').write_text('Host *')"),
    ("aws credentials", "import os\nopen(os.path.expanduser('~/.aws/credentials'), 'w').write('[default]')"),
    ("gnupg", "from pathlib import Path\n(Path.home() / '.gnupg' / 'gpg.conf').write_text('x')"),
    ("zshrc", "with open('{home}/.zshrc', 'a') as f:\n    f.write('export X=1')"),
    ("bashrc", "from pathlib import Path\nPath('~/.bashrc').expanduser().write_text('x')"),
    ("profile", "open('{home}/.profile', 'a').write('x')"),
    ("bash profile", "open('{home}/.bash_profile', 'a').write('x')"),
    ("zprofile", "import os\nopen(os.path.join(os.environ['HOME'], '.zprofile'), 'w').write('x')"),
    ("git hook", "from pathlib import Path\nPath('.git/hooks/pre-commit').write_text('#!/bin/sh')"),
    ("git hook absolute", "open('{project}/.git/hooks/post-merge', 'w').write('x')"),
    ("claude settings", "open('{home}/.claude/settings.json', 'w').write('{{}}')"),
    ("claude local settings", "from pathlib import Path\nPath('.claude/settings.local.json').write_text('{{}}')"),
    ("claude json", "open('{home}/.claude.json', 'w').write('{{}}')"),
    ("codex config", "from pathlib import Path\n(Path.home() / '.codex' / 'config.toml').write_text('x')"),
    ("codex hooks", "open('{home}/.codex/hooks.json', 'w').write('{{}}')"),
    ("copied in", "import shutil\nshutil.copy('{scratch}/key', '{home}/.ssh/id_ed25519')"),
    ("moved in", "import os\nos.replace('{scratch}/rc', '{home}/.zshrc')"),
    ("removed", "import os\nos.remove('{home}/.zshrc')"),
    ("path in a variable", "import os\ntarget = os.path.expanduser('~/.ssh/authorized_keys')\nopen(target, 'a').write('x')"),
    ("through the dot-dot spelling", "open('{home}/work/../.zshrc', 'a').write('x')"),
    ("f-string with an unknown home", "import sys\nopen(f'{{sys.argv[1]}}/.ssh/authorized_keys', 'a').write('x')"),
    ("keyword copyfile", "import shutil\nshutil.copyfile(src='{scratch}/key', dst='{home}/.ssh/id_ed25519')"),
    ("keyword move", "import shutil\nshutil.move(dst='{home}/.zshrc', src='{scratch}/rc')"),
    ("keyword rmtree", "import shutil\nshutil.rmtree(path='{home}/.gnupg')"),
    ("keyword remove", "import os\nos.remove(path='{home}/.zshrc')"),
    ("keyword rename", "import os\nos.rename(src='{scratch}/rc', dst='{home}/.zshrc')"),
    ("keyword makedirs", "import os\nos.makedirs(name='{home}/.ssh/new')"),
    ("keyword symlink", "import os\nos.symlink(src='{scratch}/rc', dst='{home}/.zshrc')"),
    ("keyword open", "open(file='{home}/.zshrc', mode='a').write('x')"),
    ("keyword path rename", "from pathlib import Path\nPath('{scratch}/rc').rename(target='{home}/.zshrc')"),
    ("keyword path replace", "from pathlib import Path\nPath('{scratch}/rc').replace(target='{home}/.zshrc')"),
    ("keyword path symlink", "from pathlib import Path\nPath('{home}/.zshrc').symlink_to(target='{scratch}/rc')"),
    ("keywords in a literal dict", "import shutil\nshutil.copyfile(**{{'src': '{scratch}/k', 'dst': '{home}/.ssh/id_ed25519'}})"),
    ("with_suffix to settings", "from pathlib import Path\nPath('{project}/.claude/settings.txt').with_suffix('.json').write_text('{{}}')"),
    ("with_name to settings", "from pathlib import Path\nPath('{project}/.claude/x.json').with_name('settings.json').write_text('{{}}')"),
    ("with_stem to settings", "from pathlib import Path\nPath('{project}/.claude/other.json').with_stem('settings').write_text('{{}}')"),
    ("with_name to zshrc", "from pathlib import Path\nPath('{home}/zshrc.txt').with_name('.zshrc').write_text('x')"),
    ("with_suffix to hook", "from pathlib import Path\nPath('{project}/.git/hooks/pre-commit.sample').with_suffix('').write_text('x')"),
]


@pytest.mark.parametrize("title,template", SENSITIVE_WRITES, ids=[item[0] for item in SENSITIVE_WRITES])
@pytest.mark.parametrize("shape", ["heredoc", "inline", "script"])
def test_민감한_위치에_쓰는_파이썬은_매번_묻는다(world, title, template, shape):
    # given
    body = template.format(**world)
    command = shapes(world, body)[shape]
    # when
    decision, reason = verdict(world, command)
    # then
    assert decision == "ask" and reason.startswith("Asks every time"), (title, shape, decision, reason)


def test_민감한_위치에_쓰는_파이썬은_승인한_뒤에도_다시_묻는다(world):
    # given
    command = shapes(world, "open('{home}/.zshrc', 'a').write('x')".format(**world))["inline"]
    verdict(world, command)
    for name in ("PostToolUse",):
        guard.handle({"hook_event_name": name, "tool_name": "Bash", "tool_input": {"command": command},
                      "session_id": "s1", "cwd": str(world["project"])}, "claude")
    # when
    decision, _ = verdict(world, command)
    # then
    assert decision == "ask"


ORDINARY_WRITES = [
    ("work tree text", "from pathlib import Path\nPath('notes.txt').write_text('x')"),
    ("work tree json", "import json\nwith open('out/result.json', 'w') as f:\n    json.dump({{}}, f)"),
    ("absolute work tree", "open('{project}/out/a.txt', 'w').write('x')"),
    ("scratch folder", "open('{scratch}/a.txt', 'w').write('x')"),
    ("temp folder", "open('/tmp/demo-a.txt', 'w').write('x')"),
    ("home folder file", "open('{home}/notes.txt', 'w').write('x')"),
    ("claude commands folder", "open('{project}/.claude/commands/demo.md', 'w').write('x')"),
    ("settings.json outside the tool folders", "open('{project}/out/settings.json', 'w').write('{{}}')"),
    ("git folder note", "open('{project}/.git/info-note.txt', 'w').write('x')"),
    ("rc-like name in the work tree", "open('{project}/out/zshrc.txt', 'w').write('x')"),
    ("rc-like name in a subfolder", "open('{project}/out/.zshrc', 'w').write('x')"),
    ("read of a hook", "print(open('{project}/.git/hooks/pre-commit.sample').read() if False else 'ok')"),
    ("read of ssh config", "print(open('{home}/.ssh/known_hosts').read() if False else 'ok')"),
    ("names only", "import os\nprint(os.listdir('{home}'))"),
    ("keyword copyfile", "import shutil\nshutil.copyfile(src='{home}/.zshrc', dst='{scratch}/zshrc')"),
    ("keyword remove", "import os\nos.remove(path='{scratch}/a.txt') if False else None"),
    ("keyword rename", "import os\nos.rename(src='{scratch}/a', dst='{scratch}/b') if False else None"),
    ("keyword open", "open(file='{scratch}/a.txt', mode='w').write('x')"),
    ("keyword path rename", "from pathlib import Path\nif False:\n    Path('{scratch}/a').rename(target='{scratch}/b')"),
    ("with_suffix elsewhere", "from pathlib import Path\nPath('{project}/.claude/settings.json').with_suffix('.bak').write_text('x')"),
    ("with_suffix other json", "from pathlib import Path\nPath('{project}/out/settings.txt').with_suffix('.json').write_text('{{}}')"),
    ("with_name elsewhere", "from pathlib import Path\nPath('{home}/zshrc.txt').with_name('notes.txt').write_text('x')"),
    ("with_stem elsewhere", "from pathlib import Path\nPath('{project}/.claude/other.json').with_stem('local').write_text('{{}}')"),
]


@pytest.mark.parametrize("title,template", ORDINARY_WRITES, ids=[item[0] for item in ORDINARY_WRITES])
@pytest.mark.parametrize("shape", ["heredoc", "inline", "script"])
def test_평범한_위치에_쓰는_파이썬은_묻지_않는다(world, title, template, shape):
    # given
    body = template.format(**world)
    command = shapes(world, body)[shape]
    # when
    decision, reason = verdict(world, command)
    # then
    assert decision not in ("ask", "deny"), (title, shape, decision, reason)
