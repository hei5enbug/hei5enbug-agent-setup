"""Agent hook: block a shell command that would publish content breaking the public boundary.

The module imports only what the fast path needs; everything else loads once a git or gh word appears.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import replace
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boundary_plugins import WordSources
    from boundary_shell import Segment, Target

SHELL_TOOLS = frozenset({"Bash", "shell", "exec_command", "local_shell", "shell_command"})
GIT_OR_GH = re.compile(r"\b(?:git|gh)\b")
BLOCK_EXIT = 2
GH_REPO_VARIABLE = "GH_REPO"
COMMAND_LABEL = "command"
STDIN_OPAQUE = "the body comes from a command whose output cannot be checked; pass it in a heredoc or a file"
UNRESOLVED_GIT_DIR = "the git directory the command sets cannot be resolved; set it to a literal path"
GIT_DIR_VARIABLE = "GIT_DIR"
GIT_WORK_TREE_VARIABLE = "GIT_WORK_TREE"
UNRESOLVED = re.compile(r"[$`]")
GLOB_CHARACTERS = re.compile(r"[*?\[]")
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


def iter_segments(command: str, base_line: int = 1, depth: int = 0) -> Iterator[Segment]:
    import boundary_shell

    for segment in boundary_shell.split_segments(command, base_line):
        yield replace(segment, depth=depth)
        payload = boundary_shell.shell_payload(segment.tokens)
        if payload:
            yield from iter_segments(payload, segment.line, depth + 1)


def assignments(tokens: tuple[str, ...]) -> dict[str, str] | None:
    """The variables a segment made only of `NAME=value` words, optionally after `export`, assigns."""
    words = tokens[1:] if tokens[:1] == ("export",) else tokens
    matches = [ASSIGNMENT.match(word) for word in words]
    if not words or not all(matches):
        return None
    return {match.group(1): match.group(2) for match in matches}


def inline_assignments(tokens: tuple[str, ...]) -> dict[str, str]:
    """The `NAME=value` words that lead a command, directly or after `env`, `sudo`, and similar wrappers."""
    import boundary_shell

    found: dict[str, str] = {}
    words = list(tokens)
    while words:
        head = words[0]
        match = ASSIGNMENT.match(head)
        if match is None and head not in boundary_shell.WRAPPERS:
            break
        words = words[1:]
        if match is not None:
            found[match.group(1)] = match.group(2)
        while match is None and words and head in boundary_shell.OPTION_WRAPPERS:
            option = ASSIGNMENT.match(words[0])
            if option is None and not words[0].startswith("-"):
                break
            if option is not None:
                found[option.group(1)] = option.group(2)
            words = words[1:]
    return found


def expand(text: str, variables: dict[str, str]) -> str:
    """`$NAME` and `${NAME}` replaced from `variables`; text with an unknown variable or a substitution stays as written."""
    if "$(" in text or "`" in text:
        return text
    names = [first or second for first, second in VARIABLE.findall(text)]
    if any(name not in variables for name in names):
        return text
    return VARIABLE.sub(lambda match: variables[match.group(1) or match.group(2)], text)


def expand_text(text: str, variables: dict[str, str]) -> str:
    """`$NAME` and `${NAME}` replaced where `variables` knows the name; other text stays as written."""
    return VARIABLE.sub(lambda match: variables.get(match.group(1) or match.group(2), match.group(0)), text)


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


def push_destinations(target: Target, where: str, variables: dict[str, str]) -> list[str] | None:
    """The URLs a push reaches, or None when its destination holds a variable or substitution that cannot be resolved."""
    import boundary_git

    named = [value for name, value in target.options if name == "--repo" and value]
    word = expand_text(named[-1] if named else target.positionals[0] if target.positionals else "", variables)
    if UNRESOLVED.search(word):
        return None
    word = word or boundary_git.default_push_remote(where, target.git_config)
    return boundary_git.remote_urls(where, word, target.git_config)


class Scope:
    """Which git and gh writes are checked, and the private words to check them against.

    In project mode the checkout at root is protected too; plugin declarations are read on first use only.
    """

    def __init__(self, root: str, project: bool, environ: dict[str, str] | None = None) -> None:
        self.root = root
        self.project = project
        self.environ = dict(os.environ) if environ is None else environ

    @cached_property
    def roots(self) -> tuple[Path, ...]:
        import boundary_plugins

        return boundary_plugins.installed_roots(self.environ, (Path(self.root),))

    @cached_property
    def repositories(self) -> frozenset[str]:
        import boundary_plugins

        declared = boundary_plugins.protected_repositories(self.roots)
        own = origin_repo(self.root) if self.project else None
        return declared | {own} if own else declared

    @cached_property
    def sources(self) -> WordSources:
        import boundary_plugins

        return boundary_plugins.word_sources(self.roots, self.environ, Path(self.root))

    def contains(
        self, target: Target, directory: str, variables: dict[str, str], overrides: dict[str, str] | None = None
    ) -> bool:
        import boundary_git
        import boundary_shell

        if target.tool == "git":
            where = fold_dirs(directory, target.git_dirs)
            if target.kind == "push":
                return self.contains_push(target, where, variables, overrides or {})
            return self.contains_git(where, overrides or {})
        named = target.repo or variables.get(GH_REPO_VARIABLE)
        if named:
            named = expand(named, variables)
            spec = boundary_shell.normalize_repo(named)
            return spec is None or UNRESOLVED.search(named) is not None or spec in self.repositories
        spec = origin_repo(directory)
        return spec is not None and spec in self.repositories

    def contains_push(self, target: Target, where: str, variables: dict[str, str], overrides: dict[str, str]) -> bool:
        """A push is checked when any destination it reaches is protected, or in project mode when its checkout is."""
        import boundary_git

        if self.project and self.contains_git(where, overrides):
            return True
        with boundary_git.repository_environment(overrides):
            if boundary_git.try_git(where, "rev-parse", "--absolute-git-dir") is None:
                return False
            destinations = push_destinations(target, where, variables)
        return destinations is None or any(self.names_protected(url) for url in destinations)

    def names_protected(self, url: str) -> bool:
        import boundary_shell

        return boundary_shell.normalize_repo(url) in self.repositories

    def contains_git(self, where: str, overrides: dict[str, str]) -> bool:
        import boundary_git

        if not overrides:
            top = boundary_git.toplevel(where)
            if top is None:
                return False
            same = os.path.realpath(top) == os.path.realpath(self.root)
            return (self.project and same) or origin_repo(str(top)) in self.repositories
        own = boundary_git.try_git(self.root, "rev-parse", "--absolute-git-dir") if self.project else None
        with boundary_git.repository_environment(overrides):
            current = boundary_git.try_git(where, "rev-parse", "--absolute-git-dir")
            if current is None:
                return False
            same = own is not None and os.path.realpath(current) == os.path.realpath(own)
            return same or origin_repo(where) in self.repositories


def repository_selection(target: Target, inline: dict[str, str], variables: dict[str, str]) -> tuple[str, ...]:
    """The paths a git command uses only to pick its repository: -C, --git-dir, --work-tree, GIT_DIR, GIT_WORK_TREE."""
    options = (target.git_dir, target.work_tree, inline.get(GIT_DIR_VARIABLE), inline.get(GIT_WORK_TREE_VARIABLE))
    return target.git_dirs + tuple(expand_text(value, variables) for value in options if value)


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
        findings.extend(boundary_git.range_findings(top, ["HEAD", "--not", "--remotes"], words))
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


def git_findings(target: Target, directory: str, words, overrides: dict[str, str] | None = None) -> list[str]:
    import boundary_git

    where = fold_dirs(directory, target.git_dirs)
    top = boundary_git.toplevel(where) or (Path(where) if overrides else None)
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


def read_stdin_file(base: str, name: str) -> str | None:
    """A file a pipeline or redirect feeds to stdin; one that does not exist is skipped, since nothing would be read."""
    if not os.path.exists(resolve_dir(base, name)):
        return None
    return read_named_file(base, name)


def expand_globs(base: str, name: str) -> list[str]:
    """The files a producer word names: a wildcard pattern expands as the shell would, other words stay as written."""
    if not GLOB_CHARACTERS.search(name):
        return [name]
    import glob

    matches = sorted(glob.glob(os.path.expanduser(name), root_dir=base))
    return [match for match in matches if os.path.isfile(resolve_dir(base, match))] or [name]


def stdin_findings(segment: Segment, upstream: list[Segment], directory: str, words, variables: dict[str, str]) -> list[str]:
    """Scan what reaches a write's stdin: earlier pipeline segments, the files they or a `<` redirect read."""
    import boundary_git
    import boundary_shell
    from public_boundary import scan_text

    findings: list[str] = []
    names = list(boundary_shell.redirect_files(segment.tokens))
    for producer in upstream:
        text = expand_text(producer.text, variables)
        findings.extend(scan_text(COMMAND_LABEL, "\n" * (producer.line - 1) + text, words=words))
        names.extend(boundary_shell.redirect_files(producer.tokens))
        produced = boundary_shell.producer_files(producer.tokens)
        if produced is None:
            raise boundary_git.CheckError(STDIN_OPAQUE)
        names.extend(item for word in produced for item in expand_globs(directory, expand(word, variables)))
    for name in (expand(item, variables) for item in names):
        content = read_stdin_file(directory, name)
        if content is not None:
            findings.extend(scan_text(name, content, words=words))
    return findings


