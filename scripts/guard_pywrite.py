"""Python code that writes only to confined paths, for the approval guard."""
import ast
import fnmatch
import os
import re
from pathlib import Path
import approval_state
import guard_paths
from guard_paths import _guard_state_dirs
from guard_self import _code_runs_guard
from guard_pyread import _read_only_python


EXEC_TEXT_METHODS = frozenset({"split", "rsplit", "replace", "strip", "lstrip", "rstrip"})
EXEC_FILE_LIMIT = 262144
PLACEHOLDER = "\x01"
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _scope_nodes(scope):
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _store_count(scope, name):
    """How many times `name` is bound in one scope, counting parameters, imports, and nested definitions."""
    count = 0
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = scope.args
        count += sum(item.arg == name for item in (*args.posonlyargs, *args.args, *args.kwonlyargs))
        count += sum(bool(item) and item.arg == name for item in (args.vararg, args.kwarg))
    for node in _scope_nodes(scope):
        if isinstance(node, ast.Name) and node.id == name and not isinstance(node.ctx, ast.Load):
            count += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            count += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            count += sum((alias.asname or alias.name.split(".")[0]) == name for alias in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name == name:
            count += 1
    return count


class _PathTexts:
    """Folds the path expressions of a script that is fully literal into the texts they can have, with one placeholder
    for each formatted piece of an f-string; None stands for anything that cannot be decided."""

    def __init__(self, tree, env=None):
        self.tree = tree
        self.env = env or {}
        self.parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        self.dynamic = False

    def bound(self, function):
        """Whether the root of a dotted call name is the imported module or class it stands for."""
        origins = {"Path": ("pathlib", "Path"), "pathlib": ("pathlib", None), "os": ("os", None)}
        root = function.split(".")[0]
        if root not in origins or _store_count(self.tree, root) != 1:
            return False
        module, member = origins[root]
        return any(isinstance(node, ast.ImportFrom) and node.module == module and not node.level and any(
            alias.name == member and alias.asname is None for alias in node.names) if member else
            isinstance(node, ast.Import) and any(alias.name == module and alias.asname is None for alias in node.names)
            for node in self.tree.body)

    def scope_of(self, node):
        while node in self.parents:
            node = self.parents[node]
            if isinstance(node, (*SCOPES, ast.Module)):
                return node
        return self.tree

    def texts(self, node, depth=0):
        if depth > 6:
            return None
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, str) else None
        if isinstance(node, ast.JoinedStr):
            first = node.values[0] if node.values else None
            if not (isinstance(first, ast.Constant) and first.value) and node.values:
                return None
            parts = []
            for item in node.values:
                if isinstance(item, ast.Constant):
                    parts.append(item.value)
                else:
                    self.dynamic = True
                    parts.append(PLACEHOLDER)
            return ["".join(parts)]
        if isinstance(node, ast.Name):
            return self.name_texts(node, depth)
        if isinstance(node, ast.Call):
            return self.call_texts(node, depth)
        if isinstance(node, ast.Subscript):
            return self.temporary_root_texts(node)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = self.texts(node.left, depth + 1), self.texts(node.right, depth + 1)
            if left is None or right is None or len(left) * len(right) > 64:
                return None
            if any(item.startswith(("/", "~")) for item in right):
                return None
            return [os.path.join(first, second) for first in left for second in right]
        return None

    def temporary_root_texts(self, node):
        """`os.environ["TMPDIR"]` stands for the temporary folder of the hook's environment when that is set."""
        root = self.env.get("TMPDIR")
        literal = isinstance(node.slice, ast.Constant) and node.slice.value == "TMPDIR"
        if not (literal and ast.unparse(node.value) == "os.environ" and self.bound("os.environ")
                and root and os.path.isabs(root)):
            return None
        return [root]

    def call_texts(self, node, depth):
        function = ast.unparse(node.func)
        if not self.bound(function):
            return None
        if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
            return None
        if function in ("Path.home", "pathlib.Path.home") and not node.args:
            return [str(Path.home())]
        if function in ("Path", "pathlib.Path", "os.path.expanduser") and len(node.args) == 1:
            found = self.texts(node.args[0], depth + 1)
            if found is not None and function == "os.path.expanduser":
                return [os.path.expanduser(item) for item in found]
            return found
        if function in ("Path", "pathlib.Path") and len(node.args) > 1:
            parts = [self.texts(arg, depth + 1) for arg in node.args]
            if any(part is None for part in parts) or any(item.startswith(("/", "~")) for part in parts[1:]
                                                          for item in part):
                return None
            joined = [""]
            for part in parts:
                if len(joined) * len(part) > 64:
                    return None
                joined = [os.path.join(first, second) for first in joined for second in part]
            return joined
        return None

    def name_texts(self, node, depth):
        scope = self.scope_of(node)
        while True:
            count = _store_count(scope, node.id)
            if count:
                break
            if scope is self.tree:
                return None
            scope = self.scope_of(scope)
        if count != 1:
            return None
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.id in {arg.arg for arg in scope.args.args}:
            return self.parameter_texts(scope, node.id, depth)
        if isinstance(scope, ast.Lambda):
            return None
        assigns = [item for item in _scope_nodes(scope) if isinstance(item, ast.Assign) and len(item.targets) == 1
                   and isinstance(item.targets[0], ast.Name) and item.targets[0].id == node.id]
        return self.texts(assigns[0].value, depth + 1) if len(assigns) == 1 else None

    def parameter_texts(self, function, name, depth):
        """The texts that every call of a module-level helper passes for one parameter, or None when the helper is
        used in any way other than a direct call, or a call passes something that does not fold."""
        arguments = function.args
        names = [arg.arg for arg in arguments.args]
        if (self.scope_of(function) is not self.tree or function.decorator_list or arguments.vararg or arguments.kwarg
                or arguments.posonlyargs or arguments.kwonlyargs or _store_count(self.tree, function.name) != 1):
            return None
        index = names.index(name)
        defaults = arguments.defaults
        default = defaults[index - (len(names) - len(defaults))] if index >= len(names) - len(defaults) else None
        found = []
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Name) and node.id == function.name and isinstance(node.ctx, ast.Load)):
                continue
            call = self.parents.get(node)
            if not (isinstance(call, ast.Call) and call.func is node):
                return None
            if any(isinstance(arg, ast.Starred) for arg in call.args) or any(item.arg is None for item in call.keywords):
                return None
            given = call.args[index] if index < len(call.args) else next(
                (item.value for item in call.keywords if item.arg == name), default)
            texts = self.texts(given, depth + 1) if given is not None else None
            if texts is None:
                return None
            found.extend(texts)
        return found


