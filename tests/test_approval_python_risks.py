"""Python code that reads a credential, writes into installed plugin code, or writes to a security-sensitive location,
judged like the shell commands that do the same; ordinary Python reads and writes stay silent."""
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
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("HEI5ENBUG_RESPONSE_LANGUAGE", "English")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    state_mod.prompt_language.cache_clear()
    for name in [name for name in os.environ if name.startswith("GIT_")] + ["KUBECONFIG", "CODEX_HOME"]:
        monkeypatch.delenv(name, raising=False)
    return {"home": home, "project": project, "tmp": tmp_path}


def verdict(world, command, cwd=None, session="s1"):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "session_id": session, "cwd": str(cwd or world["project"])}
    output = guard.handle(event, "claude")
    if not output:
        return None, ""
    details = output["hookSpecificOutput"]
    return details["permissionDecision"], details.get("permissionDecisionReason", "")


def decide(world, command, cwd=None, session="s1"):
    return verdict(world, command, cwd, session)[0]


def sensitive(world, command, session="s1"):
    decision, reason = verdict(world, command, session=session)
    return decision == "ask" and reason.startswith("Sensitive read")


def heredoc(body):
    return f"python3 - <<'EOF'\n{body}\nEOF"


def inline(body):
    return "python3 -c '" + body.replace("'", "'\"'\"'") + "'"


def shapes(body):
    return {"heredoc": heredoc(body), "inline": inline(body)}


CREDENTIAL_READS = [
    ("netrc", "import os\nprint(open(os.path.expanduser('~/.netrc')).read())"),
    ("aws credentials", "from pathlib import Path\nprint((Path.home() / '.aws' / 'credentials').read_text())"),
    ("aws config", "import os\nprint(open(os.path.join(os.path.expanduser('~'), '.aws', 'config')).read())"),
    ("docker config", "from pathlib import Path\nprint(Path('~/.docker/config.json').expanduser().read_text())"),
    ("kube config", "import os\nwith open(os.path.expanduser('~/.kube/config')) as f:\n    print(f.read())"),
    ("ssh key", "from pathlib import Path\nprint(Path.home().joinpath('.ssh', 'id_ed25519').read_bytes())"),
    ("gh hosts", "import os\ntext = open(os.path.expanduser('~/.config/gh/hosts.yml')).read()\nprint(text)"),
    ("env file", "print(open('.env').read())"),
    ("env file variant", "from pathlib import Path\nprint(Path('config/.env.production').read_text())"),
    ("path in a variable", "import os\np = os.path.expanduser('~/.netrc')\nprint(open(p, 'rb').read())"),
    ("f-string path", "import os\nhome = os.environ['HOME']\nprint(open(f'{home}/.aws/credentials').read())"),
    ("json load", "import json, os\nprint(json.load(open(os.path.expanduser('~/.docker/config.json'))))"),
    ("netrc module", "import netrc\nprint(netrc.netrc().authenticators('example.com'))"),
    ("loop over names", "from pathlib import Path\nfor name in ('.netrc', '.pgpass'):\n    print((Path.home() / name).read_text())"),
]


@pytest.mark.parametrize("title,body", CREDENTIAL_READS, ids=[item[0] for item in CREDENTIAL_READS])
@pytest.mark.parametrize("shape", ["heredoc", "inline"])
def test_자격_증명_파일을_읽는_파이썬은_cat과_같은_민감_조회로_묻는다(world, title, body, shape):
    # given
    command = shapes(body)[shape]
    # when
    result = sensitive(world, command)
    # then
    assert result, (title, shape)


def test_자격_증명_파일을_읽는_스크립트_파일_실행도_민감_조회로_묻는다(world):
    # given
    script = world["tmp"] / "scratch" / "peek.py"
    script.parent.mkdir()
    script.write_text("import os\nprint(open(os.path.expanduser('~/.netrc')).read())\n")
    # when
    result = sensitive(world, f"python3 {script}")
    # then
    assert result


def test_같은_명령에서_쓴_스크립트가_자격_증명을_읽어도_민감_조회로_묻는다(world):
    # given
    command = ("cat > /tmp/peek.py <<'EOF'\nimport os\nprint(open(os.path.expanduser('~/.netrc')).read())\nEOF\n"
               "python3 /tmp/peek.py")
    # when
    result = sensitive(world, command)
    # then
    assert result


