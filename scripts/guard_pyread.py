"""Read-only Python analysis for the approval guard."""
import ast
import os
import re
import shlex
from guard_shell import PYTHON, ParseError, strip_prefix, tokenize
from guard_reads import SECRET_NAME


READONLY_MODULES = frozenset({
    "sys", "os", "os.path", "re", "json", "csv", "argparse", "collections", "collections.abc", "itertools", "functools",
    "math", "statistics", "datetime", "time", "pathlib", "typing", "dataclasses", "textwrap", "string", "glob", "fnmatch",
    "hashlib", "base64", "enum", "decimal", "fractions", "heapq", "bisect", "copy", "pprint", "io", "difflib",
    "unicodedata", "uuid", "random", "platform", "shlex", "urllib.parse", "html", "zoneinfo",
    "calendar", "numbers", "abc", "contextlib", "struct", "binascii", "ipaddress", "tomllib", "configparser", "ast",
    "stat", "errno", "__future__", "shutil", "html.parser",
})
READONLY_SHUTIL = frozenset({"which", "get_terminal_size", "disk_usage"})
READONLY_BLOCKED = frozenset({
    "write_text", "write_bytes", "touch", "mkdir", "makedirs", "unlink", "remove", "rmdir", "removedirs", "rename",
    "renames", "replace", "symlink_to", "hardlink_to", "symlink", "link", "chmod", "lchmod", "chown", "lchown",
    "truncate", "ftruncate", "system", "popen", "kill", "killpg", "fork", "forkpty", "fdopen", "utime", "mkfifo",
    "mknod", "writev", "pwrite", "sendfile", "startfile", "setxattr", "removexattr", "environ", "environb", "getenv",
    "putenv", "unsetenv", "modules", "FileIO", "FileType", "importlib", "chroot", "setuid", "setgid", "seteuid",
    "setegid", "setreuid", "setregid", "setgroups", "setsid", "setpgid", "setpgrp", "unshare", "dup", "dup2", "fchmod",
    "fchown", "lockf", "posix_fallocate", "chflags", "lchflags",
})
READONLY_BUILTINS = frozenset({
    "eval", "exec", "compile", "__import__", "breakpoint", "setattr", "delattr", "globals", "locals", "vars", "help",
})
READONLY_PROCESS = re.compile(r"(?:exec|spawn)[lv]p?e?|posix_spawnp?")
READONLY_DUNDERS = frozenset({
    "__name__", "__file__", "__doc__", "__init__", "__str__", "__repr__", "__len__", "__iter__", "__next__", "__enter__",
    "__exit__", "__eq__", "__lt__", "__hash__", "__getitem__", "__contains__", "__call__", "__post_init__",
})
READONLY_SECRET_TEXT = re.compile(
    r"(?:^|[/\\])\.env(?:\.|$)|\.aws|\.kube|\.azure|\.ssh|\.gnupg|\.netrc|\.pgpass|\.docker|gcloud|credential|secret"
    r"|token|passw|id_rsa|\.npmrc|\.pypirc",
    re.I,
)
TOKEN_COUNT_WORD = re.compile(r"(?<![A-Za-z0-9/\\.])tokens(?![A-Za-z0-9]|\.\w)")


def _secret_text(value):
    """Whether a string literal names something secret; the plural `tokens` as the last word of an identifier or in
    prose counts usage and is not a secret name."""
    return bool(READONLY_SECRET_TEXT.search(TOKEN_COUNT_WORD.sub("", value)))


SEARCH_TEXT_METHODS = frozenset({
    "index", "find", "rfind", "rindex", "split", "rsplit", "partition", "rpartition", "replace", "startswith",
    "endswith", "count", "strip", "lstrip", "rstrip",
})
SEARCH_TEXT_REGEX = frozenset({"search", "sub", "subn", "findall", "finditer", "match", "fullmatch", "compile", "split"})


def _search_text_literal(node, parents, bound):
    """Whether the string literal `node` is only search text: the first argument of a string method or of a `re`
    function, or the left operand of `in` and `not in`. Such a literal is never opened, sent, or read as a name."""
    parent = parents.get(node)
    if isinstance(parent, ast.Compare):
        return parent.left is node and isinstance(parent.ops[0], (ast.In, ast.NotIn))
    if not (isinstance(parent, ast.Call) and parent.args and parent.args[0] is node
            and isinstance(parent.func, ast.Attribute)):
        return False
    func = parent.func
    if isinstance(func.value, ast.Name) and bound.get(func.value.id) == "re":
        return func.attr in SEARCH_TEXT_REGEX
    return func.attr in SEARCH_TEXT_METHODS


