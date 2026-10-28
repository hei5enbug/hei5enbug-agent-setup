"""Writes confined to a temporary root, which the approval guard passes."""
import os
import re
from pathlib import Path
import approval_state
from guard_shell import SHELL_KEYWORDS
import guard_paths
from guard_paths import SHALLOW_TEMPORARY_ROOTS, _mktemp_directory, _operand_paths, _temp_path
from guard_expand import _operand_texts, _unquoted_reference


TEMP_HARMLESS = frozenset({"cat", "echo", "printf", "ls", "head", "tail", "wc", "pwd", "true", "false", "wait", "sleep",
                           "cd", "for"})
COPY_FLAGS = re.compile(r"-[RrapfinvLPHTux]+")
COPY_LONG_FLAGS = frozenset({"--recursive", "--archive", "--force", "--verbose", "--no-clobber", "--update"})


def _temp_segment(words, redirects, cwd, env):
    """The number of writes a simple command makes when every destination is inside a temporary root, else None.
    Only a few commands that cannot run anything else are judged."""
    command = list(words)
    while command and command[0] in SHELL_KEYWORDS:
        command.pop(0)
    writes = 0
    for _, operator, target in redirects:
        if ">" not in operator or target == "/dev/null" or (operator == ">&" and target in ("1", "2")):
            continue
        if not _temp_path(target, cwd, env):
            return None
        writes += 1
    if not command:
        return writes
    name, args = os.path.basename(command[0]), command[1:]
    if command[0] != name and os.path.dirname(command[0]) not in ("/bin", "/usr/bin"):
        return None
    if name in TEMP_HARMLESS:
        return writes
    operands, destinations, index = [], None, 0
    clusters = {"mkdir": "pv", "touch": "acm", "tee": "aip"}.get(name)
    longs = {"mkdir": ("--parents", "--verbose"), "touch": ("--no-create",), "tee": ("--append",)}.get(name, ())
    while index < len(args):
        arg = args[index]
        if arg == "--":
            operands.extend(args[index + 1:])
            break
        if name in ("cp", "mv") and arg in ("-t", "--target-directory") and index + 1 < len(args):
            destinations, index = [args[index + 1]], index + 2
        elif name in ("cp", "mv") and arg.startswith("--target-directory="):
            destinations, index = [arg.partition("=")[2]], index + 1
        elif name == "mkdir" and arg == "-m" and index + 1 < len(args):
            index += 2
        elif ((name in ("cp", "mv") and (COPY_FLAGS.fullmatch(arg) or arg in COPY_LONG_FLAGS))
              or (clusters and re.fullmatch(r"-[" + clusters + r"]+", arg)) or arg in longs):
            index += 1
        elif arg.startswith("-") and arg != "-":
            return None
        else:
            operands.append(arg)
            index += 1
    sources = operands
    if name in ("cp", "mv"):
        if destinations is None:
            if len(operands) < 2:
                return None
            destinations, sources = operands[-1:], operands[:-1]
    elif name in ("mkdir", "touch", "tee"):
        destinations = operands
        if name != "tee" and not operands:
            return None
    else:
        return None
    if not all(_temp_path(path, cwd, env) for path in destinations):
        return None
    if name in ("cp", "mv"):
        for destination in destinations:
            folder = Path(cwd) / os.path.expanduser(destination)
            if not folder.is_dir():
                continue
            for source in sources:
                if not source or re.search(r"[$`*?\[{]", source):
                    return None
                if not guard_paths._temporary((folder / os.path.basename(source.rstrip("/"))).resolve(), env):
                    return None
    return writes + len(destinations)


EVAL_WORKSPACE = "harness-eval"
EVAL_RUNS = "runs"


