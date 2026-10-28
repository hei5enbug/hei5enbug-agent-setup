"""Self-approval and guard-source protection for the approval guard."""
import ast
import os
import re
from pathlib import Path
from guard_shell import ASSIGNMENT, ParseError, SEPARATOR_OPERATORS, _blank, _heredoc_data, _lex, strip_prefix, tokenize
from guard_paths import _guard_state_dirs, _state_path
from guard_self import GUARD_SCRIPTS, _code_runs_guard, _runs_guard
from guard_pyread import (
    READONLY_BLOCKED, READONLY_PROCESS, TEXT_METHODS, _literal_names, _open_texts, _python_stdin_documents,
    _read_only_python, _text_only_use,
)


SELF_APPROVAL_REASON = (
    "Approvals come only from the user, so a command that touches the approval state or runs approval_state is denied."
)
STATE_READS = frozenset({"ls", "cat", "head", "tail", "grep", "wc", "stat", "file", "find", "echo"})
FIND_READ_OPTIONS = frozenset({
    "-type", "-name", "-iname", "-path", "-ipath", "-maxdepth", "-mindepth", "-newer", "-mtime", "-mmin", "-size",
    "-empty", "-print", "-print0", "-ls", "-not", "!", "-a", "-and", "-o", "-or", "-L", "-H", "-P",
})
STATE_VARIABLE = re.compile(
    r"(?<!\S)([\"']?)(?:\$HOME|\$\{HOME\}|\$XDG_STATE_HOME|\$\{XDG_STATE_HOME\}"
    r"|\$\{XDG_STATE_HOME:-(/[^\s$`{}\"'\\;&|<>()]*)\})/"
)
SAFE_BASE = re.compile(r"/[^\s$`\\\"'|&;<>(){}*?\[\]!#]*")
DYNAMIC_TRIGGERS = ("$(", "`", "<(", ">(", "${", "$", "{", "}")


def _expand_state_variables(command):
    """Replace $HOME, $XDG_STATE_HOME, and ${XDG_STATE_HOME:-/path} at the start of a word with absolute paths."""
    home = os.environ.get("HOME") or str(Path.home())
    state_home = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")

    def replace(match):
        text = match[0]
        if match[2] is not None:
            base = os.environ.get("XDG_STATE_HOME") or match[2]
        else:
            base = state_home if "XDG_STATE_HOME" in text else home
        return match[1] + base + "/" if SAFE_BASE.fullmatch(base) else text
    return STATE_VARIABLE.sub(replace, command)


def _collapse_path_spelling(text):
    """The text with `//`, `/./`, and `name/../` collapsed, so an equivalent spelling of a state folder still matches."""
    text = re.sub(r"/(?:\.?/)+", "/", text)
    while True:
        collapsed = re.sub(r"[^/\s\"']+/\.\./", "", text)
        if collapsed == text:
            return text
        text = collapsed


def _mentions_state(text):
    spelled = _collapse_path_spelling(text)
    return any(str(directory) in spelled or f"hei5enbug-agent-setup/{directory.name}" in spelled
               for directory in _guard_state_dirs())


DYNAMIC_NAMES = frozenset({"eval", "exec", "compile", "__import__", "getattr", "setattr", "globals", "vars", "locals"})
PROCESS_MODULES = frozenset({"subprocess", "importlib", "runpy", "ctypes", "multiprocessing", "pty", "socket"})


