"""Repository lookups, discard detection, and git and gh rules for the approval guard."""
import os
import re
import subprocess
from pathlib import Path
import approval_state
from approval_state import Outcome
import guard_shell
from guard_shell import _digest, _has_flag, _read, option_value, option_values, subcommand_words
import guard_paths
from guard_paths import DISCARD_MAX_TARGETS, _mktemp_directory, _operand_paths, _removal_path
from guard_expand import _operand_texts, _unquoted_reference
from guard_reads import GIT_HARMLESS_CONFIG


FILES_MAY_CHANGE = "_APPROVAL_FILES_MAY_CHANGE"
IN_EXEC = "_APPROVAL_IN_EXEC"
STASH_OWN_DROP = "_APPROVAL_STASH_OWN_DROP"
GIT_HARMLESS_ENV = frozenset({
    "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_PAGER", "GIT_TERMINAL_PROMPT", "GIT_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND",
    "GIT_PROGRESS_DELAY", "GIT_FLUSH", "GIT_MERGE_AUTOEDIT",
})
GIT_HARMLESS_OPTIONS = frozenset({"--no-pager", "-P", "--no-optional-locks", "--paginate", "-p"})
COMMAND_GIT_CONFIG = "_APPROVAL_COMMAND_GIT_CONFIG"
GIT_CONFIG_ENTRY = re.compile(r"GIT_CONFIG_(?:KEY|VALUE)_(\d+)")


def _inherited_git_config(env):
    """The `GIT_CONFIG_*` names in `env` that the hook process inherited unchanged, when its own `GIT_CONFIG_COUNT`
    entries only set keys, such as the credential prompt settings a terminal exports, that cannot change which
    repository git acts on or what it runs. A command that names any of these variables itself, by assignment, `export`,
    or `env`, gets no exemption for them even when it repeats the inherited value."""
    inherited = {name: value for name, value in os.environ.items() if name.startswith("GIT_CONFIG_")}
    count = inherited.get("GIT_CONFIG_COUNT", "")
    if not count.isdigit():
        return set()
    for name in inherited:
        entry = GIT_CONFIG_ENTRY.fullmatch(name)
        if name != "GIT_CONFIG_COUNT" and (entry is None or int(entry[1]) >= int(count)):
            return set()
    keys = [inherited.get(f"GIT_CONFIG_KEY_{index}") for index in range(int(count))]
    if not all(key is not None and key.lower() in GIT_HARMLESS_CONFIG for key in keys):
        return set()
    set_by_command = set(env.get(COMMAND_GIT_CONFIG, "").split(","))
    return {name for name, value in inherited.items() if env.get(name) == value and name not in set_by_command}


def _git_directory(global_args, cwd, env):
    """The folder a git call acts on, or None when a global option other than `-C` and a few pager flags, or a variable
    that can redirect the repository, index, worktree, or object store, could send it elsewhere."""
    directory, index = Path(cwd), 0
    while index < len(global_args) and global_args[index].startswith("-"):
        if global_args[index] == "-C" and index + 1 < len(global_args):
            directory = directory / os.path.expanduser(global_args[index + 1])
            index += 2
        elif global_args[index] in GIT_HARMLESS_OPTIONS:
            index += 1
        else:
            return None
    exempt = _inherited_git_config(env)
    if any(name.startswith("GIT_") and name not in GIT_HARMLESS_ENV and not name.startswith("GIT_TRACE")
           and name not in exempt for name in env):
        return None
    return directory


def _git_lookup(directory, env, *args):
    """The stdout of a quick read-only git query, or None when it fails or times out."""
    try:
        completed = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "--no-optional-locks", "-C", str(directory), *args],
            capture_output=True, text=True, timeout=guard_shell.LOOKUP_TIMEOUT_SECONDS, env=env, stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def _clean_tracked_tree(args, cwd, env):
    """Whether the repository a git call acts on has no uncommitted change to a tracked file. Any failure, a timeout, an
    option or variable that could redirect the target, an earlier command that may change files, or output means no."""
    directory = _git_directory(args, cwd, env)
    if directory is None or FILES_MAY_CHANGE in env:
        return False
    status = _git_lookup(directory, env, "status", "--porcelain", "--untracked-files=no")
    return status is not None and not status.strip()