def _write_target_ok(text, cwd, cwd_known, env):
    """Whether a write path lies inside a temporary root, or inside the working folder when that folder is one."""
    path = Path(os.path.expanduser(text))
    try:
        if path.is_absolute():
            return guard_paths._temporary(path.resolve(), env)
        root = Path(cwd).resolve()
        return cwd_known and guard_paths._temporary(root, env) and (root / path).resolve().is_relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return False


def _confine_writes(tree, cwd, cwd_known, env, protect=(), suffixes=None):
    """Whether every `write_text`, `write_bytes`, and write-mode `open` of a script has a path that folds to a temporary
    location, ends with one of `suffixes` when they are given, and never names a file of `protect`. A confined write is renamed to its read twin in `tree`
    so that the read-only test can then judge the rest."""
    if any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(tree)):
        return False
    resolver = _PathTexts(tree, env)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("write_text", "write_bytes"):
            target, mode = func.value, None
        elif isinstance(func, ast.Name) and func.id == "open":
            if _store_count(tree, "open"):
                return False
            mode = next((item.value for item in node.keywords if item.arg == "mode"),
                        node.args[1] if len(node.args) > 1 else None)
            if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) & set("wax+")):
                continue
            target = next((item.value for item in node.keywords if item.arg == "file"),
                          node.args[0] if node.args else None)
        else:
            continue
        resolver.dynamic = False
        texts = resolver.texts(target) if target is not None else None
        if not texts or any("\0" in text or not text for text in texts):
            return False
        for text in texts:
            if not _write_target_ok(text.replace(PLACEHOLDER, "x"), cwd, cwd_known, env):
                return False
            if suffixes and not text.endswith(suffixes):
                return False
            if any(_may_name(text, cwd, item) for item in protect):
                return False
        if mode is not None:
            mode.value = "r"
        else:
            func.attr = "read_" + func.attr.split("_")[1]
    return True


def _may_name(text, cwd, file):
    """Whether a write path, with its placeholders, can be the given resolved file."""
    path = Path(os.path.expanduser(text))
    full = path if path.is_absolute() else Path(cwd) / path
    if PLACEHOLDER not in text:
        try:
            return full.resolve() == file
        except (OSError, RuntimeError, ValueError):
            return True
    pattern = os.path.normpath(str(full)).replace(PLACEHOLDER, "*")
    return fnmatch.fnmatchcase(str(file), pattern) or bool(re.search(r"[\[\]?]", pattern))