def _environ_literal_read(node, parents, bound):
    """Whether `node`, an `os.environ` attribute, is only read as `os.environ.get(<literal>, ...)` or
    `os.environ[<literal>]` with a literal name that does not look secret."""
    if not (isinstance(node.value, ast.Name) and bound.get(node.value.id) == "os"):
        return False
    parent = parents.get(node)
    if isinstance(parent, ast.Subscript) and parent.value is node and isinstance(parent.ctx, ast.Load):
        key = parent.slice
    elif (isinstance(parent, ast.Attribute) and parent.attr == "get" and isinstance(parents.get(parent), ast.Call)
          and parents[parent].func is parent):
        call = parents[parent]
        if any(isinstance(arg, ast.Starred) for arg in call.args) or any(item.arg is None for item in call.keywords):
            return False
        key = call.args[0] if call.args else None
    else:
        return False
    return isinstance(key, ast.Constant) and isinstance(key.value, str) and not SECRET_NAME.search(key.value)


def _string_replace(node, parents, bound):
    """Whether `node`, a `.replace` attribute, is the string method: called with two or three positional arguments on
    something that is not an imported module or `pathlib` class (`os.replace`, `Path.replace(path, target)`)."""
    call = parents.get(node)
    if not (isinstance(call, ast.Call) and call.func is node and 2 <= len(call.args) <= 3 and not call.keywords
            and not any(isinstance(arg, ast.Starred) for arg in call.args)):
        return False
    root = node.value
    if isinstance(root, ast.Constant):
        return False
    while isinstance(root, (ast.Attribute, ast.Subscript)):
        root = root.value
    if isinstance(root, ast.Call):
        return not (isinstance(root.func, ast.Name) and root.func.id == "type")
    if isinstance(root, ast.Name):
        return not ((root is node.value and root.id in bound) or bound.get(root.id, "").split(".")[0] == "pathlib")
    return True


def _path_module_aliased(parents, bound):
    """Whether `os` or a `pathlib` name is used other than as an attribute base or a called constructor, so that
    `.replace` may reach a path mover through an alias."""
    for node, parent in parents.items():
        if not (isinstance(node, ast.Name) and node.id in bound):
            continue
        origin = bound[node.id]
        if origin == "os" and not (isinstance(parent, ast.Attribute) and parent.value is node):
            return True
        if origin.split(".")[0] == "pathlib":
            current = node
            while isinstance(parents.get(current), ast.Attribute) and parents[current].value is current:
                current = parents[current]
            outer = parents.get(current)
            if not (isinstance(outer, ast.Call) and outer.func is current):
                return True
    return False


def _blocked_attribute(node, parents, bound, aliased):
    if node.attr == "replace":
        return aliased or not _string_replace(node, parents, bound)
    if node.attr == "environ":
        return not _environ_literal_read(node, parents, bound)
    return node.attr in READONLY_BLOCKED


def _read_mode_open(node, bound):
    """Whether an `open` call is provably a read: a literal read mode, or none."""
    if any(keyword.arg is None for keyword in node.keywords) or any(isinstance(arg, ast.Starred) for arg in node.args):
        return False
    keywords = {keyword.arg: keyword.value for keyword in node.keywords}
    if "opener" in keywords:
        return False
    func = node.func
    owner = bound.get(func.value.id) if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else None
    if owner == "os":
        return False
    builtin = isinstance(func, ast.Name) or owner == "io"
    if not builtin and len(node.args) > 1:
        return False
    mode = keywords.get("mode")
    if mode is None:
        index = 1 if builtin else 0
        mode = node.args[index] if len(node.args) > index else None
        if mode is not None and not builtin and not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
            return False
    return mode is None or (isinstance(mode, ast.Constant) and mode.value in ("r", "rb", "rt"))


GIT_RUN_GLOBALS = frozenset({"-C", "--no-pager", "--no-optional-locks"})
GIT_RUN_KEYWORDS = frozenset({"capture_output", "text", "check", "encoding", "errors", "timeout", "universal_newlines"})


