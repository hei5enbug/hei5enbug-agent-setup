"""The recursive command classifier of the approval guard."""
import ast
import copy as copy_module
import json
import os
import re
import shlex
from pathlib import Path
import approval_state
from approval_state import Outcome
from guard_shell import (
    ASSIGNMENT, COVERED, GLOBAL_VALUE_OPTIONS, PYTHON, ParseError, SHELLS, SHELL_KEYWORDS, WRAPPER, _blank, _call,
    _cd_changes_directory, _chained_by_and, _destructive, _destructive_text, _digest, _expansion_regions,
    _followed_by_and, _helper_args, _heredoc_data, _lex, _read, _redirects_allowed, _shell_c, _shell_wrapper_script,
    _substitution_end, _substitution_spans, _unclassified, _unrecognized_wrapper, _without_data, option_value,
    strip_prefix, subcommand_words, tokenize, unwrap_wrapper,
)
from guard_paths import (
    MKTEMP_OPERAND, _expand_path_variables, _heredoc_cwd, _protected_argument, _protected_path, _python_inline_code,
    _script_path, _sensitive, _static_value,
)
from guard_expand import (
    COVERED_WORD, ENVIRONMENT_CHANGERS, FLOW_ENVIRONMENT, SCRIPT_FOLDER, SCRIPT_FOLDER_KEY, VARIABLE_WRITERS,
    _ValueFlow, _covered_only_as_commands, _expand_segment_words, _plain_environment_edit, _script_seed,
    _shell_c_seed, _unconditional_assignment, _value_lookup,
)
from guard_reads import (
    PATH_ALTERING_NAMES, SECRET_NAME, _awk_filter, _changes_environment, _environment_filter, _indirect_regions,
    _only_plain_environment_changes, _prints_no_content, _xargs_argv, _xargs_input_is_inert, _xargs_list_read,
)
import guard_temp
from guard_temp import _redirects_write_only_inside_temporary_root, _temp_segment, _trace_command
from guard_git import COMMAND_GIT_CONFIG, FILES_MAY_CHANGE, IN_EXEC, STASH_OWN_DROP, _DISCARD_CACHE, _git_gh
from guard_cloud import Rules, _classify_curl, _classify_sql, _docker_metadata_inspect, _local_engine
from guard_self import CLI_RULES, MAX_DEPTH, PYTHON_EXEC, _code_runs_guard, _first_operand, _request_outcome
from guard_pyread import _git_run_command, _read_only_python
from guard_pyrisk import credential_read, secret_environment
from guard_installed import INSTALLED_CODE_REASON, installed_code_write, python_writes_installed_code
from guard_pywrite import _confine_writes, _documents_only, _exec_files_confined
from guard_proof import SELF_APPROVAL_REASON, _self_approval
from guard_scripts import (
    FILTERS, MAX_SCRIPT_BYTES, _PENDING_SCRIPTS, _aggregate, _code_commands, _command_trace_entry, _execution_policy,
    _heredoc_scripts, _keeps_pending, _local_database, _made_directories, _make_recipes, _read_verdict,
    _runs_unconditionally, _script_content, _script_unknown,
)
from guard_own import (
    BLOCK_CLOSERS, BLOCK_OPENERS, REDIRECTED, SCRIPTS_STABLE, _ARCHIVE_COPIES, _archive_fill, _confined_python_writes,
    _in_archive, _keeps_archive, _may_write_own_path, _own_export_run, _own_node_check, _own_repo_script,
    _own_stash_drops, _stdin_filter,
)


SDK_IMPORT = re.compile(
    r"\b(?:import|from|require)\b[^\n;]*(?:boto3|azure|kubernetes|psycopg2?|pymysql|sqlalchemy|pymongo|redis|google\.cloud)\b"
)
DESTRUCTIVE_COMMAND = re.compile(
    r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*(?:\s--force\b|\s-[A-Za-z]*f[A-Za-z]*(?=\s|$)|\s\+)"
    r"|(?<![\w-])dd\b[^\n;&|]*\sof="
    r"|(?<![\w-])mkfs(?:\.\w+)?\b"
)
FILE_READS = frozenset({"cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg"})