TOP_STASH = "stash@{0}"


def _lossless_stash_drop(global_args, args, cwd, env):
    """Whether `git stash drop` of the newest stash, named or not, loses nothing: the stash holds no untracked files, and
    the work tree already equals it for every tracked file and the index equals the stash's index commit. Any other form, a failed or timed out query, or an earlier
    command that may change files means no."""
    flags = [arg for arg in args[2:] if arg.startswith("-")]
    operands = [arg for arg in args[2:] if not arg.startswith("-")]
    if (args[:2] != ["stash", "drop"] or any(flag not in ("-q", "--quiet") for flag in flags)
            or operands not in ([], [TOP_STASH])):
        return False
    directory = _git_directory(global_args, cwd, env)
    if directory is None or FILES_MAY_CHANGE in env:
        return False
    commit = _git_lookup(directory, env, "rev-list", "--parents", "-n", "1", TOP_STASH, "--")
    if commit is None or len(commit.split()) != 3:
        return False
    return (_git_lookup(directory, env, "diff", "--quiet", TOP_STASH, "--") is not None
            and _git_lookup(directory, env, "diff", "--cached", "--quiet", TOP_STASH + "^2", "--") is not None)


DEFAULT_BRANCHES = frozenset({"main", "master", "develop", "trunk"})
PUSH_PLAIN_FLAGS = frozenset({
    "-u", "--set-upstream", "-n", "--dry-run", "-v", "--verbose", "-q", "--quiet", "--no-verify", "--verify", "--progress",
    "--no-progress", "--atomic", "--force-if-includes",
})
REMOTE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")


def _push_branch(name):
    """The branch a push destination or lease names, or None for HEAD, an implicit or glob name, or another ref kind."""
    name = name[len("refs/heads/"):] if name.startswith("refs/heads/") else name
    if not name or name in ("HEAD", "@") or name.startswith(("refs/", "-", "+", ":")) or re.search(r"[*?\[\s]", name):
        return None
    return name