def _evaluation_scratch(covering, expanded, cwd):
    """Whether a removal target lies strictly inside the plugin's evaluation workspace, `<state root>/harness-eval`, and
    reaches neither a `runs` folder nor a path outside it. The target arrives resolved, so a symbolic link out of the
    workspace puts it outside; a glob is checked against the entries it matches."""
    try:
        root = (approval_state.state_dir().parent / EVAL_WORKSPACE).resolve()
        if not covering.relative_to(root).parts:
            return False
        matches = _operand_paths(expanded, cwd) if re.search(r"[*?\[]", expanded) else [covering]
        return all(match.relative_to(root).parts and EVAL_RUNS not in match.relative_to(root).parts
                   and _holds_no_runs_folder(match) for match in matches)
    except (ValueError, OSError, RuntimeError):
        return False


EVAL_WALK_LIMIT = 5000


def _holds_no_runs_folder(path):
    """Whether no folder named `runs` lies below an existing path; a walk that fails or passes the entry limit counts as
    finding one."""
    failed, seen = [], 0
    if not path.is_dir():
        return True
    for _, folders, files in os.walk(path, onerror=failed.append):
        seen += len(folders) + len(files)
        if failed or seen > EVAL_WALK_LIMIT or EVAL_RUNS in folders:
            return False
    return not failed


TEMPORARY_FOLDER_DEPTH = 2
_REMOVAL_TRACE = None


def _inside_temporary_root(path, extra=0):
    """Whether a resolved path, with `extra` more levels that a glob adds below it, lies strictly inside a temporary
    root and deeper than its top-level folders; the system folder `/var/folders` needs its per-user levels as well."""
    for root in guard_paths.TEMPORARY_ROOTS:
        try:
            depth = len(path.relative_to(Path(root).resolve()).parts)
        except (ValueError, OSError, RuntimeError):
            continue
        if depth + extra >= SHALLOW_TEMPORARY_ROOTS.get(Path(root).name, TEMPORARY_FOLDER_DEPTH):
            return True
    return False


def _trace_removal(inside):
    """While a trace is open, record whether one `rm` call removes only static paths strictly inside a temporary root."""
    if _REMOVAL_TRACE is not None:
        _REMOVAL_TRACE.append(inside)


_COMMAND_TRACE = None
MKDIR_FLAGS = re.compile(r"-[pv]+")
MKDIR_LONG_FLAGS = frozenset({"--parents", "--verbose"})


def _trace_command(safe):
    """While a trace is open, record whether one simple command is inert or writes only inside a temporary root."""
    if _COMMAND_TRACE is not None:
        _COMMAND_TRACE.append(safe)


def _static_texts(operand, raw, values, choices):
    """Every text a path operand can take, resolving `$(dirname ...)` of a resolvable operand; None when it still
    expands, runs another command, or splits at white space."""
    inner = re.fullmatch(r"\$\(\s*dirname\s+(?:--\s+)?(.+?)\s*\)", operand)
    if inner is not None:
        word = inner[1]
        if len(word) > 1 and word[0] == word[-1] and word[0] in "'\"":
            word = word[1:-1]
        texts = _static_absolute_texts(word, None, values, choices)
        return None if texts is None else [os.path.dirname(text) for text in texts]
    found = _operand_texts(operand, values, choices)
    if found is not None and raw is not None and _unquoted_reference(raw) and _mktemp_directory(
            operand, values) is None:
        if "IFS" in values or "IFS" in (choices or {}) or re.search(r"\s", operand):
            return None
        found = [field for text in found for field in text.split()]
    return found or None


def _static_absolute_texts(operand, raw, values, choices):
    """Every absolute path text an operand can take, or None when it is not fully static."""
    found = _static_texts(operand, raw, values, choices)
    if not found or any(not text.startswith("/") or re.search(r"[*?\[]", text) for text in found):
        return None
    return found


def _strictly_inside_temporary_root(texts, cwd):
    try:
        return all(_inside_temporary_root((Path(cwd) / text).resolve()) for text in texts)
    except (OSError, RuntimeError):
        return False