def classify_cli(cli, args, env, cwd, command, depth=0):
    if cli in ("git", "gh"):
        return _git_gh(cli, args, command, cwd, env)
    if cli == "curl":
        return _classify_curl(args, command)
    kind = subcommand_words(args)
    if ((cli in ("docker", "podman") and "inspect" in kind[:2] and not _docker_metadata_inspect(cli, kind, args, env))
            or (cli in ("kubectl", "oc", "docker", "podman") and "exec" in kind
                and any(os.path.basename(arg) in ("env", "printenv") for arg in args))):
        return _sensitive(command)
    rules = CLI_RULES[cli](kind, args, env, cwd) if cli in CLI_RULES else Rules()
    if rules.secret:
        return Outcome("secret", [], [])
    local = cli in ("docker", "podman") and _local_engine(args, env, cli)
    if cli in ("kubectl", "oc", "docker", "podman") and kind[:1] == ["exec"]:
        if "--" in args:
            inner_args = args[args.index("--") + 1:]
        else:
            index = args.index("exec") + 1
            value_options = GLOBAL_VALUE_OPTIONS | {"-c", "--container", "-u", "--user", "-w", "--workdir",
                                                    "-e", "--env", "--env-file", "--detach-keys"}
            while index < len(args) and args[index].startswith("-"):
                index += 2 if args[index] in value_options else 1
            inner_args = args[index + 1:]
        inner = shlex.join(inner_args)
        verdict = classify_text(inner, cwd, depth + 1, {**env, FILES_MAY_CHANGE: "1", IN_EXEC: "1"})
        if verdict.kind == "secret":
            return verdict
        remote_action = _destructive_text(inner) or DESTRUCTIVE_COMMAND.search(inner)
        if verdict.kind == "always":
            removal = bool(verdict.descriptions) and all(text.startswith("Recursive removal") for text in verdict.descriptions)
            if local and removal and not remote_action:
                return _call("write", cli, kind, rules.target, command)
            return verdict._replace(every_time=True)
        if (re.search(r"(?:^|[\s;&|('\"`])(?:rm|rmdir|shred|mkfs(?:\.\w+)?|truncate)(?=\s|$)", inner)
                or re.search(r"\bdd\b[^;&|]*\bof=", inner) or _destructive_text(inner)):
            return _call("write" if local and not remote_action else "always", cli, kind, rules.target, command)
    if kind and (re.search(r"\$(?:[A-Za-z_]|\{)", kind[0]) or "$(" in kind[0] or "`" in kind[0]):
        return _unclassified(cli, command)
    if cli == "kustomize":
        return _read()
    if cli in ("psql", "mysql", "redis-cli", "mongosh") and _local_database(cli, args, env):
        return Outcome("pass", [], [])
    if cli in ("psql", "sqlcmd"):
        return _classify_sql(cli, args, env, cwd, command)
    if cli not in CLI_RULES:
        return _unclassified(cli, command)
    if rules.dry_run:
        return _read()
    if rules.sensitive:
        return _sensitive(command)
    if rules.write and not rules.read:
        return _call("write", cli, kind, rules.target, command)
    if rules.always or _destructive(kind):
        return _call("write" if local and not rules.always else "always", cli, kind, rules.target, command,
                     rules.critical)
    if rules.read:
        return _read()
    return _call("write", cli, kind, rules.target, command)


def _classify_helper(args, cwd, depth, command, env=None):
    if "--" not in args:
        return _unclassified("secret_exec", command)
    inner, _ = strip_prefix(args[args.index("--") + 1:])
    if not inner:
        return _unclassified("secret_exec", command)
    if os.path.basename(inner[0]) in SHELLS:
        script = _shell_c(inner[1:])
        if script is not None:
            return classify_text(script, cwd, depth + 1, env) if script else _unclassified("secret_exec", command)
    return _classify_argv(inner, False, cwd, depth + 1, command, env)


TEMP_WRITE_EXE = "temp-write"
INSTALLED_WRITERS = frozenset({"cp", "mv", "install", "rsync", "ln", "tee", "sed"})
OPERAND_READERS = FILE_READS | FILTERS | frozenset({
    "sed", "file", "stat", "ls", "find", "base64", "xxd", "od", "strings", "diff", "cmp", "tar", "zip", "unzip",
})
GIT_CONFIG_WORD = re.compile(r"GIT_CONFIG_[A-Z0-9_]+")
FILE_INERT = frozenset({"[", "[[", "test", ":", "true", "false"})


def _git_read_runs(processes, cwd, depth, env):
    """The `subprocess.run` calls among `processes` when every process call is one with a literal git argv that the guard
    classifies as a read, else None."""
    for call in processes:
        command = _git_run_command(call)
        if command is None or classify_text(command, cwd, depth + 1, env).kind != "read":
            return None
    return frozenset(processes)


def _git_reads_with_temp_writes(tree, processes, cwd, depth, cwd_known, env):
    """Whether a script runs only literal read-only git commands and writes only to temporary space, and the rest is
    read-only Python. The check works on a copy of `tree`, because confining writes rewrites them."""
    copy = copy_module.deepcopy(tree)
    order = {id(node): index for index, node in enumerate(ast.walk(tree))}
    nodes = list(ast.walk(copy))
    mapped = [nodes[order[id(node)]] for node in processes]
    runs = _git_read_runs(mapped, cwd, depth, env)
    return (runs is not None and _confine_writes(copy, cwd, cwd_known, env)
            and _read_only_python(copy, runs))


def _python_risk(code, cwd, env):
    """The outcome for Python code, given as text or as a parsed tree, that writes installed plugin code or exposes a
    credential, or None."""
    try:
        tree = ast.parse(code) if isinstance(code, str) else code
    except (SyntaxError, ValueError):
        return None
    if python_writes_installed_code(tree, cwd, env):
        return Outcome("forbidden", [], [INSTALLED_CODE_REASON])
    exposure = credential_read(tree, cwd, env) or secret_environment(tree)
    return _sensitive(exposure) if exposure else None