def _lease_push_allowed(global_args, args, cwd, env):
    """Whether a `git push` forces only through `--force-with-lease` or `--force-if-includes`, to an explicit remote other
    than `upstream`, onto explicit branches that are not default branches (`main`, `master`, `develop`, `trunk`, or the
    remote's HEAD branch when it can be read)."""
    if IN_EXEC in env:
        return False
    directory = _git_directory(global_args, cwd, env)
    if directory is None:
        return False
    operands, leases, index = [], [], 1
    while index < len(args):
        arg = args[index]
        if arg == "--force-with-lease" or arg.startswith("--force-with-lease="):
            leases.append(arg.partition("=")[2])
        elif arg in PUSH_PLAIN_FLAGS or re.fullmatch(r"-[uvnq]+", arg):
            pass
        elif arg.startswith("-"):
            return False
        else:
            operands.append(arg)
        index += 1
    if len(operands) < 2 or not REMOTE_NAME.fullmatch(operands[0]) or operands[0] == "upstream":
        return False
    remote, branches = operands[0], []
    for refspec in operands[1:]:
        destination = refspec.partition(":")[2] if ":" in refspec else refspec
        branch = None if refspec.startswith(("+", ":")) else _push_branch(destination)
        if branch is None:
            return False
        branches.append(branch)
    for lease in leases:
        if lease:
            branch = _push_branch(lease.partition(":")[0])
            if branch is None:
                return False
            branches.append(branch)
    if _git_lookup(directory, env, "remote", "get-url", remote) is None:
        return False
    head = _git_lookup(directory, env, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD")
    defaults = DEFAULT_BRANCHES | ({head.strip().partition("/")[2]} if head and "/" in head else set())
    return not any(branch in defaults for branch in branches)


GIT_PUSH_FLAGS = frozenset({"--force", "--force-with-lease", "--force-if-includes", "--delete", "--mirror", "--prune"})


def _git_gh_label(cli, words, args):
    """Name a git call as `git push --force (origin main)`: git push keeps its force and delete flags after the verb,
    and the other words after git's verb go in parentheses."""
    if cli != "git":
        return f"{cli} {' '.join(words[:2])}"
    if words[0] == "push":
        flags = []
        for arg in args[1:]:
            if arg.startswith("--") and arg.split("=", 1)[0] in GIT_PUSH_FLAGS:
                flags.append(arg.split("=", 1)[0])
            elif arg.startswith("-") and not arg.startswith("--"):
                flags += [f"-{letter}" for letter in "fd" if letter in arg[1:]]
        positional = [arg for arg in args[1:] if not arg.startswith("-")]
        label = " ".join(["git push", *dict.fromkeys(flags)])
        return label + (f" ({' '.join(positional)})" if positional else "")
    return f"git {words[0]}" + (f" ({' '.join(words[1:])})" if len(words) > 1 else "")


GIT_DISCARD_VERBS = frozenset({"reset", "clean", "checkout", "restore", "stash", "worktree", "rm"})


def _git_discards(words, args, short):
    """Whether a git call throws away working-tree changes that the base classification leaves unasked: a checkout
    with a `--` path, a restore of the working tree, or a forced worktree removal."""
    verb = words[0]
    if verb == "checkout":
        return _has_flag(args, "--pathspec-from-file") or ("--" in args and args.index("--") + 1 < len(args))
    if verb == "restore":
        staged_only = _has_flag(args, "--staged", "-S") and not _has_flag(args, "--worktree", "-W")
        return not staged_only and (_has_flag(args, "--pathspec-from-file")
                                    or any(not arg.startswith("-") for arg in args[1:]))
    if verb == "worktree":
        return words[1:2] == ["remove"] and (_has_flag(args, "--force") or any("f" in arg[1:] for arg in short))
    return False


def _git_gh(cli, args, command, cwd=None, env=None):
    if cli == "gh" and any(arg in ("--help", "--version") for arg in args):
        return _read()
    global_values = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"} if cli == "git" else {"-R", "--repo", "--hostname"}
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in global_values else 1
    global_args, args = args[:index], args[index:]
    words = subcommand_words(args)
    if not words:
        return Outcome("pass", [], [])
    verb = words[0]
    destructive = False
    write = False
    critical = False
    short = [arg for arg in args if arg.startswith("-") and not arg.startswith("--")]
    if cli == "git":
        if verb == "push":
            write = True
            destructive = (_has_flag(args, "--force", "--force-with-lease", "--force-if-includes", "--delete", "--mirror", "--prune")
                           or any(set(arg[1:]) & {"f", "d"} for arg in short)
                           or any(arg.startswith(("+", ":")) for arg in args))
            if destructive and _lease_push_allowed(global_args, args, cwd or os.getcwd(),
                                                   dict(os.environ if env is None else env)):
                destructive = False
        elif verb == "tag":
            operands = []
            index = 1
            while index < len(args):
                if args[index] in ("-m", "--message", "-F", "--file", "-u", "--local-user"):
                    index += 2
                    continue
                if not args[index].startswith("-"):
                    operands.append(args[index])
                index += 1
            replacing = _has_flag(args, "--delete", "--force") or any(set(arg[1:]) & {"d", "f"} for arg in short)
            listing = _has_flag(args, "-l", "--list", "-v", "--verify", "--format", "--contains", "--no-contains",
                                "--points-at", "--merged", "--no-merged", "--column", "--sort")
            listing = listing or any(arg.startswith("-n") and not arg.startswith("--") for arg in args)
            write = replacing or (bool(operands) and not listing
                                  and not any("l" in arg[1:] or "v" in arg[1:] for arg in short))
        elif verb == "reset":
            destructive = _has_flag(args, "--hard")
        elif verb == "clean":
            destructive = (_has_flag(args, "--force") or any("f" in arg[1:] for arg in short)) and not (
                _has_flag(args, "--dry-run") or any("n" in arg[1:] for arg in short))
        elif verb == "checkout":
            destructive = _has_flag(args, "--force") or any("f" in arg[1:] for arg in short) or "." in args
        elif verb == "restore":
            destructive = any(arg in (".", ":/") for arg in args) and not (
                _has_flag(args, "--staged", "-S") and not _has_flag(args, "--worktree", "-W"))
        elif verb == "stash":
            destructive = words[1:2] in (["drop"], ["clear"])
            if destructive and words[1:2] == ["drop"] and env is not None and STASH_OWN_DROP in env:
                destructive = False
            elif destructive and _lossless_stash_drop(global_args, args, cwd or os.getcwd(),
                                                      dict(os.environ if env is None else env)):
                destructive, write = False, True
        discard = not destructive and approval_state.session_scope() and (
            _git_discards(words, args, short)
            or verb == "rm" and _git_rm_discards(global_args, args, cwd or os.getcwd(),
                                                 dict(os.environ if env is None else env)))
        destructive = destructive or discard
        if destructive and verb in ("reset", "checkout", "restore") and _clean_tracked_tree(
                global_args, cwd or os.getcwd(), dict(os.environ if env is None else env)):
            destructive, write = False, write or not discard
        critical = destructive and verb in GIT_DISCARD_VERBS
    else:
        if words[:2] == ["auth", "token"]:
            return Outcome("secret", [], [])
        if verb == "api":
            data = any(arg in ("-f", "-F", "--field", "--raw-field", "--input")
                       or arg.startswith(("-f", "-F", "--field=", "--raw-field=", "--input=")) for arg in args)
            explicit = option_value(args, "-X", ("--method",))
            method = (explicit or ("POST" if data else "GET")).upper()
            if not explicit and words[1:2] == ["graphql"]:
                fields = option_values(args, "-f", ("--raw-field",)) + option_values(args, "-F", ("--field",))
                queries = [value.split("=", 1)[1] for value in fields if value and value.startswith("query=")]
                queries = [re.sub(r"#[^\n]*", "", query).lstrip() for query in queries]
                if queries and all(re.match(r"(?:query\b|\{)", query) and not re.search(r"\bmutation\b", query)
                                   for query in queries):
                    method = "GET"
            destructive, write = method == "DELETE", method != "GET"
        elif len(words) > 1:
            destructive = words[1] == "delete"
        if verb != "api":
            if words[:2] in (["pr", "checkout"], ["repo", "clone"]):
                return Outcome("pass", [], [])
            reads = {"view", "list", "ls", "status", "checks", "diff", "search", "watch", "browse"}
            read = (verb in {"status", "version", "search", "--version", "--help"}
                    or len(words) > 1 and words[1] in reads
                    or words[:2] in (["config", "get"], ["config", "list"]))
            write = not read
    if destructive or write:
        return Outcome("always" if destructive else "write", [f"{cli}:{_digest(command)}"], [_git_gh_label(cli, words, args)],
                       every_time=destructive, critical=critical)
    read_verbs = {
        "status", "show", "log", "diff", "ls-remote", "describe", "rev-parse", "ls-tree", "ls-files", "cat-file",
        "rev-list", "show-ref", "for-each-ref", "merge-base", "blame", "shortlog", "diff-tree",
    }
    gh_read = cli == "gh"
    if gh_read or cli == "git" and (verb in read_verbs or verb == "tag"):
        return _read()
    return Outcome("pass", [], [])


GIT_PLAIN_CONFIG = ("-c", "status.showUntrackedFiles=all", "-c", "core.excludesFile=/dev/null",
                    "-c", "status.ignoreSubmodules=none", "-c", "core.untrackedCache=false")
REMOVAL_TRACKED = "Recursive removal of tracked files"
REMOVAL_IGNORED = "Recursive removal of ignored files"


def _removal_scope(targets, cwd, env):
    """The descriptions that make removing `targets` recoverable, or None. Each target is a (path, link) pair that must
    lie inside the work tree that holds `cwd`, never be its root, a symbolic link, or reach `.git`, and be either
    tracked with no staged, unstaged, or untracked change under it, or untracked and ignored."""
    directory = _git_directory([], cwd, env)
    top = _git_lookup(directory, env, "rev-parse", "--show-toplevel") if directory is not None else None
    if top is None or not top.strip():
        return None
    root = Path(top.strip()).resolve()
    labels = []
    for path, link in targets:
        if (os.path.islink(link) or path == root or not path.is_relative_to(root)
                or ".git" in path.relative_to(root).parts or not path.exists()):
            return None
        listed = _git_lookup(root, env, "--literal-pathspecs", "ls-files", "-v", "--", str(path))
        if listed is None or any(line[:1] != "H" for line in listed.splitlines()):
            return None
        if listed.strip():
            status = _git_lookup(root, env, *GIT_PLAIN_CONFIG, "--literal-pathspecs", "status", "--porcelain",
                                 "--untracked-files=all", "--ignore-submodules=none", "--", str(path))
            if status is None or status.strip():
                return None
            labels.append(REMOVAL_TRACKED)
        elif _git_lookup(root, env, *GIT_PLAIN_CONFIG, "check-ignore", "-q", "--", str(path)) is not None:
            labels.append(REMOVAL_IGNORED)
        else:
            return None
    return list(dict.fromkeys(labels))


DISCARD_CHUNK = 200
DISCARD_SCAN_LIMIT = 5000
FIND_REMOVERS = frozenset({"rm", "unlink", "shred"})
FIND_EXECS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
FIND_WRITERS = frozenset({"-fprint", "-fprint0", "-fprintf", "-fls"})
_DISCARD_CACHE = {}


def _git_probe(directory, env, *args):
    """The finished read-only git query, or None when it cannot run or times out."""
    try:
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "--no-optional-locks", "-C", str(directory), *args],
            capture_output=True, text=True, timeout=guard_shell.LOOKUP_TIMEOUT_SECONDS, env=env, stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _nested_roots(directory):
    """The Git work trees found under a folder that lies outside any work tree, or None when the scan is incomplete."""
    roots, seen, failed = [], 0, []
    for current, names, files in os.walk(directory, onerror=failed.append):
        seen += len(names) + len(files)
        if seen > DISCARD_SCAN_LIMIT or failed:
            return None
        if ".git" in names or ".git" in files:
            roots.append(Path(current))
            names[:] = []
    return roots