def _mkdir_inside_temporary_root(args, raw_args, cwd, values, choices):
    """Whether a `mkdir` call with plain flags creates only static folders strictly inside a temporary root."""
    operands = []
    for position, arg in enumerate(args):
        if arg == "--" or MKDIR_FLAGS.fullmatch(arg) or arg in MKDIR_LONG_FLAGS:
            continue
        if arg.startswith("-"):
            return False
        raw = raw_args[position] if raw_args is not None and position < len(raw_args) else arg
        operands.append((arg, raw))
    if not operands:
        return False
    for arg, raw in operands:
        texts = _static_absolute_texts(arg, raw, values, choices)
        if texts is None or not _strictly_inside_temporary_root(texts, cwd):
            return False
    return True


def _redirects_write_only_inside_temporary_root(redirects, cwd, values, choices):
    """Whether every output redirect of a command goes to `/dev/null`, joins standard output or error, or writes a
    static file strictly inside a temporary root."""
    for _, operator, target in redirects:
        if ">" not in operator or target == "/dev/null" or (operator == ">&" and target in ("1", "2")):
            continue
        texts = _static_absolute_texts(target, None, values, choices)
        if texts is None or not _strictly_inside_temporary_root(texts, cwd):
            return False
    return True


def _operand_pairs(args, raw_args, allowed_flag):
    """The operands of a call as (text, raw) pairs, or None when a flag is not one that `allowed_flag` accepts."""
    pairs, flags_ended = [], False
    for position, arg in enumerate(args):
        raw = raw_args[position] if raw_args is not None and position < len(raw_args) else arg
        if not flags_ended and arg == "--":
            flags_ended = True
        elif not flags_ended and arg.startswith("-") and arg != "-":
            if not allowed_flag(arg):
                return None
        else:
            pairs.append((arg, raw))
    return pairs


def _copy_flag(arg):
    return COPY_FLAGS.fullmatch(arg) is not None or arg in COPY_LONG_FLAGS


def _copy_sources_resolve(sources, destinations, values, choices, cwd):
    """Whether every `cp` source is a static word that cannot read as an option and, where a destination is an existing
    folder, lands strictly inside a temporary root under its own name."""
    folders = [Path(cwd) / text for text in destinations if (Path(cwd) / text).is_dir()]
    for arg, raw in sources:
        texts = _static_texts(arg, raw, values, choices)
        if texts is None or any(not text or text.startswith("-") or text[0] in "*?[" for text in texts):
            return False
        if folders and any(re.search(r"[*?\[]", text) for text in texts):
            return False
        for folder in folders:
            if not _strictly_inside_temporary_root(
                    [str(folder / os.path.basename(text.rstrip("/"))) for text in texts], cwd):
                return False
    return True


def _copy_inside_temporary_root(cli, args, raw_args, cwd, values, choices):
    """Whether a plain `cp` or `mv` writes only static paths strictly inside a temporary root; a `cp` may read from
    anywhere, while a `mv` also removes its sources and so needs them inside as well."""
    pairs = _operand_pairs(args, raw_args, _copy_flag)
    if pairs is None or len(pairs) < 2:
        return False
    (destination, destination_raw), sources = pairs[-1], pairs[:-1]
    destinations = _static_absolute_texts(destination, destination_raw, values, choices)
    if destinations is None or not _strictly_inside_temporary_root(destinations, cwd):
        return False
    if cli == "mv":
        for arg, raw in sources:
            texts = _static_absolute_texts(arg, raw, values, choices)
            if texts is None or not _strictly_inside_temporary_root(texts, cwd):
                return False
    return _copy_sources_resolve(sources, destinations, values, choices, cwd)


def _touch_inside_temporary_root(args, raw_args, cwd, values, choices):
    """Whether a flagless `touch` creates only static files strictly inside a temporary root."""
    pairs = _operand_pairs(args, raw_args, lambda arg: False)
    if not pairs:
        return False
    for arg, raw in pairs:
        texts = _static_absolute_texts(arg, raw, values, choices)
        if texts is None or not _strictly_inside_temporary_root(texts, cwd):
            return False
    return True


COMMIT_ISH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./^~-]*")


