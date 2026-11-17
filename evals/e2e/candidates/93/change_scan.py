#!/usr/bin/env python3
"""List what a change did to the contracts, literals, and failure handlers of the Python code it touched.

Prints one JSON object with three lists, each entry a place to look at and none a verdict. `contracts` holds each function or class
that exists at the base revision and whose parameters, return expressions, or fields changed or that was removed, with its callers
in files the change did not touch. `literals` holds each number or string literal the change added that the working tree holds in
another place too. `handlers` holds each exception handler the change added that never re-raises and only assigns or returns
constants. Test files are not scanned. A change with none of these prints three empty lists.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator

TEST_PATH = re.compile(r"(?:^|/)(?:tests?/|test_[^/]*\.py$|[^/]*_test\.py$|conftest\.py$)")
MIN_INT = 10
MIN_TEXT = 4


class GitError(Exception):
    pass


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise GitError(done.stderr.strip() or f"git {args[0]} failed")
    return done.stdout


def parse(text: str | None) -> ast.Module | None:
    try:
        return ast.parse(text) if text is not None else None
    except SyntaxError:
        return None


def python_files(repo: Path) -> list[str]:
    listed = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.py").split("\0")
    return sorted(path for path in listed if path and (repo / path).is_file())


def changes(repo: Path, base: str) -> dict[str, str]:
    """Each changed path of the working tree against the base revision with its status letter; new untracked files are `A`."""
    found = {}
    for line in git(repo, "diff", "--name-status", "--no-renames", base).splitlines():
        status, _, path = line.partition("\t")
        found[path] = status[:1]
    for path in git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0"):
        if path:
            found[path] = "A"
    return {path: status for path, status in found.items() if path.endswith(".py") and not TEST_PATH.search(path)}


def base_text(repo: Path, base: str, path: str) -> str | None:
    try:
        return git(repo, "show", f"{base}:{path}")
    except GitError:
        return None


def now_text(repo: Path, path: str) -> str | None:
    target = repo / path
    return target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None


def definitions(tree: ast.Module | None) -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}

    def walk(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found[prefix + node.name] = node
                if isinstance(node, ast.ClassDef):
                    walk(node.body, f"{prefix}{node.name}.")

    if tree is not None:
        walk(tree.body, "")
    return found


def contract(node: ast.AST) -> tuple:
    """What callers and consumers depend on: parameters, the return annotation and expressions, or a class's bases and fields."""
    if isinstance(node, ast.ClassDef):
        fields = [ast.dump(item) for item in node.body if isinstance(item, ast.AnnAssign)]
        return (tuple(ast.dump(base) for base in node.bases), tuple(fields))
    returns = ast.dump(node.returns) if node.returns else ""
    values = sorted(ast.dump(item.value) if item.value else "" for item in ast.walk(node) if isinstance(item, ast.Return))
    return (ast.dump(node.args), returns, tuple(values))


def references(tree: ast.Module | None, name: str) -> list[int]:
    lines = []
    for node in ast.walk(tree) if tree is not None else ():
        if (isinstance(node, ast.Name) and node.id == name) or (isinstance(node, ast.Attribute) and node.attr == name) \
                or (isinstance(node, ast.alias) and node.name == name):
            lines.append(getattr(node, "lineno", 0))
    return sorted(set(lines))


def contract_entries(repo: Path, base: str, changed: dict[str, str]) -> list[dict]:
    untouched = [path for path in python_files(repo) if path not in changed]
    trees = {path: parse(now_text(repo, path)) for path in untouched}
    entries = []
    for path, status in sorted(changed.items()):
        if status == "A":
            continue
        before, after = definitions(parse(base_text(repo, base, path))), definitions(parse(now_text(repo, path)))
        for qualname, node in before.items():
            kind = "removed" if qualname not in after else "changed" if contract(node) != contract(after[qualname]) else None
            if kind:
                name = qualname.rsplit(".", 1)[-1]
                callers = [f"{other}:{line}" for other, tree in trees.items() for line in references(tree, name)]
                entries.append({"definition": f"{path}:{qualname}", "kind": kind, "callers": callers})
    return entries


def literals(tree: ast.Module | None) -> Iterator[tuple[object, int]]:
    for node in ast.walk(tree) if tree is not None else ():
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body \
                and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            node.body[0].value.value = None
    for node in ast.walk(tree) if tree is not None else ():
        if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
            continue
        value = node.value
        if isinstance(value, float) or (isinstance(value, int) and abs(value) >= MIN_INT) \
                or (isinstance(value, str) and len(value) >= MIN_TEXT and not any(char.isspace() for char in value)):
            yield value, node.lineno


def literal_entries(repo: Path, base: str, changed: dict[str, str]) -> list[dict]:
    sites: dict[object, list[str]] = {}
    for path in python_files(repo):
        if not TEST_PATH.search(path):
            for value, line in literals(parse(now_text(repo, path))):
                sites.setdefault(value, []).append(f"{path}:{line}")
    entries = []
    for path, status in sorted(changed.items()):
        if status == "D":
            continue
        before = Counter(value for value, _ in literals(parse(base_text(repo, base, path))))
        now = Counter(value for value, _ in literals(parse(now_text(repo, path))))
        for value in sorted((value for value in now if now[value] > before[value]), key=repr):
            if len(sites.get(value, [])) > 1:
                entries.append({"added_in": path, "literal": value, "also_at": sites[value]})
    return entries


def swallows(handler: ast.ExceptHandler) -> bool:
    if any(isinstance(node, ast.Raise) for node in ast.walk(handler)):
        return False
    simple = (ast.Pass, ast.Continue, ast.Break)
    for statement in handler.body:
        value = getattr(statement, "value", None)
        constant = value is None or isinstance(value, ast.Constant)
        if not (isinstance(statement, simple) or (isinstance(statement, (ast.Return, ast.Assign, ast.Expr)) and constant)):
            return False
    return True


def handler_entries(repo: Path, base: str, changed: dict[str, str]) -> list[dict]:
    entries = []
    for path, status in sorted(changed.items()):
        if status == "D":
            continue
        known = Counter(ast.dump(node) for node in ast.walk(parse(base_text(repo, base, path)) or ast.Module([], []))
                        if isinstance(node, ast.ExceptHandler))
        for node in ast.walk(parse(now_text(repo, path)) or ast.Module([], [])):
            if isinstance(node, ast.ExceptHandler):
                key = ast.dump(node)
                if known[key] > 0:
                    known[key] -= 1
                elif swallows(node):
                    entries.append({"at": f"{path}:{node.lineno}", "catches": ast.unparse(node.type) if node.type else "everything",
                                    "body": "; ".join(ast.unparse(item) for item in node.body)})
    return entries


def scan(repo: Path, base: str) -> dict[str, list[dict]]:
    changed = changes(repo, base)
    return {"contracts": contract_entries(repo, base, changed), "literals": literal_entries(repo, base, changed),
            "handlers": handler_entries(repo, base, changed)}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", help="the base revision of the change")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="the repository, the current folder by default")
    args = parser.parse_args(argv)
    try:
        result = scan(args.repo, args.base)
    except GitError as error:
        print(f"change_scan: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