def pipeline_before(segments: list[Segment], index: int) -> list[Segment]:
    """The segments whose output feeds segment `index`, nearest first, skipping payloads nested inside them."""
    chain: list[Segment] = []
    current, position = segments[index], index - 1
    while current.piped:
        while position >= 0 and segments[position].depth > current.depth:
            position -= 1
        if position < 0 or segments[position].depth < current.depth:
            break
        current = segments[position]
        chain.append(current)
        position -= 1
    return chain


def target_findings(
    segment: Segment, target: Target, directory: str, words, variables: dict[str, str],
    upstream: list[Segment] | None = None, overrides: dict[str, str] | None = None, selected: tuple[str, ...] = (),
) -> list[str]:
    from public_boundary import scan_text

    where = fold_dirs(directory, target.git_dirs)
    text = blank_directory_arguments(expand_text(segment.text, variables), selected)
    findings = scan_text(COMMAND_LABEL, "\n" * (segment.line - 1) + text, words=words)
    for name in (expand(item, variables) for item in target.files if item != "-"):
        content = read_named_file(where, name)
        if content is not None:
            findings.extend(scan_text(name, content, words=words))
    if "-" in target.files:
        findings.extend(stdin_findings(segment, upstream or [], directory, words, variables))
    if target.tool == "git":
        findings.extend(git_findings(target, directory, words, overrides))
    return findings


