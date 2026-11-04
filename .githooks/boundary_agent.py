"""Agent hook: block a shell command that would publish content breaking the public boundary.

The module imports only what the fast path needs; everything else loads once a git or gh word appears.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boundary_plugins import WordSources
    from boundary_push import PushContext
    from boundary_shell import Segment, Target

SHELL_TOOLS = frozenset({"Bash", "shell", "exec_command", "local_shell", "shell_command"})
GIT_OR_GH = re.compile(r"\b(?:git|gh)\b")
BLOCK_EXIT = 2
GH_REPO_VARIABLE = "GH_REPO"
GH_HOST_VARIABLE = "GH_HOST"
COMMAND_LABEL = "command"
STDIN_OPAQUE = "the body comes from a command whose output cannot be checked; pass it in a heredoc or a file"
UNRESOLVED_GIT_DIR = "the git directory the command sets cannot be resolved; set it to a literal path"
UNRESOLVED_DIRECTORY = "the directory the command works in cannot be resolved; change to a literal path first"
STDIN_UNRESOLVED = "the file that feeds the body has a name that cannot be resolved; use a literal file name"
SUBSTITUTION_OPAQUE = "a body or message holds a command substitution whose output cannot be checked; use a file or a heredoc"
NOT_REGULAR = "{name} is not a regular file, so it is not read"
PLACEHOLDER = re.compile(r"\{(?:owner|repo)\}")
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


def configured_host(variables: dict[str, str]) -> str | None:
    """The host GH_HOST sets for gh, lowercased, or None when it is not set."""
    value = expand(variables.get(GH_HOST_VARIABLE, ""), variables).strip().lower()
    return value or None


def current_repo(directory: str, variables: dict[str, str]) -> tuple[str, str, str] | None:
    """The host, owner, and name of the working directory's origin; GH_HOST, when set, replaces its host."""
    import boundary_git
    import boundary_shell

    url = boundary_git.try_git(directory, "remote", "get-url", "origin")
    parts = boundary_shell.split_repo(url) if url else None
    host = configured_host(variables)
    return (host, parts[1], parts[2]) if parts and host else parts


def fill_placeholders(named: str, variables: dict[str, str], directory: str) -> str | None:
    """`{owner}` and `{repo}` in a gh repository replaced from GH_REPO or the origin, as gh does; None when neither names one."""
    import boundary_shell

    host = configured_host(variables) or boundary_shell.GITHUB_HOST
    chosen = expand(variables.get(GH_REPO_VARIABLE, ""), variables)
    if chosen:
        parts = None if UNRESOLVED.search(chosen) else boundary_shell.split_repo(chosen, host)
    else:
        parts = current_repo(directory, variables)
    if parts is None:
        return None
    host, owner, name = parts
    filled = named.replace("{owner}", owner).replace("{repo}", name)
    return filled if filled.count("/") >= 2 or host == boundary_shell.GITHUB_HOST else f"{host}/{filled}"


def push_destination(target: Target, where: str, variables: dict[str, str]) -> str | None:
    """The remote name or URL a push goes to, or None when it holds a variable or substitution that cannot be resolved."""
    import boundary_git

    named = [value for name, value in target.options if name == "--repo" and value]
    word = expand_text(named[-1] if named else target.positionals[0] if target.positionals else "", variables)
    if UNRESOLVED.search(word):
        return None
    return word or boundary_git.default_push_remote(where, target.git_config)


def push_destinations(target: Target, where: str, variables: dict[str, str]) -> list[str] | None:
    """The URLs a push reaches, or None when its destination holds a variable or substitution that cannot be resolved."""
    import boundary_git

    word = push_destination(target, where, variables)
    return None if word is None else boundary_git.remote_urls(where, word, target.git_config)


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
        candidates = [expand(named, variables)] if named else []
        host = configured_host(variables)
        if host and UNRESOLVED.search(host):
            return True
        if not candidates and not target.operand_repos:
            current = current_repo(directory, variables)
            spec = boundary_shell.normalize_repo("/".join(current)) if current else None
            return spec is not None and spec in self.repositories
        for candidate in candidates:
            if PLACEHOLDER.search(candidate):
                candidate = fill_placeholders(candidate, variables, directory)
                if candidate is None:
                    return True
            spec = boundary_shell.normalize_repo(candidate, host or boundary_shell.GITHUB_HOST)
            if spec is None or UNRESOLVED.search(candidate) or spec in self.repositories:
                return True
        return any(spec in self.repositories for spec in target.operand_repos)

    def contains_push(self, target: Target, where: str, variables: dict[str, str], overrides: dict[str, str]) -> bool:
        """A push is checked when any destination it reaches is protected, or in project mode when its checkout is."""
        import boundary_git

        if self.project and self.contains_git(where, overrides):
            return True
        with boundary_git.repository_environment(overrides):
            if boundary_git.try_git(where, "rev-parse", "--absolute-git-dir") is None:
                return False
            destinations = push_destinations(target, where, variables)
        return destinations is None or any(UNRESOLVED.search(url) or self.names_protected(url) for url in destinations)

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


def read_regular_file(path: str, name: str) -> bytes:
    """The bytes of a regular file; a pipe, device, or directory is refused without waiting on it."""
    import boundary_git

    if path == os.devnull:
        return b""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            raise boundary_git.CheckError(NOT_REGULAR.format(name=name))
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise boundary_git.CheckError(NOT_REGULAR.format(name=name))
            return handle.read()
    except OSError as error:
        raise boundary_git.CheckError(f"{name} could not be read ({error.strerror})") from error