def _worktree_add_inside_temporary_root(args, raw_args, cwd, values, choices):
    """Whether `git worktree add [--detach] <path> [<commit-ish>]` puts the new work tree at a static path strictly
    inside a temporary root. Its only effect outside is the administrative entry under `.git/worktrees/`, which
    `git worktree prune` or `git worktree remove` undoes; it creates no ref and changes no tracked file."""
    if args[:2] != ["worktree", "add"]:
        return False
    pairs = _operand_pairs(args[2:], raw_args[2:] if raw_args is not None else None, lambda arg: arg == "--detach")
    if not pairs or len(pairs) > 2 or "--" in args[2:]:
        return False
    if len(pairs) == 2 and not COMMIT_ISH.fullmatch(pairs[1][0]):
        return False
    texts = _static_absolute_texts(pairs[0][0], pairs[0][1], values, choices)
    return texts is not None and _strictly_inside_temporary_root(texts, cwd)


GO_BOOLEAN_FLAGS = frozenset({"-v", "-race", "-short", "-cover", "-failfast", "-json", "-vet=off", "-mod=readonly",
                              "-mod=vendor", "-trimpath"})
GO_VALUE_FLAGS = frozenset({"-count", "-p", "-parallel", "-timeout", "-run", "-tags"})
GO_FLAG_VALUE = re.compile(r"[A-Za-z0-9_.,|^()*+?/][A-Za-z0-9_.,|^()*+?/-]*")
GO_PACKAGE = re.compile(r"\.|(?:\./)?(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*(?:\.\.\.|[A-Za-z0-9_][A-Za-z0-9_.-]*)")
GO_ENVIRONMENT_NAMES = ("GOFLAGS", "GOENV", "GOCACHE")


def _go_arguments_confined(args):
    """Whether the words after `go build|vet|test` are only plain flags and relative package patterns."""
    index = 0
    while index < len(args):
        arg = args[index]
        name, equals, value = arg.partition("=")
        if arg in GO_BOOLEAN_FLAGS:
            index += 1
        elif name in GO_VALUE_FLAGS and equals:
            if not GO_FLAG_VALUE.fullmatch(value):
                return False
            index += 1
        elif arg in GO_VALUE_FLAGS and index + 1 < len(args):
            if not GO_FLAG_VALUE.fullmatch(args[index + 1]):
                return False
            index += 2
        elif not arg.startswith("-") and GO_PACKAGE.fullmatch(arg):
            index += 1
        else:
            return False
    return True


def _go_inside_temporary_root(args, cwd, env, variables):
    """Whether `go build|vet|test` with only plain flags and relative package patterns runs in a folder strictly inside
    a temporary root and with no Go environment override: its artifacts go to that copy and to the regenerable build
    cache. `go build` of several packages discards its results."""
    if not args or args[0] not in ("build", "vet", "test") or not _go_arguments_confined(args[1:]):
        return False
    if any(name in source for name in GO_ENVIRONMENT_NAMES for source in (env, variables)):
        return False
    return _strictly_inside_temporary_root(["."], cwd)


def _confined_command(cli, args, raw_args, cwd, env, variables, choices, assignments):
    """Whether one simple command is a write the guard can confine to a temporary root: `cp`, `mv`, and `touch` of
    static paths inside it, `git worktree add` into it, and `go build|vet|test` run inside it."""
    if assignments:
        return False
    values = {**env, **variables}
    if cli in ("cp", "mv"):
        return _copy_inside_temporary_root(cli, args, raw_args, cwd, values, choices)
    if cli == "touch":
        return _touch_inside_temporary_root(args, raw_args, cwd, values, choices)
    if cli == "git":
        return _worktree_add_inside_temporary_root(args, raw_args, cwd, values, choices)
    if cli == "go":
        return _go_inside_temporary_root(args, cwd, env, variables)
    return False


def _filter_may_write(cli, args):
    """Whether a filter program of the guard writes a file or runs a program through one of its options."""
    if cli == "sort":
        return any(arg.startswith("--output") or re.fullmatch(r"-[A-Za-z]*o.*", arg) for arg in args)
    if cli == "uniq":
        return sum(1 for arg in args if not arg.startswith("-")) > 1
    return cli in ("rg", "grep", "egrep", "fgrep") and any(arg.startswith(("--pre", "--hostname-bin")) for arg in args)