def _python_policy(content, cwd, depth, env, readonly=False, cwd_known=True):
    if _code_runs_guard(content):
        return Outcome("forbidden", [], [SELF_APPROVAL_REASON])
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _unclassified("python", content) if PYTHON_EXEC.search(content) or SDK_IMPORT.search(content) else Outcome("pass", [], [])
    risk = _python_risk(tree, cwd, env)
    if risk is not None:
        return risk
    if not _exec_files_confined(ast.parse(content), cwd, cwd_known, env):
        return Outcome("write", ["python:" + _digest(content)], ["Python process or SDK execution"])
    imports = "\n".join(ast.unparse(node) for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name.split(".")[0]] = name.name
        elif isinstance(node, ast.ImportFrom):
            for name in node.names:
                aliases[name.asname or name.name] = (node.module or "") + "." + name.name
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    processes = []
    for node in calls:
        function = ast.unparse(node.func)
        root, separator, rest = function.partition(".")
        function = aliases.get(root, root) + (separator + rest if separator else "")
        if PYTHON_EXEC.search(function):
            processes.append(node)
    sdk = bool(SDK_IMPORT.search(imports))
    if not processes and not sdk:
        return _read() if readonly and _read_only_python(tree) else Outcome("pass", [], [])
    if readonly and processes and not sdk:
        runs = _git_read_runs(processes, cwd, depth, env)
        if runs is not None and _read_only_python(tree, runs):
            return _read()
        if runs is not None and _git_reads_with_temp_writes(tree, processes, cwd, depth, cwd_known, env):
            return Outcome("pass", [], [])
    values = {node.targets[0].id: node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    commands = []
    for call in processes:
        arguments = [*call.args, *(keyword.value for keyword in call.keywords
                                  if keyword.arg in ("args", "cmd", "command"))]
        for arg in arguments:
            if isinstance(arg, ast.Name):
                arg = values.get(arg.id, arg)
            try:
                value = ast.literal_eval(arg)
            except (ValueError, TypeError):
                continue
            if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
                commands.append(shlex.join(value))
            elif isinstance(value, str):
                commands.append(value)
    verdicts = [classify_text(command, cwd, depth + 1, env) for command in commands]
    if any(verdict.kind in ("secret", "forbidden", "sensitive", "always") for verdict in verdicts):
        return _aggregate(verdicts, [])
    destructive = (_destructive_text(content) or sdk and any(
        re.search(r"delete|purge|drop|truncate|destroy", ast.unparse(call.func), re.I) for call in calls))
    return Outcome("always" if destructive else "write", ["python:" + _digest(content)], ["Python process or SDK execution"],
                   every_time=bool(destructive))


LOOP_OPENERS = frozenset({"while", "until", "for", "select"})


def _classify_script(words, cwd, depth, env, variables=None, choices=None, plain=False):
    cli = os.path.basename(words[0])
    args = words[1:]
    path = None
    mode = "shell"
    if cli in SHELLS and _shell_c(args) is None:
        path = _first_operand(args)
    elif cli in ("source", "."):
        path = args[0] if args else None
    elif words[0].startswith(("./", "/")) and cli not in COVERED and not PYTHON.fullmatch(cli):
        path = words[0]
        mode = "python" if path.endswith(".py") else "executable"
    elif PYTHON.fullmatch(cli) and args and not any(arg in ("-c", "-m") or arg.startswith(("-c", "-m")) for arg in args):
        path, mode = _first_operand(args), "python"
    elif cli == "node" and args and args[0].endswith((".js", ".mjs")):
        return Outcome("pass", [], [])
    elif cli == "make":
        path, mode = "Makefile", "make"
    elif cli in ("npm", "pnpm", "yarn") and len(args) >= 2 and args[0] == "run":
        path, mode = "package.json", "package"
    if path is None:
        return None
    resolved = _script_path(path, cwd, variables or {})
    if resolved is not None and mode == "python" and resolved.suffix == ".py" and _in_archive(resolved):
        script_args = args if path == words[0] else args[args.index(path) + 1:]
        if not any(re.search(r"[$`*?\[{~]", arg) for arg in script_args):
            return Outcome("pass", [], [])
    if resolved is None:
        return _script_unknown(path, words, env, "unresolved path")
    if resolved == Path(WRAPPER):
        return _unrecognized_wrapper(" ".join(words))
    root = Path(__file__).resolve().parents[1]
    refresh = root / "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py"
    if (PYTHON.fullmatch(cli) and len(args) >= 2 and args[0] == path and args[1] == "status"
            and resolved == refresh):
        return _read()
    if (PYTHON.fullmatch(cli) and len(args) >= 2 and args[0] == path and args[1] in ("check", "apply")
            and resolved == root / "scripts/host_settings.py"):
        if args[1] == "check":
            return _read()
        return Outcome("write", [approval_state.WRITE_KEY], ["Apply plugin host settings"])
    if depth >= MAX_DEPTH:
        return _script_unknown(resolved, words, env, "recursion limit")
    try:
        pending = _PENDING_SCRIPTS.pop(resolved, None)
        content = pending if pending is not None else _script_content(resolved)
        if mode == "executable":
            header = content.splitlines()[0] if content else ""
            if re.match(r"#!.*\bpython[\d.]*\b", header):
                mode = "python"
            elif re.match(r"#!.*\b(?:sh|bash|zsh)\b", header) or resolved.suffix in (".sh", ".bash", ".zsh"):
                mode = "shell"
            else:
                return Outcome("pass", [], [])
        if mode == "python":
            script_args = args if path == words[0] else args[args.index(path) + 1:]
            if pending is None and _own_export_run(resolved, script_args, env):
                return Outcome("pass", [], [])
            if (pending is None and not any(_protected_argument(arg, cwd, env) for arg in script_args)
                    and _own_repo_script(resolved, plain, env)):
                return Outcome("pass", [], [])
            argv =[_script_path(arg, cwd, variables or {}) for arg in script_args]
            if pending is not None and not _confined_python_writes(pending, cwd, env, argv, resolved):
                return _python_risk(pending, cwd, env) or _script_unknown(resolved, words, env, "unreadable")
            readonly = not any(_protected_argument(arg, cwd, env) for arg in args)
            verdict = _python_policy(content, cwd, depth, env, readonly)
            if verdict.kind in ("write", "always"):
                verdict = verdict._replace(keys=_script_unknown(resolved, words, env, content).keys)
            return verdict
        if mode == "make":
            commands = _make_recipes(content, _first_operand(args))
        elif mode == "package":
            scripts = json.loads(content)["scripts"]
            commands = [scripts[name] for name in ("pre" + args[1], args[1], "post" + args[1]) if name in scripts]
            if args[1] not in scripts or not all(isinstance(command, str) for command in commands):
                raise ValueError("unknown package script")
        elif mode in ("python", "node"):
            commands = _code_commands(content, mode == "python")
        else:
            commands = [line for line in _heredoc_data(content).replace("\\\n", "").splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
    except UnicodeError:
        return Outcome("pass", [], []) if mode == "executable" else _script_unknown(resolved, words, env, "unreadable")
    except (OSError, ValueError, SyntaxError, KeyError, TypeError):
        if mode == "executable":
            return Outcome("pass", [], [])
        return _script_unknown(resolved, words, env, locals().get("content", "unreadable"))
    if ((mode == "python" and _code_runs_guard(content))
            or any(_self_approval(command) for command in commands)):
        return Outcome("forbidden", [], [SELF_APPROVAL_REASON])
    verdicts = None
    if mode == "shell":
        text = "\n".join(commands)
        positional = args if path == words[0] else args[args.index(path) + 1:]
        invoked = Path(os.path.abspath(
            Path(cwd) / os.path.expanduser(_expand_path_variables(path, variables or {}))))
        seed = _script_seed(invoked, positional, _value_lookup(choices, {**env, **(variables or {})}))
        try:
            tokenize(text)
            verdicts = [classify_text(text, cwd, depth + 1, env, None, None, seed)]
        except ParseError:
            pass
    if verdicts is None:
        verdicts = [classify_text(command, cwd, depth + 1, env) for command in commands]
    covered = [verdict for verdict in verdicts if verdict.kind != "pass"]
    if covered:
        return _aggregate(covered, [])
    inspected = "\n".join(commands) if mode in ("make", "package") else content
    if mode == "shell":
        inspected = _heredoc_data(inspected)
    if COVERED_WORD.search(inspected) or SDK_IMPORT.search(inspected):
        return _script_unknown(resolved, words, env, content)
    return Outcome("pass", [], [])


def _classify_argv(words, heredoc, cwd, depth, command, inherited_env=None, variables=None, choices=None,
                   raw=None):
    slot = len(guard_temp._COMMAND_TRACE) if guard_temp._COMMAND_TRACE is not None else None
    verdict = _classify_words(words, heredoc, cwd, depth, command, inherited_env, variables, choices, raw)
    if slot is not None and slot < len(guard_temp._COMMAND_TRACE) and guard_temp._COMMAND_TRACE[slot] is None:
        stripped, _ = strip_prefix(words)
        guard_temp._COMMAND_TRACE[slot] = _read_verdict(os.path.basename(stripped[0]), stripped[1:], verdict)
    return verdict


def _classify_words(words, heredoc, cwd, depth, command, inherited_env=None, variables=None, choices=None,
                    raw=None):
    helper = _helper_args(words)
    if helper is not None:
        _trace_command(False)
        return _classify_helper(helper, cwd, depth, command, inherited_env)
    stripped, assignments = strip_prefix(words)
    if not stripped:
        _trace_command(not any(PATH_ALTERING_NAMES.fullmatch(name) for name in assignments))
        if any(os.path.basename(word) == "env" for word in words):
            return _sensitive(command)
        return Outcome("pass", [], [])
    cli = os.path.basename(stripped[0])
    assignments = {key: _expand_path_variables(value, variables or {}) for key, value in assignments.items()}
    env = {**(os.environ if inherited_env is None else inherited_env), **assignments}
    if inherited_env is not None and "_APPROVAL_SESSION_DIR" in inherited_env:
        env["_APPROVAL_SESSION_DIR"] = inherited_env["_APPROVAL_SESSION_DIR"]
    if cli == "printenv":
        names = stripped[1:]
        if names and all(not name.startswith("-") and not SECRET_NAME.search(name) for name in names):
            return _read()
        return _sensitive(command)
    raw_args = raw[len(words) - len(stripped) + 1:] if raw is not None and len(raw) == len(words) else None
    if guard_temp._COMMAND_TRACE is not None:
        _trace_command(_command_trace_entry(cli, stripped[1:], raw_args, cwd, env, variables or {}, choices,
                                            assignments))
    policy = _execution_policy(cli, stripped[1:], cwd, env, variables or {}, command, choices, raw_args)
    if policy is not None:
        return policy
    if PYTHON.fullmatch(cli):
        code = _python_inline_code(stripped[1:])
        if code is None:
            code = option_value(stripped[1:], "-c")
        if code is not None:
            verdict = _python_policy(code, cwd, depth, env)
            if verdict.kind != "pass" or "--execute" not in stripped[1:]:
                return verdict
            return Outcome("write", ["python:execute"], ["Python execution with --execute"])
    if cli in FILE_READS and any(_protected_path(arg, cwd, env) for arg in stripped[1:] if not arg.startswith("-")):
        return _sensitive(command)
    script = _classify_script(stripped, cwd, depth, env, variables, choices, all(word in SHELL_KEYWORDS for word in words[:len(words) - len(stripped)]))
    if script is not None:
        if PYTHON.fullmatch(cli) and "--execute" in stripped[1:] and script.kind in ("pass", "read"):
            return Outcome("write", ["python:execute"], ["Python execution with --execute"])
        return script
    if PYTHON.fullmatch(cli) and "--execute" in stripped[1:]:
        return Outcome("write", ["python:execute"], ["Python execution with --execute"])
    if heredoc and (cli in COVERED or COVERED_WORD.search(command)):
        return _unclassified(cli, command)
    if cli not in COVERED:
        return Outcome("pass", [], [], None if cli == "awk" and not _awk_filter(stripped[1:]) else cli)
    args = stripped[1:]
    if cli == "az" and subcommand_words(args)[:1] == ["rest"]:
        args = list(args)
        for index, arg in enumerate(args):
            if index and args[index - 1] in ("--url", "--uri", "-u"):
                args[index] = _expand_path_variables(arg, variables or {})
            elif arg.startswith(("--url=", "--uri=", "-u")):
                args[index] = _expand_path_variables(arg, variables or {})
    return classify_cli(cli, args, env, cwd, command, depth)


def _process_substitutions(text, cwd, depth, env, variables):
    """Replace each unquoted `<(...)` by a same-length inert path, so that offsets stay valid, and classify the command
    inside it on its own. An unbalanced substitution leaves the text unchanged."""
    if "<(" not in text:
        return text, []
    pieces, verdicts, last, index, quote = [], [], 0, 0, None
    try:
        while index < len(text):
            char = text[index]
            if char == "\\" and quote != "'":
                index += 2
            elif quote == "'":
                quote = None if char == "'" else quote
                index += 1
            elif quote is None and text.startswith("<(", index) and text[index - 1:index] != "<":
                end = _substitution_end(text, index)
                verdicts.append(classify_text(text[index + 2:end - 1], cwd, depth + 1, env, variables))
                pieces.extend((text[last:index], "/" + "z" * (end - index - 1)))
                last = index = end
            elif text.startswith("$(", index) or char == "`":
                index = _substitution_end(text, index)
            else:
                if char in ("'", '"'):
                    quote = char if quote is None else None if quote == char else quote
                index += 1
    except ParseError:
        return text, []
    return "".join((*pieces, text[last:])), verdicts


def _python_documents(text, cwd, depth, env):
    """Blank the heredoc bodies that a plain `python3` reads and return the verdicts for them, plus those among them that
    can change only Markdown files in temporary space."""
    verdicts, spans, quiet = [], [], []
    pattern = re.compile(r"(?m)^([^\n]*?)<<[ \t]*(['\"]?)([A-Za-z_][\w]*)\2[^\n]*\n")
    for match in pattern.finditer(text):
        if any(start <= match.start() < stop for start, stop in spans):
            continue
        try:
            segments = tokenize(match[0])
            heredoc = match.end(1) - match.start()
            segment = next(item for item in segments if item.start <= heredoc < item.end)
            words, _ = strip_prefix(segment.words)
        except (ParseError, StopIteration):
            continue
        if (not words or not PYTHON.fullmatch(os.path.basename(words[0])) or "-c" in words
                or _python_inline_code(words[1:]) is not None):
            continue
        end = re.search(r"(?m)^" + re.escape(match[3]) + r"[ \t]*\r?$", text[match.end():])
        if end is None:
            continue
        body_end = match.end() + end.start()
        stdin_code = (all(arg.startswith("-") for arg in words[1:]) and "--execute" not in words
                      and not any(_protected_argument(arg, cwd, env) for arg in words[1:]))
        here, known = _heredoc_cwd(text[:match.start()], segments, segment, cwd)
        verdict = _python_policy(text[match.end():body_end], here, depth, env, stdin_code, known)
        if verdict.kind == "pass" and _documents_only(text[match.end():body_end], here, known, env):
            quiet.append(verdict)
        if verdict.kind in ("pass", "read") and "--execute" in words:
            verdict = Outcome("write", ["python:execute"], ["Python execution with --execute"])
        verdicts.append(verdict)
        tokens = _lex(match[0])
        following = next((token for token in tokens if token[0] == "op" and token[2] >= segment.end), None)
        receiver = next((item for item in segments if item.start > segment.end), None)
        receiver_words, _ = strip_prefix(receiver.words) if receiver else ([], {})
        if (following and following[1] in ("|", "|&") and receiver_words
                and os.path.basename(receiver_words[0]) in SHELLS and _shell_c(receiver_words[1:]) is None):
            verdicts.append(_unclassified("python pipe to shell", text[match.start():body_end]))
        if not match[2]:
            for start, stop in _expansion_regions(text, match.end(), body_end):
                for _, _, body in _substitution_spans(text[start:stop]):
                    verdicts.append(classify_text(body, cwd, depth + 1, env))
        spans.append((match.start() + segment.start, match.end(3) + len(match[2])))
        spans.append((match.end(), match.end() + end.end()))
    return _blank(text, spans), verdicts, quiet


def _wrapper_outcome(text, cwd, depth, env, variables):
    """Classify a command that names the wrapper: a shell call with one plain word by that word's text, anything else
    asks every time. None when the command does not name the wrapper."""
    if WRAPPER not in text:
        return None
    script = _shell_wrapper_script(text)
    if script is not None:
        return classify_text(script, cwd, depth + 1, env, variables)
    return _unrecognized_wrapper(text)


def classify_text(text, cwd, depth=0, env=None, variables=None, statics=None, choices=None):
    """Classify a shell command string; the secret helper's own inner command is classified separately."""
    if depth > MAX_DEPTH:
        return _unclassified("bash", text if isinstance(text, str) else "")
    if not isinstance(text, str) or not text.strip():
        return Outcome("pass", [], [])
    if depth == 0:
        _DISCARD_CACHE.clear()
        _PENDING_SCRIPTS.clear()
        _ARCHIVE_COPIES.clear()
    script = unwrap_wrapper(text)
    if script is not None:
        return classify_text(script, cwd, depth + 1, env, variables)
    named = _wrapper_outcome(text, cwd, depth, env, variables)
    if named is not None:
        return named
    if depth == 0:
        request = _request_outcome(text, cwd)
        if request is not None:
            return request
    environment = dict(os.environ if env is None else env)
    environment.pop(STASH_OWN_DROP, None)
    if depth == 0 or "_APPROVAL_SESSION_DIR" not in environment:
        environment["_APPROVAL_SESSION_DIR"] = environment.get("CLAUDE_PROJECT_DIR") or cwd
    filtered = _environment_filter(text)
    if filtered is not None:
        return filtered
    heredoc_scripts, script_bodies = _heredoc_scripts(text)
    text = _heredoc_data(text)
    text, python_verdicts, quiet_verdicts = _python_documents(text, cwd, depth, environment)
    text, substitution_verdicts = _process_substitutions(text, cwd, depth, environment, variables)
    python_verdicts = [*python_verdicts, *substitution_verdicts]
    try:
        segments = tokenize(text)
        operators = [token for token in _lex(text) if token[0] == "op"]
    except ParseError:
        _trace_command(False)
        match = COVERED_WORD.search(_without_data(text))
        return _unclassified(match.group(0), text) if match else Outcome("pass", [], [])
    filtered_segments = {}
    start = 0
    boundaries = [(token[2], token[3]) for token in operators if token[1] in (";", "&&", "||")]
    changes_environment = "()" in text or any(_changes_environment(segment) for segment in segments)
    names_only = changes_environment and "()" not in text and _only_plain_environment_changes(segments)
    if boundaries and (not changes_environment or names_only):
        for end, following in [*boundaries, (len(text), len(text))]:
            filtered = _environment_filter(text[start:end].strip(), names_only=changes_environment)
            if filtered is not None:
                members = [segment for segment in segments if start <= segment.start < end]
                for index, segment in enumerate(members):
                    filtered_segments[segment.start] = filtered if index == 0 else None
            start = following
    spans = [(segment.start, segment.end) for segment in segments if _helper_args(segment.words) is not None]
    checked = _blank(text, spans)
    verdicts = list(python_verdicts)
    variables = dict(variables or {})
    statics = dict(statics or {})
    recording = not any(operator[1] in ("(", ")") for operator in operators) and not any(
        segment.words and segment.words[0] == "function" for segment in segments)
    block_depth = 0
    after_assignment = False
    judged, temp_writes = not python_verdicts, 0
    files_stable = all(verdict.kind == "read" for verdict in python_verdicts)
    script_stable = (FILES_MAY_CHANGE not in environment or SCRIPTS_STABLE in environment) and all(
        verdict.kind == "read" or any(verdict is item for item in quiet_verdicts) for verdict in python_verdicts)
    substitution_names = set()
    current_env = environment
    flow = _ValueFlow(choices)
    made_directories = set()
    pending_cd = None
    own_drops = _own_stash_drops(segments, operators) if recording and "stash" in text else set()
    for index, segment in enumerate(segments):
        flow.visit(segments, index, operators, current_env)
        command_cwd = pending_cd[0] if pending_cd and _chained_by_and(segments, operators, pending_cd[1], index) else cwd
        if segment.start in filtered_segments:
            filtered = filtered_segments[segment.start]
            if filtered is not None:
                verdicts.append(filtered)
            files_stable = files_stable and filtered is not None and filtered.kind == "read"
            script_stable = script_stable and filtered is not None and filtered.kind == "read"
            judged = False
            continue
        segment = segment._replace(
            words=_expand_segment_words(segment, statics),
            redirects=[(fd, operator, _expand_path_variables(target, statics) if "<<" not in operator else target)
                       for fd, operator, target in segment.redirects],
        )
        program, assignments = strip_prefix(segment.words)
        named = {name for word in segment.words for name in GIT_CONFIG_WORD.findall(word)}
        if named:
            current_env[COMMAND_GIT_CONFIG] = ",".join(sorted(
                named | set(filter(None, current_env.get(COMMAND_GIT_CONFIG, "").split(",")))))
        if guard_temp._COMMAND_TRACE is not None:
            _trace_command(_redirects_write_only_inside_temporary_root(
                segment.redirects, command_cwd, {**current_env, **variables}, flow.choices()))
        region = checked[segment.start:segment.end]
        substitutions = list(_substitution_spans(region))
        scoped_env = current_env if files_stable else {**current_env, FILES_MAY_CHANGE: "1"}
        for _, _, body in substitutions:
            verdicts.append(classify_text(body, cwd, depth + 1, scoped_env, variables, statics, flow.choices()))
            files_stable = files_stable and verdicts[-1].kind == "read"
            script_stable = script_stable and verdicts[-1].kind == "read"
        scoped_env = current_env if files_stable else {**current_env, FILES_MAY_CHANGE: "1"}
        scoped_env = {key: value for key, value in scoped_env.items() if key != STASH_OWN_DROP}
        shell_script, shell_seed = _shell_c_seed(segment, _value_lookup(flow.choices(), {**current_env, **variables}))
        for body in _indirect_regions(region, [segment]):
            verdict = classify_text(body, cwd, depth + 1, {**scoped_env, **assignments}, None, None,
                                    shell_seed if body == shell_script else None)
            if verdict.kind in ("secret", "sensitive", "forbidden", "always"):
                verdicts.append(verdict)
            else:
                match = COVERED_WORD.search(body)
                if match:
                    indirect, _ = strip_prefix(segment.words)
                    shell = indirect and os.path.basename(indirect[0]) in SHELLS
                    pure_python = False
                    if verdict.kind == "pass":
                        try:
                            inner = [strip_prefix(item.words)[0] for item in tokenize(body)]
                            pure_python = bool(inner) and all(words and PYTHON.fullmatch(os.path.basename(words[0])) for words in inner)
                        except ParseError:
                            pass
                    classified = verdict.kind == "read" or verdict.kind == "pass" and _covered_only_as_commands(body)
                    verdicts.append(verdict if pure_python or classified and shell else _unclassified(match.group(0), body))
        name = os.path.basename(program[0]) if program else ""
        if (segment.redirects or name in INSTALLED_WRITERS) and installed_code_write(
                program, segment.redirects, command_cwd, {**current_env, **variables}):
            verdicts.append(Outcome("forbidden", [], [INSTALLED_CODE_REASON]))
        if (PYTHON.fullmatch(name) and "-c" not in program and "-m" not in program
                and _python_inline_code(program[1:]) is None):
            for _, operator, target in segment.redirects:
                if operator == "<" and not _protected_path(target, cwd, current_env):
                    path = _script_path(target, cwd, variables)
                    try:
                        verdicts.append(_python_policy(_script_content(path), cwd, depth, current_env))
                    except (OSError, ValueError, AttributeError):
                        verdicts.append(_script_unknown(target, program, current_env, "unreadable stdin"))
        if any(operator == "<" and _protected_path(target, cwd, current_env)
               for _, operator, target in segment.redirects):
            verdicts.append(_sensitive(text))
        first = segment.words[0] if segment.words else ""
        was_assignment, after_assignment = after_assignment, False
        block_depth = (block_depth + 1 if first in BLOCK_OPENERS
                       else max(0, block_depth - 1) if first in BLOCK_CLOSERS else block_depth)
        written = heredoc_scripts.get(segment.start)
        if any(start <= segment.start < stop for start, stop in script_bodies):
            pass
        elif written is not None and recording and block_depth == 0 and _runs_unconditionally(index, segments, operators):
            script_path = next((_script_path(target, cwd, variables) for _, operator, target in segment.redirects
                                if operator == ">"), None)
            if (script_path is not None and len(written.encode()) <= MAX_SCRIPT_BYTES
                    and not _may_write_own_path(written, script_path, cwd)):
                _PENDING_SCRIPTS[script_path] = written
            else:
                _PENDING_SCRIPTS.clear()
        elif _PENDING_SCRIPTS and (first in LOOP_OPENERS or not _keeps_pending(segment, program, region, cwd, variables)):
            _PENDING_SCRIPTS.clear()
        if _archive_fill(segment, program, segments, index, operators, cwd, variables, statics,
                         {**current_env, **variables}, recording and block_depth == 0):
            pass
        elif _ARCHIVE_COPIES and (first in LOOP_OPENERS or not _keeps_archive(
                segment, program, region, cwd, variables, statics, {**current_env, **variables})):
            _ARCHIVE_COPIES.clear()
        if name == "mkdir" and recording and block_depth == 0 and _runs_unconditionally(index, segments, operators):
            made_directories |= _made_directories(program, cwd, variables)
        forgotten = None if ":=" in region or "((" in region else _plain_environment_edit(program)
        if forgotten is not None:
            for key in forgotten:
                statics.pop(key, None)
        elif (name in ENVIRONMENT_CHANGERS or name in VARIABLE_WRITERS or name == "printf" and "-v" in program
                or ":=" in region or "((" in region):
            statics.clear()
        elif name in ("for", "select") and len(program) > 1:
            statics.pop(program[1], None)
        if name == "cd" and len(program) == 2:
            pending_cd = None
            if _cd_changes_directory(segment, operators):
                directory = _script_path(program[1], cwd, variables)
                if directory is not None and (directory.is_dir() or _PENDING_SCRIPTS and directory in made_directories):
                    cwd = str(directory)
                elif directory is not None and guard_temp._COMMAND_TRACE is not None and _followed_by_and(segment, operators):
                    pending_cd = (str(directory), index)
            continue
        if not program and assignments:
            _trace_command(not any(PATH_ALTERING_NAMES.fullmatch(key) for key in assignments))
            standalone =all(ASSIGNMENT.match(word) for word in segment.words)
            fixed = (standalone and recording and block_depth == 0
                     and _unconditional_assignment(segment, operators, was_assignment))
            if standalone:
                known = {name: current_env[name] for name in FLOW_ENVIRONMENT if current_env.get(name)}
                folder = flow.state.get(SCRIPT_FOLDER_KEY)
                for key, value in assignments.items():
                    if folder and len(folder) == 1 and SCRIPT_FOLDER.fullmatch(value):
                        variables[key] = folder[0]
                    else:
                        variables[key] = _expand_path_variables(value, {**known, **variables})
                    if key != "_APPROVAL_SESSION_DIR":
                        current_env[key] = variables[key]
                    if "$(" in value or "`" in value:
                        substitution_names.add(key)
                    else:
                        substitution_names.discard(key)
            for key, value in assignments.items():
                fixed_value = _static_value(value, statics, {**current_env, **variables}) if fixed else None
                if fixed_value is None:
                    statics.pop(key, None)
                else:
                    statics[key] = fixed_value
            after_assignment = bool(fixed)
            judged = judged and standalone and not segment.redirects and all(
                "$(" not in value and "`" not in value or MKTEMP_OPERAND.fullmatch(value) for value in assignments.values())
            continue
        dynamic_program = program and re.search(r"\$\(|`|\$\{|\$[A-Za-z_]", program[0])
        argv = _xargs_argv(program[1:]) if name == "xargs" else None
        if argv:
            argv = [*segment.words[:len(segment.words) - len(program)], *argv]
        verdict = (_unclassified(name, text) if dynamic_program and COVERED_WORD.search(region)
                   else _classify_argv(argv or segment.words, segment.heredoc and not argv, command_cwd, depth, text,
                                       {**{key: value for key, value in scoped_env.items() if key != SCRIPTS_STABLE},
                                        **({SCRIPTS_STABLE: "1"} if script_stable else {}),
                                        **({STASH_OWN_DROP: "1"} if index in own_drops else {}),
                                        **({} if _redirects_write_only_inside_temporary_root(
                                            segment.redirects, command_cwd, {**current_env, **variables},
                                            flow.choices()) else {REDIRECTED: "1"})},
                                       variables, flow.choices(), None if argv else segment.raw))
        if argv and (verdict.kind == "read" or verdict.kind == "pass" and os.path.basename(
                (strip_prefix(argv)[0] or [""])[0]) in OPERAND_READERS) and not (
                _prints_no_content(argv) and _xargs_input_is_inert(argv, program, segment, segments, index, operators,
                                                                    statics)) and not _xargs_list_read(
                argv, program, segment, command_cwd, variables, text, current_env):
            verdict = _sensitive(text)
        inert = verdict.kind == "pass" and (not name or name in FILE_INERT) and flow.outside_loop_header()
        header = verdict.kind == "pass" and name == "for" and not substitutions
        files_stable = files_stable and (verdict.kind == "read" or inert) and _redirects_allowed([segment])
        script_stable = script_stable and (verdict.kind == "read" or inert or header or _stdin_filter(verdict, program)
                                           or not assignments and _own_node_check(program, command_cwd, current_env)
                                           ) and _redirects_allowed([segment])
        output = name in ("echo", "printf") and (substitutions or any(
            re.search(r"\$(?:" + re.escape(key) + r"\b|\{" + re.escape(key) + r"\})", region)
            for key in substitution_names
        ))
        if verdict.kind != "pass" or not output:
            verdicts.append(verdict)
        writes = None if substitutions or argv else _temp_segment(segment.words, segment.redirects, cwd, current_env)
        judged = judged and writes is not None
        temp_writes += writes or 0
    outcome = _aggregate(verdicts, segments)
    if outcome.kind == "pass" and outcome.exe is None and judged and temp_writes:
        return Outcome("pass", [], [], TEMP_WRITE_EXE)
    return outcome
