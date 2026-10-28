"""Protected and temporary paths, path variable expansion, and mktemp handling for the approval guard."""
import glob
import os
import re
from pathlib import Path
import approval_state
from approval_state import Outcome
from guard_shell import _one_line, strip_prefix


ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
SSH_PUBLIC_NAMES = ("known_hosts", "known_hosts.old", "config")


def _sensitive(text):
    return Outcome("sensitive", [approval_state.SENSITIVE_KEY], [_one_line(text)])


def _resolved(path, cwd):
    expanded = os.path.expandvars(os.path.expanduser(path))
    return (Path(cwd) / expanded).resolve()


def _guard_state_dirs():
    root = approval_state.state_dir()
    return (root, root.parent / "heartbeats", root.parent / "pycache")


def _state_path(path, cwd):
    candidate = _resolved(path, cwd)
    return any(candidate == directory or directory in candidate.parents
               for directory in (item.resolve() for item in _guard_state_dirs()))


def _protected_path(path, cwd, env=None):
    env = os.environ if env is None else env
    candidate = _resolved(path, cwd)
    home = Path.home()
    protected = [home / item for item in (
        ".kube/config", ".aws/credentials", ".aws/config", ".pgpass", ".docker/config.json", ".netrc",
        ".config/gh/hosts.yml",
    )]
    protected.extend(_resolved(item, cwd) for item in env.get("KUBECONFIG", "").split(os.pathsep) if item)
    if candidate.name.startswith(".env") and not candidate.name.endswith(ENV_TEMPLATE_SUFFIXES) or candidate in protected:
        return True
    if home / ".ssh" in candidate.parents and not candidate.name.endswith(".pub") and candidate.name not in SSH_PUBLIC_NAMES:
        return True
    return any(candidate == directory or directory in candidate.parents for directory in (
        home / ".azure", home / ".config/gcloud",
    ))


def _expand_path_variables(value, variables):
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)",
                  lambda match: variables.get(match[1] or match[2], match[0]), value)


def _script_path(path, cwd, variables):
    expanded = _expand_path_variables(path, variables)
    if "$" in expanded or "`" in expanded:
        return None
    return (Path(cwd) / os.path.expanduser(expanded)).resolve()


TEMPORARY_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")


