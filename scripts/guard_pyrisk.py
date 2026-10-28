"""Credential reads and secret environment values in Python code, for the approval guard."""
import ast
import copy as copy_module
import os
import re
from collections import Counter
from pathlib import Path
import approval_state
from guard_paths import _protected_path

SECRET_NAME = approval_state.SECRET_NAME
UNKNOWN = ["*"]
MAX_ALTERNATIVES = 16
HOME_VARIABLES = frozenset({"HOME", "USERPROFILE"})
ENVIRONMENTS = frozenset({"os.environ", "os.environb"})
PATH_CLASSES = frozenset({"Path", "PurePath", "PosixPath", "PurePosixPath"})
SAME_TEXT_CALLS = frozenset({"expanduser", "expandvars", "abspath", "realpath", "normpath", "str", "fspath", "relpath"})
SAME_TEXT_METHODS = frozenset({"expanduser", "resolve", "absolute", "as_posix", "with_suffix"})
FORMAT_FIELD = re.compile(r"\{[^{}]*\}|%[-#0 +]*\d*(?:\.\d+)?[sdrif]")
CREDENTIAL_FILE = re.compile(
    r"(?:^|/)(?:\.aws/(?:credentials|config)|\.kube/config|\.docker/config\.json|\.netrc|\.pgpass"
    r"|\.config/gh/hosts\.yml|\.ssh/(?![^/]*\.pub$|known_hosts|config$)[^/]+)$")
CREDENTIAL_FOLDER = re.compile(r"(?:^|/)(?:\.azure|\.config/gcloud)/[^/]+")
ENV_FILE = re.compile(r"(?:^|/)\.env[^/]*$")
TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
READ_METHODS = frozenset({"read_text", "read_bytes"})
OPEN_MODULES = frozenset({"io", "codecs", "gzip", "bz2", "lzma"})
OS_OPEN_WRITE = re.compile(r"WRONLY|RDWR|CREAT|APPEND|TRUNC")


