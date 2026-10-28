"""This repository's own commands and archive handling that the approval guard recognizes."""
import ast
import glob
import json
import os
import re
from pathlib import Path
from guard_shell import PYTHON, SHELLS, _chained_by_and, _redirects_allowed, strip_prefix
import guard_paths
from guard_paths import MKTEMP_OPERAND, _static_value
from guard_temp import _filter_may_write
from guard_git import FILES_MAY_CHANGE, TOP_STASH, _git_directory, _git_lookup
from guard_self import GUARD_SCRIPTS, _first_operand
from guard_pyread import _fold_text, _literal_names, _read_only_python
from guard_scripts import FILTERS, _PENDING_SCRIPTS, _keeps_pending, _runs_unconditionally


BLOCK_OPENERS = frozenset({"if", "while", "until", "for", "case", "select", "{"})
BLOCK_CLOSERS = frozenset({"fi", "done", "esac", "}"})
REDIRECTED = "_APPROVAL_REDIRECTED"
SCRIPTS_STABLE = "_APPROVAL_SCRIPTS_STABLE"
STASH_TAG = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
STASH_FINDER = (r"\$\(\s*git stash list --format=(?:'(?:%H|%gd) %gs'|\"(?:%H|%gd) %gs\")\s*\|\s*grep (?:-F )?("
                + STASH_TAG + r")\s*\|\s*cut -d' ' -f1\s*\)")
STASH_FOUND = re.compile(STASH_FINDER)
STASH_FOUND_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=" + STASH_FINDER)
STASH_VARIABLE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
STASH_QUIET = frozenset({"-q", "--quiet"})
STASH_UNSAFE = frozenset({"cd", "pushd", "popd", "eval", "source", ".", "exec"}) | SHELLS


def _stash_push_tag(words):
    """The tag of a plain `git stash push [-q] [-u] -m <tag> [-- <paths>]`, else None."""
    if words[:3] != ["git", "stash", "push"]:
        return None
    tag, index = None, 3
    while index < len(words) and words[index] != "--":
        if words[index] in STASH_QUIET or words[index] in ("-u", "--include-untracked"):
            index += 1
        elif words[index] in ("-m", "--message") and tag is None and index + 1 < len(words):
            tag = words[index + 1]
            index += 2
        else:
            return None
    return tag if tag is not None and re.fullmatch(STASH_TAG, tag) else None


def _stash_entry(words, verb, variables):
    """The entry that a plain `git stash apply|drop [-q] <entry>` names: the tag that the command found it by, or the
    literal `stash@{0}`. None for any other form."""
    if words[:3] != ["git", "stash", verb]:
        return None
    operands = [word for word in words[3:] if word not in STASH_QUIET]
    if len(operands) != 1 or operands[0].startswith("-"):
        return None
    operand = operands[0]
    found, variable = STASH_FOUND.fullmatch(operand), STASH_VARIABLE.fullmatch(operand)
    if operand == TOP_STASH:
        return operand
    if found:
        return found[1]
    return variables.get(variable[1] or variable[2]) if variable else None