def read_named_file(base: str, name: str) -> str | None:
    from public_boundary import _decode_text

    return _decode_text(read_regular_file(resolve_dir(base, name), name))


def git_findings(
    target: Target, directory: str, words, overrides: dict[str, str] | None = None, push: PushContext | None = None
) -> list[str]:
    import boundary_git
    import boundary_push

    where = fold_dirs(directory, target.git_dirs)
    top = boundary_git.toplevel(where) or (Path(where) if overrides else None)
    if top is None:
        raise boundary_git.CheckError("git did not report the repository")
    if target.kind == "commit":
        findings = boundary_git.staged_findings(top, words)
        if target.has_option("-a", "--all"):
            findings += boundary_git.worktree_findings(top, words)
        return findings + boundary_git.identity_findings(where, words, target.git_config)
    if target.kind == "push" and push is not None:
        return boundary_push.push_findings(target, top, fold_dirs(directory, target.git_dirs), words, push)
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


def substituted_files(texts: Iterable[str], variables: dict[str, str], base: str) -> list[str]:
    """The files that command substitutions in `texts` read, as the shell would expand them; refuses unknown output."""
    import boundary_git
    import boundary_substitution

    names: list[str] = []
    for text in texts:
        if "$(" not in text and "`" not in text:
            continue
        files = boundary_substitution.substitution_files(expand_text(text, variables))
        if files is None:
            raise boundary_git.CheckError(SUBSTITUTION_OPAQUE)
        names.extend(item for word in files for item in expand_globs(base, expand(word, variables)))
    return names


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
        names.extend(substituted_files(producer.tokens, variables, directory))
    for name in (expand(item, variables) for item in names):
        if UNRESOLVED.search(name):
            raise boundary_git.CheckError(STDIN_UNRESOLVED)
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
    protected: Callable[[str], bool] = lambda _url: False,
) -> list[str]:
    from boundary_push import PushContext
    from public_boundary import scan_text

    where = fold_dirs(directory, target.git_dirs)
    text = blank_directory_arguments(expand_text(segment.text, variables), selected)
    findings = scan_text(COMMAND_LABEL, "\n" * (segment.line - 1) + text, words=words)
    values = [value for _name, value in target.options if value]
    named = [expand(item, variables) for item in target.files if item != "-"]
    for name in named + substituted_files(values, variables, where):
        content = read_named_file(where, name)
        if content is not None:
            findings.extend(scan_text(name, content, words=words))
    if "-" in target.files:
        findings.extend(stdin_findings(segment, upstream or [], directory, words, variables))
    if target.tool == "git":
        push = PushContext(
            push_destination(target, where, variables) if target.kind == "push" else None,
            lambda word: expand_text(word, variables), protected,
        )
        findings.extend(git_findings(target, directory, words, overrides, push))
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


def expand_target(target: Target, variables: dict[str, str]) -> Target:
    """The target with the variables its repository, directories, and git configuration name replaced."""
    return replace(
        target,
        git_dirs=tuple(expand_text(item, variables) for item in target.git_dirs),
        git_config=tuple(expand_text(item, variables) for item in target.git_config),
        repo=expand(target.repo, variables) if target.repo else None,
        git_dir=expand_text(target.git_dir, variables) if target.git_dir else None,
        work_tree=expand_text(target.work_tree, variables) if target.work_tree else None,
    )


def needs_directory(target: Target, variables: dict[str, str]) -> bool:
    """Whether the repository a write reaches depends on the directory it runs in: git always, gh without a named one."""
    if target.tool == "git":
        return True
    return not (target.repo or variables.get(GH_REPO_VARIABLE) or target.operand_repos)


def check_command(command: str, cwd: str, scope: Scope) -> tuple[list[str], list[str], bool]:
    """Return the findings, the problems, and whether a write to a protected repository was scanned."""
    import boundary_git
    import boundary_shell

    findings: list[str] = []
    problems: list[str] = []
    scanned = False
    directory = cwd
    lost = False
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
            lost = UNRESOLVED.search(changed) is not None
            directory = directory if lost else resolve_dir(directory, changed)
            continue
        target = boundary_shell.classify(segment.tokens)
        if target is None:
            continue
        inline = {name: expand(value, variables) for name, value in inline_assignments(segment.tokens).items()}
        local = {**variables, **inline}
        target = expand_target(target, local)
        if any(UNRESOLVED.search(item) for item in target.git_dirs) or (lost and needs_directory(target, local)):
            scanned = True
            problems.append(UNRESOLVED_DIRECTORY)
            continue
        overrides = repository_overrides(target, {**declared, **inline}, local, fold_dirs(directory, target.git_dirs))
        if overrides is None:
            scanned = True
            problems.append(UNRESOLVED_GIT_DIR)
            continue
        if not scope.contains(target, directory, local, overrides):
            continue
        scanned = True
        if lost and target.files:
            problems.append(UNRESOLVED_DIRECTORY)
            continue
        try:
            with boundary_git.repository_environment(overrides):
                findings.extend(
                    target_findings(
                        segment, target, directory, scope.sources.words, local,
                        pipeline_before(segments, index), overrides, repository_selection(target, inline, local),
                        scope.names_protected,
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