def _exec_source(argument, resolver):
    """The literal file path texts that an `exec` argument reads and the string transforms applied to the text, in
    order, or None for any other argument. A read is `open(P).read()` or `<path>.read_text()`."""
    transforms, node = [], argument
    while True:
        if isinstance(node, ast.Subscript) and not isinstance(node.ctx, (ast.Store, ast.Del)):
            index = node.slice
            if isinstance(index, ast.Constant) and type(index.value) is int:
                transforms.append(("index", index.value))
            elif (isinstance(index, ast.Slice) and index.step is None and all(
                    part is None or isinstance(part, ast.Constant) and type(part.value) is int
                    for part in (index.lower, index.upper))):
                transforms.append(("slice", index.lower and index.lower.value, index.upper and index.upper.value))
            else:
                return None
            node = node.value
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in EXEC_TEXT_METHODS
              and not node.keywords and all(isinstance(arg, ast.Constant) and isinstance(arg.value, (str, int))
                                            for arg in node.args)):
            transforms.append((node.func.attr, [arg.value for arg in node.args]))
            node = node.func.value
        else:
            break
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)) or node.keywords and not all(
            item.arg == "encoding" and isinstance(item.value, ast.Constant) for item in node.keywords):
        return None
    reader = node.func
    if reader.attr == "read" and not node.args and not node.keywords and isinstance(reader.value, ast.Call):
        opened = reader.value
        if not (isinstance(opened.func, ast.Name) and opened.func.id == "open" and opened.args
                and len(opened.args) <= 2 and not any(isinstance(arg, ast.Starred) for arg in opened.args)):
            return None
        if len(opened.args) == 2 and not (isinstance(opened.args[1], ast.Constant) and opened.args[1].value in ("r", "rt")):
            return None
        if any(item.arg != "encoding" or not isinstance(item.value, ast.Constant) for item in opened.keywords):
            return None
        path = opened.args[0]
    elif reader.attr == "read_text" and not node.args:
        path = reader.value
    else:
        return None
    resolver.dynamic = False
    texts = resolver.texts(path)
    if not texts or resolver.dynamic:
        return None
    return texts, transforms[::-1]


def _apply_transforms(text, transforms):
    for name, *arguments in transforms:
        try:
            if name == "index":
                text = text[arguments[0]]
            elif name == "slice":
                text = text[arguments[0]:arguments[1]]
            else:
                text = getattr(text, name)(*arguments[0])
        except (AttributeError, IndexError, TypeError, ValueError):
            return None
    return text if isinstance(text, str) else None


def _exec_file_zone(path, env):
    """Whether a file lies in one of the plugin's work folders under the state folder, other than the guard state, or in a
    temporary root."""
    if guard_paths._temporary(path, env):
        return True
    root = approval_state.state_dir().parent.resolve()
    if not path.is_relative_to(root):
        return False
    return not any(path == item.resolve() or item.resolve() in path.parents for item in _guard_state_dirs())


def _exec_file_ok(path, transforms, cwd, cwd_known, env, suffixes=None):
    """Whether the text that `exec` runs from one file, after the string transforms, is read-only Python with temporary
    writes only."""
    try:
        resolved = path.resolve()
        if not _exec_file_zone(resolved, env) or not resolved.is_file() or resolved.stat().st_size > EXEC_FILE_LIMIT:
            return False
        text = _apply_transforms(resolved.read_text(encoding="utf-8"), transforms)
        if text is None or _code_runs_guard(text):
            return False
        tree = ast.parse(text)
    except (OSError, RuntimeError, ValueError, SyntaxError, UnicodeError):
        return False
    return _confine_writes(tree, cwd, cwd_known, env, (resolved,), suffixes) and _read_only_python(tree)


def _exec_files_confined(tree, cwd, cwd_known, env, suffixes=None, always=False):
    """Whether each `exec` of a script runs text read from a literal file under the plugin's work folders or a temporary
    root that is itself read-only Python, and each write of the script and of that text stays in temporary space. A script
    without `exec` of a read file is not judged here unless `always` is set."""
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "exec"]
    if not calls:
        return not always or _confine_writes(tree, cwd, cwd_known, env, (), suffixes)
    if _store_count(tree, "exec") or _store_count(tree, "open"):
        return False
    resolver = _PathTexts(tree)
    files = []
    for call in calls:
        source = _exec_source(call.args[0], resolver) if len(call.args) == 1 and not call.keywords else None
        if source is None:
            return False
        files.append(source)
    protected = []
    for texts, transforms in files:
        for text in texts:
            path = Path(os.path.expanduser(text))
            path = path if path.is_absolute() else Path(cwd) / path
            if not _exec_file_ok(path, transforms, cwd, cwd_known, env, suffixes):
                return False
            protected.append(path.resolve())
    return _confine_writes(tree, cwd, cwd_known, env, tuple(protected), suffixes)


def _documents_only(content, cwd, cwd_known, env):
    """Whether a Python heredoc can change nothing but Markdown files inside temporary space: every write has a literal
    `.md` target there, each `exec` runs a vetted state or temporary file, and the rest is read-only."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False
    execs = frozenset(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name) and node.func.id == "exec")
    return _exec_files_confined(tree, cwd, cwd_known, env, (".md",), True) and _read_only_python(tree, execs=execs)