def _own_stash_drops(segments, operators):
    """The indexes of `git stash drop` segments that drop a stash entry this command pushed with `git stash push -m
    <tag>` and applied right before, through an always-running `git stash apply` that `&&` joins to the drop. The drop
    finds the entry by the same tag, or names `stash@{0}` while it is the newest entry this command pushed. Any other
    stash command, directory change, shell, or git variable between them ends what the check knows."""
    allowed, created, top, variables, applied, depth = set(), set(), None, {}, None, 0
    for index, segment in enumerate(segments):
        words = segment.words
        first = words[0] if words else ""
        nested = first in BLOCK_OPENERS or first in BLOCK_CLOSERS
        depth = depth + 1 if first in BLOCK_OPENERS else max(0, depth - 1) if first in BLOCK_CLOSERS else depth
        plain = depth == 0 and not nested and not segment.redirects and not segment.heredoc
        steady = plain and _runs_unconditionally(index, segments, operators)
        tag = _stash_push_tag(words)
        if tag is not None and steady:
            created.add(tag)
            top, applied = tag, None
            continue
        assignment = STASH_FOUND_ASSIGNMENT.fullmatch(words[0]) if len(words) == 1 else None
        if assignment and steady:
            variables[assignment[1]] = assignment[2]
            continue
        if words[:3] == ["git", "stash", "apply"]:
            entry = _stash_entry(words, "apply", variables)
            entry = top if entry == TOP_STASH else entry
            applied = (index, entry) if steady and entry in created else None
            continue
        if words[:3] == ["git", "stash", "list"]:
            continue
        if words[:3] == ["git", "stash", "drop"]:
            entry = _stash_entry(words, "drop", variables)
            entry = top if entry == TOP_STASH else entry
            after = min((op for op in operators if op[2] >= segment.end), key=lambda op: op[2], default=None)
            if (plain and applied is not None and applied == (index - 1, entry) and entry in created
                    and (after is None or after[1] in (";", "&&"))
                    and _chained_by_and(segments, operators, index - 1, index)):
                allowed.add(index)
                created.discard(entry)
            else:
                created = set()
            top, applied = None, None
            continue
        for name in [key for key in variables
                     if any(re.search(rf"(?<![A-Za-z0-9_]){key}(?![A-Za-z0-9_])", word) for word in words)]:
            del variables[name]
        if os.path.basename(first) in STASH_UNSAFE or any("stash" in word or "GIT_" in word for word in words):
            created, top, applied = set(), None, None
    return allowed


SHELL_FILE_WRITE = re.compile(r"(?<![0-9&])>(?!&)(?!\s*/dev/null)|\b(?:tee|cp|mv|dd|ln|install|truncate)\b|\bsed\s+-\S*i")