def _state_text_only_python(body):
    """Whether Python code can carry a state folder spelling only as text: it spawns no process and runs no dynamic code,
    every `open` has a literal target outside the state folders, and each string that holds a state spelling only flows
    into text."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return False
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    names = _literal_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in DYNAMIC_NAMES or isinstance(node, ast.Attribute) and (
                node.attr in READONLY_BLOCKED - {"replace", "environ"} and node.attr not in TEXT_METHODS
                or READONLY_PROCESS.fullmatch(node.attr) or node.attr in ("run", "Popen", "import_module")):
            return False
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] in PROCESS_MODULES for alias in node.names):
            return False
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in PROCESS_MODULES:
            return False
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            target = next((keyword.value for keyword in node.keywords if keyword.arg == "file"),
                          node.args[0] if node.args else None)
            texts = _open_texts(target, tree, names) if target is not None else None
            if not texts or any("\0" in text or not text or _mentions_state(text) or _state_path(text, "/")
                                for text in texts):
                return False
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _mentions_state(node.value):
            if not _text_only_use(node, parents, tree):
                return False
    return True


def _text_only_python_documents(text):
    """Spans of quoted-delimiter heredoc bodies that a plain `python3 -` reads and that carry state spellings only as text."""
    return [(start, stop) for start, stop in _python_stdin_documents(text) if _state_text_only_python(text[start:stop])]


def _configured_cache_dirs():
    """The plugin caches at their configured locations, before any symbolic link is followed."""
    home = Path.home()
    bases = [Path(os.environ["CLAUDE_CONFIG_DIR"]) if os.environ.get("CLAUDE_CONFIG_DIR") else home / ".claude", home / ".claude",
             Path(os.environ["CODEX_HOME"]) if os.environ.get("CODEX_HOME") else home / ".codex", home / ".codex"]
    return [Path(os.path.abspath(base / "plugins" / "cache")) for base in bases]


def _plugin_cache_dirs():
    """The plugin caches under both identities: where they are configured and where their symbolic links lead, so a cache
    that is a link into any other folder stays a cache."""
    configured = _configured_cache_dirs()
    return list(dict.fromkeys([*configured, *(root.resolve() for root in configured)]))


def _running_plugin_roots():
    """The folder and plugin root that this running guard was loaded from, as (path as loaded, resolved path) pairs."""
    script = Path(os.path.abspath(__file__))
    return [(root, root.resolve()) for root in (script.parent, script.parent.parent)]


def _plugin_install_dirs():
    """The resolved folders that hold running plugin code: the Claude and Codex plugin caches, and the folder and plugin
    root that this running guard was loaded from."""
    return [*(root.resolve() for root in _configured_cache_dirs()), *(resolved for _, resolved in _running_plugin_roots())]


def _in_git_work_tree(path):
    return any((parent / ".git").exists() for parent in (path, *path.parents))


def _guard_source_reason(command, cwd):
    """Why a Python heredoc in the command touches running guard code, or None. Code that runs or imports a guard module is
    denied. A string that names a guard script, or any path in a plugin cache or in the folder this guard runs from while
    the code is not read-only, is denied unless it names a guard script in a git work tree outside those folders."""
    protected = _plugin_install_dirs()
    for start, stop in _python_stdin_documents(command):
        body = command[start:stop]
        if _code_runs_guard(body):
            return SELF_APPROVAL_REASON
        try:
            tree = ast.parse(body)
        except SyntaxError:
            if any(name in body for name in GUARD_SCRIPTS):
                return SELF_APPROVAL_REASON
            continue
        readonly = None
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and 0 < len(node.value) < 4096
                    and "\0" not in node.value and "\n" not in node.value):
                continue
            try:
                path = (Path(cwd) / os.path.expanduser(node.value)).resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            inside = any(path == root or root in path.parents for root in protected)
            if os.path.basename(node.value) in GUARD_SCRIPTS and (inside or not _in_git_work_tree(path)):
                return SELF_APPROVAL_REASON
            if inside:
                readonly = _read_only_python(tree) if readonly is None else readonly
                if not readonly:
                    return SELF_APPROVAL_REASON
    return None


def _heredoc_outputs(text):
    """The file words that heredoc commands write with `>`, `>>`, or `tee`."""
    outputs = []
    for line in text.splitlines():
        if "<<" not in line:
            continue
        try:
            tokens = _lex(line)
        except ParseError:
            continue
        words = [token[1] for token in tokens if token[0] == "word"]
        outputs.extend(tokens[index + 1][1] for index, token in enumerate(tokens[:-1])
                       if token[0] == "op" and token[1] in (">", ">>", ">|") and tokens[index + 1][0] == "word")
        if "tee" in words:
            outputs.extend(word for word in words[words.index("tee") + 1:] if not word.startswith("-"))
    return outputs


RUNNERS = r"(?:python[\d.]*|node|ruby|perl|php|bash|sh|zsh|source|\.|exec)"


def _runs_written_file(text, outputs):
    """Whether a file that a heredoc command writes is later run by an interpreter or as a command."""
    for output in outputs:
        name = r"[\"']?(?:\S*/)?" + re.escape(os.path.basename(output)) + r"(?![\w.-])"
        if re.search(r"(?:^|[\s;&|(])" + RUNNERS + r"\s+(?:-\S+\s+)*" + name, text):
            return True
        if re.search(r"(?:^|[;&|(\n])[ \t]*" + name + r"[\"']?[ \t]*(?:$|[;&|)\n])", text, re.M):
            return True
    return False


def _message_spans(text, tokens):
    """Spans of `git commit -m` message values and of `echo` and `printf` words whose output goes to a file outside the
    state folders, when the text holds no expansion that runs a command."""
    spans, segment = [], []
    for token in [*tokens, ("op", ";", len(text), len(text))]:
        if token[0] == "op" and token[1] in SEPARATOR_OPERATORS:
            spans.extend(_segment_message_spans(text, segment))
            segment = []
        else:
            segment.append(token)
    return spans


def _plain_text_token(text, token):
    raw = text[token[2]:token[3]]
    return (raw.startswith("'") and raw.endswith("'") and "'" not in raw[1:-1]) or not re.search(r"\$\(|`|<\(|>\(", raw)


def _segment_message_spans(text, tokens):
    words = [token for token in tokens if token[0] == "word"]
    redirects = [(tokens[index], tokens[index + 1]) for index in range(len(tokens) - 1)
                 if tokens[index][0] == "op" and tokens[index + 1][0] == "word"]
    redirect_words = {id(target) for _, target in redirects}
    words = [token for token in words if id(token) not in redirect_words]
    program, _ = strip_prefix([token[1] for token in words])
    if not program:
        return []
    body = words[len(words) - len(program):]
    name = os.path.basename(program[0])
    if name == "git" and program[1:2] == ["commit"]:
        values = []
        for index, token in enumerate(body[:-1]):
            if token[1] == "--message" or re.fullmatch(r"-[A-Za-z]*m", token[1]):
                values.append(body[index + 1])
        values.extend(token for token in body if token[1].startswith("--message=") and token not in values)
        return [(token[2], token[3]) for token in values if _plain_text_token(text, token)]
    if name in ("echo", "printf"):
        if not redirects or any(op[1] not in (">", ">>") or _mentions_state(target[1]) or re.search(
                r"[$`*?\[{]", target[1]) or _state_path(target[1], "/") for op, target in redirects):
            return []
        return [(token[2], token[3]) for token in body[1:] if _plain_text_token(text, token)]
    return []


COMMIT_HEREDOC = re.compile(
    r"(\bgit\b[^\n;&|]*\bcommit\b[^\n;&|]*?(?:-m|--message)[ =]\s*\"\$\(cat\s+<<-?\s*'(\w+)'[^\n]*\n)(.*?)(\n[ \t]*\2[ \t]*\n?\s*\)\")",
    re.S)


def _mention_text(command):
    """The command with the text that cannot touch a state folder blanked: heredoc data, Python heredoc bodies that only
    carry text, commit messages, and the words of an `echo` or `printf` that writes elsewhere."""
    text = _heredoc_data(command)
    outputs = _heredoc_outputs(command)
    spans = []
    if text != command and _runs_written_file(command, outputs):
        text = command
    spans.extend(_text_only_python_documents(command))
    spans.extend((match.start(3), match.end(3)) for match in COMMIT_HEREDOC.finditer(command))
    try:
        tokens = _lex(text)
        spans.extend(_message_spans(text, tokens))
    except ParseError:
        pass
    return _blank(text, spans)


def _self_approval_reason(command, cwd=None):
    """Return why a command is self-approval, or None. A command that names the state folders may use only a path prefix variable.
    With a working folder, the bodies of Python heredocs are judged by `_guard_source_reason` instead of as command words."""
    if cwd is None:
        guarded = _runs_guard(command)
    else:
        reason = _guard_source_reason(command, cwd)
        if reason:
            return reason
        guarded = _runs_guard(_blank(command, _python_stdin_documents(command)))
    if guarded:
        return SELF_APPROVAL_REASON
    command = _mention_text(command)
    if _mentions_state(command):
        command = _expand_state_variables(command)
        trigger = next((item for item in DYNAMIC_TRIGGERS if item in command), None)
        if trigger:
            return f'{SELF_APPROVAL_REASON} It was denied because of "{trigger}".'
        try:
            segments = tokenize(command)
        except ParseError:
            return SELF_APPROVAL_REASON
        if not segments:
            return SELF_APPROVAL_REASON
        for segment in segments:
            if (not segment.words or ASSIGNMENT.match(segment.words[0])
                    or os.path.basename(segment.words[0]) not in STATE_READS):
                return SELF_APPROVAL_REASON
            if os.path.basename(segment.words[0]) == "find" and any(
                    re.search(r"[*?\[]", word) or word.startswith("-") and word not in FIND_READ_OPTIONS
                    for word in segment.words[1:]):
                return SELF_APPROVAL_REASON
            if any(">" in operator and target != "/dev/null" for _, operator, target in segment.redirects):
                return SELF_APPROVAL_REASON
    return None


def _self_approval(command):
    return _self_approval_reason(command) is not None
