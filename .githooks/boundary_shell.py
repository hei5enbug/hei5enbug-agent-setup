"""Split a shell command into segments and recognize the git and gh commands that publish content."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    text: str
    line: int
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class Target:
    tool: str
    kind: str
    git_dirs: tuple[str, ...]
    git_config: tuple[str, ...]
    repo: str | None
    files: tuple[str, ...]
    options: tuple[tuple[str, str | None], ...]
    positionals: tuple[str, ...]

    def has_option(self, *names: str) -> bool:
        return any(name in names for name, _value in self.options)


WRAPPERS = frozenset(
    {"command", "builtin", "exec", "nohup", "time", "sudo", "env", "nice", "{", "}", "!", "if", "then",
     "else", "elif", "do", "while", "until"}
)
OPTION_WRAPPERS = frozenset({"sudo", "env", "nice"})
SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELL_C_FLAG = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
HEREDOC_STOPS = " \t\n;|&()<>"

GIT_VALUE_GLOBALS = frozenset({"--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"})
COMMIT_VALUES = frozenset(
    {"-m", "--message", "-F", "--file", "-C", "-c", "--reuse-message", "--reedit-message", "-t", "--template",
     "--author", "--date", "--cleanup", "--fixup", "--squash", "--pathspec-from-file", "--trailer"}
)
TAG_VALUES = frozenset(
    {"-m", "--message", "-F", "--file", "-u", "--local-user", "--contains", "--no-contains", "--points-at",
     "--merged", "--no-merged", "--sort", "--format", "--cleanup"}
)
TAG_READ_ONLY = frozenset(
    {"-d", "--delete", "-l", "--list", "-v", "--verify", "--contains", "--no-contains", "--points-at",
     "--merged", "--no-merged"}
)
TAG_CREATE_FLAGS = frozenset({"-a", "--annotate", "-s", "--sign", "-m", "--message", "-F", "--file", "-u",
                              "--local-user"})
PUSH_VALUES = frozenset({"--repo", "-o", "--push-option", "--receive-pack", "--exec"})
GH_VALUES = frozenset(
    {"-R", "--repo", "-t", "--title", "-b", "--body", "-F", "--body-file", "--notes-file", "-n", "--notes",
     "-f", "--field", "--raw-field", "--input", "-X", "--method", "-H", "--header", "-q", "--jq", "--hostname"}
)
GH_WRITES = {
    "issue": frozenset({"create", "edit", "comment"}),
    "pr": frozenset({"create", "edit", "comment", "review"}),
    "release": frozenset({"create", "edit"}),
}
GH_FILE_OPTIONS = frozenset({"-F", "--body-file", "--notes-file"})
GH_FIELD_OPTIONS = frozenset({"-f", "-F", "--field", "--raw-field"})
GH_WRITE_METHODS = frozenset({"POST", "PATCH", "PUT"})
API_REPO = re.compile(r"^/?repos/([^/]+)/([^/]+)")


class _Splitter:
    def __init__(self, command: str, base_line: int) -> None:
        self.command = command
        self.line = base_line
        self.start = base_line
        self.head: list[str] = []
        self.full: list[str] = []
        self.pending: list[tuple[str, bool]] = []
        self.segments: list[Segment] = []
        self.i = 0

    def emit(self, text: str, to_head: bool = True) -> None:
        if not self.full and not text.strip():
            self.line += text.count("\n")
            return
        if not self.full:
            self.start = self.line
        self.full.append(text)
        if to_head:
            self.head.append(text)
        self.line += text.count("\n")

    def flush(self) -> None:
        text = "".join(self.full).strip()
        tokens = tokenize("".join(self.head))
        if text and tokens:
            self.segments.append(Segment(text, self.start, tokens))
        self.head = []
        self.full = []

    def separator_length(self) -> int:
        c, nxt, prev = self.command[self.i], self.command[self.i + 1 : self.i + 2], self.command[self.i - 1 : self.i]
        if self.command.startswith(("&&", "||", "|&"), self.i):
            return 2
        if c in ";|()`":
            return 1
        if c == "&" and prev not in "<>" and nxt != ">":
            return 1
        return 0

    def heredoc(self) -> bool:
        cmd, j = self.command, self.i + 2
        strip = cmd.startswith("-", j)
        j += 1 if strip else 0
        while j < len(cmd) and cmd[j] in " \t":
            j += 1
        if j < len(cmd) and cmd[j] in "'\"":
            end = cmd.find(cmd[j], j + 1)
            if end == -1:
                return False
            delimiter, stop = cmd[j + 1 : end], end + 1
        else:
            stop = j
            while stop < len(cmd) and cmd[stop] not in HEREDOC_STOPS:
                stop += 1
            delimiter = cmd[j:stop].replace("\\", "")
        if not delimiter:
            return False
        self.emit(cmd[self.i : stop])
        self.pending.append((delimiter, strip))
        self.i = stop
        return True

    def newline(self) -> None:
        if not self.pending:
            self.flush()
            self.line += 1
            self.i += 1
            return
        self.emit("\n", to_head=False)
        self.i += 1
        for delimiter, strip in self.pending:
            self.read_body(delimiter, strip)
        self.pending = []
        self.flush()

    def read_body(self, delimiter: str, strip: bool) -> None:
        cmd = self.command
        while self.i < len(cmd):
            end = cmd.find("\n", self.i)
            end = len(cmd) if end == -1 else end
            row = cmd[self.i : end]
            self.emit(row + "\n", to_head=False)
            self.i = end + 1
            if (row.lstrip("\t") if strip else row) == delimiter:
                return

    def run(self) -> tuple[Segment, ...]:
        cmd, quote = self.command, ""
        while self.i < len(cmd):
            c = cmd[self.i]
            if c == "\\" and quote != "'" and self.i + 1 < len(cmd):
                self.emit(cmd[self.i : self.i + 2])
                self.i += 2
            elif quote:
                self.emit(c)
                quote = "" if c == quote else quote
                self.i += 1
            elif c in "'\"":
                quote = c
                self.emit(c)
                self.i += 1
            elif c == "#" and (self.i == 0 or cmd[self.i - 1] in " \t\n;|&()"):
                end = cmd.find("\n", self.i)
                self.i = len(cmd) if end == -1 else end
            elif cmd.startswith("<<", self.i) and not cmd.startswith("<<<", self.i) and self.heredoc():
                continue
            elif c == "\n":
                self.newline()
            elif self.separator_length():
                self.flush()
                self.i += self.separator_length()
            else:
                self.emit(c)
                self.i += 1
        self.flush()
        return tuple(self.segments)


def tokenize(text: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(text))
    except ValueError:
        return tuple(text.split())


def split_segments(command: str, base_line: int = 1) -> tuple[Segment, ...]:
    return _Splitter(command, base_line).run()


def strip_prefix(tokens: list[str] | tuple[str, ...]) -> list[str]:
    words = list(tokens)
    while words:
        head = words[0]
        if ASSIGNMENT.match(head) or head in WRAPPERS:
            words = words[1:]
            while words and head in OPTION_WRAPPERS and (words[0].startswith("-") or ASSIGNMENT.match(words[0])):
                words = words[1:]
        else:
            break
    return words


def shell_payload(tokens: list[str] | tuple[str, ...]) -> str | None:
    words = strip_prefix(tokens)
    if not words or os.path.basename(words[0]) not in SHELLS:
        return None
    for index, word in enumerate(words[1:], start=1):
        if SHELL_C_FLAG.match(word):
            return words[index + 1] if index + 1 < len(words) else None
    return None


def change_dir(tokens: list[str] | tuple[str, ...]) -> str | None:
    words = strip_prefix(tokens)
    if not words or words[0] not in ("cd", "pushd"):
        return None
    args = iter(words[1:])
    for arg in args:
        if arg == "--":
            return next(args, None)
        if arg == "-":
            return None
        if not arg.startswith("-"):
            return arg
    return None


def parse_options(
    args: list[str], takes_value: frozenset[str]
) -> tuple[tuple[tuple[str, str | None], ...], tuple[str, ...]]:
    options: list[tuple[str, str | None]] = []
    positionals: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        index += 1
        if token == "--":
            positionals.extend(args[index:])
            break
        if token.startswith("--"):
            name, equals, value = token.partition("=")
            if name in takes_value and not equals and index < len(args):
                value, index = args[index], index + 1
            options.append((name, value if name in takes_value else None))
        elif token.startswith("-") and len(token) > 1:
            for offset, char in enumerate(token[1:], start=1):
                name = "-" + char
                if name in takes_value:
                    value = token[offset + 1 :]
                    if not value and index < len(args):
                        value, index = args[index], index + 1
                    options.append((name, value or None))
                    break
                options.append((name, None))
        else:
            positionals.append(token)
    return tuple(options), tuple(positionals)


def option_values(options: tuple[tuple[str, str | None], ...], *names: str) -> tuple[str, ...]:
    return tuple(value for name, value in options if name in names and value is not None)


def classify(tokens: list[str] | tuple[str, ...]) -> Target | None:
    words = strip_prefix(tokens)
    if not words:
        return None
    name = os.path.basename(words[0])
    if name == "git":
        return _classify_git(words[1:])
    if name == "gh":
        return _classify_gh(words[1:])
    return None


def _classify_git(args: list[str]) -> Target | None:
    dirs: list[str] = []
    config: list[str] = []
    index = 0
    while index < len(args) and args[index].startswith("-"):
        flag = args[index]
        if flag in ("-C", "-c") and index + 1 < len(args):
            (dirs if flag == "-C" else config).append(args[index + 1])
            index += 2
        else:
            index += 2 if flag in GIT_VALUE_GLOBALS else 1
    if index >= len(args):
        return None
    sub, rest = args[index], args[index + 1 :]
    values = {"commit": COMMIT_VALUES, "tag": TAG_VALUES, "push": PUSH_VALUES}.get(sub)
    if values is None:
        return None
    options, positionals = parse_options(rest, values)
    names = {name for name, _value in options}
    if sub == "tag" and (names & TAG_READ_ONLY or not (names & TAG_CREATE_FLAGS or positionals)):
        return None
    files = option_values(options, "-F", "--file") if sub in ("commit", "tag") else ()
    return Target("git", sub, tuple(dirs), tuple(config), None, files, options, positionals)


def _gh_files(group: str, options: tuple[tuple[str, str | None], ...]) -> tuple[str, ...]:
    if group != "api":
        return option_values(options, *GH_FILE_OPTIONS)
    inputs = option_values(options, "--input")
    fields = option_values(options, *GH_FIELD_OPTIONS)
    attached = tuple(value.partition("=")[2][1:] for value in fields if value.partition("=")[2].startswith("@"))
    return tuple(path for path in inputs + attached if path != "-")


def _classify_gh(args: list[str]) -> Target | None:
    options, positionals = parse_options(args, GH_VALUES)
    if not positionals:
        return None
    group = positionals[0]
    repo = next(iter(option_values(options, "-R", "--repo")), None)
    if group in GH_WRITES:
        if len(positionals) < 2 or positionals[1] not in GH_WRITES[group]:
            return None
    elif group == "api":
        methods = option_values(options, "-X", "--method")
        method = methods[-1].upper() if methods else None
        has_body = bool(option_values(options, *GH_FIELD_OPTIONS, "--input"))
        if method not in GH_WRITE_METHODS and not (method is None and has_body):
            return None
        endpoint = API_REPO.match(positionals[1]) if len(positionals) > 1 else None
        repo = repo or (f"{endpoint.group(1)}/{endpoint.group(2)}" if endpoint else None)
    else:
        return None
    return Target("gh", "gh-write", (), (), repo, _gh_files(group, options), options, positionals)


def normalize_repo(spec: str) -> str | None:
    cleaned = spec.strip().replace(":", "/").removesuffix(".git").rstrip("/")
    parts = [part for part in cleaned.split("/") if part]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else None
