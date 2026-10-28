"""Script files, heredoc scripts, and the execution policy of the approval guard."""
import ast
import fnmatch
import hashlib
import json
import os
import re
import shlex
from pathlib import Path
import approval_state
from approval_state import Outcome
from guard_shell import (
    COVERED, PYTHON, ParseError, SEPARATOR_OPERATORS, SHELLS, _destructive_text, _digest, _has_flag, _lex, _merge,
    _redirects_allowed, _shell_c, _unknown_kind, option_value, option_values, strip_prefix, tokenize,
)
import guard_paths
from guard_paths import _mktemp_directory, _script_path, _shared_temporary
from guard_expand import COVERED_WORD, PIPE_OPERATORS, _operand_texts, _unmodeled_expansion, _unquoted_reference
from guard_reads import PATH_ALTERING_NAMES
from guard_temp import (
    _confined_command, _evaluation_scratch, _filter_may_write, _inside_temporary_root, _mkdir_inside_temporary_root,
    _trace_removal,
)
from guard_git import FILES_MAY_CHANGE, IN_EXEC, _find_discards, _holds_git_entry, _removal_scope, _rm_discards
from guard_cloud import _split_url
from guard_self import _first_operand


FILTERS = frozenset({"grep", "egrep", "fgrep", "rg", "head", "tail", "wc", "sort", "uniq", "jq", "cut", "tr", "column",
                     "awk"})
MAX_SCRIPT_BYTES = 256 * 1024


def _script_unknown(path, args, env, content):
    identity = json.dumps([str(path), args, {key: env.get(key, "") for key in (
        "KUBECONFIG", "AWS_PROFILE", "CLOUDSDK_CORE_PROJECT", "DOCKER_CONTEXT",
    )}, content], ensure_ascii=False)
    kind = _unknown_kind(_destructive_text(content))
    return Outcome(kind, ["script:" + hashlib.sha256(identity.encode()).hexdigest()],
                   [f"Script {path} contains a covered CLI or SDK call that cannot be classified"],
                   every_time=kind == "always", critical=True)


def _script_content(path):
    if not path.is_file():
        raise OSError("script is not a regular file")
    with path.open("rb") as handle:
        data = handle.read(MAX_SCRIPT_BYTES + 1)
    if len(data) > MAX_SCRIPT_BYTES:
        raise ValueError("script is larger than 256 KiB")
    return data.decode("utf-8")


def _make_recipes(content, target):
    rules = {}
    current = []
    for line in content.splitlines():
        if line.startswith("\t"):
            for name in current:
                rules[name][1].append(line.strip().lstrip("@+-"))
        elif line.strip() and not line.lstrip().startswith("#"):
            match = re.match(r"([^:=]+):([^=].*|$)", line)
            current = match.group(1).split() if match else []
            if match:
                dependencies, _, recipe = match.group(2).partition(";")
                for name in current:
                    rules[name] = (dependencies.split(), [recipe.strip()] if recipe.strip() else [])
    if not rules:
        raise ValueError("no Makefile target")
    target = target or next((name for name in rules if not name.startswith(".")), next(iter(rules)))
    if target not in rules:
        raise ValueError("unknown Makefile target")
    dependencies, recipes = rules[target]
    return [*recipes, *(line for name in dependencies if name in rules for line in rules[name][1])]


def _code_commands(content, python):
    commands = []
    if python:
        tree = ast.parse(content)
        argv_nodes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple)):
                try:
                    values = ast.literal_eval(node)
                except (ValueError, TypeError):
                    continue
                if values and all(isinstance(value, str) for value in values) and os.path.basename(values[0]) in COVERED:
                    commands.append(shlex.join(values))
                    argv_nodes.update(id(child) for child in ast.walk(node))
        commands.extend(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                        and isinstance(node.value, str) and id(node) not in argv_nodes)
    else:
        argv_spans = []
        for match in re.finditer(r"\[(\s*['\"](?:[^\]]|\n)*?)\]", content):
            try:
                values = ast.literal_eval("[" + match.group(1) + "]")
            except (ValueError, SyntaxError):
                continue
            if values and all(isinstance(value, str) for value in values) and os.path.basename(values[0]) in COVERED:
                commands.append(shlex.join(values))
                argv_spans.append(match.span())
        for match in re.finditer(r"(['\"`])((?:\\.|(?!\1)[^\\])*?)\1", content, re.S):
            if not any(start <= match.start() < end for start, end in argv_spans):
                commands.append(match.group(2))
    return [command for command in commands if COVERED_WORD.match(command.lstrip())
            or re.match(r"/[^\s]+/(?:" + "|".join(COVERED) + r")(?:\s|$)", command.lstrip())]