def _may_write_own_path(body, script, cwd):
    """Whether a script body writes, or may write, to the file it is saved in: a Python `open` for writing whose target
    is that path or cannot be folded to a literal, or any shell file write or reference to its own name."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return bool(SHELL_FILE_WRITE.search(body) or script.name in body or "$0" in body or "BASH_SOURCE" in body)
    names = _literal_names(tree)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"):
            continue
        mode = next((keyword.value for keyword in node.keywords if keyword.arg == "mode"),
                    node.args[1] if len(node.args) > 1 else None)
        if mode is None or isinstance(mode, ast.Constant) and isinstance(mode.value, str) and not set(
                mode.value) & set("wax+"):
            continue
        target = next((keyword.value for keyword in node.keywords if keyword.arg == "file"),
                      node.args[0] if node.args else None)
        if target is not None and _argv_index(target, tree) is not None:
            continue
        text = _fold_text(target, names) if target is not None else None
        if not text or "\0" in text:
            return True
        try:
            if (Path(cwd) / os.path.expanduser(text)).resolve() == script.resolve():
                return True
        except (OSError, RuntimeError):
            return True
    return False


def _confined_python_writes(content, cwd, env, argv=None, script=None):
    """Whether Python text is provably read-only once each of its literal `open` writes is counted as a read, and every
    one of those writes lands in a temporary root or the session folder. `argv` holds the resolved paths of the run's
    arguments after the script, or None for an argument that does not resolve; a `sys.argv[N]` target uses them."""
    if "chdir" in content:
        return False
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False
    names = _literal_names(tree)
    session = Path(env.get("_APPROVAL_SESSION_DIR", cwd)).resolve()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"):
            continue
        mode = next((keyword.value for keyword in node.keywords if keyword.arg == "mode"),
                    node.args[1] if len(node.args) > 1 else None)
        if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) & set("wax+")):
            continue
        target = next((keyword.value for keyword in node.keywords if keyword.arg == "file"),
                      node.args[0] if node.args else None)
        index = _argv_index(target, tree) if target is not None else None
        if index is not None:
            path = argv[index - 1] if argv and 0 < index <= len(argv) else None
            if (path is None or path == script or path in _PENDING_SCRIPTS
                    or not guard_paths._temporary(path.parent, env)):
                return False
            mode.value = "r"
            continue
        text = _fold_text(target, names) if target is not None else None
        if not text or "\0" in text:
            return False
        path = (Path(cwd) / os.path.expanduser(text)).resolve()
        if not (guard_paths._temporary(path, env) or path.is_relative_to(session)):
            return False
        mode.value = "r"
    return _read_only_python(tree)


def _argv_index(target, tree):
    """The constant index N of a `sys.argv[N]` target, when `sys` is the imported module and the script never changes
    `sys.argv`; else None."""
    if not (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Attribute)
            and target.value.attr == "argv" and isinstance(target.value.value, ast.Name)
            and target.value.value.id == "sys" and isinstance(target.slice, ast.Constant)
            and type(target.slice.value) is int):
        return None
    if not any(isinstance(node, ast.Import) and any(alias.name == "sys" and alias.asname is None for alias in node.names)
               for node in ast.walk(tree)):
        return None
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "sys" and not isinstance(node.ctx, ast.Load):
            return None
        if isinstance(node, ast.Attribute) and node.attr == "argv":
            parent = parents.get(node)
            if not isinstance(node.ctx, ast.Load) or isinstance(parent, ast.Attribute) or (
                    isinstance(parent, ast.Subscript) and not isinstance(parent.ctx, ast.Load)):
                return None
    return target.slice.value


EXPORT_HARNESS = "evals/e2e/harness/cli.py"
EXPORT_PLUGIN_NAME = "hei5enbug-agent-setup"
EXPORT_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~^/@-]*")


def _export_arguments(arguments):
    """Whether the arguments after the harness script are `export-plugin`, optionally with one literal `--ref` value."""
    if arguments[:1] != ["export-plugin"]:
        return False
    rest = arguments[1:]
    if len(rest) == 2 and rest[0] == "--ref":
        return bool(EXPORT_REF.fullmatch(rest[1]))
    return not rest or len(rest) == 1 and rest[0].startswith("--ref=") and bool(EXPORT_REF.fullmatch(rest[0][6:]))


def _own_export_run(script, arguments, env):
    """Whether a Python run is this plugin's evaluation harness exporting a commit: only `export-plugin [--ref <ref>]`,
    on a script that is committed and unchanged in the work tree whose `.claude-plugin/plugin.json` names this plugin.
    That subcommand writes only under the plugin's own state folder."""
    if not _export_arguments(arguments) or FILES_MAY_CHANGE in env:
        return False
    root = _plugin_tree(script.parent, env)
    if root is None or script != root / EXPORT_HARNESS:
        return False
    committed = _git_lookup(root, env, "rev-parse", f"HEAD:{EXPORT_HARNESS}")
    current = _git_lookup(root, env, "hash-object", "--", EXPORT_HARNESS)
    return bool(committed) and committed == current


REPO_SCRIPT_FOLDERS = re.compile(r"scripts(?:/.+)?|skills/[^/]+/scripts(?:/.+)?")
REPO_SCRIPT_EXCEPTIONS = re.compile(r"runner|publish|release|install|refresh", re.I)
REPO_SCRIPT_EFFECTFUL = frozenset({"data_removal.py", "plugin_toggles.py", "run_eval.py", "run_loop.py",
                                   "detached_job.py", "stream_agent.py"})


def _repo_script_excepted(parts):
    """Whether a work-tree path, as its parts, names a guard file, a hook, a runner, a publishing, release, install, or
    refresh script, or a script that deletes data, changes settings, or starts model or agent runs, whose run is never
    judged as the repository's own code."""
    return (parts[-1] in GUARD_SCRIPTS or parts[-1] in REPO_SCRIPT_EFFECTFUL or "hooks" in parts
            or bool(REPO_SCRIPT_EXCEPTIONS.search(parts[-1])))


