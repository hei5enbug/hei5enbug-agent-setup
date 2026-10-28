"""Writes into installed plugin code, for the approval guard."""
import os
import re
from pathlib import Path
from guard_paths import _expand_path_variables
from guard_proof import _in_git_work_tree, _plugin_cache_dirs, _running_plugin_roots
from guard_pyrisk import path_matches

INSTALLED_CODE_REASON = (
    "Installed plugin code changes only through a plugin release, so a write into a plugin cache or the running plugin "
    "root is denied."
)
INSTALLED_TAIL = re.compile(r"(?:^|/)\.(?:claude|codex)/plugins/cache(?:/|$)")
REDIRECT_WRITES = frozenset({">", ">>", ">|", "&>", "&>>", ">&"})
NOT_A_FILE = re.compile(r"\d+|-|&\d+|/dev/(?:null|stdout|stderr|fd/\d+)")
VALUE_OPTIONS = {
    "cp": frozenset({"-S", "--suffix"}),
    "mv": frozenset({"-S", "--suffix"}),
    "ln": frozenset({"-S", "--suffix"}),
    "install": frozenset({"-m", "-o", "-g", "-S", "--mode", "--owner", "--group", "--suffix"}),
    "rsync": frozenset({
        "-e", "--rsh", "--exclude", "--include", "--filter", "-f", "--exclude-from", "--include-from", "--files-from",
        "--port", "--bwlimit", "--rsync-path", "--chmod", "--chown", "--backup-dir", "--suffix", "--link-dest",
        "--compare-dest", "--copy-dest", "--log-file", "--temp-dir", "-T", "--partial-dir", "--timeout", "--max-size",
        "--min-size", "--password-file", "--out-format", "-M", "--remote-option",
    }),
    "sed": frozenset({"-e", "-f", "-l", "--expression", "--file", "--line-length"}),
    "tee": frozenset(),
}
TARGET_PROGRAMS = frozenset({"cp", "mv", "install", "ln"})
TARGET_DIRECTORY = ("-t", "--target-directory")
SED_IN_PLACE = re.compile(r"-[A-Za-z]*i[^\s]*|--in-place(?:=.*)?")
SED_SCRIPT_OPTIONS = ("-e", "-f", "--expression", "--file")


def _installed_roots():
    """The plugin caches under their configured and resolved locations, and the running plugin root unless it is a
    development checkout: a git work tree that neither lies in a cache nor is reached through one, because that changes
    through ordinary commits rather than releases."""
    caches = _plugin_cache_dirs()
    roots = list(caches)
    for loaded, resolved in _running_plugin_roots():
        cached = any(cache in (*loaded.parents, loaded) or cache in (*resolved.parents, resolved) for cache in caches)
        if cached or not _in_git_work_tree(resolved):
            roots.extend((loaded, resolved))
    return roots


def _under_installed_code(*spellings):
    """Whether any spelling of a path lies in installed plugin code."""
    roots = _installed_roots()
    return any(spelling == str(root) or spelling.startswith(f"{root}{os.sep}") for spelling in spellings for root in roots)


def path_in_installed_code(text, cwd):
    """Whether a path text, resolved through `..`, repeated slashes, and symbolic links, or spelled as given, lies in a
    plugin cache or in the running plugin root."""
    try:
        joined = Path(cwd, os.path.expanduser(text))
        return _under_installed_code(str(joined.resolve()), os.path.abspath(joined))
    except (OSError, RuntimeError, ValueError):
        return False


def python_writes_installed_code(tree, cwd, env):
    """The first path text that a Python script writes inside installed plugin code, or None."""
    return path_matches(tree, cwd, env, _under_installed_code, INSTALLED_TAIL)


def _operands(name, args):
    """The positional operands of a program and the folder its `-t` option names."""
    values = VALUE_OPTIONS.get(name, frozenset())
    positional, folder, index, options = [], None, 0, True
    while index < len(args):
        arg = args[index]
        index += 1
        if options and arg == "--":
            options = False
        elif options and arg.startswith(TARGET_DIRECTORY[0]) and name in TARGET_PROGRAMS and not arg.startswith("--"):
            folder = arg[2:] or (args[index] if index < len(args) else None)
            index += 0 if arg[2:] else 1
        elif options and arg.startswith(TARGET_DIRECTORY[1]) and name in TARGET_PROGRAMS:
            folder = arg.partition("=")[2] or (args[index] if index < len(args) else None)
            index += 0 if "=" in arg else 1
        elif options and arg in values:
            index += 1
        elif options and arg.startswith("-") and arg != "-":
            continue
        elif arg:
            positional.append(arg)
    return positional, folder


def _written_operands(name, args):
    """The operands that a `cp`, `mv`, `install`, `rsync`, `ln`, `tee`, or `sed -i` call changes."""
    if name == "sed":
        if not any(SED_IN_PLACE.fullmatch(arg) for arg in args if arg.startswith("-")):
            return []
        positional, _ = _operands(name, args)
        scripted = any(arg.startswith(SED_SCRIPT_OPTIONS) for arg in args)
        return positional if scripted else positional[1:]
    positional, folder = _operands(name, args)
    if name == "tee":
        return positional
    if name == "mv":
        return [*positional, *([folder] if folder else [])]
    if folder:
        return [folder]
    if name == "install" and "-d" in args:
        return positional
    return positional[-1:] if len(positional) > 1 else []


def installed_code_write(program, redirects, cwd, variables):
    """Whether one simple command writes into installed plugin code, through a redirection, `tee`, `sed -i`, or the
    destination of `cp`, `mv`, `install`, `rsync`, or `ln`. A target with an expansion that is still unresolved is not
    judged."""
    name = os.path.basename(program[0]) if program else ""
    targets = [target for _, operator, target in redirects if operator in REDIRECT_WRITES
               and not NOT_A_FILE.fullmatch(target)]
    if name in VALUE_OPTIONS:
        targets.extend(_written_operands(name, program[1:]))
    for target in targets:
        expanded = _expand_path_variables(target, variables)
        if "$" in expanded or "`" in expanded or re.match(r"[^/]*:", expanded) and name == "rsync":
            continue
        if path_in_installed_code(expanded, cwd):
            return True
    return False