def _local_database(cli, args, env):
    host = option_value(args, "-h", ("--host",)) or (env.get("PGHOST") if cli == "psql" else None)
    if cli == "redis-cli":
        url = option_value(args, "-u", ("--uri",))
        host = _split_url(url).hostname if url else host
    if cli in ("psql", "mongosh", "mysql"):
        for arg in args:
            if "://" in arg:
                host = _split_url(arg).hostname
            elif cli == "psql":
                match = re.search(r"(?:^|\s)host=([^\s]+)", arg)
                if match:
                    host = match[1]
    if cli == "mysql":
        host = option_value(args, "-S", ("--socket",)) or host
    return isinstance(host, str) and (host.lower() in ("localhost", "127.0.0.1", "::1") or host.startswith("/"))


DISCARD_LABEL = "Removal that discards uncommitted work"
INERT_PROGRAMS = frozenset({"cd", "ls", "pwd", "echo", "printf", "true", "false", "wc", "du", "df", "sleep", "[", "[[",
                            "test", ":", "for", "dirname", "basename", "shopt"})
READER_BLOCKED_PROGRAMS = frozenset(COVERED - {"git"}) | SHELLS


def _read_verdict(cli, args, verdict):
    """Whether the guard classified one simple command as a local read: its kind `read`, or one of its filter programs
    (`head`, `tail`, `grep`, and the others). Remote and infrastructure programs other than `git`, shells, and Python are
    never accepted here."""
    if cli in READER_BLOCKED_PROGRAMS or PYTHON.fullmatch(cli):
        return False
    if verdict.kind == "read":
        return True
    return verdict.kind == "pass" and verdict.exe in FILTERS and not _filter_may_write(verdict.exe, args)


def _inert_command(cli, args, raw_args, cwd, env, variables, choices, assignments):
    """Whether one simple command is inert or writes only inside a temporary root: the structure and test words of the
    shell, `cd`, `echo`, `printf`, and other commands that only print, `rm` (judged by its own trace), `mkdir` of
    static folders strictly inside a temporary root, `mktemp -d`, and `sh|bash|zsh -c` with a parseable script (whose
    commands are judged on their own)."""
    if any(PATH_ALTERING_NAMES.fullmatch(name) for name in assignments):
        return False
    if any(_unmodeled_expansion(arg) for arg in (cli, *args)) or cli != os.path.basename(cli):
        return False
    if cli == "rm" or cli in INERT_PROGRAMS:
        return not (cli == "printf" and "-v" in args)
    if cli == "mktemp":
        return all(arg in ("-d", "-u", "--directory") for arg in args)
    if cli == "mkdir":
        return _mkdir_inside_temporary_root(args, raw_args, cwd, {**env, **variables}, choices)
    if cli in SHELLS:
        script = _shell_c(args)
        if not script:
            return False
        try:
            tokenize(script)
        except ParseError:
            return False
        return True
    return False


def _command_trace_entry(cli, args, raw_args, cwd, env, variables, choices, assignments):
    """The trace entry of one simple command: True when it is inert or a write confined to a temporary root, False when
    nothing can accept it, None when it is acceptable only if the guard classifies it as a local read."""
    if any(PATH_ALTERING_NAMES.fullmatch(name) for name in assignments):
        return False
    if any(_unmodeled_expansion(arg) for arg in (cli, *args)) or cli != os.path.basename(cli):
        return False
    if _inert_command(cli, args, raw_args, cwd, env, variables, choices, assignments):
        return True
    if _confined_command(cli, args, raw_args, cwd, env, variables, choices, assignments):
        return True
    return None


