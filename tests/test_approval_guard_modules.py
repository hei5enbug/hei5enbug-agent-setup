"""Acceptance checks: the approval guard's split modules stay layered, owned once, and as protected as the entry point."""
import ast
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_approval_guard import SCRIPTS, bash_event, decision_of, fake_bin, guard, source_tree, state  # noqa: F401

GUARD_FILE = re.compile(r"(?:guard_\w+|approval_guard|approval_state\w*|datagrip_\w+|db_read_policy)\.py")
LATE_BOUND = {
    "TEMPORARY_ROOTS": "guard_paths",
    "_temporary": "guard_paths",
    "LOOKUP_TIMEOUT_SECONDS": "guard_shell",
    "_lookup": "guard_shell",
    "_git_probe": "guard_git",
    "PODMAN_SYSTEM_CONFIGS": "guard_cloud",
    "classify_text": "guard_dispatch",
    "classify_mcp": "guard_tools",
    "_REMOVAL_TRACE": "guard_temp",
    "_COMMAND_TRACE": "guard_temp",
}


def guard_stems():
    return sorted(path.stem for path in SCRIPTS.glob("*.py") if GUARD_FILE.fullmatch(path.name))


def split_stems():
    return [stem for stem in guard_stems() if stem not in {"approval_guard", "approval_state", "datagrip_guard", "db_read_policy"}]


def top_level_imports(stem):
    tree = ast.parse((SCRIPTS / f"{stem}.py").read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_보호_목록은_디스크의_가드_모듈_전부와_정확히_같다():
    # given
    on_disk = set(guard_stems())
    # when
    listed = set(importlib.import_module("guard_self").GUARD_MODULE_NAMES)
    # then
    assert listed == on_disk
    assert importlib.import_module("guard_self").GUARD_SCRIPTS == {f"{name}.py" for name in on_disk} | {"hook_python.sh"}


@pytest.mark.parametrize("stem", split_stems())
def test_분리한_모듈은_진입점을_가져오지_않는다(stem):
    # given
    imports = top_level_imports(stem)
    # when
    imports_entry = "approval_guard" in imports
    # then
    assert not imports_entry


def test_가드_모듈의_모듈_수준_가져오기에는_순환이_없다():
    # given
    stems = set(guard_stems())
    graph = {stem: top_level_imports(stem) & stems - {stem} for stem in stems}
    # when
    resolved = set()
    while len(resolved) < len(graph):
        ready = {stem for stem, deps in graph.items() if stem not in resolved and deps <= resolved}
        if not ready:
            break
        resolved |= ready
    # then
    assert resolved == set(graph), f"import cycle among {sorted(set(graph) - resolved)}"


@pytest.mark.parametrize("name", sorted(LATE_BOUND))
def test_바꿔_끼우는_이름은_정의_모듈_하나에만_묶여_있다(name):
    # given
    owner = LATE_BOUND[name]
    others = [stem for stem in split_stems() if stem != owner]
    # when
    holders = [stem for stem in others if hasattr(importlib.import_module(stem), name)]
    # then
    assert hasattr(importlib.import_module(owner), name)
    assert holders == []


@pytest.mark.parametrize("stem", split_stems())
def test_분리한_모듈은_혼자_가져와도_동작한다(stem):
    # given
    code = f"import {stem}"
    # when
    done = subprocess.run([sys.executable, "-c", code], cwd=SCRIPTS, capture_output=True, text=True, timeout=60)
    # then
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("template", [
    "python3 scripts/{stem}.py",
    "./scripts/{stem}.py",
    "printf '{{}}' | python3 scripts/{stem}.py",
    "python3 -m {stem}",
    "python3 -c 'import {stem}'",
    "python3 -c 'from {stem} import x'",
    "sh -c 'python3 scripts/{stem}.py'",
    "env PYTHONPATH=x python3 scripts/{stem}.py",
])
@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("stem", guard_stems())
def test_가드_모듈을_실행하거나_가져오는_명령은_두_호스트_모두_거부한다(state, fake_bin, stem, host, template):
    # given
    event = bash_event(template.format(stem=stem), cwd=state)
    # when
    output = guard.handle(event, host)
    # then
    assert decision_of(output) == "deny"


@pytest.mark.parametrize("body", [
    "import {stem}\n",
    "from {stem} import x\n",
    "__import__('{stem}')\n",
    "import subprocess\nsubprocess.run(['python3', 'scripts/{stem}.py'])\n",
    "import runpy\nrunpy.run_path('scripts/{stem}.py')\n",
])
@pytest.mark.parametrize("stem", guard_stems())
def test_작업_트리에서도_가드_모듈을_가져오거나_실행하는_heredoc은_거부한다(source_tree, stem, body):
    # given
    event = bash_event(f"python3 - <<'EOF'\n{body.format(stem=stem)}EOF\n", cwd=source_tree)
    # when
    output = guard.handle(event, "claude")
    # then
    assert decision_of(output) == "deny"


@pytest.mark.parametrize("template", [
    "cat scripts/{stem}.py",
    "rg {stem} scripts/",
    "sed -n 1,20p scripts/{stem}.py",
])
@pytest.mark.parametrize("stem", guard_stems())
def test_가드_모듈을_읽기만_하는_명령은_거부하지_않는다(state, fake_bin, stem, template):
    # given
    event = bash_event(template.format(stem=stem), cwd=state)
    # when
    output = guard.handle(event, "codex")
    # then
    assert output is None