def _git_run_command(call):
    """The command text that a `subprocess.run([...])` call with a literal git argv stands for, or None. Only `-C` may take
    a computed value, and a word after the subcommand may be computed only as an f-string that starts with a literal
    word not beginning with `-`; computed words stand for a placeholder."""
    if (ast.unparse(call.func) != "subprocess.run" or len(call.args) != 1 or not isinstance(call.args[0], ast.List)
            or any(keyword.arg not in GIT_RUN_KEYWORDS or not isinstance(keyword.value, ast.Constant)
                   for keyword in call.keywords)):
        return None
    items = call.args[0].elts
    if len(items) < 2 or not (isinstance(items[0], ast.Constant) and items[0].value == "git"):
        return None
    words, subcommand, position = ["git"], False, 1
    while position < len(items):
        item = items[position]
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            if item.value.startswith("--output") or not subcommand and item.value not in GIT_RUN_GLOBALS and (
                    item.value.startswith("-")):
                return None
            words.append(item.value)
            subcommand = subcommand or not item.value.startswith("-") and words[-2:-1] != ["-C"]
            if item.value == "-C" and not subcommand and position + 1 < len(items):
                words.append(".")
                position += 1
        elif (subcommand and isinstance(item, ast.JoinedStr) and item.values
              and isinstance(item.values[0], ast.Constant) and isinstance(item.values[0].value, str)
              and item.values[0].value and not item.values[0].value.startswith("-")):
            words.append(item.values[0].value + "x")
        else:
            return None
        position += 1
    return shlex.join(words) if subcommand else None


def _read_only_python(tree, runs=frozenset(), execs=frozenset()):
    """A conservative, exact test for Python code that cannot change anything: only listed standard modules, no process,
    network, environment, dynamic execution, or file mutation, and every `open` in a literal read mode. Anything that the
    test cannot decide is not read-only. `runs` holds the git read calls that may use `subprocess.run`, and `execs` the vetted `exec` calls, whose own text is not judged."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    vetted = {node for call in execs for node in ast.walk(call)}
    bound = {}
    openers = {"open"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in READONLY_MODULES and not (alias.name == "subprocess" and runs):
                    return False
                bound[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                return False
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if alias.name == "*" or alias.name in READONLY_BLOCKED | READONLY_BUILTINS or not (
                        node.module in READONLY_MODULES or full in READONLY_MODULES):
                    return False
                if node.module == "shutil" and alias.name not in READONLY_SHUTIL or node.module == "os" and alias.name == "open":
                    return False
                bound[alias.asname or alias.name] = full
                if alias.name == "open":
                    openers.add(alias.asname or alias.name)
    aliased = _path_module_aliased(parents, bound)
    for node in ast.walk(tree):
        if node in vetted and not isinstance(node, ast.Call):
            continue
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and _secret_text(node.value)
                and not _search_text_literal(node, parents, bound)):
            return False
        if isinstance(node, ast.Attribute):
            if (_blocked_attribute(node, parents, bound, aliased) or READONLY_PROCESS.fullmatch(node.attr)
                    or node.attr.startswith("__") and node.attr not in READONLY_DUNDERS):
                return False
            if node.attr == "open" and not (isinstance(parents.get(node), ast.Call) and parents[node].func is node):
                return False
            if isinstance(node.value, ast.Name) and bound.get(node.value.id) == "shutil" and node.attr not in READONLY_SHUTIL:
                return False
        elif isinstance(node, ast.Name):
            if node.id in READONLY_BUILTINS or node.id.startswith("__") and node.id not in READONLY_DUNDERS:
                return False
            if bound.get(node.id) == "shutil" and not (
                    isinstance(parents.get(node), ast.Attribute) and parents[node].attr in READONLY_SHUTIL):
                return False
            if bound.get(node.id) == "subprocess":
                attribute = parents.get(node)
                call = parents.get(attribute)
                if not (isinstance(attribute, ast.Attribute) and attribute.attr == "run" and call in runs
                        and call.func is attribute):
                    return False
            if node.id in openers and not (isinstance(parents.get(node), ast.Call) and parents[node].func is node):
                return False
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "getattr":
                name = node.args[1] if len(node.args) > 1 else None
                if not (isinstance(name, ast.Constant) and isinstance(name.value, str) and name.value != "open"
                        and name.value not in READONLY_BLOCKED and not name.value.startswith("__")):
                    return False
            if (isinstance(func, ast.Name) and func.id in openers) or (isinstance(func, ast.Attribute) and func.attr == "open"):
                if not _read_mode_open(node, bound):
                    return False
        elif isinstance(node, (ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith, ast.Await)):
            return False
    return True


def _fold_text(node, names):
    """The text of a string literal, a once-assigned name that holds one, or a `+` or f-string of those; else None."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold_text(node.left, names), _fold_text(node.right, names)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts = [_fold_text(item.value if isinstance(item, ast.FormattedValue) and item.conversion == -1
                            and item.format_spec is None else item, names) for item in node.values]
        return None if any(part is None for part in parts) else "".join(parts)
    return None