def _own_repo_script(script, plain, env):
    """Whether a run is this plugin's own code: a plain `python3 <script>` of a `.py` file under `scripts/` or
    `skills/*/scripts/` of a work tree whose `.claude-plugin/plugin.json` names this plugin, unchanged from HEAD and
    tracked, with no earlier command that may change files. Guard files, hooks, runners, and scripts that publish,
    release, install, or refresh are left to the usual judgement."""
    if (not plain or FILES_MAY_CHANGE in env and SCRIPTS_STABLE not in env or REDIRECTED in env
            or script.suffix != ".py"):
        return False
    root = _plugin_tree(script.parent, env)
    if root is None or not script.is_relative_to(root):
        return False
    relative = script.relative_to(root)
    if not REPO_SCRIPT_FOLDERS.fullmatch(relative.parent.as_posix() + "/" + relative.name) or _repo_script_excepted(relative.parts):
        return False
    committed = _git_lookup(root, env, "rev-parse", f"HEAD:{relative.as_posix()}")
    current = _git_lookup(root, env, "hash-object", "--", relative.as_posix())
    return bool(committed) and committed == current


def _stdin_filter(verdict, program):
    """Whether a segment is one of the guard's filter programs (`grep`, `tail`, `cut`, and the others) without an option
    that writes a file or runs a program."""
    return (verdict.kind == "pass" and verdict.exe in FILTERS and bool(program)
            and not _filter_may_write(verdict.exe, program[1:]))


NODE_VERSION_FLAGS = frozenset({"--version", "-v"})


def _own_node_check(program, cwd, env):
    """Whether a segment only prints the node version or runs `node --test <file>` on a test file of this plugin's work
    tree that is tracked and unchanged from HEAD. Such a run is the repository's own code, under the trust that the
    own-script rule gives its scripts, so it does not count as a writer of those scripts."""
    if program[:1] != ["node"] or len(program) not in (2, 3):
        return False
    if len(program) == 2:
        return program[1] in NODE_VERSION_FLAGS
    path = Path(program[2]) if program[1] == "--test" and not re.search(r"[$`*?\[{~]", program[2]) else None
    if path is None or path.suffix not in (".mjs", ".js", ".cjs"):
        return False
    script = (Path(cwd) / path).resolve()
    root = _plugin_tree(script.parent, env)
    if root is None or not script.is_relative_to(root) or "tests" not in script.relative_to(root).parts[:-1]:
        return False
    relative = script.relative_to(root).as_posix()
    committed = _git_lookup(root, env, "rev-parse", f"HEAD:{relative}")
    return bool(committed) and committed == _git_lookup(root, env, "hash-object", "--", relative)


def _plugin_tree(directory, env):
    """The root of the git work tree that holds `directory` when its `.claude-plugin/plugin.json` names this plugin,
    else None."""
    git_directory = _git_directory([], directory, env)
    top = _git_lookup(git_directory, env, "rev-parse", "--show-toplevel") if git_directory is not None else None
    if not top or not top.strip():
        return None
    root = Path(top.strip()).resolve()
    try:
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return root if isinstance(manifest, dict) and manifest.get("name") == EXPORT_PLUGIN_NAME else None


_ARCHIVE_COPIES = {}
ARCHIVE_FLAGS = re.compile(r"-[rRp]+")


def _archive_directory(word, variables, statics, env):
    """The resolved path `word` when it is the folder that a variable got from a `mktemp -d` substitution in this command
    and the folder lies strictly inside a temporary root, else None."""
    if not word.startswith("/"):
        return None
    path = Path(os.path.normpath(word)).resolve()
    named = any(MKTEMP_OPERAND.fullmatch(value) and statics.get(name) is not None
                and Path(statics[name]).resolve() == path for name, value in variables.items())
    return path if named and guard_paths._temporary(path.parent, env) else None