def _ignored_untracked(root, path, env):
    """Whether a path holds no tracked file and Git ignores it."""
    listed = _git_lookup(root, env, "--literal-pathspecs", "ls-files", "--", str(path))
    return (listed is not None and not listed.strip()
            and _git_lookup(root, env, "check-ignore", "-q", "--", str(path)) is not None)


def _discards_work(paths, env, untracked=True):
    """Whether removing these paths could discard uncommitted work: a path that is, or holds, a tracked file with a staged
    or unstaged change or (with `untracked`) an untracked file that Git does not ignore, in any work tree. A state Git
    cannot report counts as discarding. After an earlier command that may change files, only an ignored untracked path
    is safe inside a work tree."""
    git_env = {name: value for name, value in env.items() if not name.startswith("GIT_")}
    git_env["LC_ALL"] = "C"
    strict = FILES_MAY_CHANGE in env or IN_EXEC in env
    groups = {}
    for path in paths:
        if ".git" in path.parts or not (path.exists() or os.path.islink(path)):
            continue
        found = _git_probe(path if path.is_dir() else path.parent, git_env, "rev-parse", "--show-toplevel")
        if found is None:
            return True
        if found.returncode != 0:
            if "not a git repository" not in found.stderr:
                return True
            if path.is_dir() and not guard_paths._temporary(path, env):
                nested = _nested_roots(path)
                if nested is None:
                    return True
                for root in nested:
                    groups.setdefault(root.resolve(), []).append(root.resolve())
            continue
        groups.setdefault(Path(found.stdout.strip()).resolve(), []).append(path)
    for root, members in groups.items():
        members = sorted(dict.fromkeys(members))
        for start in range(0, len(members), DISCARD_CHUNK):
            chunk = tuple(str(member) for member in members[start:start + DISCARD_CHUNK])
            key = (str(root), chunk, untracked)
            if key not in _DISCARD_CACHE:
                done = _git_probe(root, git_env, "--literal-pathspecs", "status", "--porcelain",
                                  "--untracked-files=all" if untracked else "--untracked-files=no", "--ignored=no",
                                  "--ignore-submodules=none", "--", *chunk)
                _DISCARD_CACHE[key] = done is None or done.returncode != 0 or bool(done.stdout.strip())
            if _DISCARD_CACHE[key]:
                return True
        if strict and not all(_ignored_untracked(root, member, git_env) for member in members):
            return True
    return False