def _python_inline_code(args):
    """The code of a Python `-c` option in any spelling (`-c code`, `-ccode`, `-Ic code`), "" when it has no code, or
    None when the interpreter arguments name a module, a script, or no inline code before the first operand."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--" or arg == "-" or not arg.startswith("-"):
            return None
        if arg.startswith("--"):
            index += 2 if arg == "--check-hash-based-pycs" else 1
            continue
        for position, letter in enumerate(arg[1:], 1):
            if letter == "c":
                return arg[position + 1:] or (args[index + 1] if index + 1 < len(args) else "")
            if letter == "m":
                return None
            if letter in "WX":
                index += 1 if len(arg) > position + 1 else 2
                break
        else:
            index += 1
    return None


def _protected_argument(arg, cwd, env):
    """Whether an argument, or the value attached to its option (`--file=.env`, `-f.env`), names a protected file."""
    values = [arg] if not arg.startswith("-") else [arg.partition("=")[2]] if "=" in arg else []
    if arg.startswith("-") and not arg.startswith("--") and len(arg) > 2:
        values.append(arg[2:].lstrip("="))
    return any(value and _protected_path(value, cwd, env) for value in values)


def _temp_roots(env):
    return [Path(path).resolve() for path in (*TEMPORARY_ROOTS, env.get("TMPDIR") or "/tmp", str(Path.home() / ".cache"))]


SHARED_TEMPORARY_FOLDER = re.compile(r"claude-\d+")


def _shared_temporary(path, env):
    """Whether a resolved path is a temporary root, a folder that holds one, or a folder every session of a user shares:
    the per-user levels of `/var/folders` and a `claude-<uid>` folder directly in `/tmp`."""
    if any(path == root or path in root.parents for root in _temp_roots(env)):
        return True
    for root in TEMPORARY_ROOTS:
        try:
            parts = path.relative_to(Path(root).resolve()).parts
        except (ValueError, OSError, RuntimeError):
            continue
        if parts and (len(parts) < SHALLOW_TEMPORARY_ROOTS.get(Path(root).name, 1)
                      or len(parts) == 1 and SHARED_TEMPORARY_FOLDER.fullmatch(parts[0])):
            return True
    return False


def _job_tmp(path):
    """Whether a resolved path lies inside a Claude Code job temp folder, `~/.claude/jobs/<id>/tmp`."""
    try:
        parts = path.relative_to((Path.home() / ".claude" / "jobs").resolve()).parts
    except ValueError:
        return False
    return len(parts) >= 2 and parts[1] == "tmp"


def _temporary(path, env):
    return any(path.is_relative_to(root) for root in _temp_roots(env)) or _job_tmp(path)


def _temp_path(path, cwd, env):
    """Whether a destination word, with no unresolved expansion, resolves into a temporary root."""
    if not path or "$" in path or "`" in path or re.search(r"[*?\[{]", path):
        return False
    return _temporary((Path(cwd) / os.path.expanduser(path)).resolve(), env)


def _static_value(value, statics, environment):
    """The fixed text of an assigned value: a `mktemp -d` substitution resolves like `rm` targets, anything that still
    expands or runs a command has none."""
    expanded = _expand_path_variables(value, statics)
    resolved = _mktemp_directory(expanded if "mktemp" in value else value, environment)
    if resolved is not None:
        return resolved
    return None if "$" in expanded or "`" in expanded else expanded


MKTEMP_ARGS = r"((?:\s+[^\s()`$;&|<>\\'\"]+)*)\s*"
MKTEMP_OPERAND = re.compile(r"\$\(\s*mktemp" + MKTEMP_ARGS + r"\)|`\s*mktemp" + MKTEMP_ARGS + "`")
TMPDIR_DEFAULT = re.compile(r"\$\{TMPDIR:-([^${}`\s]*)\}(?=/|$)")


def _mktemp_directory(operand, values):
    """Resolve an operand that is exactly a `mktemp -d` substitution to a path inside the directory it would create in."""
    match = MKTEMP_OPERAND.fullmatch(operand)
    if match is None:
        return None
    words = (match[1] or match[2] or "").split()
    if not any(word == "--directory" or word.startswith("-") and not word.startswith("--") and "d" in word
               for word in words):
        return None
    directory, index = None, 0
    while index < len(words):
        word = words[index]
        if word == "-p" and index + 1 < len(words):
            directory, index = words[index + 1], index + 2
            continue
        if word.startswith("--tmpdir="):
            directory = word.partition("=")[2]
        elif not word.startswith("-"):
            directory = directory or (os.path.dirname(word) or None)
        index += 1
    return os.path.join(directory or values.get("TMPDIR") or "/tmp", "mktemp.XXXXXX")


def _tmpdir_default(operand, values):
    """Resolve a leading ${TMPDIR:-default} to TMPDIR when it is set, else to the literal default."""
    match = TMPDIR_DEFAULT.match(operand)
    return (values.get("TMPDIR") or match[1]) + operand[match.end():] if match else operand


DISCARD_MAX_TARGETS = 3000


def _removal_path(text):
    """The path a removal deletes, with its folder resolved and a symbolic link kept as the link itself, or None for a
    link or the filesystem root."""
    text = os.path.abspath(text)
    if text == os.path.dirname(text) or os.path.islink(text):
        return None
    return Path(os.path.realpath(os.path.dirname(text))) / os.path.basename(text)


def _operand_paths(text, cwd):
    """The paths a resolved `rm` or `git rm` operand names, expanding a glob to its matches."""
    link = os.path.join(cwd, os.path.expanduser(text))
    if re.search(r"[*?\[]", link):
        matches = sorted(glob.glob(link))
        if len(matches) > DISCARD_MAX_TARGETS:
            fixed = re.split(r"[*?\[]", link, maxsplit=1)[0]
            matches = [fixed if fixed.endswith("/") else os.path.dirname(fixed)]
    else:
        matches = [link]
    return [path for path in map(_removal_path, matches) if path is not None]


SHALLOW_TEMPORARY_ROOTS = {"folders": 4}
CD_WORD = re.compile(r"(?<![\w.-])(?:cd|pushd|popd)(?![\w.-])")


def _heredoc_cwd(before, segments, segment, cwd):
    """The folder a heredoc script runs in and whether it is certain: the `cd <folder>` steps ahead of it on its own line
    count when the folder exists, and any earlier `cd`, `pushd`, or `popd` leaves the folder uncertain."""
    known = CD_WORD.search(before) is None
    for item in segments:
        if item.start >= segment.start:
            break
        words, _ = strip_prefix(item.words)
        if words[:1] == ["cd"]:
            directory = _script_path(words[1], cwd, {}) if len(words) == 2 and "-" != words[1][:1] else None
            if directory is None or not directory.is_dir():
                return cwd, False
            cwd = str(directory)
        elif words and words[0] in ("pushd", "popd"):
            return cwd, False
    return cwd, known