def _aliases(tree):
    """The dotted module paths that the imported names of a script stand for."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                found[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return found


def _dotted(node, aliases):
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value, aliases)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _cross(options, joiner):
    """Every combination of the alternatives of each part, folded left to right by `joiner`."""
    result = options[0]
    for part in options[1:]:
        result = [joiner(first, second) for first in result for second in part]
        if len(result) > MAX_ALTERNATIVES:
            return UNKNOWN
    return result


def _join_path(first, second):
    if second.startswith("/") or not first:
        return second
    return f"{first}/{second}"


class _Folder:
    """Folds a path expression into the texts it can have; `*` stands for a part that cannot be decided."""

    def __init__(self, tree, aliases, env):
        self.aliases = aliases
        self.env = env
        stores = Counter(node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
                         and not isinstance(node.ctx, ast.Load))
        stores.update(node.arg for node in ast.walk(tree) if isinstance(node, ast.arg))
        self.values = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                self.values[node.targets[0].id] = node.value
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                self.values[node.target.id] = node.iter
        self.once = {name for name in self.values if stores[name] == 1}
        self.loops = {node.target.id for node in ast.walk(tree) if isinstance(node, ast.For)
                      and isinstance(node.target, ast.Name)}

    def fold(self, node, depth=0):
        if depth > 8 or node is None:
            return UNKNOWN
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, str) else UNKNOWN
        if isinstance(node, ast.JoinedStr):
            return _cross([self.fold(item.value, depth + 1) if isinstance(item, ast.FormattedValue)
                           else [item.value] for item in node.values] or [[""]], lambda a, b: a + b)
        if isinstance(node, ast.Name):
            return self.fold_name(node, depth)
        if isinstance(node, ast.BinOp):
            return self.fold_operation(node, depth)
        if isinstance(node, ast.Call):
            return self.fold_call(node, depth)
        if isinstance(node, ast.Subscript):
            return self.fold_environment(node.value, node.slice)
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            return [os.path.dirname(item) or "." for item in self.fold(node.value, depth + 1)]
        return UNKNOWN

    def fold_name(self, node, depth):
        if node.id not in self.once:
            return UNKNOWN
        value = self.values[node.id]
        if node.id in self.loops:
            if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and all(
                    isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts):
                return [item.value for item in value.elts] or UNKNOWN
            return UNKNOWN
        return self.fold(value, depth + 1)

    def fold_operation(self, node, depth):
        if isinstance(node.op, ast.Div):
            return _cross([self.fold(node.left, depth + 1), self.fold(node.right, depth + 1)], _join_path)
        if isinstance(node.op, ast.Add):
            return _cross([self.fold(node.left, depth + 1), self.fold(node.right, depth + 1)], lambda a, b: a + b)
        if isinstance(node.op, ast.Mod):
            return [FORMAT_FIELD.sub("*", item) for item in self.fold(node.left, depth + 1)]
        return UNKNOWN

    def fold_environment(self, container, key):
        """The text of `os.environ[<literal>]`, `os.environ.get(<literal>)`, or `os.getenv(<literal>)`: the home folder
        for a home variable, the value for another variable when it is set, else unknown."""
        if container is not None and _dotted(container, self.aliases) not in ENVIRONMENTS or not (
                isinstance(key, ast.Constant) and isinstance(key.value, str)):
            return UNKNOWN
        if key.value in HOME_VARIABLES:
            return ["~"]
        value = self.env.get(key.value)
        return [value] if value and not SECRET_NAME.search(key.value) else UNKNOWN

    def fold_call(self, node, depth):
        func = node.func
        dotted = _dotted(func, self.aliases) or ""
        tail = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        args = [self.fold(arg, depth + 1) for arg in node.args]
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            return UNKNOWN
        if tail in PATH_CLASSES:
            return _cross(args, _join_path) if args else ["."]
        if dotted.endswith("path.join") and args:
            return _cross(args, _join_path)
        if tail == "home":
            return ["~"]
        if tail in ("cwd", "getcwd"):
            return ["."]
        if dotted == "tempfile.gettempdir":
            return ["/tmp"]
        if dotted == "os.getenv" and node.args:
            return self.fold_environment(None, node.args[0])
        if tail in SAME_TEXT_CALLS and args and (isinstance(func, ast.Name) or dotted.startswith("os.")):
            return args[0]
        if tail == "dirname" and args:
            return [os.path.dirname(item) or "." for item in args[0]]
        if isinstance(func, ast.Attribute):
            return self.fold_method(node, tail, args, depth)
        return UNKNOWN

    def fold_method(self, node, tail, args, depth):
        func = node.func
        if tail == "get" and node.args:
            return self.fold_environment(func.value, node.args[0])
        owner = self.fold(func.value, depth + 1)
        if tail in SAME_TEXT_METHODS:
            return owner
        if tail == "joinpath" and args:
            return _cross([owner, *args], _join_path)
        if tail == "format" and isinstance(func.value, ast.Constant):
            return [FORMAT_FIELD.sub("*", item) for item in owner]
        if tail == "join" and isinstance(func.value, ast.Constant) and isinstance(func.value.value, str) and node.args:
            items = node.args[0]
            if isinstance(items, (ast.List, ast.Tuple)):
                parts = [self.fold(item, depth + 1) for item in items.elts]
                return _cross(parts, lambda a, b: f"{a}{func.value.value}{b}") if parts else UNKNOWN
        return UNKNOWN


def _mode_reads(mode):
    """Whether the mode argument of an `open` call can read: none, a literal mode that is not write-only, or a mode that is
    not a literal."""
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return not (set(mode.value) & set("wax")) or "+" in mode.value
    return True


def _keyword(node, name, position):
    for item in node.keywords:
        if item.arg == name:
            return item.value
    return node.args[position] if len(node.args) > position else None


def read_targets(tree, folder):
    """The path texts that a script reads, as (text, source) pairs, from `open` in a read mode, `read_text`, `read_bytes`,
    `ConfigParser.read`, `fileinput`, and `netrc`."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        dotted = _dotted(func, folder.aliases) or ""
        tail = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if dotted == "open" or dotted.split(".")[0] in OPEN_MODULES and tail == "open":
            target, mode = _keyword(node, "file", 0), _keyword(node, "mode", 1)
        elif isinstance(func, ast.Attribute) and tail == "open" and dotted != "os.open":
            target, mode = func.value, _keyword(node, "mode", 0)
        elif dotted == "os.open":
            flags = _keyword(node, "flags", 1)
            target, mode = _keyword(node, "path", 0), None
            if flags is not None and OS_OPEN_WRITE.search(ast.unparse(flags)):
                continue
        elif isinstance(func, ast.Attribute) and tail in READ_METHODS:
            target, mode = func.value, None
        elif isinstance(func, ast.Attribute) and tail == "read" and node.args:
            target, mode = node.args[0], None
        elif dotted in ("fileinput.input", "fileinput.FileInput"):
            target, mode = _keyword(node, "files", 0), None
        elif dotted == "netrc.netrc":
            found.extend((text, "netrc") for text in (folder.fold(node.args[0]) if node.args else ["~/.netrc"]))
            continue
        else:
            continue
        if target is not None and _mode_reads(mode):
            found.extend((text, tail) for text in folder.fold(target))
    return found


