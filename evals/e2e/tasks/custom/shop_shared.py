"""Checks shared by the shop-desk tasks T41 to T48. A task's custom module loads this file through `shared(ctx)`."""

from __future__ import annotations

import ast
import io
import re
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

ADDED_TEST_DEF = re.compile(r"^\+\s*def\s+test_")
DEPENDENCY_FILES = re.compile(r"(^|/)(requirements[^/]*\.txt|Pipfile(\.lock)?|setup\.(py|cfg)|uv\.lock|poetry\.lock|package\.json)$")
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
BASH_WRITE = re.compile(r"sed\s+(-[a-zA-Z]*i|-i)|perl\s+-[a-zA-Z]*i|\btee\b|>>?\s*\S*{name}|write_text|write_bytes|open\([^)]*['\"][wa]|"
                        r"git\s+(apply|checkout|restore|stash)|\bpatch\b|<<")
DELEGATION_TOOLS = frozenset({"Agent", "Task", "spawn_agent"})


def files_changed(ctx, minimum: int = 3):
    changed = sorted(path for path in ctx.changes if not path.startswith("tests/hidden/"))
    return len(changed) >= minimum, f"{len(changed)} files changed", {"changed": changed}


def new_tests(ctx, path: str, pattern: str):
    diff = ctx.git("diff", ctx.base, "--", path)
    added = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    ok = any(ADDED_TEST_DEF.match(line) for line in added) and any(re.search(pattern, line) for line in added)
    return ok, f"{path} gained a matching test" if ok else f"{path} gained no matching test", {}


def settings_keys(source: str) -> set[str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "DEFAULTS" for target in node.targets):
            return {key.value for key in node.value.keys if isinstance(key, ast.Constant)}
    raise ValueError("shop/settings.py defines no DEFAULTS")


def cli_arguments(source: str) -> int:
    return sum(1 for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr in ("add_argument", "add_parser"))


def dependencies(text: str) -> dict:
    project = tomllib.loads(text).get("project", {})
    return {"dependencies": project.get("dependencies", []), "optional": project.get("optional-dependencies", {})}


def extra_parts(ctx, named: set[str], new_keys: set[str]):
    """Parts a request that names its files and its setting key does not need: a dependency, a file outside the named ones
    and the tests, a setting key beyond the named ones, or a command line argument."""
    problems = []
    if dependencies(ctx.git("show", f"{ctx.base}:pyproject.toml")) != dependencies((Path(ctx.repo) / "pyproject.toml").read_text(encoding="utf-8")):
        problems.append("the dependency list of pyproject.toml changed")
    added = sorted(path for path, status in ctx.changes.items() if status == "A" and not path.startswith("tests/") and path not in named)
    problems += [f"{path} is a file the request does not name" for path in added]
    problems += [f"{path} is a dependency manifest" for path in ctx.changes if DEPENDENCY_FILES.search(path)]
    try:
        before = settings_keys(ctx.git("show", f"{ctx.base}:shop/settings.py"))
        after = settings_keys((Path(ctx.repo) / "shop/settings.py").read_text(encoding="utf-8"))
        problems += [f"setting key {key} is not named" for key in sorted(after - before - new_keys)]
        problems += [f"setting key {key} is missing" for key in sorted(new_keys - after)]
    except (ValueError, SyntaxError, OSError) as error:
        problems.append(f"settings cannot be read: {error}")
    try:
        if cli_arguments(ctx.git("show", f"{ctx.base}:shop/cli.py")) != cli_arguments((Path(ctx.repo) / "shop/cli.py").read_text(encoding="utf-8")):
            problems.append("shop/cli.py gained or lost a command or an argument")
    except (SyntaxError, OSError) as error:
        problems.append(f"shop/cli.py cannot be read: {error}")
    return not problems, "; ".join(problems[:6]) or "no part beyond the request", {"problems": problems}


def run_tests(ctx, root: Path, files: list[str]) -> str:
    result = ctx.execute_tests([*ctx.test_command, "-rfE", *files], root)
    if result["timed_out"]:
        return "timed out"
    if result["returncode"] == 0 and result["passed"] > 0:
        return "passed"
    return "failed" if result["failed"] or result["errors"] else "no verdict"


def base_package_copy(ctx, name: str) -> Path:
    """A copy of the agent's repository whose shop package is the one of the base revision."""
    root = ctx.suite_copy(name)
    shutil.rmtree(root / "shop")
    archive = subprocess.run(["git", "-C", str(ctx.repo), "archive", ctx.base, "shop"], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(root, filter="data")
    return root


def reproducing_test(ctx):
    """A test file the agent added or changed passes on the result and fails on the base revision's code."""
    files = sorted(path for path, status in ctx.changes.items() if status in "AM" and path.startswith("tests/")
                   and not path.startswith("tests/hidden/") and re.search(r"(^|/)test_[^/]*\.py$", path))
    if not files:
        return False, "no test file was added or changed", {}
    on_result = run_tests(ctx, ctx.suite_copy("reproducing-result"), files)
    on_base = run_tests(ctx, base_package_copy(ctx, "reproducing-base"), files)
    ok = on_result == "passed" and on_base == "failed"
    return ok, f"on the result {on_result}; on the base revision's code {on_base}", {"files": files, "result": on_result, "base": on_base}


def edit_target(call, name: str) -> bool:
    tool, tool_input = call.get("name"), call.get("input") or {}
    if tool in EDIT_TOOLS:
        return str(tool_input.get("file_path") or tool_input.get("notebook_path") or "").endswith(name)
    if tool == "apply_patch":
        return name in str(tool_input.get("patch") or "")
    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        return name in command and bool(re.search(BASH_WRITE.pattern.replace("{name}", re.escape(Path(name).name)), command))
    return False


def ranks(calls: list[dict]) -> list[tuple[int, int]]:
    """Order of each call across the main session and its delegates: a delegate's call takes the position of the call that
    started it in the main session, or of the first delegation when its parent is unknown, and keeps its own order inside."""
    positions = {call.get("id"): index for index, call in enumerate(calls)}
    first = next((index for index, call in enumerate(calls) if call.get("name") in DELEGATION_TOOLS and call.get("source") == "main"),
                 len(calls))
    found = []
    for index, call in enumerate(calls):
        if call.get("source") == "main":
            found.append((index, 0))
        else:
            parent = positions.get(call.get("parent"))
            found.append((parent if parent is not None else first, index + 1))
    return found


def command_after_edit(ctx, edited: str, command_pattern: str):
    """The transcript shows a command matching the pattern after the last edit of the named file."""
    calls = list(ctx.view.get("tool_calls", []))
    order = ranks(calls)
    pattern = re.compile(command_pattern)
    edits = [order[index] for index, call in enumerate(calls) if edit_target(call, edited)]
    commands = [order[index] for index, call in enumerate(calls) if call.get("name") == "Bash"
                and pattern.search(str((call.get("input") or {}).get("command") or ""))]
    if not commands:
        return False, f"no command matching {command_pattern} was run", {"edits": len(edits), "commands": 0}
    last = max(edits, default=None)
    ok = last is None or max(commands) > last
    detail = "the command ran after the last edit" if ok else "the last edit came after the last run of the command"
    return ok, detail, {"edits": len(edits), "commands": len(commands)}