def _execution_policy(cli, args, cwd, env, variables, command, choices=None, raw_args=None):
    session = Path(env.get("_APPROVAL_SESSION_DIR", env.get("CLAUDE_PROJECT_DIR") or cwd)).resolve()
    target = lambda kind, label, every_time=False: Outcome(kind, [f"{cli}:{_digest(command)}"], [label],
                                                            every_time=every_time)
    positional = [arg for arg in args if not arg.startswith("-")]
    if (cli in ("npm", "pnpm", "yarn", "uv", "poetry", "cargo") and "publish" in positional
            or cli == "twine" and "upload" in positional or cli == "gem" and "push" in positional):
        return target("always", f"{cli} package publishing", True)
    codex_options = {"-c", "--config", "-C", "--cd", "--add-dir", "-s", "--sandbox", "-m", "--model", "-p",
                     "--profile", "-i", "--image", "-a", "--ask-for-approval", "--enable", "--disable",
                     "--local-provider", "-o", "--output-last-message", "--output-schema"}
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in codex_options else 1
    worker = cli == "codex" and args[index:index + 1] in (["exec"], ["e"])
    runner = PYTHON.fullmatch(cli) and any(arg == "scripts/role_runner.py" or arg.endswith("/scripts/role_runner.py") for arg in args)
    if cli == "codex":
        settings = option_values(args, "-c", ("--config",))
        if (_has_flag(args, "--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust")
                or "danger-full-access" in option_values(args, "-s", ("--sandbox",))
                or any(value and re.search(r"sandbox[^=]*=.*danger-full-access", value) for value in settings)):
            return target("always", "Codex access without sandbox protection", True)
    if worker or runner:
        directories = option_values(args, longs=("--add-dir",))
        if worker:
            directories += option_values(args, "-C", ("--cd",))
        for directory in directories:
            resolved = _script_path(directory or "$UNKNOWN", cwd, {**env, **variables})
            if resolved is None or not resolved.is_relative_to(session):
                return target("write", "Worker access outside the session folder")
        if runner:
            return Outcome("pass", [], [])
    if (cli == "rm" and approval_state.session_scope() and _rm_discards(args, cwd, env, variables, choices, raw_args)
            or cli == "find" and approval_state.session_scope() and _find_discards(args, cwd, env)):
        return Outcome("always", [f"{cli}:{_digest(command)}"], [DISCARD_LABEL], every_time=True, critical=True)
    if cli == "rm":
        flags = [arg for arg in args if arg.startswith("-")]
        recursive = "--recursive" in flags or any(not arg.startswith("--") and set(arg[1:]) & {"r", "R"} for arg in flags)
        if not recursive:
            _trace_removal(False)
            return Outcome("pass", [], [])
        values = {**env, **variables}
        outside, in_temporary_root = [], True
        for position, operand in enumerate(args):
            if operand.startswith("-"):
                continue
            texts = _operand_texts(operand, values, choices)
            if texts is None:
                return target("always", "Recursive removal with an unresolved target", True)
            raw = raw_args[position] if raw_args is not None and position < len(raw_args) else operand
            if _unquoted_reference(raw) and _mktemp_directory(operand, values) is None:
                if "IFS" in (choices or {}) or "IFS" in variables or re.search(r"\s", operand):
                    return target("always", "Recursive removal with an unresolved target", True)
                texts = [field for text in texts for field in text.split()]
            for expanded in texts:
                if not expanded:
                    continue
                head, tail = os.path.split(expanded)
                if re.search(r"[*?\[]", tail) and not re.search(r"[*?\[]", head) and re.search(r"[^*?.\[\]]", tail):
                    if fnmatch.fnmatch(".git", tail) and (
                            re.search(r"[A-Za-z]", re.sub(r"\[[^\]]*\]", "", tail)) or _holds_git_entry(cwd, head)):
                        return target("always", "Recursive removal of a protected or external path", True)
                    link = Path(cwd) / os.path.expanduser(head or ".")
                    path = link.resolve() / "_"
                    covering = path.parent
                else:
                    fixed = re.split(r"[*?\[]", expanded, maxsplit=1)[0]
                    if fixed != expanded and not fixed.endswith("/"):
                        fixed = str(Path(fixed).parent)
                    link = Path(cwd) / os.path.expanduser(fixed or ".")
                    path = covering = link.resolve()
                temporary = guard_paths._temporary(path, env)
                emptied = covering if not re.search(r"[*?\[]", expanded) or not re.search(r"\w", tail) else path
                if (path == Path("/") or path == Path.home() or path == session or path in session.parents
                        or ".git" in path.parts or temporary and _shared_temporary(emptied, env)):
                    return target("always", "Recursive removal of a protected or external path", True)
                in_temporary_root = in_temporary_root and _inside_temporary_root(
                    covering, int(bool(re.search(r"[*?\[]", expanded))))
                if not (path.is_relative_to(session) or temporary or _evaluation_scratch(covering, expanded, cwd)):
                    outside.append((covering, link))
        if outside:
            labels = None if IN_EXEC in env or FILES_MAY_CHANGE in env else _removal_scope(outside, cwd, env)
            if labels is None:
                return target("always", "Recursive removal of a protected or external path", True)
            return Outcome("write", [f"{cli}:{_digest(command)}"], labels)
        _trace_removal(in_temporary_root)
        return Outcome("pass", [], [])
    return None