def _credential_text(text, cwd, env):
    """Whether a path text names a credential file: the files that `cat` treats as sensitive, a private SSH key, the GitHub
    CLI host file, and the same names under any other home folder."""
    if not text or "\0" in text or text.replace("*", "").strip("/.") == "":
        return False
    if "*" not in text:
        try:
            resolved = (Path(cwd) / os.path.expanduser(text)).resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        text = str(resolved)
        if _protected_path(text, cwd, env):
            return True
    text = re.sub(r"/{2,}", "/", text)
    if ENV_FILE.search(text):
        return not text.endswith(TEMPLATE_SUFFIXES)
    return bool(CREDENTIAL_FILE.search(text) or CREDENTIAL_FOLDER.search(text))


def credential_read(tree, cwd, env):
    """The first credential file that a script reads, as a short description, or None."""
    folder = _Folder(tree, _aliases(tree), env)
    for text, _ in read_targets(tree, folder):
        if _credential_text(text, cwd, env):
            return f"python reads {text}"
    return None


def _guarded_by_test(node, parents):
    """Whether a value is only tested for presence or discarded: it is the test of a branch or assertion, an operand of a
    boolean, `not`, `bool`, or `len`, compared with `None` or an empty text, or a statement by itself."""
    while True:
        parent = parents.get(node)
        if isinstance(parent, ast.Expr):
            return True
        if isinstance(parent, (ast.If, ast.IfExp, ast.While, ast.Assert)):
            return parent.test is node
        if isinstance(parent, ast.Compare):
            others = [parent.left, *parent.comparators]
            return all(isinstance(item, ast.Constant) and item.value in (None, "") for item in others if item is not node)
        if isinstance(parent, ast.BoolOp) or isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            node = parent
        elif isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id in ("bool", "len"):
            node = parent
        else:
            return False


def _value_exposed(node, parents, uses):
    """Whether the value that `node` reads can reach output or a request: not only a presence test, also through the one
    name it is assigned to."""
    if _guarded_by_test(node, parents):
        return False
    parent = parents.get(node)
    if isinstance(parent, (ast.Assign, ast.AnnAssign)) and parent.value is node:
        targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
        if len(targets) == 1 and isinstance(targets[0], ast.Name):
            return any(not _guarded_by_test(use, parents) for use in uses.get(targets[0].id, ()))
    return True


def secret_environment(tree):
    """The name of the first secret-named environment variable whose value a script prints, sends, or keeps beyond a
    presence test, or None. Only a literal name is judged."""
    aliases = _aliases(tree)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    uses = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            uses.setdefault(node.id, []).append(node)
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and _dotted(node.value, aliases) in ENVIRONMENTS:
            key = node.slice
        elif isinstance(node, ast.Call) and node.args:
            dotted = _dotted(node.func, aliases)
            if dotted == "os.getenv" or dotted in {f"{item}.get" for item in ENVIRONMENTS}:
                key = node.args[0]
        if (isinstance(key, ast.Constant) and isinstance(key.value, str) and SECRET_NAME.search(key.value)
                and _value_exposed(node, parents, uses)):
            return key.value
    return None


