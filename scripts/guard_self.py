"""Approval request parsing and the detection of commands that run guard code, for the approval guard."""
import argparse
import ast
import functools
import os
import re
import shlex
from pathlib import Path
import approval_state
from approval_state import Outcome
from guard_shell import (
    CLI_DESTRUCTIVE_WORDS, PYTHON, ParseError, SHELLS, _helper_args, _shell_c, _substitution_spans, strip_prefix,
    tokenize,
)
from guard_paths import _resolved
from guard_cloud import (
    _aws_rules, _az_rules, _docker_rules, _gcloud_rules, _gsutil_rules, _helm_rules, _kubectl_rules, _terraform_rules,
)


MAX_DEPTH = 4
SOURCE_COMMANDS = frozenset({".", "source"})
GUARD_MODULE_NAMES = (
    "approval_guard",
    "approval_state",
    "approval_state_records",
    "approval_state_store",
    "datagrip_guard",
    "datagrip_sql",
    "db_read_policy",
    "guard_cloud",
    "guard_dispatch",
    "guard_expand",
    "guard_git",
    "guard_own",
    "guard_paths",
    "guard_permissions",
    "guard_proof",
    "guard_pyread",
    "guard_pyrisk",
    "guard_pywrite",
    "guard_reads",
    "guard_scripts",
    "guard_self",
    "guard_shell",
    "guard_temp",
    "guard_tools",
)
GUARD_SCRIPTS = frozenset({*(f"{name}.py" for name in GUARD_MODULE_NAMES), "hook_python.sh"})
GUARD_MODULES = frozenset(GUARD_MODULE_NAMES)
_GUARD_NAMES = "|".join(GUARD_MODULE_NAMES)
GUARD_CODE = re.compile(
    rf"\bimport\s+[\w.,\s]*?\b(?:{_GUARD_NAMES})\b"
    rf"|\bfrom\s+(?:[\w.]+\.)?(?:{_GUARD_NAMES})\b"
    rf"|(?:__import__|import_module)\(\s*['\"](?:[\w.]+\.)?(?:{_GUARD_NAMES})['\"]"
)
GUARD_ENTRY = (Path(__file__).resolve().parent / "approval_guard.py").resolve()
PYTHON_EXEC = re.compile(r"subprocess|os\.system|os\.exec|os\.spawn|os\.popen|runpy|\bexec\s*\(|Popen")
CLI_RULES = {
    "kubectl": _kubectl_rules, "oc": _kubectl_rules, "helm": _helm_rules, "az": _az_rules,
    "terraform": _terraform_rules, "tofu": _terraform_rules, "aws": _aws_rules, "gcloud": _gcloud_rules,
    "gsutil": _gsutil_rules, "docker": _docker_rules,
    "podman": functools.partial(_docker_rules, engine="podman"),
}


def _valid_request_key(key):
    if key in ("mcp:session", approval_state.WRITE_KEY, approval_state.SENSITIVE_KEY):
        return True
    match = re.fullmatch(r"([a-z0-9-]+):([^@\n]+)@([^\n]+)", key)
    if not match:
        return False
    cli, kind, target = match.groups()
    try:
        words = shlex.split(kind)
    except ValueError:
        return False
    lowered = set(re.findall(r"[a-z]+", kind.lower()))
    if not words or lowered & (CLI_DESTRUCTIVE_WORDS | {"force", "forced", "prune", "always", "sensitive", "unclassified"}):
        return False
    if cli in ("psql", "sqlcmd"):
        return all(word in {"select", "insert", "update", "merge", "create", "alter", "grant", "revoke", "copy", "set", "with"}
                   for word in kind.split("+"))
    if cli == "curl":
        return bool(re.fullmatch(r"[A-Z][A-Z0-9_-]*", kind) and re.fullmatch(r"[a-z][a-z0-9+.-]*://[^/\s]+", target))
    if cli not in CLI_RULES:
        return False
    rules = CLI_RULES[cli](words, words, {}, os.getcwd())
    sensitive = (cli in ("docker", "podman") and "inspect" in words[:2]) or (
        cli in ("kubectl", "oc", "docker", "podman") and "exec" in words
        and any(word in ("env", "printenv") for word in words)
    )
    return not (rules.secret or rules.always or sensitive)


class RequestParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def _request_args(args):
    parser = RequestParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--key", action="append", required=True)
    parser.add_argument("--why", required=True)
    parsed = parser.parse_args(args)
    if not parsed.why.strip() or not all(_valid_request_key(key) for key in parsed.key):
        raise ValueError("Only classified, non-destructive write keys can be pre-approved")
    return Outcome("request", sorted(set(parsed.key)), [*sorted(set(parsed.key)), parsed.why])


def _request_outcome(command, cwd):
    try:
        segments = tokenize(command)
    except ParseError:
        return None
    try:
        if len(segments) != 1 or segments[0].redirects:
            return None
        words, assignments = strip_prefix(segments[0].words)
        if assignments or len(words) < 3 or not PYTHON.fullmatch(os.path.basename(words[0])):
            return None
        if _resolved(words[1], cwd) != GUARD_ENTRY or words[2] != "request":
            return None
        return _request_args(words[3:])
    except ValueError as error:
        return Outcome("forbidden", [], [str(error)])


def _names_guard(node, tainted):
    """True when an expression holds a guard module or script name directly or through a name assigned one."""
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str) and any(m in child.value for m in GUARD_MODULES):
            return True
        if isinstance(child, ast.Name) and child.id in tainted:
            return True
    return False


def _code_runs_guard(code):
    """True when Python code imports a guard module or passes a guard name to a process or exec call.

    A guard path that only appears as data, such as a list of files to check, does not count. Code that cannot be
    parsed falls back to the conservative text check.
    """
    if GUARD_CODE.search(code):
        return True
    if not any(module in code for module in GUARD_MODULES) or PYTHON_EXEC.search(code) is None:
        return False
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return True
    tainted = set()
    for _ in range(3):
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node.value is not None \
                    and _names_guard(node.value, tainted):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                tainted.update(t.id for target in targets for t in ast.walk(target) if isinstance(t, ast.Name))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and PYTHON_EXEC.search(ast.unparse(node.func)):
            if any(_names_guard(arg, tainted) for arg in [*node.args, *(k.value for k in node.keywords)]):
                return True
    return False


def _python_runs_guard(args):
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-c":
            return _code_runs_guard(args[index + 1] if index + 1 < len(args) else "")
        if arg == "-m":
            module = args[index + 1] if index + 1 < len(args) else ""
            return module.split(".")[-1] in GUARD_MODULES
        if arg.startswith("-") and arg != "-":
            index += 1
            continue
        return os.path.basename(arg) in GUARD_SCRIPTS
    return False


def _first_operand(args):
    for arg in args:
        if not arg.startswith("-"):
            return arg
    return None


def _argv_runs_guard(words, depth):
    name = os.path.basename(words[0])
    if name in GUARD_SCRIPTS:
        return True
    if PYTHON.fullmatch(name):
        return _python_runs_guard(words[1:])
    if name in SHELLS:
        script = _shell_c(words[1:])
        if script is not None:
            return _runs_guard(script, depth + 1)
        operand = _first_operand(words[1:])
        return operand is not None and os.path.basename(operand) in GUARD_SCRIPTS
    if name in SOURCE_COMMANDS:
        operand = _first_operand(words[1:])
        return operand is not None and os.path.basename(operand) in GUARD_SCRIPTS
    return False


def _runs_guard(text, depth=0):
    """Whether a command executes an approval guard script, runs Python that imports or executes one, or runs one with -m."""
    if depth > MAX_DEPTH or not isinstance(text, str):
        return False
    try:
        segments = tokenize(text)
    except ParseError:
        return any(module in text for module in GUARD_MODULES)
    for segment in segments:
        helper = _helper_args(segment.words)
        if helper is not None:
            if "--" in helper:
                inner, _ = strip_prefix(helper[helper.index("--") + 1:])
                if inner and _argv_runs_guard(inner, depth + 1):
                    return True
            continue
        words, _ = strip_prefix(segment.words)
        if words and _argv_runs_guard(words, depth):
            return True
        if any(_runs_guard(body, depth + 1)
               for _, _, body in _substitution_spans(text[segment.start:segment.end])):
            return True
    return False