def repository_overrides(target: Target, declared: dict[str, str], variables: dict[str, str], where: str) -> dict[str, str] | None:
    """The GIT_DIR and GIT_WORK_TREE that govern a git write, from its options or the command's own assignments.

    Returns None when a value still holds an unexpanded variable or substitution.
    """
    chosen: dict[str, str] = {}
    for variable, option in ((GIT_DIR_VARIABLE, target.git_dir), (GIT_WORK_TREE_VARIABLE, target.work_tree)):
        value = option if option is not None else declared.get(variable)
        if not value:
            continue
        value = expand_text(value, variables)
        if UNRESOLVED.search(value):
            return None
        chosen[variable] = resolve_dir(where, value)
    return chosen


def check_command(command: str, cwd: str, scope: Scope) -> tuple[list[str], list[str], bool]:
    """Return the findings, the problems, and whether a write to a protected repository was scanned."""
    import boundary_git
    import boundary_shell

    findings: list[str] = []
    problems: list[str] = []
    scanned = False
    directory = cwd
    variables = dict(os.environ)
    declared: dict[str, str] = {}
    segments = list(iter_segments(command))
    for index, segment in enumerate(segments):
        assigned = assignments(segment.tokens)
        if assigned is not None:
            expanded = {name: expand(value, variables) for name, value in assigned.items()}
            variables.update(expanded)
            declared.update(expanded)
            continue
        changed = boundary_shell.change_dir(segment.tokens)
        if changed is not None:
            changed = expand(changed, variables)
            directory = directory if re.search(r"[$`]", changed) else resolve_dir(directory, changed)
            continue
        target = boundary_shell.classify(segment.tokens)
        if target is None:
            continue
        inline = {name: expand(value, variables) for name, value in inline_assignments(segment.tokens).items()}
        local = {**variables, **inline}
        target = replace(
            target,
            git_dirs=tuple(expand_text(item, local) for item in target.git_dirs),
            repo=expand(target.repo, local) if target.repo else None,
            git_dir=expand_text(target.git_dir, local) if target.git_dir else None,
            work_tree=expand_text(target.work_tree, local) if target.work_tree else None,
        )
        overrides = repository_overrides(target, {**declared, **inline}, local, fold_dirs(directory, target.git_dirs))
        if overrides is None:
            scanned = True
            problems.append(UNRESOLVED_GIT_DIR)
            continue
        if not scope.contains(target, directory, local, overrides):
            continue
        scanned = True
        try:
            with boundary_git.repository_environment(overrides):
                findings.extend(
                    target_findings(
                        segment, target, directory, scope.sources.words, local,
                        pipeline_before(segments, index), overrides, repository_selection(target, inline, local),
                    )
                )
        except boundary_git.CheckError as error:
            problems.append(str(error))
        except Exception as error:
            problems.append(f"unexpected {type(error).__name__}")
    if scanned:
        problems.extend(dict.fromkeys(scope.sources.problems))
        for note in scope.sources.notes:
            print(note, file=sys.stderr)
    return list(dict.fromkeys(findings)), problems, scanned


def notice_output(notice: str) -> str:
    return json.dumps(
        {"systemMessage": notice, "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": notice}}
    )


def run(stdin_text: str, root: str, project: bool = True) -> int:
    import boundary_plugins

    try:
        parsed = command_from(json.loads(stdin_text))
    except ValueError:
        return 0
    if parsed is None:
        return 0
    scope = Scope(root, project)
    findings, problems, scanned = check_command(*parsed, scope)
    unlisted = scanned and scope.sources.lists == 0
    if not findings and not problems:
        if unlisted:
            print(notice_output(boundary_plugins.NO_LIST_NOTICE))
        return 0
    if findings:
        print("public boundary: blocked before it ran; matched values are not shown", file=sys.stderr)
        print("\n".join(f"  {item}" for item in findings), file=sys.stderr)
    for problem in problems:
        print(f"public boundary: the command could not be checked, so it is blocked: {problem}", file=sys.stderr)
    if unlisted:
        print(boundary_plugins.NO_LIST_NOTICE, file=sys.stderr)
    return BLOCK_EXIT