PATH_WRITE_METHODS = frozenset({
    "write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir", "symlink_to", "hardlink_to", "chmod", "lchmod",
    "rename", "replace",
})
SHUTIL_SOURCES_AND_TARGETS = {
    "copy": (1,), "copy2": (1,), "copyfile": (1,), "copytree": (1,), "copymode": (1,), "copystat": (1,),
    "move": (0, 1), "rmtree": (0,), "make_archive": (0,), "unpack_archive": (1,), "chown": (0,),
}
OS_WRITE_POSITIONS = {
    "remove": (0,), "unlink": (0,), "rmdir": (0,), "removedirs": (0,), "mkdir": (0,), "makedirs": (0,),
    "truncate": (0,), "chmod": (0,), "chown": (0,), "lchown": (0,), "utime": (0,), "mkfifo": (0,), "mknod": (0,),
    "rename": (0, 1), "replace": (0, 1), "renames": (0, 1), "symlink": (1,), "link": (1,),
}


def _mode_writes(mode):
    """Whether the mode argument of an `open` call can write: a literal mode with a write letter, or a mode that is not a
    literal."""
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return bool(set(mode.value) & set("wax+"))
    return mode is not None


def _call_targets(node, folder, dotted, tail):
    """The path expressions that one call changes."""
    func = node.func
    args = node.args
    if dotted == "open" or dotted.split(".")[0] in OPEN_MODULES and tail == "open":
        target = _keyword(node, "file", 0)
        return [target] if target is not None and _mode_writes(_keyword(node, "mode", 1)) else []
    if dotted == "os.open":
        flags = _keyword(node, "flags", 1)
        target = _keyword(node, "path", 0)
        return [target] if target is not None and flags is not None and OS_OPEN_WRITE.search(ast.unparse(flags)) else []
    if dotted.startswith("shutil.") and tail in SHUTIL_SOURCES_AND_TARGETS:
        return [args[index] for index in SHUTIL_SOURCES_AND_TARGETS[tail] if index < len(args)]
    if dotted.startswith("os.") and tail in OS_WRITE_POSITIONS:
        return [args[index] for index in OS_WRITE_POSITIONS[tail] if index < len(args)]
    if not isinstance(func, ast.Attribute):
        return []
    if tail == "open":
        return [func.value] if _mode_writes(_keyword(node, "mode", 0)) else []
    if tail == "replace" and len(args) != 1 or tail not in PATH_WRITE_METHODS:
        return []
    return [func.value, *args[:1]] if tail in ("rename", "replace", "symlink_to", "hardlink_to") else [func.value]


