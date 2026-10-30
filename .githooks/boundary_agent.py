"""Agent hook: block a shell command that would publish content breaking the public boundary.

The module imports only what the fast path needs; everything else loads once a git or gh word appears.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boundary_shell import Segment, Target

SHELL_TOOLS = frozenset({"Bash", "shell", "exec_command", "local_shell", "shell_command"})
GIT_OR_GH = re.compile(r"\b(?:git|gh)\b")
BLOCK_EXIT = 2
COMMAND_LABEL = "command"
ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
VARIABLE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def command_from(payload: object) -> tuple[str, str] | None:
    if not isinstance(payload, dict) or payload.get("tool_name") not in SHELL_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    if not isinstance(command, str) or not GIT_OR_GH.search(command):
        return None
    cwd = payload.get("cwd")
    return command, cwd if isinstance(cwd, str) and cwd else os.getcwd()


def iter_segments(command: str, base_line: int = 1) -> Iterator[Segment]:
    import boundary_shell

    for segment in boundary_shell.split_segments(command, base_line):
        yield segment
        payload = boundary_shell.shell_payload(segment.tokens)
        if payload:
            yield from iter_segments(payload, segment.line)


def assignments(tokens: tuple[str, ...]) -> dict[str, str] | None:
    """The variables a segment made only of `NAME=value` words, optionally after `export`, assigns."""
    words = tokens[1:] if tokens[:1] == ("export",) else tokens
    matches = [ASSIGNMENT.match(word) for word in words]
    if not words or not all(matches):
        return None
    return {match.group(1): match.group(2) for match in matches}


def expand(text: str, variables: dict[str, str]) -> str:
    """`$NAME` and `${NAME}` replaced from `variables`; text with an unknown variable or a substitution stays as written."""
    if "$(" in text or "`" in text:
        return text
    names = [first or second for first, second in VARIABLE.findall(text)]
    if any(name not in variables for name in names):
        return text
    return VARIABLE.sub(lambda match: variables[match.group(1) or match.group(2)], text)


def resolve_dir(base: str, directory: str) -> str:
    return os.path.normpath(os.path.join(base, os.path.expanduser(directory)))


def fold_dirs(base: str, directories: tuple[str, ...]) -> str:
    current = base
    for directory in directories:
        current = resolve_dir(current, directory)
    return current


def origin_repo(directory: str) -> str | None:
    import boundary_git
    import boundary_shell

    url = boundary_git.try_git(directory, "remote", "get-url", "origin")
    return boundary_shell.normalize_repo(url) if url else None


def in_scope(target: Target, directory: str, root: str) -> bool:
    import boundary_git
    import boundary_shell

    if target.tool == "git":
        top = boundary_git.toplevel(fold_dirs(directory, target.git_dirs))
        return top is not None and os.path.realpath(top) == os.path.realpath(root)
    spec = boundary_shell.normalize_repo(target.repo) if target.repo else origin_repo(directory)
    return spec is not None and spec == origin_repo(root)


def blank_directory_arguments(text: str, directories: tuple[str, ...]) -> str:
    from public_boundary import HOME_PATH

    for directory in directories:
        if HOME_PATH.search(directory):
            text = text.replace(directory, "-" * len(directory), 1)
    return text


def read_named_file(base: str, name: str) -> str | None:
    import boundary_git
    from public_boundary import _decode_text

    try:
        with open(resolve_dir(base, name), "rb") as handle:
            return _decode_text(handle.read())
    except OSError as error:
        raise boundary_git.CheckError(f"{name} could not be read ({error.strerror})") from error


def push_findings(target: Target, top, words) -> list[str]:
    import boundary_git

    findings = []
    if boundary_git.has_head(top):
        findings.extend(boundary_git.range_findings(top, ["HEAD", "--not", "--remotes"], "HEAD", words))
    tags = boundary_git.local_tags(top)
    if target.has_option("--tags", "--follow-tags"):
        names = list(tags)
    else:
        refspecs = [spec for spec in target.positionals[1:] if spec != "tag"]
        names = [re.sub(r"^\+|:.*$", "", spec).removeprefix("refs/tags/") for spec in refspecs]
    for name in dict.fromkeys(names):
        if name in tags:
            findings.extend(boundary_git.tag_findings(top, name, tags[name], words))
    return findings


def git_findings(target: Target, directory: str, words) -> list[str]:
    import boundary_git

    where = fold_dirs(directory, target.git_dirs)
    top = boundary_git.toplevel(where)
    if top is None:
        raise boundary_git.CheckError("git did not report the repository")
    if target.kind == "commit":
        findings = boundary_git.staged_findings(top, words)
        if target.has_option("-a", "--all"):
            findings += boundary_git.worktree_findings(top, words)
        return findings + boundary_git.identity_findings(where, words, target.git_config)
    if target.kind == "push":
        return push_findings(target, top, words)
    return boundary_git.identity_findings(where, words, target.git_config, author=False)


def target_findings(segment: Segment, target: Target, directory: str, words, variables: dict[str, str]) -> list[str]:
    from public_boundary import scan_text

    where = fold_dirs(directory, target.git_dirs)
    text = blank_directory_arguments(segment.text, target.git_dirs)
    findings = scan_text(COMMAND_LABEL, "\n" * (segment.line - 1) + text, words=words)
    for name in (expand(item, variables) for item in target.files if item != "-"):
        content = read_named_file(where, name)
        if content is not None:
            findings.extend(scan_text(name, content, words=words))
    if target.tool == "git":
        findings.extend(git_findings(target, directory, words))
    return findings


def check_command(command: str, cwd: str, root: str) -> tuple[list[str], list[str]]:
    from pathlib import Path

    import boundary_git
    import boundary_shell
    from public_boundary import load_private_words

    findings: list[str] = []
    problems: list[str] = []
    words = None
    directory = cwd
    variables = dict(os.environ)
    for segment in iter_segments(command):
        assigned = assignments(segment.tokens)
        if assigned is not None:
            variables.update({name: expand(value, variables) for name, value in assigned.items()})
            continue
        changed = boundary_shell.change_dir(segment.tokens)
        if changed is not None:
            changed = expand(changed, variables)
            directory = directory if re.search(r"[$`]", changed) else resolve_dir(directory, changed)
            continue
        target = boundary_shell.classify(segment.tokens)
        if target is None or not in_scope(target, directory, root):
            continue
        words = load_private_words(Path(root)) if words is None else words
        try:
            findings.extend(target_findings(segment, target, directory, words, variables))
        except boundary_git.CheckError as error:
            problems.append(str(error))
        except Exception as error:
            problems.append(f"unexpected {type(error).__name__}")
    return list(dict.fromkeys(findings)), problems


def run(stdin_text: str, root: str) -> int:
    try:
        parsed = command_from(json.loads(stdin_text))
    except ValueError:
        return 0
    if parsed is None:
        return 0
    findings, problems = check_command(*parsed, root)
    if not findings and not problems:
        return 0
    if findings:
        print("public boundary: blocked before it ran; matched values are not shown", file=sys.stderr)
        print("\n".join(f"  {item}" for item in findings), file=sys.stderr)
    for problem in problems:
        print(f"public boundary: the command could not be checked, so it is blocked: {problem}", file=sys.stderr)
    return BLOCK_EXIT