def _rm_discards(args, cwd, env, variables, choices, raw_args):
    """Whether an `rm` call removes uncommitted work among the operands it resolves."""
    values = {**env, **variables}
    targets = []
    for position, operand in enumerate(args):
        if operand.startswith("-"):
            continue
        texts = _operand_texts(operand, values, choices)
        if texts is None:
            continue
        raw = raw_args[position] if raw_args is not None and position < len(raw_args) else operand
        if _unquoted_reference(raw) and _mktemp_directory(operand, values) is None:
            texts = [field for text in texts for field in text.split()]
        for text in texts:
            if text:
                targets += _operand_paths(text, cwd)
    return _discards_work(targets, env)


def _find_discards(args, cwd, env):
    """Whether a `find` call with `-delete` or `-exec rm` removes uncommitted work. The call runs again with a listing
    action in place of the removal, and an expression that cannot be listed safely counts as discarding."""
    words = list(args)
    removing = "-delete" in words or any(
        word in FIND_EXECS and index + 1 < len(words) and os.path.basename(words[index + 1]) in FIND_REMOVERS
        for index, word in enumerate(words))
    if not removing:
        return False
    index = 0
    while index < len(words) and words[index] in ("-H", "-L", "-P"):
        index += 1
    leading, start = words[:index], index
    while index < len(words) and not words[index].startswith("-") and words[index] not in ("(", ")", "!", ","):
        index += 1
    starts = words[start:index] or ["."]
    expression, listing, cursor = words[index:], [], 0
    while cursor < len(expression):
        word = expression[cursor]
        if word in FIND_WRITERS:
            return True
        if word == "-delete":
            listing.append("-print0")
        elif word in FIND_EXECS:
            end = next((offset for offset in range(cursor + 1, len(expression)) if expression[offset] in (";", "+")), None)
            if end is None or end == cursor + 1 or os.path.basename(expression[cursor + 1]) not in FIND_REMOVERS:
                return True
            listing.append("-print0")
            cursor = end
        else:
            listing.append(word)
        cursor += 1
    if "-delete" in words:
        listing.insert(0, "-depth")
    try:
        done = subprocess.run(["find", *leading, *starts, *listing], capture_output=True, timeout=guard_shell.LOOKUP_TIMEOUT_SECONDS,
                              cwd=cwd, env=env, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return True
    names = [name for name in done.stdout.decode("utf-8", "surrogateescape").split("\0") if name]
    if len(names) > DISCARD_MAX_TARGETS:
        return True
    targets = []
    for name in names:
        full = os.path.join(cwd, name)
        path = None if os.path.isdir(full) else _removal_path(full)
        if path is not None:
            targets.append(path)
    return _discards_work(targets, env)


def _git_rm_discards(global_args, args, cwd, env):
    """Whether a forced `git rm` that deletes the files removes tracked files with uncommitted changes."""
    short = "".join(arg[1:] for arg in args if arg.startswith("-") and not arg.startswith("--"))
    if not (_has_flag(args, "--force") or "f" in short):
        return False
    if _has_flag(args, "--cached", "--dry-run") or "n" in short:
        return False
    directory = _git_directory(global_args, cwd, env)
    if directory is None or _has_flag(args, "--pathspec-from-file"):
        return True
    operands, literal = [], False
    for arg in args[1:]:
        if literal or not arg.startswith("-"):
            operands.append(arg)
        elif arg == "--":
            literal = True
    targets = []
    for text in operands:
        targets += _operand_paths(text, str(directory))
    return _discards_work(targets, env, untracked=False)


def _holds_git_entry(cwd, directory):
    """Whether the folder a glob lists holds a `.git` file or folder; a folder that cannot be resolved counts as holding
    one."""
    try:
        return os.path.lexists((Path(cwd) / os.path.expanduser(directory or ".")).resolve() / ".git")
    except (OSError, RuntimeError):
        return True