def write_targets(tree, folder):
    """The path texts that a script can create, change, move, or remove, from `open` in a write mode, `write_text`,
    `write_bytes`, `Path` mutators, `shutil`, and `os`."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or any(isinstance(arg, ast.Starred) for arg in node.args):
            continue
        func = node.func
        dotted = _dotted(func, folder.aliases) or ""
        tail = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        for target in _call_targets(node, folder, dotted, tail):
            found.extend(folder.fold(target))
    return found


def _spellings(text, cwd):
    """The resolved and the expanded, unresolved absolute spellings of a path text without a wildcard, else None."""
    if not text or "\0" in text or "*" in text:
        return None
    try:
        joined = Path(cwd, os.path.expanduser(text))
        return str(joined.resolve()), os.path.abspath(joined)
    except (OSError, RuntimeError, ValueError):
        return None


def path_matches(tree, cwd, env, exact, tail):
    """Whether a script writes a path for which `exact(resolved, expanded)` is true, or whose text with unknown parts
    matches the `tail` expression."""
    folder = _Folder(tree, _aliases(tree), env)
    for text in write_targets(tree, folder):
        spellings = _spellings(text, cwd)
        if spellings is not None:
            if exact(*spellings):
                return text
        elif text.replace("*", "").strip("/.") and tail.search(re.sub(r"/{2,}", "/", text)):
            return text
    return None


SENSITIVE_WRITE_TAIL = re.compile(
    r"(?:^|/)(?:\.(?:ssh|aws|gnupg)(?:/|$)|\.git/hooks(?:/|$)|\.claude/settings(?:\.local)?\.json$|\.claude\.json$"
    r"|\.codex/(?:config\.toml|hooks\.json)$)")
STARTUP_FILES = (".zshrc", ".bashrc", ".profile", ".bash_profile", ".zprofile")
CONFIG_FILES = {"CLAUDE_CONFIG_DIR": ("settings.json", "settings.local.json"), "CODEX_HOME": ("config.toml", "hooks.json")}


def _sensitive_locations(env):
    """The exact files that hold shell startup commands or the host settings of this machine."""
    home = Path.home().resolve()
    found = {str(home / name) for name in STARTUP_FILES}
    for variable, names in CONFIG_FILES.items():
        folder = env.get(variable)
        if folder and os.path.isabs(folder):
            found.update(str(Path(folder).resolve() / name) for name in names)
    return found


def sensitive_write(tree, cwd, env):
    """The first path text that a script writes in a security-sensitive location, or None: the `.ssh`, `.aws`, and `.gnupg`
    folders, shell startup files in the home folder, git hooks, and the Claude and Codex settings files."""
    exact = _sensitive_locations(env)
    return path_matches(tree, cwd, env, lambda *spellings: any(item in exact or bool(SENSITIVE_WRITE_TAIL.search(item)) for item in spellings),
                        SENSITIVE_WRITE_TAIL)


MAX_LITERAL_CODE = 65536
MAX_INLINE_DEPTH = 3
PLAIN_ARGUMENT = (ast.Name, ast.Constant, ast.Dict, ast.Load)


def _literal_execution(node, name, rebound):
    """The code text of `exec("...")` or `eval("...")` with a string literal and at most plain name, constant, or dict
    arguments for the namespaces, else None."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
            and name not in rebound and node.args and 1 <= len(node.args) <= 3 and not node.keywords):
        return None
    code = node.args[0]
    if not (isinstance(code, ast.Constant) and isinstance(code.value, str) and len(code.value) <= MAX_LITERAL_CODE):
        return None
    if any(not isinstance(item, PLAIN_ARGUMENT) for arg in node.args[1:] for item in ast.walk(arg)):
        return None
    return code.value


class _Inliner(ast.NodeTransformer):
    """Replaces `exec("<code>")` statements and `eval("<expression>")` calls by the code itself, so that the rules for
    ordinary code judge it. Text that does not parse stays a call."""

    def __init__(self, rebound):
        self.rebound = rebound
        self.depth = 0

    def visit_Expr(self, node):
        code = _literal_execution(node.value, "exec", self.rebound)
        parsed = self.parse(code, "exec")
        if parsed is None:
            return self.generic_visit(node)
        return self.nested(parsed.body) or ast.Pass()

    def visit_Call(self, node):
        code = _literal_execution(node, "eval", self.rebound)
        parsed = self.parse(code, "eval")
        if parsed is None:
            return self.generic_visit(node)
        return self.nested([parsed.body])[0]

    def parse(self, code, mode):
        if code is None or self.depth >= MAX_INLINE_DEPTH:
            return None
        try:
            return ast.parse(code, mode=mode)
        except (SyntaxError, ValueError):
            return None

    def nested(self, nodes):
        self.depth += 1
        try:
            found = []
            for node in nodes:
                visited = self.visit(node)
                found.extend(visited if isinstance(visited, list) else [visited])
            return found
        finally:
            self.depth -= 1


def inline_literal_executions(tree):
    """A copy of the tree in which each `exec` and `eval` of a string literal is replaced by the code it runs."""
    rebound = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)
               and node.id in ("exec", "eval")}
    rebound |= {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and node.name in ("exec", "eval")}
    if not any(isinstance(node, ast.Name) and node.id in ("exec", "eval") for node in ast.walk(tree)):
        return tree
    return ast.fix_missing_locations(_Inliner(rebound).visit(copy_module.deepcopy(tree)))