_PENDING_SCRIPTS = {}
PENDING_KEEPERS = frozenset({
    "cd", "mkdir", "echo", "printf", "true", "false", "test", "[", "[[", ":", "ls", "pwd", "wc", "head", "tail", "sort",
    "cut", "tr", "du", "stat", "grep", "egrep", "fgrep", "sleep", "read", "for", "case", "done", "fi", "esac", "chmod",
    "exit", "cat",
})


def _heredoc_scripts(text):
    """The bodies of quoted-delimiter heredocs that a lone `cat` writes to one file, by the start of that `cat`, and the
    text spans of those bodies with their closing delimiter lines."""
    if "<<" not in text:
        return {}, []
    lines = text.splitlines(keepends=True)
    found, spans, index, offset = {}, [], 0, 0
    while index < len(lines):
        line = lines[index]
        base = offset
        offset += len(line)
        index += 1
        if "<<" not in line:
            continue
        try:
            tokens = _lex(line)
        except ParseError:
            continue
        documents = []
        for position, token in enumerate(tokens[:-1]):
            if token[0] == "op" and token[1] == "<<" and tokens[position + 1][0] == "word":
                delimiter = tokens[position + 1][1]
                tabs = line[token[3]:token[3] + 1] == "-"
                raw = line[tokens[position + 1][2]:tokens[position + 1][3]]
                documents.append((position, delimiter[1:] if tabs else delimiter, tabs,
                                  any(char in raw for char in "'\"\\")))
        bodies, opened = [], offset
        for _position, delimiter, tabs, _quoted in documents:
            body = []
            while index < len(lines):
                candidate = lines[index].rstrip("\r\n")
                index += 1
                offset += len(lines[index - 1])
                if (candidate.lstrip("\t") if tabs else candidate) == delimiter:
                    bodies.append("".join(item.lstrip("\t") if tabs else item for item in body))
                    break
                body.append(lines[index - 1])
            else:
                bodies.append(None)
        if len(documents) != 1 or not documents[0][3] or bodies[0] is None:
            continue
        start = _lone_cat_start(tokens, documents[0][0])
        if start is not None:
            found[base + start] = bodies[0]
            spans.append((opened, offset))
    return found, spans