@pytest.mark.parametrize("target", ["~/.ssh/id_rsa", "~/.config/gh/hosts.yml", "~/.netrc", ".env"])
def test_셸_cat이_읽는_같은_자격_증명_집합이_파이썬과_일치한다(world, target):
    # given
    shell = decide(world, f"cat {target}")
    # when
    python = decide(world, heredoc(f"import os\nprint(open(os.path.expanduser('{target}')).read())"), session="s2")
    # then
    assert shell == python == "ask"


@pytest.mark.parametrize("target", ["~/.ssh/known_hosts", "~/.ssh/id_rsa.pub", "~/.ssh/config"])
def test_공개_정보인_ssh_파일_읽기는_묻지_않는다(world, target):
    # given
    command = heredoc(f"import os\nprint(open(os.path.expanduser('{target}')).read())")
    # when
    result = decide(world, command)
    # then
    assert result not in ("ask", "deny")


SECRET_ENVIRONMENT = [
    ("environ subscript", "import os\nprint(os.environ['GITHUB_TOKEN'])"),
    ("getenv", "import os\nprint(os.getenv('AWS_SECRET_ACCESS_KEY'))"),
    ("environ get", "import os\nprint(os.environ.get('DB_PASSWORD', ''))"),
    ("from import", "from os import environ\nprint(environ.get('API_KEY'))"),
    ("alias", "import os as o\nprint(o.environ['SESSION_COOKIE'])"),
    ("sent in a header", "import os, urllib.request\nreq = urllib.request.Request('https://example.com', headers="
     "{'Authorization': 'token ' + os.environ['GITHUB_TOKEN']})\nprint(req.full_url)"),
    ("held then printed", "import os\ntoken = os.getenv('GH_TOKEN')\nprint(token)"),
]


@pytest.mark.parametrize("title,body", SECRET_ENVIRONMENT, ids=[item[0] for item in SECRET_ENVIRONMENT])
@pytest.mark.parametrize("shape", ["heredoc", "inline"])
def test_비밀_이름_환경변수의_값을_출력하거나_보내는_파이썬은_민감_조회로_묻는다(world, title, body, shape):
    # given
    command = shapes(body)[shape]
    # when
    result = sensitive(world, command)
    # then
    assert result, (title, shape)


QUIET_PYTHON = [
    ("existence test", "import os\nif os.environ.get('GITHUB_TOKEN'):\n    print('set')\nelse:\n    print('unset')"),
    ("held then tested", "import os\ntoken = os.getenv('GH_TOKEN')\nif not token:\n    raise SystemExit('missing')"),
    ("membership", "import os\nprint('GITHUB_TOKEN' in os.environ)"),
    ("names only", "import os\nprint(sorted(name for name in os.environ if 'TOKEN' in name))"),
    ("non-secret variable", "import os\nprint(os.environ.get('HOME'), os.getenv('LANG'))"),
    ("search text", "line = 'a .netrc b'\nprint('.netrc' in line, line.startswith('.aws'), line.split('credentials'))"),
    ("regex text", "import re\nprint(re.sub(r'\\.ssh|\\.netrc', '', 'x .ssh y'))"),
    ("exists only", "import os\nprint(os.path.exists(os.path.expanduser('~/.netrc')))"),
    ("template env file", "print(open('.env.example').read())"),
    ("plain work tree read", "print(open('README.md').read()[:10])"),
    ("work tree write", "from pathlib import Path\nPath('notes.txt').write_text('x')"),
    ("work tree open write", "with open('out/result.json', 'w') as f:\n    f.write('{}')"),
    ("temp write", "import tempfile\nopen('/tmp/demo.txt', 'w').write('x')"),
]


@pytest.mark.parametrize("title,body", QUIET_PYTHON, ids=[item[0] for item in QUIET_PYTHON])
@pytest.mark.parametrize("shape", ["heredoc", "inline"])
def test_평범한_파이썬_읽기와_쓰기는_묻지_않는다(world, title, body, shape):
    # given
    command = shapes(body)[shape]
    # when
    result = decide(world, command)
    # then
    assert result not in ("ask", "deny"), (title, shape)