def _tar_extract_target(program):
    """The folder after `-C` of a `tar` call that only extracts from standard input, else None."""
    forms = (["tar", "-x", "-C"], ["tar", "-xf", "-", "-C"], ["tar", "-x", "-f", "-", "-C"], ["tar", "-xC"])
    for form in forms:
        if len(program) == len(form) + 1 and program[:len(form)] == form:
            return program[-1]
    return None


def _unconditional_pipeline(index, segments, operators):
    """Whether the two segments ending at `index` run as one pipeline that follows nothing or `;` and is followed by
    nothing or `;`."""
    first, last = segments[index - 1], segments[index]
    before = max((op for op in operators if op[3] <= first.start), key=lambda op: op[3], default=None)
    after = min((op for op in operators if op[2] >= last.end), key=lambda op: op[2], default=None)
    between = [op for op in operators if op[2] >= first.end and op[3] <= last.start]
    return ((before is None or before[1] == ";") and (after is None or after[1] == ";")
            and len(between) == 1 and between[0][1] == "|")


def _archive_fill(segment, program, segments, index, operators, cwd, variables, statics, env, steady):
    """Record or extend a folder that holds only this plugin's work tree: a `mktemp -d` folder that
    `git archive HEAD | tar -x -C <folder>` fills from the current work tree, and relative paths of that work tree that
    `cp` adds. Returns whether the segment is such a step."""
    if not steady or not program or segment.redirects:
        return False
    name = os.path.basename(program[0])
    if name == "tar" and index > 0:
        previous, _ = strip_prefix(segments[index - 1].words)
        target = _tar_extract_target(program)
        folder = _archive_directory(target, variables, statics, env) if target else None
        root = _plugin_tree(cwd, env) if folder is not None else None
        if (previous == ["git", "archive", "HEAD"] and not segments[index - 1].redirects and root is not None
                and _unconditional_pipeline(index, segments, operators)):
            _ARCHIVE_COPIES[folder] = root
            return True
        return False
    if name != "cp" or not _ARCHIVE_COPIES or not _runs_unconditionally(index, segments, operators):
        return False
    args = program[1:]
    flags = [arg for arg in args if arg.startswith("-")]
    words = [arg for arg in args if not arg.startswith("-")]
    if len(words) < 2 or any(not ARCHIVE_FLAGS.fullmatch(flag) for flag in flags):
        return False
    destination = _static_value(words[-1], statics, env)
    if destination is None:
        return False
    target = Path(os.path.normpath(destination)).resolve()
    folder = next((key for key in _ARCHIVE_COPIES if target == key or key in target.parents), None)
    if folder is None or not Path(cwd).resolve().is_relative_to(_ARCHIVE_COPIES[folder]):
        return False
    for source in words[:-1]:
        if re.search(r"[$`~]|(?:^|/)\.\.(?:/|$)", source) or source.startswith("/"):
            return False
        matches = glob.glob(os.path.join(cwd, source))
        if not matches or any(not Path(item).resolve().is_relative_to(_ARCHIVE_COPIES[folder]) for item in matches):
            return False
    return True


def _keeps_archive(segment, program, region, cwd, variables, statics, env):
    """Whether a segment leaves an archive copy as it is: a segment that `_keeps_pending` accepts, or a run of a Python file
    inside the copy."""
    if _keeps_pending(segment, program, region, cwd, variables):
        return True
    if not program or not PYTHON.fullmatch(os.path.basename(program[0])) or segment.redirects and not (
            _redirects_allowed([segment])):
        return False
    operand = _first_operand(program[1:])
    return operand is not None and _in_archive(Path(os.path.normpath(Path(cwd) / operand)).resolve())


def _in_archive(path):
    """Whether a resolved path lies inside a folder that the archive registry holds."""
    return any(key in path.parents for key in _ARCHIVE_COPIES)