def _lone_cat_start(tokens, document):
    """The start of the command that holds the heredoc at `document` when it is a plain `cat` with exactly that heredoc
    and one `>` file output, not piped; else None."""
    groups, separators = [[]], []
    for position, token in enumerate(tokens):
        if token[0] == "op" and token[1] in SEPARATOR_OPERATORS:
            groups.append([])
            separators.append(token[1])
        else:
            groups[-1].append((position, token))
    for number, group in enumerate(groups):
        if not any(position == document for position, _ in group):
            continue
        neighbours = separators[max(number - 1, 0):number + 1]
        if any(separator in PIPE_OPERATORS for separator in neighbours):
            return None
        words, operators, cursor = [], [], 0
        while cursor < len(group):
            token = group[cursor][1]
            if token[0] == "word":
                words.append(token[1])
                cursor += 1
            elif cursor + 1 < len(group) and group[cursor + 1][1][0] == "word":
                operators.append(token[1])
                cursor += 2
            else:
                return None
        if words == ["cat"] and sorted(operators) == ["<<", ">"] and group[0][1][0] == "word":
            return group[0][1][2]
    return None


def _runs_unconditionally(index, segments, operators):
    """Whether segment `index` always runs: it follows nothing or `;`, or a chain of `&&` that only `mkdir` and `cd`
    precede, and it is not sent to the background or a pipe."""
    segment = segments[index]
    after = min((op for op in operators if op[2] >= segment.end), key=lambda op: op[2], default=None)
    if after is not None and after[1] not in (";", "&&"):
        return False
    while True:
        before = max((op for op in operators if op[3] <= segment.start), key=lambda op: op[3], default=None)
        if before is None or before[1] == ";":
            return True
        if before[1] != "&&" or index == 0:
            return False
        index -= 1
        segment = segments[index]
        words, _ = strip_prefix(segment.words)
        if not words or os.path.basename(words[0]) not in ("mkdir", "cd"):
            return False


def _keeps_pending(segment, program, region, cwd, variables):
    """Whether a segment leaves the files written earlier in the same command unchanged: no substitution or file
    redirect, and either a command that cannot modify a file or the run of a pending script itself."""
    if re.search(r"\$\(|`|[<>]\(", region) or not _redirects_allowed([segment]):
        return False
    if not program:
        return True
    name = os.path.basename(program[0])
    if name == "sort" and any(re.match(r"-[^-]*o|--output", arg) for arg in program[1:]):
        return False
    if name in PENDING_KEEPERS:
        return True
    operand = (program[0] if program[0].startswith(("./", "/")) else
               _first_operand(program[1:]) if PYTHON.fullmatch(name) or name in SHELLS else None)
    return operand is not None and _script_path(operand, cwd, variables) in _PENDING_SCRIPTS


def _made_directories(program, cwd, variables):
    paths = set()
    for arg in program[1:]:
        if not arg.startswith("-"):
            path = _script_path(arg, cwd, variables)
            if path is not None:
                paths.update((path, *path.parents))
    return paths


def _aggregate(verdicts, segments):
    if any(verdict.kind == "secret" for verdict in verdicts):
        return Outcome("secret", [], [])
    always = [verdict for verdict in verdicts if verdict.kind == "always"]
    writes = [verdict for verdict in verdicts if verdict.kind == "write"]
    if any(verdict.kind == "forbidden" for verdict in verdicts):
        return next(verdict for verdict in verdicts if verdict.kind == "forbidden")
    sensitive = [verdict for verdict in verdicts if verdict.kind == "sensitive"]
    if sensitive:
        return _merge("sensitive", [*sensitive, *always], writes)
    if always:
        return _merge("always", always, writes)
    if writes:
        return _merge("write", writes)
    reads = any(verdict.kind == "read" for verdict in verdicts)
    filters_only = all(
        verdict.kind == "read" or (verdict.kind == "pass" and verdict.exe in FILTERS) for verdict in verdicts
    )
    if reads and filters_only and _redirects_allowed(segments):
        psql = any(verdict.kind == "read" and verdict.exe == "psql" for verdict in verdicts)
        return Outcome("read", [], [], "psql" if psql else None)
    return Outcome("pass", [], [])