def _literal_names(tree):
    """The module-level names that one assignment binds to a text the parser can fold."""
    stores = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            stores[node.id] = stores.get(node.id, 0) + 1
    names = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and stores.get(node.targets[0].id) == 1):
            value = _fold_text(node.value, names)
            if value is not None:
                names[node.targets[0].id] = value
    return names


TEXT_METHODS = frozenset({
    "replace", "write", "format", "count", "startswith", "endswith", "find", "rfind", "index", "join", "strip", "lstrip",
    "rstrip", "split", "splitlines", "lower", "upper", "encode", "removeprefix", "removesuffix", "center",
})
TEXT_CALLS = frozenset({"print", "len", "str", "repr"})


def _open_texts(target, tree, names):
    """Every text the target of an `open` can take when it is a string literal, a name that only literal strings are
    assigned to, or a fold of literals; else None."""
    if isinstance(target, ast.Name):
        values = [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                  and any(isinstance(item, ast.Name) and item.id == target.id for item in node.targets)]
        texts = [item.value for item in values if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        return texts if values and len(texts) == len(values) else None
    text = _fold_text(target, names)
    return None if text is None else [text]


def _text_only_use(source, parents, tree):
    """Whether the state spelling in `source` only flows into text: concatenation, formatting, string methods, `write`,
    `print`, comparisons, and names that are used the same way. A path or process call, a `/` join, or anything else
    that could use it as a path means no."""
    pending, seen = [source], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        parent = parents.get(current)
        if parent is None or isinstance(parent, (ast.Expr, ast.Compare, ast.Assert, ast.Return)):
            continue
        if isinstance(parent, (ast.JoinedStr, ast.FormattedValue)) or (
                isinstance(parent, ast.BinOp) and isinstance(parent.op, (ast.Add, ast.Mod))):
            pending.append(parent)
        elif isinstance(parent, ast.Call) and current is not parent.func:
            func = parent.func
            if isinstance(func, ast.Attribute) and func.attr in TEXT_METHODS:
                pending.append(parent)
            elif not (isinstance(func, ast.Name) and func.id in TEXT_CALLS):
                return False
        elif isinstance(parent, ast.Attribute) and parent.attr in TEXT_METHODS and isinstance(
                parents.get(parent), ast.Call) and parents[parent].func is parent:
            pending.append(parents[parent])
        elif isinstance(parent, (ast.Assign, ast.AugAssign)) and current is parent.value:
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            if not all(isinstance(item, ast.Name) for item in targets):
                return False
            pending.extend(node for node in ast.walk(tree) if isinstance(node, ast.Name)
                           and isinstance(node.ctx, ast.Load) and node.id in {item.id for item in targets})
        else:
            return False
    return True


PYTHON_DOCUMENT = re.compile(r"(?m)^([^\n]*?)<<[ \t]*(['\"])([A-Za-z_]\w*)\2[^\n]*\n")


def _python_stdin_documents(text):
    """The bodies of quoted-delimiter heredocs that a plain `python3 -` reads, as (start, end) spans in `text`."""
    spans = []
    for match in PYTHON_DOCUMENT.finditer(text):
        if any(start <= match.start() < stop for start, stop in spans):
            continue
        try:
            segments = tokenize(match[0])
            marker = match.end(1) - match.start()
            segment = next(item for item in segments if item.start <= marker < item.end)
            words, _ = strip_prefix(segment.words)
        except (ParseError, StopIteration):
            continue
        if (not words or not PYTHON.fullmatch(os.path.basename(words[0])) or segment.redirects[1:]
                or not all(arg.startswith("-") and not arg.startswith(("-c", "-m")) for arg in words[1:])):
            continue
        end = re.search(r"(?m)^" + re.escape(match[3]) + r"[ \t]*\r?$", text[match.end():])
        if end is None:
            continue
        spans.append((match.end(), match.end() + end.start()))
    return spans
