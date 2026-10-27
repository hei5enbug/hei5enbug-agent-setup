#!/usr/bin/env python3
"""Approval guard for covered CLI, MCP, and DataGrip writes, shared by Claude Code and Codex.

Reads run without approval, writes and sensitive reads ask once per session, and always calls ask every time.
Requests bundle session keys, secrets and forbidden state edits are denied, and pass leaves the host in charge.
Every verb and CLI table lives in this module. DataGrip queries are classified
by datagrip_guard, which makes its own PreToolUse decision; this entry point records and consumes their approvals.
Production database reads (tabularis and DataGrip) follow db_read_policy, and this entry point records plan estimates.
The guard always exits 0; covered calls fail closed when their classification fails.
"""
import argparse
import ast
import fnmatch
import functools
import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from collections import namedtuple
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = sys.pycache_prefix is None
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugin_toggles import detect_host, enabled  # noqa: E402
import approval_state  # noqa: E402
import db_read_policy  # noqa: E402
from approval_state import Outcome  # noqa: E402

DATAGRIP_TOOL = "mcp__datagrip__execute_sql_query"
TABULARIS_TOOL = "mcp__tabularis__run_query"
POST_EVENTS = ("PostToolUse", "PostToolUseFailure")
EVENTS = ("PreToolUse", "PermissionRequest", *POST_EVENTS)
MAX_DEPTH = 4
WRAPPER = str(Path(__file__).resolve().parents[1] / "scripts" / "approve_wrapper.sh")
LOOKUP_TIMEOUT_SECONDS = 3
COVERED = frozenset({
    "kubectl", "oc", "helm", "kustomize", "az", "terraform", "tofu", "aws", "gcloud", "gsutil",
    "docker", "podman", "psql", "sqlcmd", "mysql", "mongosh", "redis-cli", "curl", "git", "gh",
})
PYTHON = re.compile(r"python(?:\d+(?:\.\d+)*)?")
SHELLS = frozenset({"sh", "bash", "zsh"})
SOURCE_COMMANDS = frozenset({".", "source"})
FILTERS = frozenset({"grep", "egrep", "fgrep", "rg", "head", "tail", "wc", "sort", "uniq", "jq", "cut", "tr", "column",
                     "awk"})
AWK_PRINT = re.compile(
    r"(?:NR\s*(?:==|!=|>=|<=|>|<)\s*\d+\s*)?\{\s*print(?:\s+(?:\$\d+|\$NF)(?:\s*,\s*(?:\$\d+|\$NF))*)?\s*\}"
)
WRAPPER_VALUE_OPTIONS = {
    "sudo": frozenset({"-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U", "-D", "-T"}),
    "env": frozenset({"-u", "-C", "-S"}),
    "command": frozenset(),
    "time": frozenset({"-f", "-o"}),
    "nice": frozenset({"-n"}),
    "nohup": frozenset(),
    "exec": frozenset({"-a"}),
}
SHELL_KEYWORDS = frozenset({"!", "{", "}", "if", "then", "else", "elif", "do", "done", "while", "until", "fi"})
CLI_DESTRUCTIVE_WORDS = frozenset(
    "delete del destroy purge prune remove rm rmi rb terminate uninstall un drain force-unlock wipe truncate drop".split()
)
GLOBAL_VALUE_OPTIONS = frozenset({
    "-n", "--namespace", "--context", "--kube-context", "--kubeconfig", "--profile", "--region", "--project",
    "--subscription", "-g", "--resource-group", "-chdir", "-H", "--host", "-o", "--output",
})
MCP_READ_VERBS = frozenset({
    "get", "list", "search", "read", "fetch", "query", "find", "lookup", "describe", "show", "view", "check",
    "count", "browse", "download", "export", "preview", "introspect", "analyze", "explain", "info", "whoami",
})
MCP_WRITE_WORDS = frozenset({
    "send", "post", "reply", "create", "update", "edit", "add", "write", "upsert", "transition", "schedule",
    "share", "copy", "move", "upload", "comment", "label", "unlabel", "mark", "unmark", "forward", "apply", "set",
    "rename", "link", "react", "reaction", "publish", "merge", "close", "reopen", "assign", "invite", "patch",
})
MCP_DESTRUCTIVE_WORDS = frozenset({"delete", "trash", "remove", "destroy", "purge", "drop", "unshare", "revoke"})
SECRET_REASON = (
    "This command would print a secret value. Run it through `python3 {root}/scripts/secret_exec.py --secret "
    "VAR=<source> -- <command>` instead; the value reaches the command only through an environment variable or a "
    "temporary file."
)
SELF_APPROVAL_REASON = (
    "Approvals come only from the user, so a command that touches the approval state or runs approval_state is denied."
)
READ_REASON = "Read-only call; it runs without approval."

ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
ENVIRONMENT_CHANGERS = frozenset({
    "export", "declare", "typeset", "readonly", "local", "set", "unset", "source", ".", "eval", "exec", "alias",
    "function",
})
# Calls fall into three tiers. A write asks once per session (WRITE_KEY) and a sensitive read asks once per session
# (SENSITIVE_KEY). The actions that ask every time are the always outcomes, which all set Outcome.every_time: calls that
# affect remote or production systems or destroy local data that cannot be recovered. They are destructive git push
# (except a lease-protected push to a feature branch, which is a session write),
# git clean and stash drop, git reset --hard and forced checkout or restore over uncommitted tracked changes, recursive
# removal of a protected or external path, destructive gh and database statements, remote infrastructure deletion,
# docker or podman removal against a remote engine, package publishing, destructive curl methods and MCP tools, Codex
# runs without sandbox protection, unclassifiable calls whose text names a destructive action, and guard classification
# failures. Disposable or recoverable local actions do not ask every time: docker removal on the local engine and a hard
# reset on a clean tracked tree are session writes, and removal or writes inside a temporary root pass. Everything else
# is a read, a pass, a write, or a denial.
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
STATE_READS = frozenset({"ls", "cat", "head", "tail", "grep", "wc", "stat", "file", "find", "echo"})
FIND_READ_OPTIONS = frozenset({
    "-type", "-name", "-iname", "-path", "-ipath", "-maxdepth", "-mindepth", "-newer", "-mtime", "-mmin", "-size",
    "-empty", "-print", "-print0", "-ls", "-not", "!", "-a", "-and", "-o", "-or", "-L", "-H", "-P",
})
COVERED_WORD = re.compile(r"(?<![\w-])(?:" + "|".join(sorted(COVERED, key=len, reverse=True)) + r")(?![\w-])")
OPAQUE_CONSTRUCT = re.compile(r"\b(?:eval|xargs)\b|\b(?:sh|bash|zsh)\b[^;&|\n]*?\s-[A-Za-z]*c[A-Za-z]*\b")
SHELL_C_FLAG = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
GUARD_SCRIPTS = frozenset({"approval_guard.py", "approval_state.py", "datagrip_guard.py", "db_read_policy.py", "hook_python.sh"})
GUARD_MODULES = frozenset({"approval_guard", "approval_state", "datagrip_guard", "db_read_policy"})
GUARD_CODE = re.compile(
    r"\bimport\s+[\w.,\s]*?\b(?:approval_guard|approval_state|datagrip_guard|db_read_policy)\b"
    r"|\bfrom\s+(?:[\w.]+\.)?(?:approval_guard|approval_state|datagrip_guard|db_read_policy)\b"
    r"|(?:__import__|import_module)\(\s*['\"](?:[\w.]+\.)?(?:approval_guard|approval_state|datagrip_guard|db_read_policy)['\"]"
)
PYTHON_EXEC = re.compile(r"subprocess|os\.system|os\.exec|os\.spawn|os\.popen|runpy|\bexec\s*\(|Popen")
GCLOUD_READ_VERBS = frozenset({"list", "describe", "ls", "cat"})
GCLOUD_WRITE_VERBS = frozenset({
    "create", "update", "delete", "set", "deploy", "start", "stop", "reset", "resize", "patch", "import", "export",
    "run", "submit", "ssh", "scp", "cp", "mv", "rsync",
})
GCLOUD_WRITE_PREFIXES = ("set-", "add-", "remove-")
READ_ONLY_PREFIX = (
    'export PGOPTIONS="${PGOPTIONS:+$PGOPTIONS }-c default_transaction_read_only=on -c statement_timeout=60000"; '
)
MAX_SCRIPT_BYTES = 256 * 1024
SDK_IMPORT = re.compile(
    r"\b(?:import|from|require)\b[^\n;]*(?:boto3|azure|kubernetes|psycopg2?|pymysql|sqlalchemy|pymongo|redis|google\.cloud)\b"
)
FAILURE_REASON = "The approval guard failed to check this call"
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
FILE_TOOLS = EDIT_TOOLS | {"Read", "apply_patch"}
CLAUDE_PROTECTED_DIRS = frozenset({".git", ".claude", ".vscode", ".idea", ".husky"})
CLAUDE_PROTECTED_FILES = frozenset({
    ".bashrc", ".bash_profile", ".zshrc", ".zprofile", ".profile", ".gitconfig", ".gitmodules", ".mcp.json",
    ".claude.json", ".ripgreprc",
})
REMOTE_PROGRAM = re.compile(r"(?<![\w.-])(?:ssh|scp|rsync|sudo|su|doas)(?![\w-])")
DESTRUCTIVE_COMMAND = re.compile(
    r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*(?:\s--force\b|\s-[A-Za-z]*f[A-Za-z]*(?=\s|$)|\s\+)"
    r"|(?<![\w-])dd\b[^\n;&|]*\sof="
    r"|(?<![\w-])mkfs(?:\.\w+)?\b"
)
FILE_READS = frozenset({"cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg"})
EXEC_WORDS = frozenset({"repl", "exec", "execute", "eval", "run", "code", "script", "command"})
SECRET_NAME = approval_state.SECRET_NAME


def _datagrip():
    import datagrip_guard
    return datagrip_guard


def read_only_command(command):
    """Run a psql read in a subshell so the read-only option never outlives this call."""
    return "( " + READ_ONLY_PREFIX + command + "\n)"
SEPARATOR_OPERATORS = ("&&", "||", "|&", ";;", ";", "|", "&", "(", ")")
REDIRECT_OPERATORS = ("&>>", "&>", ">>", ">&", ">|", "<<<", "<<", "<&", "<>", ">", "<")
OPERATORS = tuple(sorted(SEPARATOR_OPERATORS + REDIRECT_OPERATORS, key=len, reverse=True))

Segment = namedtuple("Segment", "words redirects heredoc start end raw", defaults=((),))
Rules = namedtuple("Rules", "secret dry_run always read target sensitive write critical",
                   defaults=(False, False, False, False, None, False, False, None))


class ParseError(ValueError):
    """The command cannot be split into simple commands safely."""


def _operator_at(text, index):
    for operator in OPERATORS:
        if text.startswith(operator, index):
            return operator
    return None


def _substitution_end(text, start):
    if text[start] == "`":
        index = start + 1
        while index < len(text):
            if text[index] == "\\":
                index += 2
            elif text[index] == "`":
                return index + 1
            else:
                index += 1
        raise ParseError("unterminated backtick substitution")
    index, nesting, quote = start + 2, 1, None
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote == "'":
            if char == "'":
                quote = None
        elif text.startswith("$(", index) or char == "`":
            index = _substitution_end(text, index)
            continue
        elif char in ("'", '"'):
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        elif quote is None:
            nesting += {"(": 1, ")": -1}.get(char, 0)
            if nesting == 0:
                return index + 1
        index += 1
    raise ParseError("unterminated command substitution")


def _substitution_spans(text):
    index, quote = 0, None
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote == "'":
            if char == "'":
                quote = None
        elif text.startswith("$(", index) or char == "`":
            end = _substitution_end(text, index)
            offset = 2 if char == "$" else 1
            yield index, end, text[index + offset:end - 1]
            index = end
            continue
        elif char in ("'", '"'):
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        index += 1


def _lex(text):
    """Return (kind, value, start, end) tokens: words are unquoted text, ops are shell operators."""
    tokens = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and text.startswith("\n", index + 1):
            index += 2
            continue
        if char == "\\" and text.startswith("\r\n", index + 1):
            index += 3
            continue
        if char in " \t\r":
            index += 1
            continue
        if char == "\n":
            tokens.append(("op", ";", index, index + 1))
            index += 1
            continue
        operator = _operator_at(text, index)
        if operator:
            tokens.append(("op", operator, index, index + len(operator)))
            index += len(operator)
            continue
        start = index
        value = []
        while index < len(text) and text[index] not in " \t\r\n" and not _operator_at(text, index):
            char = text[index]
            if text.startswith("$(", index) or char == "`":
                end = _substitution_end(text, index)
                value.append(text[index:end])
                index = end
            elif char == "\\":
                if text.startswith("\n", index + 1):
                    index += 2
                    continue
                if text.startswith("\r\n", index + 1):
                    index += 3
                    continue
                if index + 1 >= len(text):
                    raise ParseError("trailing backslash")
                value.append(text[index + 1])
                index += 2
            elif char == "'":
                end = text.find("'", index + 1)
                if end < 0:
                    raise ParseError("unterminated single quote")
                value.append(text[index + 1:end])
                index = end + 1
            elif char == '"':
                index += 1
                while True:
                    if index >= len(text):
                        raise ParseError("unterminated double quote")
                    if text.startswith("$(", index) or text[index] == "`":
                        end = _substitution_end(text, index)
                        value.append(text[index:end])
                        index = end
                        continue
                    if text[index] == '"':
                        index += 1
                        break
                    if text[index] == "\\" and text.startswith("\n", index + 1):
                        index += 2
                    elif text[index] == "\\" and text.startswith("\r\n", index + 1):
                        index += 3
                    elif text[index] == "\\" and index + 1 < len(text):
                        value.append(text[index + 1])
                        index += 2
                    else:
                        value.append(text[index])
                        index += 1
            else:
                value.append(char)
                index += 1
        tokens.append(("word", "".join(value), start, index))
    return tokens


def tokenize(text):
    """Split a command at separators into segments with their words and redirections."""
    text = _heredoc_data(text)
    groups = [[]]
    for token in _lex(text):
        if token[0] == "op" and token[1] in SEPARATOR_OPERATORS:
            groups.append([])
        else:
            groups[-1].append(token)
    segments = []
    for group in groups:
        if not group:
            continue
        words = []
        raw = []
        redirects = []
        heredoc = False
        index = 0
        plain_before = False
        while index < len(group):
            kind, value, start, end = group[index]
            if kind == "word":
                words.append(value)
                raw.append(text[start:end])
                plain_before = True
                index += 1
                continue
            fd = None
            previous = group[index - 1] if index > 0 else None
            if plain_before and previous[3] == start and previous[1].isdigit():
                fd = words.pop()
                raw.pop()
            if index + 1 >= len(group) or group[index + 1][0] != "word":
                raise ParseError("redirection without a target")
            redirects.append((fd, value, group[index + 1][1]))
            heredoc = heredoc or value in ("<<", "<<<")
            plain_before = False
            index += 2
        if words or redirects:
            segments.append(Segment(words, redirects, heredoc, group[0][2], group[-1][3], raw))
    return segments


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _read():
    return Outcome("read", [], [])


def _one_line(text, limit=60):
    return " ".join(approval_state.redact(text).split())[:limit]


def _unknown_kind(destructive):
    """What a call the guard cannot classify needs: an approval every time when it looks destructive or the `session`
    approval scope is on, else a session write approval."""
    return "always" if destructive or approval_state.session_scope() else "write"


def _unclassified(cli, command):
    kind = _unknown_kind(_destructive_text(command) and not _local_docker_only(command))
    return Outcome(kind, [f"{cli}:unclassified:{_digest(command)}"], ["Unclassified command: " + _one_line(command)],
                   every_time=kind == "always", critical=True)


def _destructive_text(text):
    text = _heredoc_data(text)
    names = "|".join(re.escape(name) for name in COVERED - {"git", "gh"})
    destructive = "|".join(CLI_DESTRUCTIVE_WORDS)
    return bool(re.search(r"\b(?:" + names + r")\b[^\n;&|]*\b(?:" + destructive + r")\b", text, re.I)
                or re.search(r"\b(?:delete\s+from|drop\s+(?:table|database|schema)|truncate\s+table)\b", text, re.I))


LOCAL_DOCKER_REMOTE = re.compile(
    r"\b(?:DOCKER_HOST|DOCKER_CONTEXT|CONTAINER_HOST|CONTAINER_CONNECTION)=|--(?:context|host|url|connection|remote)\b"
    r"|(?<![\w-])-[Hc]\b|(?:tcp|ssh)://"
)


def _local_docker_only(text):
    """Whether every destructive word in a text that names a destructive action comes from docker or podman removal that
    names no remote engine."""
    text = _heredoc_data(text)
    others = "|".join(re.escape(name) for name in COVERED - {"git", "gh", "docker", "podman"})
    destructive = "|".join(CLI_DESTRUCTIVE_WORDS)
    return not (LOCAL_DOCKER_REMOTE.search(text)
                or re.search(r"\b(?:" + others + r")\b[^\n;&|]*\b(?:" + destructive + r")\b", text, re.I)
                or re.search(r"\b(?:delete\s+from|drop\s+(?:table|database|schema)|truncate\s+table)\b", text, re.I))


def _call(kind_name, cli, kind, target_fn, command, critical=None):
    if not kind:
        return _unclassified(cli, command)
    target = target_fn()
    label = " ".join(kind)
    return Outcome(kind_name, [f"{cli}:{label}@{target}"], [f"{cli} {label} on {target}"],
                   every_time=kind_name == "always", critical=kind_name == "always" and bool(critical and critical()))


def subcommand_words(args):
    """Return the positional words before the first flag, skipping leading global options and their values."""
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in GLOBAL_VALUE_OPTIONS else 1
    words = []
    while index < len(args) and not args[index].startswith("-"):
        words.append(args[index])
        index += 1
    return words


def _matches(kind, table):
    return any(tuple(kind[:len(prefix)]) == prefix for prefix in table)


def _contains(kind, sequence):
    return any(tuple(kind[i:i + len(sequence)]) == sequence for i in range(len(kind)))


def _has_flag(args, *names):
    return any(arg in names or any(arg.startswith(name + "=") for name in names) for arg in args)


def _destructive(kind):
    for word in kind:
        lowered = word.lower()
        if {lowered, *lowered.split("-")} & CLI_DESTRUCTIVE_WORDS:
            return True
    return False


def option_values(args, short=None, longs=()):
    values = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == short or arg in longs:
            values.append(args[index + 1] if index + 1 < len(args) else None)
            index += 2
            continue
        for name in longs:
            if arg.startswith(name + "="):
                values.append(arg[len(name) + 1:])
        if short and arg.startswith(short) and len(arg) > len(short) and not arg.startswith("--"):
            values.append(arg[len(short):].lstrip("="))
        index += 1
    return values


def option_value(args, short=None, longs=()):
    values = option_values(args, short, longs)
    return values[-1] if values else None


def _lookup(argv, env, cwd):
    """Return the stdout of a target lookup within the timeout, or None when it fails."""
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=LOOKUP_TIMEOUT_SECONDS, env=env, cwd=cwd,
            stdin=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    text = completed.stdout.strip() if completed.returncode == 0 else ""
    return text or None


def _secret_resource(args):
    for arg in args:
        if arg.startswith("-"):
            continue
        for part in arg.split(","):
            if part.split("/")[0].lower() in ("secret", "secrets"):
                return True
    return False


OUTPUT_SECRET_FORMATS = ("jsonpath", "go-template", "template", "custom-columns")
KUBE_LIST_INDEX = r"\[\*\]"
KUBE_METADATA_PATH = re.compile(
    r"(?:\.items" + KUBE_LIST_INDEX + r")?(?:"
    r"\.metadata\.(?:name|namespace|uid|creationTimestamp|deletionTimestamp|resourceVersion|generation|generateName)"
    r"|\.metadata\.labels(?:\.[A-Za-z0-9_-]+)?"
    r"|\.metadata\.finalizers(?:" + KUBE_LIST_INDEX + r")?"
    r"|\.metadata\.ownerReferences(?:" + KUBE_LIST_INDEX + r")?(?:\.[A-Za-z0-9_-]+)*"
    r"|\.(?:type|kind|apiVersion|immutable))"
)
KUBE_RANGE_PATH = re.compile(
    r"\.items(?:" + KUBE_LIST_INDEX + r")?"
    r"|(?:\.items" + KUBE_LIST_INDEX + r")?\.metadata\.(?:finalizers|ownerReferences)(?:" + KUBE_LIST_INDEX + r")?"
)
KUBE_QUOTED_LITERAL = r'"(?:\\.|[^"\\])*"' + r"|'(?:\\.|[^'\\])*'"
KUBE_JSONPATH_EXPRESSION = re.compile(r"\{((?:" + KUBE_QUOTED_LITERAL + r"|[^{}'\"])*?)\}")
KUBECTL_READS = (
    ("get",), ("describe",), ("logs",), ("top",), ("explain",), ("api-resources",), ("api-versions",),
    ("version",), ("cluster-info",), ("events",), ("diff",), ("auth", "can-i"), ("auth", "whoami"),
    ("config", "view"), ("config", "get-contexts"), ("config", "current-context"), ("config", "get-clusters"),
    ("rollout", "status"), ("rollout", "history"),
)


def _metadata_path(path, context=""):
    if not path.startswith((".", "$")):
        return ""
    return path[1:] if path.startswith("$") else context + path


def _metadata_output(output):
    name, separator, template = output.partition("=")
    if not separator or not template:
        return False
    if name.lower() == "custom-columns":
        columns = [column.partition(":") for column in template.split(",")]
        return all(header.strip() and colon and KUBE_METADATA_PATH.fullmatch(_metadata_path(path.strip()))
                   for header, colon, path in columns)
    if name.lower() != "jsonpath":
        return False
    contexts = [""]
    offset = 0
    for match in KUBE_JSONPATH_EXPRESSION.finditer(template):
        if "{" in template[offset:match.start()] or "}" in template[offset:match.start()]:
            return False
        expression = match[1].strip()
        if expression.startswith("range "):
            path = _metadata_path(expression[6:].strip(), contexts[-1])
            if not KUBE_RANGE_PATH.fullmatch(path):
                return False
            contexts.append(path if path.endswith("]") else path + "[*]")
        elif expression == "end":
            if len(contexts) == 1:
                return False
            contexts.pop()
        elif not re.fullmatch(KUBE_QUOTED_LITERAL, expression) and not KUBE_METADATA_PATH.fullmatch(
                _metadata_path(expression, contexts[-1])):
            return False
        offset = match.end()
    return len(contexts) == 1 and "{" not in template[offset:] and "}" not in template[offset:]


def _kube_context(args, env, cwd, explicit_context):
    argv = ["kubectl"]
    if option_value(args, longs=("--kubeconfig",)):
        argv += ["--kubeconfig", option_value(args, longs=("--kubeconfig",))]
    return explicit_context or _lookup([*argv, "config", "current-context"], env, cwd) or "(current)"


def _production_name(name):
    """Whether a target name cannot be shown to be non-production; `/` separates the parts of a target."""
    return db_read_policy.is_production(name.replace("/", " "))


def _kube_target(args, env, cwd, explicit_context, context=None):
    kubeconfig = option_value(args, longs=("--kubeconfig",)) or env.get("KUBECONFIG") or "(default)"
    context = context or _kube_context(args, env, cwd, explicit_context)
    namespace = option_value(args, "-n", ("--namespace",)) or "(default)"
    return f"{kubeconfig} {context}/{namespace}"


def _kubectl_rules(kind, args, env, cwd):
    secret = _matches(kind, (("create", "token"),)) or (kind[:2] == ["config", "view"] and _has_flag(args, "--raw"))
    if kind[:1] == ["get"]:
        raw = option_value(args, longs=("--raw",))
        output = option_value(args, "-o", ("--output",)) or ""
        output_name = output.split("=", 1)[0].lower()
        output_secret = output_name in ("json", "yaml") or output_name.startswith(OUTPUT_SECRET_FORMATS)
        if (output_secret and option_value(args, longs=("--template",)) is None
                and not any(arg.startswith("--allow-missing-template-keys") for arg in args)
                and _metadata_output(output)):
            output_secret = False
        secret = secret or (raw is not None and "secrets" in raw) or (_secret_resource(args) and output_secret)
    dry_run = _has_flag(args, "--dry-run=client", "--dry-run=server") or option_value(
        args, longs=("--dry-run",)) in ("client", "server")
    own_args = args[:args.index("--")] if "--" in args else args
    forced = any(arg in ("--force", "--prune") or arg.startswith(("--force=", "--prune=")) for arg in own_args)

    @functools.cache
    def context():
        return _kube_context(args, env, cwd, option_value(args, longs=("--context",)))

    def target():
        return _kube_target(args, env, cwd, None, context())

    return Rules(secret=secret, dry_run=dry_run, always=forced, read=_matches(kind, KUBECTL_READS), target=target,
                 write=kind[:1] == ["config"], critical=lambda: _destructive(kind) and _production_name(context()))


HELM_READS = (
    ("list",), ("ls",), ("status",), ("history",), ("show",), ("search",), ("template",), ("lint",), ("version",),
    ("env",), ("get", "notes"), ("get", "hooks"), ("get", "metadata"), ("repo", "list"), ("dependency", "list"),
    ("plugin", "list"),
)
HELM_SENSITIVE = (("get", "all"), ("get", "manifest"), ("get", "values"))


def _helm_rules(kind, args, env, cwd):
    @functools.cache
    def context():
        return _kube_context(args, env, cwd, option_value(args, longs=("--kube-context",)) or env.get("HELM_KUBECONTEXT"))

    def target():
        return _kube_target(args, env, cwd, None, context())

    sensitive = _matches(kind, HELM_SENSITIVE)
    return Rules(always=sensitive, read=_matches(kind, HELM_READS), target=target, sensitive=sensitive,
                 write=kind[:2] in (["repo", "remove"], ["repo", "rm"]),
                 critical=lambda: _destructive(kind) and _production_name(context()))


AZ_READ_WORDS = frozenset({"list", "show", "exists", "query"})
AZ_READ_PREFIXES = ("get-", "list-", "show-", "check-", "query-")
AZ_READ_PATHS = (("find",), ("version",), ("account", "show"), ("account", "list"))
AZ_SECRET_PATHS = (
    ("keyvault", "secret", "show"), ("keyvault", "secret", "download"), ("keyvault", "key", "download"),
    ("keyvault", "certificate", "download"), ("account", "get-access-token"), ("acr", "credential", "show"),
)
AZ_SECRET_WORDS = frozenset({"list-keys", "keys", "list-credentials", "show-connection-string", "list-connection-strings"})


def _az_rules(kind, args, env, cwd):
    secret = _matches(kind, AZ_SECRET_PATHS) or any(word in AZ_SECRET_WORDS for word in kind)
    read = (
        any(word in AZ_READ_WORDS or word.startswith(AZ_READ_PREFIXES) for word in kind)
        or _matches(kind, AZ_READ_PATHS) or _has_flag(args, "--version")
    )
    method = (option_value(args, "-m", ("--method",)) or "").upper()
    rest = kind[:1] == ["rest"]
    if rest:
        url = option_value(args, "-u", ("--url", "--uri")) or ""
        lowered = url.lower()
        parsed = _split_url(lowered)
        vault_secret = ((parsed.hostname or "").endswith(".vault.azure.net")
                        and re.search(r"/(?:secrets|keys)(?:/|$)", parsed.path))
        secret = secret or (method == "GET" and bool(vault_secret))
        read = (method == "GET" and (lowered.startswith("https://management.azure.com/") or url.startswith("$"))
                and not _has_flag(args, "--resource")
                and not any(word in lowered for word in (
                    "secret", "listkeys", "list-keys", "connectionstring", "listcredentials")))

    @functools.cache
    def target():
        subscription = option_value(args, longs=("--subscription",)) or _lookup(
            ["az", "account", "show", "--query", "id", "-o", "tsv"], env, cwd) or "(current)"
        group = option_value(args, "-g", ("--resource-group",)) or "(default)"
        return f"{subscription}/{group}"

    always = rest and method == "DELETE"
    return Rules(secret=secret, always=always, read=read, target=target,
                 critical=lambda: (always or _destructive(kind)) and _production_name(target()))


TF_READS = (
    ("plan",), ("show",), ("validate",), ("version",), ("providers",), ("graph",), ("state", "list"),
    ("workspace", "list"), ("workspace", "show"),
)
TF_SENSITIVE = (("state", "show"), ("state", "pull"))


def _read_workspace(directory):
    try:
        return Path(directory, ".terraform", "environment").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _terraform_rules(kind, args, env, cwd):
    sensitive_output = kind[:1] == ["output"] and (_has_flag(args, "-json") or _has_flag(args, "-raw"))
    sensitive = _matches(kind, TF_SENSITIVE) or sensitive_output
    always = sensitive or (kind[:1] == ["apply"] and _has_flag(args, "-destroy"))
    plain_output = kind[:1] == ["output"] and not sensitive_output
    read = _matches(kind, TF_READS) or plain_output or (kind[:1] == ["fmt"] and _has_flag(args, "-check"))

    def target():
        chdir = option_value(args, longs=("-chdir",))
        directory = os.path.normpath(os.path.join(cwd, chdir)) if chdir else cwd
        workspace = env.get("TF_WORKSPACE") or _read_workspace(directory) or "default"
        return f"{directory}:{workspace}"

    destroys = kind[:1] == ["destroy"] or (kind[:1] == ["apply"] and _has_flag(args, "-destroy"))
    return Rules(always=always, read=read, target=target, sensitive=sensitive, critical=lambda: destroys)


AWS_SECRET = (
    ("secretsmanager", "get-secret-value"), ("kms", "decrypt"), ("ecr", "get-login-password"),
    ("sts", "assume-role"), ("sts", "get-session-token"), ("configure", "get"), ("rds", "generate-db-auth-token"),
    ("secretsmanager", "batch-get-secret-value"),
)
AWS_READ_PREFIXES = ("describe-", "list-", "get-")
AWS_READS = (("s3", "ls"), ("sts", "get-caller-identity"), ("configure", "list"))


def _aws_rules(kind, args, env, cwd):
    operation = kind[1] if len(kind) > 1 else ""
    secret = _matches(kind, AWS_SECRET) or (
        kind[:1] == ["ssm"] and operation.startswith("get-parameter") and _has_flag(args, "--with-decryption"))
    read = operation.startswith(AWS_READ_PREFIXES) or _matches(kind, AWS_READS)

    def target():
        profile = option_value(args, longs=("--profile",)) or env.get("AWS_PROFILE") or "(default)"
        region = option_value(args, longs=("--region",)) or env.get("AWS_REGION") or "(default)"
        return f"{profile}/{region}"

    always = kind[:2] == ["s3", "sync"] and _has_flag(args, "--delete")
    return Rules(secret=secret, always=always, read=read, target=target,
                 critical=lambda: (always or _destructive(kind)) and _production_name(target()))


GCLOUD_SECRET = (
    ("secrets", "versions", "access"), ("auth", "print-access-token"), ("auth", "print-identity-token"),
    ("sql", "generate-login-token"),
)


def _project_target(args, env):
    return option_value(args, longs=("--project",)) or env.get("CLOUDSDK_CORE_PROJECT") or "(current)"


def _gcloud_verb_read(kind):
    """The first verb in the command path decides: a read verb reads, a write verb or no verb is a write."""
    for word in kind:
        if word in GCLOUD_READ_VERBS or word.startswith("get-"):
            return True
        if word in GCLOUD_WRITE_VERBS or word.startswith(GCLOUD_WRITE_PREFIXES):
            return False
    return False


def _gcloud_rules(kind, args, env, cwd):
    secret = any(_contains(kind, sequence) for sequence in GCLOUD_SECRET)
    return Rules(secret=secret, read=_gcloud_verb_read(kind), target=lambda: _project_target(args, env),
                 critical=lambda: _destructive(kind) and _production_name(_project_target(args, env)))


def _gsutil_rules(kind, args, env, cwd):
    return Rules(read=_gcloud_verb_read(kind), target=lambda: _project_target(args, env),
                 critical=lambda: _destructive(kind) and _production_name(_project_target(args, env)))


DOCKER_READ_FIRST = frozenset({"ps", "images", "inspect", "logs", "version", "info"})
DOCKER_OBJECTS = frozenset({
    "container", "image", "network", "volume", "context", "plugin", "node", "service", "stack", "secret", "config",
})
DOCKER_READS = (("context", "show"), ("compose", "ps"), ("compose", "logs"), ("compose", "config"))


DOCKER_METADATA_FIELD = re.compile(r"\.(?:Labels|Name|Driver|Mountpoint|CreatedAt|Id|RepoTags|Size)(?:\.[\w-]+)*")
DOCKER_TEMPLATE_ACTION = re.compile(r"\{\{(.*?)\}\}", re.S)
DOCKER_TEMPLATE_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|`[^`]*`')


def _metadata_template(template):
    """Whether a Go template has at least one action and each action only names metadata fields: the labels, name,
    driver, mount point, creation time, ID, tags, and size, with the `json` and `index` helpers."""
    actions = DOCKER_TEMPLATE_ACTION.findall(template)
    outside = DOCKER_TEMPLATE_ACTION.sub("", template)
    if not actions or "{{" in outside or "}}" in outside:
        return False
    for action in actions:
        words = DOCKER_TEMPLATE_STRING.sub(" ", action).split()
        if not words or not all(word in ("json", "index") or DOCKER_METADATA_FIELD.fullmatch(word) for word in words):
            return False
    return True


def _docker_metadata_inspect(cli, kind, args, env):
    """A local `docker volume|image|network inspect` whose format template shows only metadata fields."""
    templates = option_values(args, "-f", ("--format",))
    return (cli == "docker" and kind[:2] in (["volume", "inspect"], ["image", "inspect"], ["network", "inspect"])
            and bool(templates) and all(isinstance(template, str) and _metadata_template(template) for template in templates)
            and _local_engine(args, env, cli))


def _docker_rules(kind, args, env, cwd, engine="docker"):
    read = (
        (bool(kind) and kind[0] in DOCKER_READ_FIRST)
        or (len(kind) >= 2 and kind[0] in DOCKER_OBJECTS and kind[1] in ("ls", "inspect"))
        or _matches(kind, DOCKER_READS)
        or kind[:2] == ["system", "df"] and engine == "docker" and _local_engine(args, env, engine)
    )
    always = (kind[:2] == ["compose", "down"] and (_has_flag(args, "-v") or _has_flag(args, "--volumes"))
              and not _local_engine(args, env, engine))

    def target():
        return (option_value(args, longs=("--context",)) or env.get("DOCKER_CONTEXT")
                or env.get("DOCKER_HOST") or "(current)")

    return Rules(always=always, read=read, target=target)


CLI_RULES = {
    "kubectl": _kubectl_rules, "oc": _kubectl_rules, "helm": _helm_rules, "az": _az_rules,
    "terraform": _terraform_rules, "tofu": _terraform_rules, "aws": _aws_rules, "gcloud": _gcloud_rules,
    "gsutil": _gsutil_rules, "docker": _docker_rules,
    "podman": functools.partial(_docker_rules, engine="podman"),
}


def _classify_sql(cli, args, env, cwd, command):
    postgres = cli == "psql"
    if postgres:
        commands = option_values(args, "-c", ("--command",))
        files = option_values(args, "-f", ("--file",))
        known = option_value(args, "-h", ("--host",)) or env.get("PGHOST")
        database = option_value(args, "-d", ("--dbname",)) or env.get("PGDATABASE") or "(default)"
        service = env.get("PGSERVICE") or ""
    else:
        commands = option_values(args, "-Q") + option_values(args, "-q")
        files = option_values(args, "-i")
        known = option_value(args, "-S")
        database = option_value(args, "-d") or "(default)"
        service = ""
    host = known or "(default)"
    if not commands or files or any(value is None for value in commands):
        return _unclassified(cli, command)
    datagrip = _datagrip()
    if all(datagrip.is_read(value, postgres) for value in commands):
        return Outcome("read", [], [], "psql" if postgres else None)
    facts = [datagrip.query_facts(value, postgres) for value in commands]
    if any(keywords is None for keywords, _ in facts):
        return _unclassified(cli, command)
    label = "+".join(sorted(set().union(*(keywords for keywords, _ in facts))))
    target = f"{host}/{database}"
    kind_name = "always" if any(destructive for _, destructive in facts) else "write"
    return Outcome(kind_name, [f"{cli}:{label}@{target}"], [f"{cli} {label} on {target}"],
                   every_time=kind_name == "always",
                   critical=kind_name == "always" and (not known or _production_name(f"{target} {service}")))


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


def strip_prefix(words):
    """Drop leading VAR=value assignments and wrapper commands with their options, returning (words, assignments)."""
    assignments = {}
    index = 0
    while index < len(words):
        word = words[index]
        name = os.path.basename(word)
        if ASSIGNMENT.match(word):
            key, _, value = word.partition("=")
            assignments[key] = value
            index += 1
        elif name == "command" and index + 1 < len(words) and words[index + 1] in ("-v", "-V"):
            return [], assignments
        elif name in WRAPPER_VALUE_OPTIONS:
            value_options = WRAPPER_VALUE_OPTIONS[name]
            index += 1
            while index < len(words) and words[index].startswith("-") and words[index] != "--":
                index += 2 if words[index] in value_options else 1
            if index < len(words) and words[index] == "--":
                index += 1
        elif word in SHELL_KEYWORDS:
            index += 1
        else:
            break
    return words[index:], assignments


def _shell_c(args):
    """Return the script of a sh, bash, or zsh -c call: "" when -c has no script, None when the call is not -c."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return None
        if SHELL_C_FLAG.fullmatch(arg):
            return args[index + 1] if index + 1 < len(args) else ""
        if arg in ("-o", "+o"):
            index += 2
            continue
        if arg.startswith(("-", "+")):
            index += 1
            continue
        return None
    return None


def _helper_args(words):
    """Return the arguments after a `python3 .../secret_exec.py` invocation, or None for any other command."""
    stripped, _ = strip_prefix(words)
    if len(stripped) > 1 and PYTHON.fullmatch(os.path.basename(stripped[0])) and os.path.basename(stripped[1]) == "secret_exec.py":
        return stripped[2:]
    return None


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


def _sensitive(text):
    return Outcome("sensitive", [approval_state.SENSITIVE_KEY], [_one_line(text)])


def _resolved(path, cwd):
    expanded = os.path.expandvars(os.path.expanduser(path))
    return (Path(cwd) / expanded).resolve()


def _guard_state_dirs():
    root = approval_state.state_dir()
    return (root, root.parent / "heartbeats", root.parent / "pycache")


def _state_path(path, cwd):
    candidate = _resolved(path, cwd)
    return any(candidate == directory or directory in candidate.parents
               for directory in (item.resolve() for item in _guard_state_dirs()))


def _protected_path(path, cwd, env=None):
    env = os.environ if env is None else env
    candidate = _resolved(path, cwd)
    home = Path.home()
    protected = [home / item for item in (
        ".kube/config", ".aws/credentials", ".aws/config", ".pgpass", ".docker/config.json", ".netrc",
    )]
    protected.extend(_resolved(item, cwd) for item in env.get("KUBECONFIG", "").split(os.pathsep) if item)
    if candidate.name.startswith(".env") and not candidate.name.endswith(ENV_TEMPLATE_SUFFIXES) or candidate in protected:
        return True
    return any(candidate == directory or directory in candidate.parents for directory in (
        home / ".azure", home / ".config/gcloud",
    ))


def _split_url(url):
    try:
        return urlsplit(url)
    except ValueError:
        return urlsplit("")


def _curl_origin(url):
    """Return scheme://host[:port] for a URL; a malformed port or IPv6 bracket falls back to the scheme and host."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
        scheme = parsed.scheme
    except ValueError:
        match = re.match(r"([a-zA-Z][a-zA-Z0-9+.-]*)://([^/?#]*)", url)
        if not match:
            return None
        scheme, authority = match[1].lower(), match[2].rpartition("@")[2]
        host = authority[1:].partition("]")[0] if authority.startswith("[") else authority.partition(":")[0]
        port = None
    if not host:
        return None
    if ":" in host:
        host = "[" + host + "]"
    return f"{scheme}://{host}" + (f":{port}" if port else "")


def _classify_curl(args, command):
    headers = option_values(args, "-H", ("--header",))
    credentials = (_has_flag(args, "-u", "--user") or bool(option_values(args, "-u", ("--user",)))
                   or any(value and re.match(r"authorization\s*:", value, re.I) for value in headers))
    outcome = _classify_curl_method(args, command)
    if not credentials or outcome.kind in ("pass", "forbidden", "secret") or outcome.every_time:
        return outcome
    if outcome.kind == "read":
        return _sensitive(command)
    return Outcome("sensitive", [approval_state.SENSITIVE_KEY], outcome.descriptions, None, outcome.keys)


def _classify_curl_method(args, command):
    data = any(
        arg in ("-d", "-F", "-T") or arg.startswith(("--data", "--form", "--upload-file", "--json"))
        or (arg.startswith(("-d", "-F", "-T")) and len(arg) > 2) for arg in args
    )
    upload = any(arg == "-T" or arg.startswith(("-T", "--upload-file")) for arg in args)
    method = option_value(args, "-X", ("--request",))
    method = (method or ("PUT" if upload else "POST" if data else "HEAD" if _has_flag(args, "-I", "--head") else "GET")).upper()
    if method in ("GET", "HEAD") and not data:
        return _read()
    targets = set()
    value_options = {
        "-X", "--request", "-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode",
        "--json", "-F", "--form", "--form-string", "-T", "--upload-file", "-H", "--header", "-u", "--user",
        "-x", "--proxy", "-o", "--output", "-b", "--cookie", "-c", "--cookie-jar", "--cacert", "--cert", "--key",
        "--connect-timeout", "--max-time", "-m",
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in value_options:
            index += 2
            continue
        if arg == "--url" and index + 1 < len(args):
            index += 1
            arg = args[index]
        url = arg.partition("=")[2] if arg.startswith("--url=") else arg
        origin = _curl_origin(url) if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*://", url) else None
        if origin:
            targets.add(origin)
        index += 1
    if not targets:
        return _unclassified("curl", command)
    destructive = _destructive([method])
    return Outcome("always" if destructive else "write", [f"curl:{method}@{target}" for target in sorted(targets)],
                   [f"curl {method} on {target}" for target in sorted(targets)], every_time=destructive)


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


def _expand_path_variables(value, variables):
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)",
                  lambda match: variables.get(match[1] or match[2], match[0]), value)


def _script_path(path, cwd, variables):
    expanded = _expand_path_variables(path, variables)
    if "$" in expanded or "`" in expanded:
        return None
    return (Path(cwd) / os.path.expanduser(expanded)).resolve()


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


TEMPORARY_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
TEMP_WRITE_EXE = "temp-write"
VARIABLE_REFERENCE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
BLOCK_OPENERS = frozenset({"if", "while", "until", "for", "case", "select", "{"})
BLOCK_CLOSERS = frozenset({"fi", "done", "esac", "}"})
FILES_MAY_CHANGE = "_APPROVAL_FILES_MAY_CHANGE"
IN_EXEC = "_APPROVAL_IN_EXEC"
OPERAND_READERS = FILE_READS | FILTERS | frozenset({
    "sed", "file", "stat", "ls", "find", "base64", "xxd", "od", "strings", "diff", "cmp", "tar", "zip", "unzip",
})
VARIABLE_WRITERS = frozenset({"read", "mapfile", "readarray", "getopts", "let"})
XARGS_FLAGS = frozenset({
    "-0", "-r", "-t", "-x", "-p", "-o", "--null", "--no-run-if-empty", "--verbose", "--exit", "--interactive",
    "--open-tty",
})
XARGS_VALUE_OPTIONS = frozenset({"-n", "-L", "-P", "-s", "-d", "-E", "-a", "-I", "-J"})
XARGS_ATTACHED_OPTIONS = ("-n", "-L", "-P", "-s", "-d", "-E", "-a", "-l", "-e")
XARGS_LONG_VALUES = ("--max-args", "--max-procs", "--delimiter", "--max-lines", "--arg-file", "--eof", "--max-chars")
XARGS_ARGUMENT = "$XARGS_ARGUMENT"
TEMP_HARMLESS = frozenset({"cat", "echo", "printf", "ls", "head", "tail", "wc", "pwd", "true", "false", "wait", "sleep",
                           "cd", "for"})
COPY_FLAGS = re.compile(r"-[RrapfinvLPHTux]+")
COPY_LONG_FLAGS = frozenset({"--recursive", "--archive", "--force", "--verbose", "--no-clobber", "--update"})


def _python_inline_code(args):
    """The code of a Python `-c` option in any spelling (`-c code`, `-ccode`, `-Ic code`), "" when it has no code, or
    None when the interpreter arguments name a module, a script, or no inline code before the first operand."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--" or arg == "-" or not arg.startswith("-"):
            return None
        if arg.startswith("--"):
            index += 2 if arg == "--check-hash-based-pycs" else 1
            continue
        for position, letter in enumerate(arg[1:], 1):
            if letter == "c":
                return arg[position + 1:] or (args[index + 1] if index + 1 < len(args) else "")
            if letter == "m":
                return None
            if letter in "WX":
                index += 1 if len(arg) > position + 1 else 2
                break
        else:
            index += 1
    return None


def _protected_argument(arg, cwd, env):
    """Whether an argument, or the value attached to its option (`--file=.env`, `-f.env`), names a protected file."""
    values = [arg] if not arg.startswith("-") else [arg.partition("=")[2]] if "=" in arg else []
    if arg.startswith("-") and not arg.startswith("--") and len(arg) > 2:
        values.append(arg[2:].lstrip("="))
    return any(value and _protected_path(value, cwd, env) for value in values)


def _temp_roots(env):
    return [Path(path).resolve() for path in (*TEMPORARY_ROOTS, env.get("TMPDIR") or "/tmp", str(Path.home() / ".cache"))]


def _job_tmp(path):
    """Whether a resolved path lies inside a Claude Code job temp folder, `~/.claude/jobs/<id>/tmp`."""
    try:
        parts = path.relative_to((Path.home() / ".claude" / "jobs").resolve()).parts
    except ValueError:
        return False
    return len(parts) >= 2 and parts[1] == "tmp"


def _temporary(path, env):
    return any(path.is_relative_to(root) for root in _temp_roots(env)) or _job_tmp(path)


def _temp_path(path, cwd, env):
    """Whether a destination word, with no unresolved expansion, resolves into a temporary root."""
    if not path or "$" in path or "`" in path or re.search(r"[*?\[{]", path):
        return False
    return _temporary((Path(cwd) / os.path.expanduser(path)).resolve(), env)


def _static_value(value, statics, environment):
    """The fixed text of an assigned value: a `mktemp -d` substitution resolves like `rm` targets, anything that still
    expands or runs a command has none."""
    expanded = _expand_path_variables(value, statics)
    resolved = _mktemp_directory(expanded if "mktemp" in value else value, environment)
    if resolved is not None:
        return resolved
    return None if "$" in expanded or "`" in expanded else expanded


def _expand_raw_word(raw, statics, split=True):
    """Expand `$NAME` and `${NAME}` that statics define in one raw word, splitting unquoted values at white space as
    sh does. Returns the resulting words, or None when nothing was expanded."""
    fields, current, changed, index, quote = [], None, False, 0, None

    def add(text):
        nonlocal current
        current = (current or "") + text

    def close():
        nonlocal current
        if current is not None:
            fields.append(current)
            current = None

    while index < len(raw):
        char = raw[index]
        if quote == "'":
            if char == "'":
                quote = None
            else:
                add(char)
            index += 1
        elif raw.startswith("$(", index) or char == "`":
            end = _substitution_end(raw, index)
            add(raw[index:end])
            index = end
        elif char == "\\" and quote is None and raw.startswith("\n", index + 1):
            index += 2
        elif char == "\\" and index + 1 < len(raw):
            add(raw[index + 1])
            index += 2
        elif char == "'" and quote is None:
            add("")
            quote = "'"
            index += 1
        elif char == '"':
            add("")
            quote = None if quote == '"' else '"'
            index += 1
        elif char == "$":
            match = VARIABLE_REFERENCE.match(raw, index)
            name = (match[1] or match[2]) if match else None
            value = statics.get(name) if name else None
            if value is None or (quote is None and split and not value.strip()):
                add(char)
                index += 1
                continue
            changed = True
            index = match.end()
            if quote == '"' or not split:
                add(value)
                continue
            if value[0].isspace():
                close()
            for position, part in enumerate(value.split()):
                if position:
                    close()
                add(part)
            if value[-1].isspace():
                close()
        else:
            add(char)
            index += 1
    close()
    return fields if changed else None


def _expand_segment_words(segment, statics):
    """The segment's words with the fixed variables expanded; leading assignment words are never split."""
    if not statics or len(segment.raw) != len(segment.words):
        return segment.words
    words, assigning = [], True
    for word, raw in zip(segment.words, segment.raw):
        assignment = assigning and ASSIGNMENT.match(word) is not None
        assigning = assignment or (assigning and word in SHELL_KEYWORDS)
        try:
            expanded = _expand_raw_word(raw, statics, split=not assignment)
        except ParseError:
            expanded = None
        words.extend([word] if expanded is None else expanded)
    return words


PLAIN_ENVIRONMENT_ARGUMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:=.*)?", re.S)


def _plain_environment_edit(program):
    """For a plain `unset NAME...` or `export NAME[=value]...` (no options, only names): the names whose fixed value is
    forgotten, so the other fixed variables survive it. An exported value is never recorded as fixed. None for any other
    form, which forgets every fixed variable."""
    name = os.path.basename(program[0]) if program else ""
    arguments = program[1:]
    if (name not in ("unset", "export") or not arguments
            or not all(PLAIN_ENVIRONMENT_ARGUMENT.fullmatch(argument) for argument in arguments)
            or name == "unset" and any("=" in argument for argument in arguments)):
        return None
    return {argument.partition("=")[0] for argument in arguments if name == "unset" or "=" in argument}


def _unconditional_assignment(segment, operators, after_assignment):
    """Whether a standalone assignment always runs in the current shell: it follows nothing, `;`, or another assignment
    joined by `&&`, and it is not sent to the background or a pipe."""
    before = max((op for op in operators if op[3] <= segment.start), key=lambda op: op[3], default=None)
    after = min((op for op in operators if op[2] >= segment.end), key=lambda op: op[2], default=None)
    return ((before is None or before[1] == ";" or (before[1] == "&&" and after_assignment))
            and (after is None or after[1] in (";", "&&")))


LISTING_OPTIONS = {
    "grep": (frozenset("lLcq"), "efmABCDd", frozenset({"--files-with-matches", "--files-without-match", "--count", "--quiet",
                                                       "--silent"})),
    "rg": (frozenset("lcq"), "efgmABCdjEMrtT", frozenset({"--files-with-matches", "--files-without-match", "--count",
                                                          "--count-matches", "--quiet"})),
}
LISTING_BLOCKED = frozenset({"--json", "--vimgrep", "--passthru", "--pre", "--replace", "--only-matching"})
LISTING_LONG_VALUES = frozenset({"--regexp", "--file", "--max-count", "--after-context", "--before-context", "--context",
                                 "--include", "--exclude", "--exclude-dir", "--glob", "--type", "--type-not"})


def _lists_names_only(name, args):
    """Whether a grep or rg call has an option that makes it print only file names or counts."""
    letters, values, longs = LISTING_OPTIONS["rg" if name == "rg" else "grep"]
    found, index = False, 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            break
        if arg.split("=", 1)[0] in LISTING_BLOCKED:
            return False
        if arg.startswith("--"):
            found = found or arg in longs
            index += arg in LISTING_LONG_VALUES
        elif arg.startswith("-") and len(arg) > 1:
            for position, letter in enumerate(arg[1:], 1):
                if letter in values:
                    index += position == len(arg) - 1
                    break
                found = found or letter in letters
    return found


def _prints_no_content(words):
    """Whether a simple command can print only the names, counts, sizes, or metadata of the files it is given."""
    stripped, _ = strip_prefix(words)
    if not stripped:
        return False
    name = os.path.basename(stripped[0])
    if name in ("wc", "ls", "stat", "du"):
        return True
    return name in ("grep", "egrep", "fgrep", "rg") and _lists_names_only(name, stripped[1:])


FIND_OUTPUT_ACTIONS = frozenset({"-printf", "-fprintf", "-ls", "-fls", "-exec", "-execdir", "-ok", "-okdir", "-fprint",
                                 "-fprint0"})
PLAIN_LITERAL = re.compile(r"[^$`\\*?\[{}~()<>|&;]*")


def _find_prints_plain_paths(args):
    """Whether a `find` call prints only paths that start with one of its literal roots, none of which starts with `-`."""
    index = 0
    while index < len(args) and args[index] in ("-H", "-L", "-P"):
        index += 1
    roots = []
    while index < len(args) and not args[index].startswith("-") and args[index] not in ("(", "\\(", "!"):
        roots.append(args[index])
        index += 1
    return (all(PLAIN_LITERAL.fullmatch(root) for root in roots) and "--" not in args
            and not FIND_OUTPUT_ACTIONS & set(args))


def _echoes_plain_words(name, args):
    """Whether an `echo` or `printf` call prints only literal words, none of which starts with `-`."""
    if name == "echo" and args[:1] == ["-n"]:
        args = args[1:]
    if name == "printf":
        args = [re.sub(r"\\[nt]", " ", args[0])] + args[1:] if args else args
    return bool(args) and all(PLAIN_LITERAL.fullmatch(arg) and not any(word.startswith("-") for word in arg.split())
                              for arg in args)


def _xargs_reads_file(args):
    """Whether the options of an `xargs` call, before its command, name a file that supplies the input."""
    index = 0
    while index < len(args) and args[index] != "--" and args[index].startswith("-"):
        arg = args[index]
        if arg == "-a" or arg.startswith("--arg-file") or arg.startswith("-a") and not arg.startswith("--"):
            return True
        name = arg.split("=", 1)[0]
        index += 2 if arg in XARGS_VALUE_OPTIONS or (
            name in XARGS_LONG_VALUES and "=" not in arg and name not in ("--eof", "--max-lines")) else 1
    return False


def _xargs_input_has_no_options(argv, call, segment, producer):
    """Whether the words `xargs` appends cannot start with `-` and so cannot reach the command as options: an `--`
    precedes them, or they come from a pipe whose producer prints only literal words or `find` paths."""
    marks = [position for position, word in enumerate(argv) if XARGS_ARGUMENT in word]
    if marks and "--" in argv[:marks[0]]:
        return True
    if producer is None or _xargs_reads_file(call) or any(op == "<" or op == "<<" or op == "<<<"
                                                         for _, op, _ in segment.redirects):
        return False
    words, _ = strip_prefix(producer)
    name = os.path.basename(words[0]) if words else ""
    if name == "find":
        return _find_prints_plain_paths(words[1:])
    return name in ("echo", "printf") and _echoes_plain_words(name, words[1:])


def _xargs_argv(args):
    """The simple command an `xargs` call runs, with its input as one unresolved operand, or None when the call has an
    option, a shell, `eval`, a nested `xargs`, or a replacement in the command name that makes it opaque."""
    replacement, index = None, 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if not arg.startswith("-"):
            break
        name = arg.split("=", 1)[0]
        if arg in XARGS_FLAGS:
            index += 1
        elif arg in ("-I", "-J") and index + 1 < len(args):
            replacement, index = args[index + 1], index + 2
        elif arg in XARGS_VALUE_OPTIONS and index + 1 < len(args):
            index += 2
        elif arg.startswith(("-I", "-J")) and len(arg) > 2:
            replacement, index = arg[2:], index + 1
        elif arg in ("-i", "--replace"):
            replacement, index = "{}", index + 1
        elif arg.startswith("--replace="):
            replacement, index = arg.partition("=")[2], index + 1
        elif arg.startswith("-i") and not arg.startswith("--"):
            replacement, index = arg[2:], index + 1
        elif name in XARGS_LONG_VALUES and ("=" in arg or name in ("--eof", "--max-lines")):
            index += 1
        elif name in XARGS_LONG_VALUES and index + 1 < len(args):
            index += 2
        elif arg.startswith(XARGS_ATTACHED_OPTIONS) and not arg.startswith("--") and len(arg) > 2:
            index += 1
        else:
            return None
    template = list(args[index:])
    stripped, _ = strip_prefix(template)
    if not stripped or replacement == "":
        return None
    name = os.path.basename(stripped[0])
    if name in SHELLS or name in ("eval", "xargs", "exec") or name.startswith("$"):
        return None
    if replacement:
        if replacement in stripped[0]:
            return None
        return [word.replace(replacement, XARGS_ARGUMENT) for word in template]
    return [*template, XARGS_ARGUMENT]


def _temp_segment(words, redirects, cwd, env):
    """The number of writes a simple command makes when every destination is inside a temporary root, else None.
    Only a few commands that cannot run anything else are judged."""
    command = list(words)
    while command and command[0] in SHELL_KEYWORDS:
        command.pop(0)
    writes = 0
    for _, operator, target in redirects:
        if ">" not in operator or target == "/dev/null" or (operator == ">&" and target in ("1", "2")):
            continue
        if not _temp_path(target, cwd, env):
            return None
        writes += 1
    if not command:
        return writes
    name, args = os.path.basename(command[0]), command[1:]
    if command[0] != name and os.path.dirname(command[0]) not in ("/bin", "/usr/bin"):
        return None
    if name in TEMP_HARMLESS:
        return writes
    operands, destinations, index = [], None, 0
    clusters = {"mkdir": "pv", "touch": "acm", "tee": "aip"}.get(name)
    longs = {"mkdir": ("--parents", "--verbose"), "touch": ("--no-create",), "tee": ("--append",)}.get(name, ())
    while index < len(args):
        arg = args[index]
        if arg == "--":
            operands.extend(args[index + 1:])
            break
        if name in ("cp", "mv") and arg in ("-t", "--target-directory") and index + 1 < len(args):
            destinations, index = [args[index + 1]], index + 2
        elif name in ("cp", "mv") and arg.startswith("--target-directory="):
            destinations, index = [arg.partition("=")[2]], index + 1
        elif name == "mkdir" and arg == "-m" and index + 1 < len(args):
            index += 2
        elif ((name in ("cp", "mv") and (COPY_FLAGS.fullmatch(arg) or arg in COPY_LONG_FLAGS))
              or (clusters and re.fullmatch(r"-[" + clusters + r"]+", arg)) or arg in longs):
            index += 1
        elif arg.startswith("-") and arg != "-":
            return None
        else:
            operands.append(arg)
            index += 1
    sources = operands
    if name in ("cp", "mv"):
        if destinations is None:
            if len(operands) < 2:
                return None
            destinations, sources = operands[-1:], operands[:-1]
    elif name in ("mkdir", "touch", "tee"):
        destinations = operands
        if name != "tee" and not operands:
            return None
    else:
        return None
    if not all(_temp_path(path, cwd, env) for path in destinations):
        return None
    if name in ("cp", "mv"):
        for destination in destinations:
            folder = Path(cwd) / os.path.expanduser(destination)
            if not folder.is_dir():
                continue
            for source in sources:
                if not source or re.search(r"[$`*?\[{]", source):
                    return None
                if not _temporary((folder / os.path.basename(source.rstrip("/"))).resolve(), env):
                    return None
    return writes + len(destinations)


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
ENGINE_REMOTE_LONG = frozenset({"--host", "--remote", "--url", "--connection", "--identity"})
ENGINE_REMOTE_SHORT = ("-c", "-H", "-r")
ENGINE_VALUE_OPTIONS = GLOBAL_VALUE_OPTIONS | frozenset({
    "-c", "-l", "--log-level", "--config", "--tlscacert", "--tlscert", "--tlskey", "--identity", "--url", "--connection",
})
PODMAN_SYSTEM_CONFIGS = ("/etc/containers/containers.conf", "/usr/share/containers/containers.conf")
PODMAN_REMOTE_SETTING = re.compile(r"^\s*(?:active_service\s*=\s*[\"'][^\"'\n]+[\"']|remote\s*=\s*true\b)", re.M | re.I)


def _config_text(path):
    """The text of a config file, None when it does not exist; any other failure is raised as OSError or ValueError."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None


def _docker_context_local(name, config_dir):
    """Whether a named Docker context points at a local socket, from its metadata file in the Docker config folder; a
    missing, unreadable, or malformed file, a missing host, or any other scheme counts as remote."""
    if name == "default":
        return True
    try:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        text = _config_text(Path(config_dir) / "contexts" / "meta" / digest / "meta.json")
        host = json.loads(text)["Endpoints"]["docker"]["Host"] if text is not None else None
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return isinstance(host, str) and host.startswith(("unix://", "npipe://"))


def _docker_context_name(config_dir, env):
    """The context the config selects, "default" when none, None when the config cannot be read."""
    try:
        text = _config_text(Path(config_dir) / "config.json")
        data = json.loads(text) if text is not None else {}
    except (OSError, ValueError):
        return None
    current = data.get("currentContext", "") if isinstance(data, dict) else None
    return (current or "default") if isinstance(current, str) else None


def _podman_remote_default(env):
    """Whether containers.conf or the saved system connection makes podman talk to a remote service by default; an
    unreadable file counts as remote."""
    config_home = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "containers"
    files = [env["CONTAINERS_CONF"]] if env.get("CONTAINERS_CONF") else []
    files += [str(config_home / "containers.conf"), *PODMAN_SYSTEM_CONFIGS]
    try:
        for file in list(files):
            folder = Path(file + ".d")
            if folder.is_dir():
                files += sorted(str(item) for item in folder.glob("*.conf"))
        for file in files:
            text = _config_text(file)
            if text is not None and PODMAN_REMOTE_SETTING.search(text):
                return True
        saved = _config_text(config_home / "podman-connections.json")
        if saved is not None:
            connection = json.loads(saved).get("Connection")
            return not isinstance(connection, dict) or bool(connection.get("Default"))
    except (OSError, ValueError, AttributeError):
        return True
    return False


def _local_engine(args, env, engine="docker"):
    """Whether a docker or podman call talks to the engine on this machine: no remote option before the subcommand, no
    context or host variable or saved configuration that names a remote. A named Docker context is local when its
    metadata names a unix socket."""
    index, config_dir, context = 0, None, None
    while index < len(args) and args[index].startswith("-"):
        arg = args[index]
        if engine == "docker" and arg == "--context" and index + 1 < len(args):
            context = args[index + 1]
        elif engine == "docker" and arg.startswith("--context="):
            context = arg.partition("=")[2]
        elif engine == "docker" and arg == "-c" and index + 1 < len(args):
            context = args[index + 1]
        elif engine == "docker" and arg.startswith("-c") and not arg.startswith("--") and len(arg) > 2:
            context = arg[2:].lstrip("=")
        elif arg.split("=", 1)[0] in ENGINE_REMOTE_LONG or (not arg.startswith("--") and arg[:2] in ENGINE_REMOTE_SHORT):
            return False
        elif arg == "--config" and index + 1 < len(args):
            config_dir = args[index + 1]
        elif arg.startswith("--config="):
            config_dir = arg.partition("=")[2]
        index += 2 if arg in ENGINE_VALUE_OPTIONS else 1
    if env.get("CONTAINER_HOST") or env.get("CONTAINER_CONNECTION"):
        return False
    host = (env.get("DOCKER_HOST") or "").strip()
    if host and not host.startswith(("/", "unix://")) and not (
            "://" not in host and (_split_url("//" + host).hostname or "").lower() in LOCAL_HOSTS):
        return False
    if engine == "podman":
        return (env.get("DOCKER_CONTEXT") or "default") == "default" and not _podman_remote_default(env)
    config_dir = config_dir or env.get("DOCKER_CONFIG") or str(Path.home() / ".docker")
    name = context or env.get("DOCKER_CONTEXT") or _docker_context_name(config_dir, env)
    return name is not None and _docker_context_local(name, config_dir)


GIT_HARMLESS_ENV = frozenset({
    "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_PAGER", "GIT_TERMINAL_PROMPT", "GIT_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND",
    "GIT_PROGRESS_DELAY", "GIT_FLUSH", "GIT_MERGE_AUTOEDIT",
})
GIT_HARMLESS_OPTIONS = frozenset({"--no-pager", "-P", "--no-optional-locks", "--paginate", "-p"})
GIT_HARMLESS_CONFIG = frozenset({"credential.interactive", "credential.guiprompt"})
COMMAND_GIT_CONFIG = "_APPROVAL_COMMAND_GIT_CONFIG"
GIT_CONFIG_WORD = re.compile(r"GIT_CONFIG_[A-Z0-9_]+")
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
            capture_output=True, text=True, timeout=LOOKUP_TIMEOUT_SECONDS, env=env, stdin=subprocess.DEVNULL,
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
            if destructive and _lossless_stash_drop(global_args, args, cwd or os.getcwd(),
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


MKTEMP_ARGS = r"((?:\s+[^\s()`$;&|<>\\'\"]+)*)\s*"
MKTEMP_OPERAND = re.compile(r"\$\(\s*mktemp" + MKTEMP_ARGS + r"\)|`\s*mktemp" + MKTEMP_ARGS + "`")
TMPDIR_DEFAULT = re.compile(r"\$\{TMPDIR:-([^${}`\s]*)\}(?=/|$)")


def _mktemp_directory(operand, values):
    """Resolve an operand that is exactly a `mktemp -d` substitution to a path inside the directory it would create in."""
    match = MKTEMP_OPERAND.fullmatch(operand)
    if match is None:
        return None
    words = (match[1] or match[2] or "").split()
    if not any(word == "--directory" or word.startswith("-") and not word.startswith("--") and "d" in word
               for word in words):
        return None
    directory, index = None, 0
    while index < len(words):
        word = words[index]
        if word == "-p" and index + 1 < len(words):
            directory, index = words[index + 1], index + 2
            continue
        if word.startswith("--tmpdir="):
            directory = word.partition("=")[2]
        elif not word.startswith("-"):
            directory = directory or (os.path.dirname(word) or None)
        index += 1
    return os.path.join(directory or values.get("TMPDIR") or "/tmp", "mktemp.XXXXXX")


def _tmpdir_default(operand, values):
    """Resolve a leading ${TMPDIR:-default} to TMPDIR when it is set, else to the literal default."""
    match = TMPDIR_DEFAULT.match(operand)
    return (values.get("TMPDIR") or match[1]) + operand[match.end():] if match else operand


VALUE_REFERENCE = re.compile(
    r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*|\d)(?::-([^${}`\s]*)|:\?[^${}`]*)?\}|([A-Za-z_][A-Za-z0-9_]*|\d))")
SCRIPT_ZERO = r'"?\$(?:0|\{0\}|\{BASH_SOURCE\[0\]\})"?'
SCRIPT_DIRNAME = rf"\$\(\s*dirname\s+{SCRIPT_ZERO}\s*\)"
SCRIPT_FOLDER = re.compile(
    rf'\$\(\s*cd\s+"?{SCRIPT_DIRNAME}"?\s*&&\s*pwd\s*\)|{SCRIPT_DIRNAME}|\$\{{(?:0|BASH_SOURCE\[0\])%/\*\}}')
SCRIPT_FOLDER_KEY = "@dir"
POSITIONAL_WRITERS = frozenset({"set", "shift", "eval", "source", ".", "exec"})
VALUE_LIMIT = 32
FLOW_ENVIRONMENT = frozenset({"HOME", "TMPDIR"})
FLOW_LEADS = frozenset({"then", "else", "do", "{", "!"})
FLOW_LOOPS = frozenset({"for", "select", "while", "until"})
FILE_INERT = frozenset({"[", "[[", "test", ":", "true", "false"})
FLOW_CLOSERS = {"then": "if", "else": "if", "elif": "if", "fi": "if", "do": "loop", "done": "loop", "esac": "case",
                "}": "brace"}
PIPE_OPERATORS = ("|", "|&")
GIT_PLAIN_CONFIG = ("-c", "status.showUntrackedFiles=all", "-c", "core.excludesFile=/dev/null",
                    "-c", "status.ignoreSubmodules=none", "-c", "core.untrackedCache=false")
REMOVAL_TRACKED = "Recursive removal of tracked files"
REMOVAL_IGNORED = "Recursive removal of ignored files"


UNMODELED_EXPANSION = re.compile(
    r"(?<!\$)\{[^{}]*(?:,|\.\.)[^{}]*\}|\$[@*]|\$\{[@*]|\$\(\(|[<>]\(|(?:^|[=:])~[A-Za-z_]")


def _unmodeled_expansion(text):
    """Whether a word holds an expansion the guard does not model: brace expansion, `$@`, `$*`, arithmetic expansion,
    process substitution, or `~user`."""
    return UNMODELED_EXPANSION.search(text) is not None


def _unquoted_glob(raw):
    """Whether a raw shell word holds a glob character outside quotes."""
    quote, index = None, 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if char in "'\"" and quote in (None, char):
            quote = None if quote else char
        elif quote is None and char in "*?[":
            return True
        index += 1
    return False


def _expand_references(text, lookup):
    """Every value `text` can take when each `$NAME`, `${NAME}`, `${NAME:-default}`, or `${NAME:?message}` takes any
    value that `lookup(name, default)` returns; the last form aborts the shell when the name is unset or empty, so it
    can only take the values `$NAME` takes. None when a command runs, a reference stays unresolved, or the combinations
    exceed the limit."""
    if "`" in text or "$(" in text or _unmodeled_expansion(text):
        return None
    results, position = [""], 0
    for match in VALUE_REFERENCE.finditer(text):
        options = lookup(match[1] or match[3], match[2])
        if options is None:
            return None
        if match[2] is None and ":?" in match[0]:
            options = tuple(option for option in options if option)
        literal = text[position:match.start()]
        results = [done + literal + option for done in results for option in options]
        if len(results) > VALUE_LIMIT:
            return None
        position = match.end()
    results = [done + text[position:] for done in results]
    return None if any("$" in done for done in results) else tuple(dict.fromkeys(results))


def _merge_values(states, missing=None):
    """The variable table after paths that end in `states` rejoin: a name keeps the union of its values only when every
    path assigns it, and is unresolved (None) otherwise. With `missing`, a path that never assigned a name contributes
    `missing(name)` instead, the value of a variable that is unset there."""
    merged = {}
    for name in {name for state in states for name in state}:
        values = [state[name] if name in state else missing(name) if missing else False for state in states]
        if any(value is None or value is False for value in values):
            merged[name] = None
            continue
        union = tuple(dict.fromkeys(item for value in values for item in value))
        merged[name] = union if len(union) <= VALUE_LIMIT else None
    return merged


def _option_only_set(args):
    """Whether the arguments of `set` only switch shell options and write no variable or positional parameter."""
    index = 0
    while index < len(args):
        if args[index] in ("-o", "+o"):
            index += 2
        elif re.fullmatch(r"[-+][A-Za-z]+", args[index]):
            index += 1
        else:
            return False
    return True


def _wide_effect(words, raw):
    """The names a command may write through something other than a plain assignment, or None when it writes none."""
    program, _ = strip_prefix(words)
    name = os.path.basename(program[0]) if program else ""
    if name == "set" and _option_only_set(program[1:]):
        return None
    if not (name in ENVIRONMENT_CHANGERS or name in VARIABLE_WRITERS or name in POSITIONAL_WRITERS
            or name == "printf" and "-v" in program or ":=" in raw or "((" in raw):
        return None
    names = ({word.partition("=")[0] for word in program[1:] if not word.startswith("-")}
             | {word.partition("=")[0] for word in words if ASSIGNMENT.match(word)})
    return names | set("123456789") if name in POSITIONAL_WRITERS else names


def _positional(name):
    return name.isdigit() or name == SCRIPT_FOLDER_KEY


def _loop_raws(segment, words, start):
    """The raw shell words of `words[start:]`, where `words` is the tail of the segment's words, or None when the raw
    words do not line up with the words."""
    raw = segment.raw
    if len(raw) != len(segment.words) or len(words) > len(raw):
        return None
    return raw[len(raw) - len(words) + start:]


def _loop_effects(segments, index):
    """The names the body of the loop that segment `index` opens may write, and whether anything in it may write any
    name."""
    names, wide, depth, closed = set(), False, 0, False
    for segment in segments[index + 1:]:
        words = list(segment.words)
        while words and (words[0] in FLOW_LEADS or words[0] in ("if", "elif")):
            words.pop(0)
        if words[:1] == ["done"]:
            if not depth:
                closed = True
                break
            depth -= 1
        elif words[:1] and words[0] in FLOW_LOOPS:
            depth += 1
            if words[0] in ("for", "select") and len(words) > 1:
                names.add(words[1])
            words.pop(0)
        assigned = [word for word in words if ASSIGNMENT.match(word)]
        if words and len(assigned) == len(words):
            names.update(word.partition("=")[0] for word in assigned)
            continue
        effect = _wide_effect(words, " ".join(segment.raw)) if words else None
        if effect is not None:
            wide = True
            names.update(effect)
    return names, wide or not closed


class _ValueFlow:
    """The values each variable can hold while a command text runs, followed through `if`, `case`, loops, brace groups,
    and subshells. `state` maps a name to a tuple of every value it can hold at the current point, or to None when it
    is unresolved; a name assigned on only some paths is unresolved. An assignment that runs only when an earlier
    command of a `&&` or `||` list succeeds or fails is conditional: the rest of that list sees the new value, and what
    follows the list sees it together with the value from before the list, which is the empty string for a variable
    that is unset. When the structure cannot be followed, `enabled` turns False and callers fall back to the plain
    variable table."""

    def __init__(self, inherited=None):
        self.state = dict(inherited or {})
        self.frames = []
        self.enabled = True
        self.environment = {}
        self.pending = {}
        self.may_skip = False
        self.or_seen = False

    def choices(self):
        return self.state if self.enabled else None

    def outside_loop_header(self):
        """Whether the segment just visited is known not to be in a loop header, which runs again after the body."""
        return self.enabled and not (self.frames and self.frames[-1]["kind"] == "loop"
                                     and self.frames[-1]["phase"] == "cond")

    def _fail(self):
        self.enabled = False

    def _poison(self, names=(), everything=False):
        top = self.frames[-1] if self.frames else None
        tables = [self.state]
        if top is not None and top.get("phase") == "cond":
            tables += [top["entry"], *top["branches"]]
        for table in tables:
            for name in [*(name for name in table if not _positional(name)), *names] if everything else names:
                table[name] = None

    def _lookup(self, name, default, environment):
        if name in self.state:
            values = self.state[name]
        elif name in FLOW_ENVIRONMENT and environment.get(name):
            values = (environment[name],)
        elif name == "TMPDIR" and default is not None:
            return (default,)
        else:
            return None
        return values if values is None or default is None else tuple(value or default for value in values)

    def _expand(self, text, environment):
        folder = self.state.get(SCRIPT_FOLDER_KEY)
        if folder:
            text = SCRIPT_FOLDER.sub(lambda _: folder[0], text)
        resolved = _mktemp_directory(text, environment)
        template = re.fullmatch(r"\$\(\s*mktemp((?:\s+[^\s()`;&|<>\\'\"]+)*)\s*\)", text)
        if resolved is None and template is not None:
            texts = _expand_references(template[1], lambda name, default: self._lookup(name, default, environment))
            resolved = (_mktemp_directory(f"$(mktemp{texts[0]})", environment)
                        if texts is not None and len(texts) == 1 else None)
        if resolved is not None:
            return (resolved,)
        return _expand_references(text, lambda name, default: self._lookup(name, default, environment))

    def _restore(self, saved):
        """Go back to `saved` after a group whose assignments do not last; a name only that group assigned stays
        unresolved instead of falling back to the process environment."""
        for name in self.state:
            saved.setdefault(name, None)
        self.state = saved

    def _unset(self, name):
        """The value a name has where no assignment ran: the environment's, else the empty string."""
        return (self.environment.get(name, ""),)

    def _resolve_pending(self):
        """End a `&&` or `||` list: each name a conditional assignment set now also keeps its value from before."""
        for name, before in self.pending.items():
            self.state[name] = _merge_values([{name: before}, {name: self.state.get(name)}])[name]
        self.pending = {}

    def _push(self, kind, before, **fields):
        guard = before if before in PIPE_OPERATORS or before == "||" or before == "&&" and self.may_skip else None
        self.frames.append({"kind": kind, "outer": dict(self.state), "guard": guard, "branches": [],
                            "entry": dict(self.state), **fields})
        self.may_skip = self.or_seen = False

    def _pop(self, after):
        """Close the top frame; a group that runs only after `&&` or `||` may not have run, and one run in a pipe or in
        the background leaves no assignment behind."""
        frame = self.frames.pop()
        if frame["guard"] in PIPE_OPERATORS or after in (*PIPE_OPERATORS, "&"):
            self._restore(frame["outer"])
        elif frame["guard"] in ("&&", "||"):
            self.state = _merge_values([frame["outer"], self.state], self._unset)
        self.may_skip = True

    def visit(self, segments, index, operators, environment):
        """Apply one segment, with the operators between it and the segment before it, to the variable table."""
        if not self.enabled:
            return
        self.environment = environment
        segment = segments[index]
        start = segments[index - 1].end if index else 0
        before, previous = None, None
        for token in (op for op in operators if start <= op[2] and op[3] <= segment.start):
            symbol = token[1]
            top = self.frames[-1] if self.frames else None
            in_pattern = top is not None and top["kind"] == "case" and top["phase"] == "pattern"
            if symbol == "(":
                if (previous is not None and previous[1] == "(" and previous[3] == token[2]
                        or before is None and index and not in_pattern):
                    return self._fail()
                if not in_pattern:
                    self._push("sub", before)
            elif symbol == ")":
                self._resolve_pending()
                if in_pattern:
                    top["phase"] = "body"
                    self.state = dict(top["entry"])
                elif top is not None and top["kind"] == "sub":
                    self.frames.pop()
                    self._restore(top["entry"])
                    self.may_skip = True
                else:
                    return self._fail()
            elif symbol == ";;":
                self._resolve_pending()
                self.may_skip = self.or_seen = False
                if top is None or top["kind"] != "case" or top["phase"] != "body":
                    return self._fail()
                top["branches"].append(self.state)
                top["phase"] = "pattern"
            else:
                if symbol in (";", "&"):
                    self._resolve_pending()
                    self.may_skip = self.or_seen = False
                elif symbol == "||" or symbol == "&&" and self.or_seen:
                    self._resolve_pending()
                    self.or_seen = self.or_seen or symbol == "||"
                before = symbol
            previous = token
        after = min((op for op in operators if op[2] >= segment.end), key=lambda op: op[2], default=None)
        self._statement(list(segment.words), segments, index, before, after[1] if after else None,
                        " ".join(segment.raw), environment)

    def _statement(self, words, segments, index, before, after, raw, environment):
        top = self.frames[-1] if self.frames else None
        if top is not None and top["kind"] == "case" and top["phase"] == "pattern" and words[:1] != ["esac"]:
            top["default"] = top["default"] or "*" in words
            return
        while words:
            word, top = words[0], (self.frames[-1] if self.frames else None)
            kind = top["kind"] if top is not None else None
            if word == "function" or word in FLOW_CLOSERS and kind != FLOW_CLOSERS[word]:
                return self._fail()
            if word == "{":
                self._push("brace", before)
            elif word == "if":
                self._push("if", before, has_else=False, phase="cond")
            elif word in ("then", "do"):
                top["phase"] = "body"
            elif word in ("else", "elif"):
                top["branches"].append(self.state)
                self.state = dict(top["entry"])
                top["has_else"] = top["has_else"] or word == "else"
                top["phase"] = "body" if word == "else" else "cond"
            elif word == "fi":
                self.state = _merge_values([*top["branches"], self.state, *([] if top["has_else"] else [top["entry"]])])
                return self._pop(after)
            elif word == "}":
                return self._pop(after)
            elif word == "case":
                patterns = words[words.index("in") + 1:] if "in" in words else []
                self._push("case", before, phase="pattern", default="*" in patterns)
                return
            elif word == "esac":
                arms = [*top["branches"], *([self.state] if top["phase"] == "body" else [])]
                self.state = _merge_values(arms if top["default"] else [*arms, top["entry"]])
                return self._pop(after)
            elif word in FLOW_LOOPS:
                variable = words[1] if word in ("for", "select") and len(words) > 1 else None
                values = None
                if variable is not None and len(words) > 3 and words[2] == "in":
                    values = self._loop_values(words[3:], _loop_raws(segments[index], words, 3), environment)
                names, wide = _loop_effects(segments, index)
                self._poison(names, everything=wide)
                self._push("loop", before, phase="cond", variable=variable)
                if variable is not None:
                    self.state[variable] = values
                if word in ("while", "until"):
                    words.pop(0)
                    continue
                return
            elif word == "done":
                self.state = _merge_values([top["entry"], self.state])
                if top["variable"] is not None:
                    self.state[top["variable"]] = None
                return self._pop(after)
            elif word != "!":
                break
            words.pop(0)
        self._effect(words, before, after, raw, environment)

    def _loop_values(self, items, raws, environment):
        """The words a `for` list can take: an unquoted expansion splits its value at white space, and a value with white
        space whose quoting is unknown leaves the list unresolved."""
        values = []
        for position, item in enumerate(items):
            expanded = self._expand(item, environment)
            if expanded is None:
                return None
            raw = raws[position] if raws is not None and position < len(raws) else None
            if raw is not None and _unquoted_reference(raw) and _mktemp_directory(item, environment) is None:
                if "IFS" in self.state:
                    return None
                expanded = tuple(field for value in expanded for field in value.split())
            elif any(re.search(r"\s", value) for value in expanded) and raw is None:
                return None
            values.extend(expanded)
        return tuple(dict.fromkeys(values)) if len(values) <= VALUE_LIMIT else None

    def _effect(self, words, before, after, raw, environment):
        if not words:
            return
        condition = bool(self.frames) and self.frames[-1].get("phase") == "cond"
        assigned = [word for word in words if ASSIGNMENT.match(word)]
        if len(assigned) != len(words):
            self.may_skip = True
            effect = _wide_effect(words, raw)
            if effect is not None:
                self._poison(effect, everything=True)
            return
        detached = before in PIPE_OPERATORS or after in (*PIPE_OPERATORS, "&")
        guarded = before == "||" or before == "&&" and self.may_skip
        for word in words:
            name, _, value = word.partition("=")
            values = self._expand(value, environment)
            if condition or detached:
                self._poison({name})
            elif guarded:
                if name not in self.pending:
                    self.pending[name] = self.state[name] if name in self.state else self._unset(name)
                self.state[name] = values
            else:
                self.state[name] = values
        self.may_skip = self.may_skip or before == "||"


def _value_lookup(choices, values):
    """The `lookup` that resolves a reference against the flow table first and the plain values second."""
    choices = choices or {}

    def lookup(name, default):
        if name in choices:
            found = choices[name]
        elif values.get(name) is not None:
            found = (values[name],)
        elif name == "TMPDIR" and default is not None:
            return (default,)
        else:
            return None
        return found if found is None or default is None else tuple(value or default for value in found)

    return lookup


def _script_seed(resolved, positional, lookup):
    """The flow table a script starts with: its own path and folder, and the values of `$1` to `$9` from the call's
    literal arguments, each unresolved when its argument is or when a glob in an earlier or the same argument may change
    the argument count."""
    seed = {"0": (str(resolved),), SCRIPT_FOLDER_KEY: (str(resolved.parent),)}
    settled = True
    for number in range(1, 10):
        values = None
        if settled and number <= len(positional):
            settled = re.search(r"[*?\[]", positional[number - 1]) is None
            values = _expand_references(positional[number - 1], lookup) if settled else None
        elif settled:
            values = ("",)
        seed[str(number)] = values
    return seed


def _shell_c_seed(segment, lookup):
    """For a `sh|bash|zsh -c '<script>' <name> <arg>...` call: the script and the flow table that starts it, with `$0` and
    `$1` to `$9` taken from the call's arguments when they resolve. An unquoted argument whose value has white space
    splits into more words, so it and every argument after it stay unresolved. (None, None) for any other call."""
    words, _ = strip_prefix(segment.words)
    if not words or os.path.basename(words[0]) not in SHELLS or not _shell_c(words[1:]):
        return None, None
    args = words[1:]
    index = next(position for position, arg in enumerate(args) if SHELL_C_FLAG.fullmatch(arg))
    rest = args[index + 2:]
    raw = segment.raw if len(segment.raw) == len(segment.words) else None
    raws = raw[len(raw) - len(rest):] if raw is not None and rest else [None] * len(rest)
    table, resolved = {}, True
    for number in range(10):
        if number < len(rest):
            quoted = raws[number]
            values = _expand_references(rest[number], lookup) if resolved else None
            if resolved and (_unquoted_glob(quoted) if quoted is not None else re.search(r"[*?\[]", rest[number])):
                values = None
            elif values is not None and quoted is not None and "'" in quoted:
                values = None
            elif values is not None and (quoted is None or _unquoted_reference(quoted)) and any(
                    re.search(r"\s", value) for value in values):
                values = None
            resolved = resolved and values is not None
        else:
            values = ("",) if resolved and number else None
        table[str(number)] = values
    return args[index + 1], table


def _covered_only_as_commands(body):
    """Whether every covered CLI the script names outside quoted data is the program of a simple command, which the
    classification of the script already judged."""
    try:
        segments = tokenize(body)
    except ParseError:
        return False
    programs = sum(1 for segment in segments
                   if (words := strip_prefix(segment.words)[0]) and os.path.basename(words[0]) in COVERED)
    return programs == len(list(COVERED_WORD.finditer(_without_data(body))))


def _operand_texts(operand, values, choices):
    """Every text a recursive `rm` operand can take, or None when it still expands or runs a command. Without a flow
    table the operand resolves against `values` alone."""
    if _unmodeled_expansion(operand):
        return None
    if choices is None:
        expanded = (_mktemp_directory(operand, values)
                    or _mktemp_directory(_expand_path_variables(operand, values), values)
                    or _expand_path_variables(_tmpdir_default(operand, values), values))
        return None if "$" in expanded or "`" in expanded else [expanded]
    resolved = _mktemp_directory(operand, values)
    if resolved is not None:
        return [resolved]
    texts = _expand_references(operand, _value_lookup(choices, values))
    return None if texts is None else list(texts)


def _unquoted_reference(raw):
    """Whether a raw shell word expands a variable or a command outside quotes, which splits its value at white
    space."""
    quote, index = None, 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if char in "'\"" and quote in (None, char):
            quote = None if quote else char
        elif quote is None and (char == "`" or char == "$" and VALUE_REFERENCE.match(raw, index)):
            return True
        elif quote is None and char == "$" and raw.startswith("$(", index):
            return True
        index += 1
    return False


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


DISCARD_LABEL = "Removal that discards uncommitted work"
DISCARD_MAX_TARGETS = 3000
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
            capture_output=True, text=True, timeout=LOOKUP_TIMEOUT_SECONDS, env=env, stdin=subprocess.DEVNULL,
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
            if path.is_dir() and not _temporary(path, env):
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


def _removal_path(text):
    """The path a removal deletes, with its folder resolved and a symbolic link kept as the link itself, or None for a
    link or the filesystem root."""
    text = os.path.abspath(text)
    if text == os.path.dirname(text) or os.path.islink(text):
        return None
    return Path(os.path.realpath(os.path.dirname(text))) / os.path.basename(text)


def _operand_paths(text, cwd):
    """The paths a resolved `rm` or `git rm` operand names, expanding a glob to its matches."""
    link = os.path.join(cwd, os.path.expanduser(text))
    if re.search(r"[*?\[]", link):
        matches = sorted(glob.glob(link))
        if len(matches) > DISCARD_MAX_TARGETS:
            fixed = re.split(r"[*?\[]", link, maxsplit=1)[0]
            matches = [fixed if fixed.endswith("/") else os.path.dirname(fixed)]
    else:
        matches = [link]
    return [path for path in map(_removal_path, matches) if path is not None]


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
        done = subprocess.run(["find", *leading, *starts, *listing], capture_output=True, timeout=LOOKUP_TIMEOUT_SECONDS,
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


EVAL_WORKSPACE = "harness-eval"
EVAL_RUNS = "runs"


def _evaluation_scratch(covering, expanded, cwd):
    """Whether a removal target lies strictly inside the plugin's evaluation workspace, `<state root>/harness-eval`, and
    reaches neither a `runs` folder nor a path outside it. The target arrives resolved, so a symbolic link out of the
    workspace puts it outside; a glob is checked against the entries it matches."""
    try:
        root = (approval_state.state_dir().parent / EVAL_WORKSPACE).resolve()
        if not covering.relative_to(root).parts:
            return False
        matches = _operand_paths(expanded, cwd) if re.search(r"[*?\[]", expanded) else [covering]
        return all(match.relative_to(root).parts and EVAL_RUNS not in match.relative_to(root).parts
                   and _holds_no_runs_folder(match) for match in matches)
    except (ValueError, OSError, RuntimeError):
        return False


EVAL_WALK_LIMIT = 5000


def _holds_no_runs_folder(path):
    """Whether no folder named `runs` lies below an existing path; a walk that fails or passes the entry limit counts as
    finding one."""
    failed, seen = [], 0
    if not path.is_dir():
        return True
    for _, folders, files in os.walk(path, onerror=failed.append):
        seen += len(folders) + len(files)
        if failed or seen > EVAL_WALK_LIMIT or EVAL_RUNS in folders:
            return False
    return not failed


SHALLOW_TEMPORARY_ROOTS = {"folders": 4}
TEMPORARY_FOLDER_DEPTH = 2
_REMOVAL_TRACE = None


def _inside_temporary_root(path, extra=0):
    """Whether a resolved path, with `extra` more levels that a glob adds below it, lies strictly inside a temporary
    root and deeper than its top-level folders; the system folder `/var/folders` needs its per-user levels as well."""
    for root in TEMPORARY_ROOTS:
        try:
            depth = len(path.relative_to(Path(root).resolve()).parts)
        except (ValueError, OSError, RuntimeError):
            continue
        if depth + extra >= SHALLOW_TEMPORARY_ROOTS.get(Path(root).name, TEMPORARY_FOLDER_DEPTH):
            return True
    return False


def _trace_removal(inside):
    """While a trace is open, record whether one `rm` call removes only static paths strictly inside a temporary root."""
    if _REMOVAL_TRACE is not None:
        _REMOVAL_TRACE.append(inside)


_COMMAND_TRACE = None
INERT_PROGRAMS = frozenset({"cd", "ls", "pwd", "echo", "printf", "true", "false", "wc", "du", "df", "sleep", "[", "[[",
                            "test", ":", "for", "dirname", "basename", "shopt"})
PATH_ALTERING_NAMES = re.compile(r"PATH|IFS|ENV|BASH_ENV|SHELLOPTS|BASHOPTS|PROMPT_COMMAND|PS4|LD_\w*|DYLD_\w*")
FUNCTION_DEFINITION = re.compile(r"\(\s*\)")
MKDIR_FLAGS = re.compile(r"-[pv]+")
MKDIR_LONG_FLAGS = frozenset({"--parents", "--verbose"})


def _trace_command(safe):
    """While a trace is open, record whether one simple command is inert or writes only inside a temporary root."""
    if _COMMAND_TRACE is not None:
        _COMMAND_TRACE.append(safe)


def _static_texts(operand, raw, values, choices):
    """Every text a path operand can take, resolving `$(dirname ...)` of a resolvable operand; None when it still
    expands, runs another command, or splits at white space."""
    inner = re.fullmatch(r"\$\(\s*dirname\s+(?:--\s+)?(.+?)\s*\)", operand)
    if inner is not None:
        word = inner[1]
        if len(word) > 1 and word[0] == word[-1] and word[0] in "'\"":
            word = word[1:-1]
        texts = _static_absolute_texts(word, None, values, choices)
        return None if texts is None else [os.path.dirname(text) for text in texts]
    found = _operand_texts(operand, values, choices)
    if found is not None and raw is not None and _unquoted_reference(raw) and _mktemp_directory(
            operand, values) is None:
        if "IFS" in values or "IFS" in (choices or {}) or re.search(r"\s", operand):
            return None
        found = [field for text in found for field in text.split()]
    return found or None


def _static_absolute_texts(operand, raw, values, choices):
    """Every absolute path text an operand can take, or None when it is not fully static."""
    found = _static_texts(operand, raw, values, choices)
    if not found or any(not text.startswith("/") or re.search(r"[*?\[]", text) for text in found):
        return None
    return found


def _strictly_inside_temporary_root(texts, cwd):
    try:
        return all(_inside_temporary_root((Path(cwd) / text).resolve()) for text in texts)
    except (OSError, RuntimeError):
        return False


def _mkdir_inside_temporary_root(args, raw_args, cwd, values, choices):
    """Whether a `mkdir` call with plain flags creates only static folders strictly inside a temporary root."""
    operands = []
    for position, arg in enumerate(args):
        if arg == "--" or MKDIR_FLAGS.fullmatch(arg) or arg in MKDIR_LONG_FLAGS:
            continue
        if arg.startswith("-"):
            return False
        raw = raw_args[position] if raw_args is not None and position < len(raw_args) else arg
        operands.append((arg, raw))
    if not operands:
        return False
    for arg, raw in operands:
        texts = _static_absolute_texts(arg, raw, values, choices)
        if texts is None or not _strictly_inside_temporary_root(texts, cwd):
            return False
    return True


def _redirects_write_only_inside_temporary_root(redirects, cwd, values, choices):
    """Whether every output redirect of a command goes to `/dev/null`, joins standard output or error, or writes a
    static file strictly inside a temporary root."""
    for _, operator, target in redirects:
        if ">" not in operator or target == "/dev/null" or (operator == ">&" and target in ("1", "2")):
            continue
        texts = _static_absolute_texts(target, None, values, choices)
        if texts is None or not _strictly_inside_temporary_root(texts, cwd):
            return False
    return True


def _operand_pairs(args, raw_args, allowed_flag):
    """The operands of a call as (text, raw) pairs, or None when a flag is not one that `allowed_flag` accepts."""
    pairs, flags_ended = [], False
    for position, arg in enumerate(args):
        raw = raw_args[position] if raw_args is not None and position < len(raw_args) else arg
        if not flags_ended and arg == "--":
            flags_ended = True
        elif not flags_ended and arg.startswith("-") and arg != "-":
            if not allowed_flag(arg):
                return None
        else:
            pairs.append((arg, raw))
    return pairs


def _copy_flag(arg):
    return COPY_FLAGS.fullmatch(arg) is not None or arg in COPY_LONG_FLAGS


def _copy_sources_resolve(sources, destinations, values, choices, cwd):
    """Whether every `cp` source is a static word that cannot read as an option and, where a destination is an existing
    folder, lands strictly inside a temporary root under its own name."""
    folders = [Path(cwd) / text for text in destinations if (Path(cwd) / text).is_dir()]
    for arg, raw in sources:
        texts = _static_texts(arg, raw, values, choices)
        if texts is None or any(not text or text.startswith("-") or text[0] in "*?[" for text in texts):
            return False
        if folders and any(re.search(r"[*?\[]", text) for text in texts):
            return False
        for folder in folders:
            if not _strictly_inside_temporary_root(
                    [str(folder / os.path.basename(text.rstrip("/"))) for text in texts], cwd):
                return False
    return True


def _copy_inside_temporary_root(cli, args, raw_args, cwd, values, choices):
    """Whether a plain `cp` or `mv` writes only static paths strictly inside a temporary root; a `cp` may read from
    anywhere, while a `mv` also removes its sources and so needs them inside as well."""
    pairs = _operand_pairs(args, raw_args, _copy_flag)
    if pairs is None or len(pairs) < 2:
        return False
    (destination, destination_raw), sources = pairs[-1], pairs[:-1]
    destinations = _static_absolute_texts(destination, destination_raw, values, choices)
    if destinations is None or not _strictly_inside_temporary_root(destinations, cwd):
        return False
    if cli == "mv":
        for arg, raw in sources:
            texts = _static_absolute_texts(arg, raw, values, choices)
            if texts is None or not _strictly_inside_temporary_root(texts, cwd):
                return False
    return _copy_sources_resolve(sources, destinations, values, choices, cwd)


def _touch_inside_temporary_root(args, raw_args, cwd, values, choices):
    """Whether a flagless `touch` creates only static files strictly inside a temporary root."""
    pairs = _operand_pairs(args, raw_args, lambda arg: False)
    if not pairs:
        return False
    for arg, raw in pairs:
        texts = _static_absolute_texts(arg, raw, values, choices)
        if texts is None or not _strictly_inside_temporary_root(texts, cwd):
            return False
    return True


COMMIT_ISH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./^~-]*")


def _worktree_add_inside_temporary_root(args, raw_args, cwd, values, choices):
    """Whether `git worktree add [--detach] <path> [<commit-ish>]` puts the new work tree at a static path strictly
    inside a temporary root. Its only effect outside is the administrative entry under `.git/worktrees/`, which
    `git worktree prune` or `git worktree remove` undoes; it creates no ref and changes no tracked file."""
    if args[:2] != ["worktree", "add"]:
        return False
    pairs = _operand_pairs(args[2:], raw_args[2:] if raw_args is not None else None, lambda arg: arg == "--detach")
    if not pairs or len(pairs) > 2 or "--" in args[2:]:
        return False
    if len(pairs) == 2 and not COMMIT_ISH.fullmatch(pairs[1][0]):
        return False
    texts = _static_absolute_texts(pairs[0][0], pairs[0][1], values, choices)
    return texts is not None and _strictly_inside_temporary_root(texts, cwd)


GO_BOOLEAN_FLAGS = frozenset({"-v", "-race", "-short", "-cover", "-failfast", "-json", "-vet=off", "-mod=readonly",
                              "-mod=vendor", "-trimpath"})
GO_VALUE_FLAGS = frozenset({"-count", "-p", "-parallel", "-timeout", "-run", "-tags"})
GO_FLAG_VALUE = re.compile(r"[A-Za-z0-9_.,|^()*+?/][A-Za-z0-9_.,|^()*+?/-]*")
GO_PACKAGE = re.compile(r"\.|(?:\./)?(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*(?:\.\.\.|[A-Za-z0-9_][A-Za-z0-9_.-]*)")
GO_ENVIRONMENT_NAMES = ("GOFLAGS", "GOENV", "GOCACHE")


def _go_arguments_confined(args):
    """Whether the words after `go build|vet|test` are only plain flags and relative package patterns."""
    index = 0
    while index < len(args):
        arg = args[index]
        name, equals, value = arg.partition("=")
        if arg in GO_BOOLEAN_FLAGS:
            index += 1
        elif name in GO_VALUE_FLAGS and equals:
            if not GO_FLAG_VALUE.fullmatch(value):
                return False
            index += 1
        elif arg in GO_VALUE_FLAGS and index + 1 < len(args):
            if not GO_FLAG_VALUE.fullmatch(args[index + 1]):
                return False
            index += 2
        elif not arg.startswith("-") and GO_PACKAGE.fullmatch(arg):
            index += 1
        else:
            return False
    return True


def _go_inside_temporary_root(args, cwd, env, variables):
    """Whether `go build|vet|test` with only plain flags and relative package patterns runs in a folder strictly inside
    a temporary root and with no Go environment override: its artifacts go to that copy and to the regenerable build
    cache. `go build` of several packages discards its results."""
    if not args or args[0] not in ("build", "vet", "test") or not _go_arguments_confined(args[1:]):
        return False
    if any(name in source for name in GO_ENVIRONMENT_NAMES for source in (env, variables)):
        return False
    return _strictly_inside_temporary_root(["."], cwd)


def _confined_command(cli, args, raw_args, cwd, env, variables, choices, assignments):
    """Whether one simple command is a write the guard can confine to a temporary root: `cp`, `mv`, and `touch` of
    static paths inside it, `git worktree add` into it, and `go build|vet|test` run inside it."""
    if assignments:
        return False
    values = {**env, **variables}
    if cli in ("cp", "mv"):
        return _copy_inside_temporary_root(cli, args, raw_args, cwd, values, choices)
    if cli == "touch":
        return _touch_inside_temporary_root(args, raw_args, cwd, values, choices)
    if cli == "git":
        return _worktree_add_inside_temporary_root(args, raw_args, cwd, values, choices)
    if cli == "go":
        return _go_inside_temporary_root(args, cwd, env, variables)
    return False


READER_BLOCKED_PROGRAMS = frozenset(COVERED - {"git"}) | SHELLS


def _filter_may_write(cli, args):
    """Whether a filter program of the guard writes a file or runs a program through one of its options."""
    if cli == "sort":
        return any(arg.startswith("--output") or re.fullmatch(r"-[A-Za-z]*o.*", arg) for arg in args)
    if cli == "uniq":
        return sum(1 for arg in args if not arg.startswith("-")) > 1
    return cli in ("rg", "grep", "egrep", "fgrep") and any(arg.startswith(("--pre", "--hostname-bin")) for arg in args)


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
                temporary = _temporary(path, env)
                if (path == Path("/") or path == Path.home() or path == session or path in session.parents
                        or ".git" in path.parts):
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


def _git_read_runs(processes, cwd, depth, env):
    """The `subprocess.run` calls among `processes` when every process call is one with a literal git argv that the guard
    classifies as a read, else None."""
    for call in processes:
        command = _git_run_command(call)
        if command is None or classify_text(command, cwd, depth + 1, env).kind != "read":
            return None
    return frozenset(processes)


def _read_only_python(tree, runs=frozenset()):
    """A conservative, exact test for Python code that cannot change anything: only listed standard modules, no process,
    network, environment, dynamic execution, or file mutation, and every `open` in a literal read mode. Anything that the
    test cannot decide is not read-only. `runs` holds the git read calls that may use `subprocess.run`."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
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
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _secret_text(node.value):
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

    def __init__(self, tree):
        self.tree = tree
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
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = self.texts(node.left, depth + 1), self.texts(node.right, depth + 1)
            if left is None or right is None or len(left) * len(right) > 64:
                return None
            if any(item.startswith(("/", "~")) for item in right):
                return None
            return [os.path.join(first, second) for first in left for second in right]
        return None

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
            return _temporary(path.resolve(), env)
        root = Path(cwd).resolve()
        return cwd_known and _temporary(root, env) and (root / path).resolve().is_relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return False


def _confine_writes(tree, cwd, cwd_known, env, protect=()):
    """Whether every `write_text`, `write_bytes`, and write-mode `open` of a script has a path that folds to a temporary
    location and never names a file of `protect`. A confined write is renamed to its read twin in `tree`
    so that the read-only test can then judge the rest."""
    if any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(tree)):
        return False
    resolver = _PathTexts(tree)
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
    if _temporary(path, env):
        return True
    root = approval_state.state_dir().parent.resolve()
    if not path.is_relative_to(root):
        return False
    return not any(path == item.resolve() or item.resolve() in path.parents for item in _guard_state_dirs())


def _exec_file_ok(path, transforms, cwd, cwd_known, env):
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
    return _confine_writes(tree, cwd, cwd_known, env, (resolved,)) and _read_only_python(tree)


def _exec_files_confined(tree, cwd, cwd_known, env):
    """Whether each `exec` of a script runs text read from a literal file under the plugin's work folders or a temporary
    root that is itself read-only Python, and each write of the script and of that text stays in temporary space. A script
    without `exec` of a read file is not judged here."""
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "exec"]
    if not calls:
        return True
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
            if not _exec_file_ok(path, transforms, cwd, cwd_known, env):
                return False
            protected.append(path.resolve())
    return _confine_writes(tree, cwd, cwd_known, env, tuple(protected))


def _python_policy(content, cwd, depth, env, readonly=False, cwd_known=True):
    if _code_runs_guard(content):
        return Outcome("forbidden", [], [SELF_APPROVAL_REASON])
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _unclassified("python", content) if PYTHON_EXEC.search(content) or SDK_IMPORT.search(content) else Outcome("pass", [], [])
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


_PENDING_SCRIPTS = {}
PENDING_KEEPERS = frozenset({
    "cd", "mkdir", "echo", "printf", "true", "false", "test", "[", "[[", ":", "ls", "pwd", "wc", "head", "tail", "sort",
    "cut", "tr", "du", "stat", "grep", "egrep", "fgrep", "sleep", "read", "for", "case", "done", "fi", "esac", "chmod",
    "exit", "cat",
})
LOOP_OPENERS = frozenset({"while", "until", "for", "select"})


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
                    or not _temporary(path.parent, env)):
                return False
            mode.value = "r"
            continue
        text = _fold_text(target, names) if target is not None else None
        if not text or "\0" in text:
            return False
        path = (Path(cwd) / os.path.expanduser(text)).resolve()
        if not (_temporary(path, env) or path.is_relative_to(session)):
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
    return path if named and _temporary(path.parent, env) else None


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


def _classify_script(words, cwd, depth, env, variables=None, choices=None):
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
            argv =[_script_path(arg, cwd, variables or {}) for arg in script_args]
            if pending is not None and not _confined_python_writes(pending, cwd, env, argv, resolved):
                return _script_unknown(resolved, words, env, "unreadable")
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


LISTERS = frozenset({"wc", "ls", "stat", "du"})


def _xargs_input_is_inert(argv, program, segment, segments, index, operators, statics):
    """Whether the input of an `xargs` reader is harmless: `wc`, `ls`, `stat`, and `du` take no option that runs a program
    or prints file content, and anything else needs the input to be free of option-like words."""
    stripped, _ = strip_prefix(argv)
    if os.path.basename(stripped[0]) in LISTERS:
        return True
    producer = None
    before = max((op for op in operators if op[3] <= segment.start), key=lambda op: op[3], default=None)
    if index > 0 and before is not None and before[1] == "|" and segments[index - 1].end <= before[2]:
        producer = _expand_segment_words(segments[index - 1], statics)
    return _xargs_input_has_no_options(argv, program[1:], segment, producer)


ONLY_MATCHING_FLAGS = re.compile(r"-[hoiE]+")
ONLY_MATCHING_LONG = frozenset({"--only-matching", "--no-filename", "--ignore-case", "--extended-regexp"})
BOUNDED_TOTAL_LIMIT = 512
CHARACTER_CLASS = re.compile(r"\[\^?[^\]\\\n\[]+\]")
NARROW_CLASS = re.compile(r"(?:[A-Za-z0-9_]|[a-z]-[a-z]|[A-Z]-[A-Z]|[0-9]-[0-9])+")


def _open_ended_class(text):
    """Whether a character class may repeat without a bound: it excludes the double quote, or it is a narrow positive
    class of letters, digits, and `_`."""
    inner = text[1:-1]
    if inner.startswith("^"):
        return '"' in inner[1:]
    return NARROW_CLASS.fullmatch(inner) is not None


def _anchored_pattern(pattern, extended):
    """Whether a grep pattern holds a literal run of at least six characters and no secret-name word, and every variable
    part is bounded: a lone `.` or a character class with an explicit count, or a class that may repeat without a bound
    only when it excludes the double quote or is a narrow positive class. The explicit counts add up to at most 512."""
    if len(pattern) > 300 or "\n" in pattern or SECRET_NAME.search(pattern):
        return False
    quantifier = re.compile(r"[*+?]|\{(\d+)(?:,(\d+))?\}" if extended else r"\*|\\\{(\d+)(?:,(\d+))?\\\}")
    longest = run = total = position = 0
    while position < len(pattern):
        class_match = CHARACTER_CLASS.match(pattern, position)
        if class_match or pattern[position] == ".":
            end = class_match.end() if class_match else position + 1
            counted = quantifier.match(pattern, end)
            if counted is None or counted[0] == "?":
                total += 1
            elif counted[1] is not None:
                total += int(counted[2] or counted[1])
            elif class_match is None or not _open_ended_class(class_match[0]):
                return False
            longest, run = max(longest, run), 0
            position = counted.end() if counted else end
        elif pattern.startswith("\\.", position):
            run, position = run + 1, position + 2
        elif re.fullmatch(r"[^.\[\]*\\^$+?{}()|]", pattern[position]):
            if quantifier.match(pattern, position + 1):
                return False
            run, position = run + 1, position + 1
        else:
            return False
    return max(longest, run) >= 6 and total <= BOUNDED_TOTAL_LIMIT


def _anchored_only_matching(argv):
    """Whether an `xargs grep` call prints only text that an anchored pattern matches: `-o`, a harmless option set, and
    one pattern before the appended input."""
    stripped, _ = strip_prefix(argv)
    if (not stripped or os.path.basename(stripped[0]) != "grep" or stripped[-1] != XARGS_ARGUMENT
            or sum(XARGS_ARGUMENT in word for word in stripped) != 1):
        return False
    patterns, flags = [], []
    for word in stripped[1:-1]:
        if ONLY_MATCHING_FLAGS.fullmatch(word) or word in ONLY_MATCHING_LONG:
            flags.append(word)
        elif word.startswith("-") or len(patterns) == 1:
            return False
        else:
            patterns.append(word)
    only = any(word == "--only-matching" or word.startswith("-") and not word.startswith("--") and "o" in word
               for word in flags)
    extended = any(word == "--extended-regexp" or not word.startswith("--") and "E" in word for word in flags)
    return only and len(patterns) == 1 and _anchored_pattern(patterns[0], extended)


VARIABLE_REWRITE = r"(?:\b(?:read|mapfile|readarray|getopts|let|printf|declare|typeset|eval)\b[^;&|\n]*|\bfor\s+){name}\b"


def _xargs_temp_list(program, segment, cwd, variables, text, environment):
    """Whether an `xargs` call takes its list from one `<` redirect of a file that lies inside a temporary root, with no
    other redirect and no `-a` option. A variable in the path counts only when it holds a value from an assignment and
    nothing before the call reads, loops over, or evaluates into it."""
    if _xargs_reads_file(program[1:]) or len(segment.redirects) != 1 or segment.redirects[0][1] != "<":
        return False
    target = segment.redirects[0][2]
    before = text[:segment.start]
    for match in VARIABLE_REFERENCE.finditer(target):
        name = match[1] or match[2]
        if name not in variables or re.search(VARIABLE_REWRITE.format(name=re.escape(name)), before) or ":=" in before:
            return False
    expanded = _expand_path_variables(target, variables)
    return "$" not in expanded and "`" not in expanded and _temp_path(expanded, cwd, environment)


def _xargs_list_read(argv, program, segment, cwd, variables, text, environment):
    """Whether `xargs grep` over a list file inside a temporary root prints only file names or counts (any pattern), or
    only text next to an anchored pattern. Never `rg`, and never with an `--` before the input."""
    stripped, _ = strip_prefix(argv)
    if (not stripped or os.path.basename(stripped[0]) != "grep" or "--" in stripped
            or not _xargs_temp_list(program, segment, cwd, variables, text, environment)):
        return False
    return _prints_no_content(argv) or _anchored_only_matching(argv)


def _classify_argv(words, heredoc, cwd, depth, command, inherited_env=None, variables=None, choices=None,
                   raw=None):
    slot = len(_COMMAND_TRACE) if _COMMAND_TRACE is not None else None
    verdict = _classify_words(words, heredoc, cwd, depth, command, inherited_env, variables, choices, raw)
    if slot is not None and slot < len(_COMMAND_TRACE) and _COMMAND_TRACE[slot] is None:
        stripped, _ = strip_prefix(words)
        _COMMAND_TRACE[slot] = _read_verdict(os.path.basename(stripped[0]), stripped[1:], verdict)
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
    if _COMMAND_TRACE is not None:
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
    script = _classify_script(stripped, cwd, depth, env, variables, choices)
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


def _merge(kind, verdicts, extra_writes=()):
    keys = sorted({key for verdict in verdicts for key in verdict.keys})
    writes = sorted({key for verdict in extra_writes for key in verdict.keys}
                    | {key for verdict in verdicts for key in verdict.writes})
    descriptions = list(dict.fromkeys(
        text for verdict in [*verdicts, *extra_writes] for text in verdict.descriptions
    ))
    every_time = any(verdict.every_time for verdict in [*verdicts, *extra_writes])
    critical = any(verdict.critical for verdict in [*verdicts, *extra_writes])
    return Outcome(kind, keys, descriptions, None, writes, every_time, critical)


def _redirects_allowed(segments):
    for segment in segments:
        for fd, operator, target in segment.redirects:
            if ">" not in operator:
                continue
            if (operator == ">&" and fd == "2" and target == "1") or target == "/dev/null":
                continue
            return False
    return True


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


def _blank(text, spans):
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            chars[index] = " "
    return "".join(chars)


def _expansion_regions(text, start, end):
    """Spans of the `$(...)` and backtick substitutions that the shell runs inside an unquoted heredoc body."""
    regions = []
    index = start
    while index < end:
        char = text[index]
        if char == "\\":
            index += 2
        elif char == "`" or text.startswith("$(", index):
            try:
                close = _substitution_end(text[:end], index)
            except ParseError:
                close = end
            regions.append((index, close))
            index = close
        else:
            index += 1
    return regions


def _heredoc_gaps(text, start, end, quoted):
    """The parts of a data heredoc body to blank: all of it when quoted, else all but the substitutions it runs."""
    if quoted:
        return [(start, end)]
    gaps, position = [], start
    for left, right in _expansion_regions(text, start, end):
        if left > position:
            gaps.append((position, left))
        position = right
    if position < end:
        gaps.append((position, end))
    return gaps


def _heredoc_data(text):
    if "<<" not in text:
        return text
    lines = text.splitlines(keepends=True)
    spans = []
    index, offset = 0, 0
    receivers = frozenset((
        "cat tee echo printf head tail wc sort uniq cut tr base64 xxd od grep egrep fgrep rg jq column fold fmt nl tac rev "
        "cmp diff git gh"
    ).split())
    while index < len(lines):
        line = lines[index]
        try:
            tokens = _lex(line)
        except ParseError:
            offset += len(line)
            index += 1
            continue
        groups = [[]]
        piped = set()
        for token in tokens:
            if token[0] == "op" and token[1] in SEPARATOR_OPERATORS:
                if token[1] in ("|", "|&"):
                    piped.add(len(groups) - 1)
                groups.append([])
            else:
                groups[-1].append(token)
        documents = []
        for group_index, group in enumerate(groups):
            words, redirects, outputs = [], [], []
            cursor = 0
            while cursor < len(group):
                kind, value, start, end = group[cursor]
                if kind == "op" and cursor + 1 < len(group):
                    target = group[cursor + 1][1]
                    if value == "<<":
                        strip_tabs = line[end:end + 1] == "-"
                        raw_delimiter = line[group[cursor + 1][2]:group[cursor + 1][3]]
                        quoted = any(char in raw_delimiter for char in "'\"\\")
                        redirects.append((target[1:] if strip_tabs else target, strip_tabs,
                                          quoted, (offset + start, offset + group[cursor + 1][3])))
                    elif value in (">", ">>", ">|", "&>"):
                        outputs.append(target)
                    cursor += 2
                else:
                    words.append(value)
                    cursor += 1
            program, _ = strip_prefix(words)
            receiver = os.path.basename(program[0]) if program else ""
            if receiver == "tee":
                outputs.extend(word for word in program[1:] if not word.startswith("-"))
            data = group_index not in piped and receiver in receivers
            documents.extend((delimiter, tabs, quoted, data, span, tuple(outputs)) for delimiter, tabs, quoted, span in redirects)
        offset += len(line)
        index += 1
        for delimiter, tabs, quoted, data, header_span, outputs in documents:
            start = offset
            while index < len(lines):
                body_line = lines[index]
                offset += len(body_line)
                index += 1
                candidate = body_line.rstrip("\r\n")
                if (candidate.lstrip("\t") if tabs else candidate) == delimiter:
                    break
            if data:
                for target in outputs:
                    if re.search(r"\b(?:bash|sh|zsh|source)\s+" + re.escape(target) + r"(?:\s|$)", text[offset:]):
                        data = False
                if not data:
                    continue
                spans.append(header_span)
                spans.extend(_heredoc_gaps(text, start, offset, quoted))
    return _blank(text, spans)


def _indirect_regions(text, segments):
    """Return sh -c scripts and eval and xargs bodies."""
    regions = []
    for segment in segments:
        if _helper_args(segment.words) is not None:
            continue
        words, _ = strip_prefix(segment.words)
        if not words:
            continue
        name = os.path.basename(words[0])
        if name in SHELLS:
            script = _shell_c(words[1:])
            if script:
                regions.append(script)
        elif name == "eval" or name == "xargs" and _xargs_argv(words[1:]) is None:
            regions.append(" ".join(words[1:]))
    return regions





def _cd_changes_directory(segment, operators):
    """Track only an unconditional `cd` in the current shell."""
    before = max((op for op in operators if op[3] <= segment.start), key=lambda op: op[3], default=None)
    after = min((op for op in operators if op[2] >= segment.end), key=lambda op: op[2], default=None)
    depth = sum({"(": 1, ")": -1}.get(op[1], 0) for op in operators if op[3] <= segment.start)
    return (depth == 0 and (before is None or before[1] == ";")
            and (after is None or after[1] in ("&&", ";")))


def _followed_by_and(segment, operators):
    """Whether the next operator after a segment is `&&`, so the command after it runs only when the segment succeeds."""
    after = min((op for op in operators if op[2] >= segment.end), key=lambda op: op[2], default=None)
    return after is not None and after[1] == "&&"


def _chained_by_and(segments, operators, first, last):
    """Whether segment `last` follows segment `first` through `&&` operators alone."""
    start, stop = segments[first].end, segments[last].start
    between = [op for op in operators if op[2] >= start and op[3] <= stop]
    return last > first and bool(between) and all(op[1] == "&&" for op in between)


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


CD_WORD = re.compile(r"(?<![\w.-])(?:cd|pushd|popd)(?![\w.-])")


def _heredoc_cwd(before, segments, segment, cwd):
    """The folder a heredoc script runs in and whether it is certain: the `cd <folder>` steps ahead of it on its own line
    count when the folder exists, and any earlier `cd`, `pushd`, or `popd` leaves the folder uncertain."""
    known = CD_WORD.search(before) is None
    for item in segments:
        if item.start >= segment.start:
            break
        words, _ = strip_prefix(item.words)
        if words[:1] == ["cd"]:
            directory = _script_path(words[1], cwd, {}) if len(words) == 2 and "-" != words[1][:1] else None
            if directory is None or not directory.is_dir():
                return cwd, False
            cwd = str(directory)
        elif words and words[0] in ("pushd", "popd"):
            return cwd, False
    return cwd, known


def _python_documents(text, cwd, depth, env):
    verdicts, spans = [], []
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
    return _blank(text, spans), verdicts


def _cut_names(words):
    """`cut -d= -f1` prints only the variable names of env output."""
    delimiter = fields = None
    args, index = words[1:], 0
    while index < len(args):
        arg = args[index]
        if arg in ("-d", "--delimiter", "-f", "--fields") and index + 1 < len(args):
            if arg in ("-d", "--delimiter"):
                delimiter = args[index + 1]
            else:
                fields = args[index + 1]
            index += 2
            continue
        if arg.startswith("--delimiter="):
            delimiter = arg.partition("=")[2]
        elif arg.startswith("--fields="):
            fields = arg.partition("=")[2]
        elif arg.startswith("-d") and not arg.startswith("--"):
            delimiter = arg[2:]
        elif arg.startswith("-f") and not arg.startswith("--"):
            fields = arg[2:]
        elif arg not in ("-s", "--only-delimited"):
            return False
        index += 1
    return delimiter == "=" and fields == "1"


def _awk_names(words):
    """`awk -F= '{print $1}'` prints only the variable names of env output."""
    args = words[1:]
    if not args or not args[0].startswith("-F"):
        return False
    separator, args = args[0][2:], args[1:]
    if not separator and args:
        separator, args = args[0], args[1:]
    return separator == "=" and len(args) == 1 and re.fullmatch(r"\{\s*print\s+\$1\s*\}", args[0]) is not None


def _sed_masks(words):
    """A sed substitution that replaces everything after the first `=` hides the variable values."""
    script, index, args = None, 1, words
    while index < len(args):
        arg = args[index]
        if arg in ("-E", "-r", "--regexp-extended"):
            index += 1
        elif arg == "-e" and script is None and index + 1 < len(args):
            script, index = args[index + 1], index + 2
        elif not arg.startswith("-") and script is None:
            script, index = arg, index + 1
        else:
            return False
    match = re.fullmatch(r"s([^\w\\\s])(.*?)\1(.*?)\1[gI]*", script or "")
    if match is None:
        return False
    regex, replacement = match[2], match[3]
    if regex in ("=.*", "=.+"):
        return re.search(r"[&\\]", replacement) is None
    if regex in ("^([^=]*)=.*", r"^\([^=]*\)=.*"):
        return re.fullmatch(r"(?:\\1|[^\\&])*", replacement) is not None
    return False


def _simple_sed(words):
    """A standard-input `sed` that applies one `s` substitution with only the `g` and `I` flags."""
    args = words[1:]
    if args[:1] in (["-E"], ["-r"], ["--regexp-extended"]):
        args = args[1:]
    return len(args) == 1 and re.fullmatch(r"s([^\w\\\s])(.*?)\1(.*?)\1[gI]*", args[0]) is not None


def _simple_tr(words):
    """A `tr` over its standard input: set operands only, with the `-c`, `-d`, and `-s` options."""
    operands = [arg for arg in words[1:] if not re.fullmatch(r"-[cds]+", arg)]
    return 1 <= len(operands) <= 2 and not any(len(arg) > 1 and arg.startswith("-") for arg in operands)


def _names_only_pattern(pattern):
    """An anchored pattern whose every element refuses `=` can match only inside the variable name."""
    rest = pattern[1:]
    if not pattern.startswith("^") or not re.fullmatch(r"(?:(?:\[\^?[^\]\\]+\]|[A-Za-z0-9_])[*+]?)+", rest):
        return False
    try:
        return not any(re.match(item, "=") for item in re.findall(r"\[\^?[^\]\\]+\]", rest))
    except re.error:
        return False


def _grep_parts(args, flag_pattern):
    """Return (flags, patterns) of a grep or rg call whose options all match flag_pattern, else None."""
    flags, patterns, index = [], [], 0
    while index < len(args):
        arg = args[index]
        if arg in ("-e", "--regexp") and index + 1 < len(args):
            patterns.append(args[index + 1])
            index += 2
            continue
        if arg.startswith("-"):
            if not re.fullmatch(flag_pattern, arg):
                return None
            flags.append(arg)
        else:
            patterns.append(arg)
        index += 1
    return flags, patterns


def _grep_names(words):
    """`grep -o '^[A-Z_]*'` prints only the variable names of env output."""
    if words[0] not in ("grep", "rg"):
        return False
    parts = _grep_parts(words[1:], r"--only-matching|--ignore-case|--extended-regexp|-[Eio]+")
    if parts is None or len(parts[1]) != 1:
        return False
    flags, (pattern,) = parts
    only = any(flag == "--only-matching" or not flag.startswith("--") and "o" in flag for flag in flags)
    return only and _names_only_pattern(pattern)


def _plain_grep(words):
    parts = _grep_parts(words[1:], r"--ignore-case|--fixed-strings|--invert-match|--extended-regexp|--count|-[EiFvc]+")
    return parts is not None and len(parts[1]) == 1


def _awk_filter(args):
    """A standard-input awk call that only prints fields, so it can end a read pipeline like `cut`."""
    rest, index = [], 0
    while index < len(args):
        if args[index] == "-F" and index + 1 < len(args):
            index += 2
        elif args[index].startswith("-F") and len(args[index]) > 2:
            index += 1
        else:
            rest.append(args[index])
            index += 1
    return len(rest) == 1 and AWK_PRINT.fullmatch(rest[0].strip()) is not None


CUT_RANGE = r"(?:\d+(?:-\d*)?|-\d+)(?:,(?:\d+(?:-\d*)?|-\d+))*"
INERT_VALUES = frozenset({"", "true", "false", "0", "1", "yes", "no", "on", "off", "never", "always", "auto"})


def _changes_environment(segment):
    """Whether a segment changes the shell's environment for the commands after it: a standalone assignment or an
    environment changer. A `NAME=value command` prefix lasts for that command only."""
    if not segment.words:
        return False
    program, _ = strip_prefix(segment.words)
    return (all(ASSIGNMENT.match(word) for word in segment.words)
            or any(os.path.basename(words[0]) in ENVIRONMENT_CHANGERS for words in (segment.words, program) if words))


def _cut_characters(words):
    """`cut -c1-60` only shortens each line, so it shows nothing that the filter before it did not."""
    args = words[1:]
    return words[0] == "cut" and (len(args) == 1 and re.fullmatch(r"-c" + CUT_RANGE, args[0]) is not None
                                  or len(args) == 2 and args[0] == "-c" and re.fullmatch(CUT_RANGE, args[1]) is not None)


def _inert_variable(name, value):
    """Whether a secret-named variable cannot hold a secret: an empty or on/off-like value, the count of Git config
    entries, or a Git config name that is one of the inert credential prompt keys with an empty or on/off-like paired
    value."""
    match = re.fullmatch(r"GIT_CONFIG_KEY_(\d+)", name)
    if match is not None:
        return (value.lower() in GIT_HARMLESS_CONFIG
                and os.environ.get("GIT_CONFIG_VALUE_" + match[1], "x").lower() in INERT_VALUES)
    if value.lower() in INERT_VALUES:
        return True
    return name == "GIT_CONFIG_COUNT" and value.isdigit()


def _name_only_stage(words):
    checks = {"cut": _cut_names, "awk": _awk_names, "sed": _sed_masks}
    return checks.get(words[0], _grep_names)(words)


def _environment_filter(text):
    try:
        segments = tokenize(text)
        operators = [token[1] for token in _lex(text) if token[0] == "op"]
    except ParseError:
        return None
    if not segments or any(op != "|" for op in operators) or any(segment.redirects for segment in segments):
        return None
    first = segments[0].words
    if not first or first[0] not in ("env", "printenv") or len(first) != 1:
        return None
    if len(segments) < 2:
        return None
    rest = [segment.words for segment in segments[1:]]
    if any("$" in word or "`" in word for words in rest if not (words and words[0] == "awk" and _awk_names(words))
           for word in words):
        return None
    if any(not words or words[0] not in ("grep", "rg", "head", "sort", "wc", "cut", "awk", "sed", "tr", "tail", "uniq")
           for words in rest):
        return None
    name_only = [_name_only_stage(words) for words in rest]
    first_names = next((position for position, named in enumerate(name_only) if named), len(rest))
    after_names = [position > first_names for position in range(len(rest))]

    def allowed(position, words, named):
        if words[0] in ("tr", "tail", "uniq") and not after_names[position]:
            return False
        if words[0] == "tr":
            return _simple_tr(words)
        if words[0] in ("cut", "awk", "sed"):
            return named or _cut_characters(words) or after_names[position] and words[0] == "sed" and _simple_sed(words)
        return True

    if not all(allowed(position, words, named) for position, (words, named) in enumerate(zip(rest, name_only))):
        return None
    numeric_options = {"-n", "--lines", "-c", "--bytes", "-k", "--key", "--parallel", "--batch-size", "-S", "--buffer-size"}
    for words in rest:
        if words[0] in ("head", "sort", "wc", "tail", "uniq"):
            for index, word in enumerate(words[1:], 1):
                if not word.startswith("-") and not (word.isdigit() and words[index - 1] in numeric_options):
                    return None
    if any(name_only):
        plain = all(named or words[0] not in ("grep", "rg") or _plain_grep(words)
                    for words, named in zip(rest, name_only))
        return _read() if plain else None
    if any(words[0] == "wc" and "-l" in words for words in rest):
        return _read()
    words = rest[0]
    if words[0] not in ("grep", "rg"):
        return None
    args = words[1:]
    if any(arg in ("-c", "--count") or re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", arg) for arg in args):
        return _read()
    flags, patterns = [], []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("-e", "--regexp") and index + 1 < len(args):
            patterns.append(args[index + 1])
            index += 2
        elif arg.startswith("-"):
            if arg not in ("--ignore-case", "--fixed-strings", "--invert-match", "--extended-regexp") and not re.fullmatch(r"-[EiFv]+", arg):
                return _sensitive(text)
            flags.append(arg)
            index += 1
        else:
            patterns.append(arg)
            index += 1
    if len(patterns) != 1:
        return _sensitive(text)
    pattern = patterns[0]
    if any("F" in flag or flag == "--fixed-strings" for flag in flags):
        pattern = re.escape(pattern)
    elif words[0] == "grep" and not any("E" in flag or flag == "--extended-regexp" for flag in flags):
        if "\\" in pattern:
            return _sensitive(text)
        pattern = re.sub(r"[()+?{}|]", lambda match: "\\" + match[0], pattern)
    if len(pattern) > 256 or re.search(r"\\[1-9]|\(\?|\)[+*{?]", pattern) or pattern.count("*") + pattern.count("+") > 1:
        return _sensitive(text)
    try:
        regex = re.compile(pattern, re.I if any("i" in flag or flag == "--ignore-case" for flag in flags) else 0)
    except re.error:
        return _sensitive(text)
    invert = any("v" in flag or flag == "--invert-match" for flag in flags)
    for name, value in os.environ.items():
        if (bool(regex.search(name + "=" + value)) != invert and SECRET_NAME.search(name)
                and not _inert_variable(name, value)):
            return _sensitive(text)
    return _read()


def _without_data(text):
    """Blank heredoc bodies and complete quoted strings, so that only words outside data can name a covered CLI."""
    text = _heredoc_data(text)
    return re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", lambda match: " " * len(match[0]), text)


def _expands(raw):
    """Whether the shell would expand `$` or a backtick in a raw word, outside single quotes and escapes."""
    index, quote = 0, None
    while index < len(raw):
        char = raw[index]
        if quote == "'":
            if char == "'":
                quote = None
        elif char == "\\":
            index += 1
        elif char in "$`":
            return True
        elif quote == '"':
            if char == '"':
                quote = None
        elif char in "'\"":
            quote = char
        index += 1
    return False


def unwrap_wrapper(command):
    """Return the script that a call of this plugin's approve_wrapper.sh with one plain argument runs, else None."""
    if not isinstance(command, str) or WRAPPER not in command:
        return None
    try:
        tokens = _lex(command)
    except ParseError:
        return None
    if len(tokens) != 2 or any(token[0] != "word" for token in tokens) or tokens[0][1] != WRAPPER:
        return None
    _, script, start, end = tokens[1]
    return None if _expands(command[start:end]) else script


def wrap_command(command):
    return f"{shlex.quote(WRAPPER)} {shlex.quote(command)}"


def _shell_wrapper_script(text):
    """The script of `sh|bash|zsh <wrapper> <one plain word>`, alone or behind the usual wrappers; None for any other
    command that names the wrapper."""
    try:
        tokens = _lex(text)
    except ParseError:
        return None
    if len(tokens) < 3 or any(token[0] != "word" for token in tokens):
        return None
    stripped, assignments = strip_prefix([token[1] for token in tokens])
    if (assignments or len(stripped) != 3 or os.path.basename(stripped[0]) not in SHELLS
            or stripped[1] != WRAPPER):
        return None
    _, script, start, end = tokens[-1]
    return None if _expands(text[start:end]) else script


def _wrapper_outcome(text, cwd, depth, env, variables):
    """Classify a command that names the wrapper: a shell call with one plain word by that word's text, anything else
    asks every time. None when the command does not name the wrapper."""
    if WRAPPER not in text:
        return None
    script = _shell_wrapper_script(text)
    if script is not None:
        return classify_text(script, cwd, depth + 1, env, variables)
    return _unrecognized_wrapper(text)


def _unrecognized_wrapper(text):
    return Outcome("always", ["wrapper:unrecognized:" + _digest(text)], ["Unrecognized approval wrapper call"],
                   every_time=True, critical=True)


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
    if depth == 0 or "_APPROVAL_SESSION_DIR" not in environment:
        environment["_APPROVAL_SESSION_DIR"] = environment.get("CLAUDE_PROJECT_DIR") or cwd
    filtered = _environment_filter(text)
    if filtered is not None:
        return filtered
    heredoc_scripts, script_bodies = _heredoc_scripts(text)
    text = _heredoc_data(text)
    text, python_verdicts = _python_documents(text, cwd, depth, environment)
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
    if boundaries and not changes_environment:
        for end, following in [*boundaries, (len(text), len(text))]:
            filtered = _environment_filter(text[start:end].strip())
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
    substitution_names = set()
    current_env = environment
    flow = _ValueFlow(choices)
    made_directories = set()
    pending_cd = None
    for index, segment in enumerate(segments):
        flow.visit(segments, index, operators, current_env)
        command_cwd = pending_cd[0] if pending_cd and _chained_by_and(segments, operators, pending_cd[1], index) else cwd
        if segment.start in filtered_segments:
            filtered = filtered_segments[segment.start]
            if filtered is not None:
                verdicts.append(filtered)
            files_stable = files_stable and filtered is not None and filtered.kind == "read"
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
        if _COMMAND_TRACE is not None:
            _trace_command(_redirects_write_only_inside_temporary_root(
                segment.redirects, command_cwd, {**current_env, **variables}, flow.choices()))
        region = checked[segment.start:segment.end]
        substitutions = list(_substitution_spans(region))
        scoped_env = current_env if files_stable else {**current_env, FILES_MAY_CHANGE: "1"}
        for _, _, body in substitutions:
            verdicts.append(classify_text(body, cwd, depth + 1, scoped_env, variables, statics, flow.choices()))
            files_stable = files_stable and verdicts[-1].kind == "read"
        scoped_env = current_env if files_stable else {**current_env, FILES_MAY_CHANGE: "1"}
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
                elif directory is not None and _COMMAND_TRACE is not None and _followed_by_and(segment, operators):
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
                                       scoped_env,
                                       variables, flow.choices(), None if argv else segment.raw))
        if argv and (verdict.kind == "read" or verdict.kind == "pass" and os.path.basename(
                (strip_prefix(argv)[0] or [""])[0]) in OPERAND_READERS) and not (
                _prints_no_content(argv) and _xargs_input_is_inert(argv, program, segment, segments, index, operators,
                                                                    statics)) and not _xargs_list_read(
                argv, program, segment, command_cwd, variables, text, current_env):
            verdict = _sensitive(text)
        inert = verdict.kind == "pass" and (not name or name in FILE_INERT) and flow.outside_loop_header()
        files_stable = files_stable and (verdict.kind == "read" or inert) and _redirects_allowed([segment])
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


def mcp_tool_part(tool):
    first = tool.find("__")
    if first < 0:
        return None
    second = tool.find("__", first + 2)
    if second < 0:
        return None
    return tool[second + 2:]


def tool_words(part):
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", part)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", spaced)
    return [word for word in re.split(r"[_\-\s]+", spaced.lower()) if word]


SQL_FIELDS = ("sql", "statement", "queryText")
SQL_LEAD = re.compile(
    r"^\s*(?:--[^\n]*\n\s*|/\*.*?\*/\s*)*\(?\s*(?:select|with|insert|update|delete|merge|upsert|replace|create|alter|"
    r"drop|truncate|explain|show|values|table|call|exec|execute|do|grant|revoke|set|begin|commit|rollback|copy|"
    r"vacuum|analyze|declare|lock)\b",
    re.IGNORECASE | re.DOTALL,
)


def _is_sql_field(key, text):
    """Explicit SQL fields always carry SQL; a generic `query` field does only when its text starts like SQL."""
    return key in SQL_FIELDS or (key == "query" and SQL_LEAD.match(text) is not None)


def _input_strings(value, sql_only=False):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and (not sql_only or _is_sql_field(key, item)):
                yield item
            elif isinstance(item, (dict, list)):
                yield from _input_strings(item, sql_only)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and not sql_only:
                yield item
            else:
                yield from _input_strings(item, sql_only)


def tabularis_connection(identifier):
    override = os.environ.get("HEI5ENBUG_TABULARIS_DIR")
    if override:
        directory = Path(override).expanduser()
    elif sys.platform == "darwin":
        directory = Path.home() / "Library" / "Application Support" / "tabularis"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        directory = Path(appdata) / "tabularis"
    else:
        directory = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "tabularis"
    try:
        entries = json.loads((directory / "connections.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(entries, dict):
        entries = entries.get("connections")
    if not isinstance(identifier, str) or not isinstance(entries, list):
        return None
    connections = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        connection_id, name, params = entry.get("id"), entry.get("name"), entry.get("params")
        driver = params.get("driver") if isinstance(params, dict) else None
        if isinstance(connection_id, str) and connection_id and isinstance(name, str):
            connections.append((connection_id, name, driver if isinstance(driver, str) else None))
    matches = [connection for connection in connections if connection[0] == identifier]
    if not matches:
        matches = [connection for connection in connections if connection[1] == identifier]
    return matches[0] if len(matches) == 1 else None


def classify_tabularis(tool_input, host=None, session=None):
    arguments = tool_input if isinstance(tool_input, dict) else {}
    identifier, sql = arguments.get("connection_id"), arguments.get("query")
    connection = tabularis_connection(identifier)
    connection_id = connection[0] if connection else identifier if isinstance(identifier, str) else "unknown"
    name = connection[1] if connection else "an unidentified connection"
    text = sql if isinstance(sql, str) else ""
    always = Outcome("always", [f"sql:always:tabularis:{connection_id}:{_digest(text)}"],
                     [f"tabularis query on {name}"], every_time=True,
                     critical=db_read_policy.is_production(name if connection else None))
    write = Outcome("write", ["mcp:session"], [f"tabularis query on {name}"])
    datagrip = _datagrip()
    driver = connection[2] if connection else None
    postgres = {"postgresql": True, "sqlserver": False, "sqlserver-entra": False}.get(driver)
    if datagrip.asks_every_time(text, postgres, name if connection else None):
        return always
    if not connection or postgres is None or not isinstance(sql, str):
        return always._replace(critical=True) if approval_state.session_scope() else write
    if datagrip.is_read(sql, postgres):
        return db_read_policy.read_outcome(host or detect_host(), session, "tabularis", connection_id, name, postgres,
                                           sql, datagrip.read_shape(sql) if postgres else None)
    keywords, destructive = datagrip.query_facts(sql, postgres, name)
    if destructive:
        return always
    if not keywords and approval_state.session_scope():
        return always._replace(critical=True)
    return Outcome("write", ["mcp:session"], [f"tabularis write on {name}"])


UNSPLIT_READ_PREFIXES = ("get", "list", "search", "fetch", "read", "describe", "show", "find", "lookup", "count", "check")


def _unsplit_read(words):
    """A tool name written as one lowercase run, like getjiraissue, reads when a read verb leads and no write word follows."""
    if len(words) != 1:
        return False
    for prefix in UNSPLIT_READ_PREFIXES:
        if words[0].startswith(prefix) and len(words[0]) > len(prefix):
            rest = words[0][len(prefix):]
            return not any(word in rest for word in MCP_WRITE_WORDS | MCP_DESTRUCTIVE_WORDS)
    return False


def _code_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("language", "lang"):
                continue
            yield from _code_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _code_strings(item)
    elif isinstance(value, str):
        yield value


def _looks_python(code):
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    return any(not (isinstance(node, ast.Expr) and isinstance(node.value, (ast.Name, ast.Constant)))
               for node in tree.body)


def _classify_executable(tool, tool_input, cwd):
    """Classify the code an executable MCP tool runs with the shell and Python classifiers.

    A forbidden or secret result and an every-time result are kept, and a sensitive result adds its sensitive-read
    approval to the session write; any other code is a session write. Returns None when the input holds no code.
    """
    language = None
    if isinstance(tool_input, dict):
        language = next((tool_input[key].lower() for key in ("language", "lang")
                         if isinstance(tool_input.get(key), str)), None)
    verdicts = []
    for code in _code_strings(tool_input):
        python = _looks_python(code) if language is None else language in ("py", "py3") or "python" in language
        verdicts.append(_python_policy(code, cwd, 0, dict(os.environ)) if python else classify_text(code, cwd))
    if not verdicts:
        return None
    for kind in ("forbidden", "secret"):
        found = next((verdict for verdict in verdicts if verdict.kind == kind), None)
        if found is not None:
            return found
    every_time = [verdict for verdict in verdicts if verdict.every_time]
    if every_time:
        return _merge("always", [verdict._replace(keys=[key for key in verdict.keys if key not in approval_state.SESSION_KEYS])
                                 for verdict in every_time])
    if any(verdict.kind == "sensitive" for verdict in verdicts):
        return Outcome("sensitive", [approval_state.SENSITIVE_KEY], [f"MCP execution tool {tool}"], None,
                       ["mcp:session"])
    return Outcome("write", ["mcp:session"], [f"MCP execution tool {tool}"])


def classify_mcp(tool, tool_input=None, cwd=None, host=None, session=None):
    if tool == TABULARIS_TOOL:
        return classify_tabularis(tool_input, host, session)
    part = mcp_tool_part(tool)
    words = tool_words(part) if part else []
    sql = list(_input_strings(tool_input, sql_only=True))
    datagrip = _datagrip() if sql else None
    if any(datagrip.is_destructive(text) for text in sql):
        return Outcome("always", [f"mcp:{tool}:{_digest(json.dumps(sql))}"], [f"destructive SQL in MCP tool {tool}"],
                       every_time=True, critical=True)
    if any(word in MCP_DESTRUCTIVE_WORDS for word in words):
        return Outcome("always", [f"mcp:{tool}"], [f"destructive MCP tool {tool}"], every_time=True)
    action = tool_input.get("action") if isinstance(tool_input, dict) else None
    action_words = tool_words(action) if isinstance(action, str) else []
    if set(action_words) & MCP_DESTRUCTIVE_WORDS:
        return Outcome("always", [f"mcp:{tool}"], [f"destructive MCP action via {tool}"], every_time=True)
    if sql:
        if all(datagrip.is_read(text, True) or datagrip.is_read(text, False) for text in sql):
            return _read()
        return Outcome("write", ["mcp:session"], [f"MCP SQL write via {tool}"])
    if set(words) & EXEC_WORDS:
        verdict = _classify_executable(tool, tool_input, cwd or os.getcwd())
        if verdict is not None:
            return verdict
    if set(action_words) & (MCP_WRITE_WORDS | EXEC_WORDS):
        return Outcome("write", ["mcp:session"], [f"MCP write action via {tool}"])
    if set(action_words) & MCP_READ_VERBS:
        return _read()
    if set(words) & EXEC_WORDS:
        return Outcome("write", ["mcp:session"], [f"MCP execution tool {tool}"])
    if not words:
        return Outcome("write", [f"mcp:{tool}"], [f"MCP tool {tool}"])
    if _unsplit_read(words[-1:]) and not any(word in MCP_WRITE_WORDS for word in words[:-1]):
        return _read()
    if words[0] in MCP_READ_VERBS:
        return _read()
    if not any(word in MCP_WRITE_WORDS for word in words) and any(word in MCP_READ_VERBS for word in words):
        return _read()
    return Outcome("write", ["mcp:session"], [f"MCP write: {tool}"])


def _cwd(event):
    cwd = event.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()


def _deny_secret():
    root = Path(__file__).resolve().parents[1]
    return approval_state.pre_output("deny", SECRET_REASON.format(root=root))


def _enforced_read(outcome, tool_input):
    """The tabularis input of a production read with its result limit and SQL Server safeguards, or None."""
    if outcome.exe not in (db_read_policy.ENFORCE_POSTGRES, db_read_policy.ENFORCE_SQLSERVER) \
            or not isinstance(tool_input, dict) or not isinstance(tool_input.get("query"), str):
        return None
    connection = tabularis_connection(tool_input.get("connection_id")) or (None, None)
    return db_read_policy.enforce("tabularis", tool_input, outcome.exe, connection[:2],
                                  _datagrip().session_settings(tool_input["query"]))


def _read_decision(host, outcome, tool_input):
    """A psql read runs with the server enforcing read-only mode; when that cannot be applied, it runs as before."""
    enforced = _enforced_read(outcome, tool_input)
    if enforced is not None:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": READ_REASON,
            "updatedInput": enforced,
        }}
    if outcome.exe == "psql" and isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        updated = {**tool_input, "command": read_only_command(tool_input["command"])}
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": READ_REASON,
            "updatedInput": updated,
        }}
    if host == "codex":
        return None
    return approval_state.pre_output("allow", READ_REASON)


def _claude_settings_files(project):
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    return [Path(project) / ".claude" / "settings.local.json", Path(project) / ".claude" / "settings.json",
            (Path(config) if config else Path.home() / ".claude") / "settings.json"]


def _edit_roots(project):
    roots = [Path(project).resolve()]
    for path in _claude_settings_files(project):
        try:
            values = json.loads(path.read_text(encoding="utf-8"))["permissions"]["additionalDirectories"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(values, list):
            roots.extend((Path(project) / os.path.expanduser(value)).resolve()
                         for value in values if isinstance(value, str) and value)
    return roots


def _editable_path(path, cwd, roots):
    """A path inside a root, outside the guard state and the host's protected paths, so the host would only prompt."""
    if "$" in path:
        return False
    candidate = (Path(cwd) / os.path.expanduser(path)).resolve()
    if (_state_path(path, cwd) or _protected_path(path, cwd) or candidate.name in CLAUDE_PROTECTED_FILES
            or CLAUDE_PROTECTED_DIRS & set(candidate.parts)):
        return False
    return any(candidate.is_relative_to(root) for root in roots)


def _session_covered(session, host="claude"):
    """Whether the session-wide key of the `session` approval scope is held."""
    return approval_state.scope_held(host, session)


def _edit_permission(session, tool_input, tool_name, cwd):
    paths = [tool_input.get(key) for key in ("file_path", "notebook_path")] if isinstance(tool_input, dict) else []
    paths = [path for path in paths if path is not None]
    if not paths or not all(isinstance(path, str) and path for path in paths):
        return None
    roots = _edit_roots(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
    if not all(_editable_path(path, cwd, roots) for path in paths):
        return None
    if _session_covered(session) or approval_state.is_approved("claude", session, [approval_state.WRITE_KEY]):
        return approval_state.permission_allow()
    if not approval_state.parent_session():
        digest = approval_state.permission_digest(tool_name, tool_input)
        grants = [approval_state.WRITE_KEY, *([approval_state.ALL_KEY] if approval_state.session_scope() else [])]
        if not approval_state.request_ask("claude", session, [], [approval_state.WRITE_KEY], "pr:" + digest, grants):
            return approval_state.permission_deny(approval_state.stop_reason("claude"))
    return None


def _plugin_file(tool_input, cwd):
    """A Read of this plugin's own files, such as its instruction references, which the host asks about only because
    they sit outside the working directories."""
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(path, str) or not path or "$" in path:
        return False
    root = Path(__file__).resolve().parents[1]
    return (Path(cwd) / os.path.expanduser(path)).resolve().is_relative_to(root)


def _plain_command(command):
    return not (_destructive_text(command) or REMOTE_PROGRAM.search(command) or DESTRUCTIVE_COMMAND.search(command))


RM_WORD = re.compile(r"(?<![\w./-])rm(?![\w-])")


def _removes_only_inside_temporary_root(command, cwd):
    """Whether a command that the guard passes holds recursive removals and every `rm` in it removes only static paths
    strictly inside a temporary root. Claude Code's own check of dangerous removals asks even when the guard passes, and
    only a PermissionRequest answer can settle it. The command is classified again with a trace of each `rm` call; a
    call the trace missed, an unresolved target, or a non-recursive removal means no. Every other command in it must be
    inert, a local read the guard itself classifies, or a write confined to a temporary root."""
    global _REMOVAL_TRACE, _COMMAND_TRACE
    mentions = len(RM_WORD.findall(command))
    if not mentions or FUNCTION_DEFINITION.search(command):
        return False
    trace = _REMOVAL_TRACE = []
    commands = _COMMAND_TRACE = []
    try:
        outcome = _classify_safely(lambda: classify_text(command, cwd), command)
    finally:
        _REMOVAL_TRACE = _COMMAND_TRACE = None
    return (outcome.kind == "pass" and len(trace) >= mentions and all(trace)
            and all(entry is True for entry in commands))


MEMORY_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})


def _memory_project_folder(event):
    """The folder of this session's project under Claude's projects folder: the transcript path's nearest ancestor whose
    parent is named `projects`, else, only when the event has no transcript path, the folder that the sanitized
    CLAUDE_PROJECT_DIR names under `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`."""
    transcript = event.get("transcript_path") if isinstance(event, dict) else None
    if transcript is not None:
        if not isinstance(transcript, str) or not transcript:
            return None
        return next((parent for parent in Path(transcript).parents if parent.parent.name == "projects"), None)
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project:
        return None
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(configured) if configured else Path.home() / ".claude"
    return root / "projects" / re.sub(r"[^A-Za-z0-9]", "-", project)


def _auto_memory_file(tool_input, event, cwd):
    """Whether a Write, Edit, or MultiEdit targets a Markdown file inside this session's own auto-memory folder, after
    both the file and the folder resolve through links, and the folder stays inside the project folder."""
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(path, str) or not path or "\0" in path or not path.endswith(".md") or path.endswith("/.md"):
        return False
    project = _memory_project_folder(event)
    if project is None:
        return False
    try:
        folder = (project / "memory").resolve()
        target = (Path(cwd) / os.path.expanduser(path)).resolve()
        return folder.is_relative_to(project.resolve()) and target != folder and target.is_relative_to(folder)
    except (OSError, RuntimeError, ValueError):
        return False


def _claude_permission(session, outcome, tool_input, tool_name, cwd, event=None):
    """Claude's PermissionRequest answers `allow` only for what the session's write approval already covers."""
    if outcome.kind in ("pass", "write") and tool_name in MEMORY_TOOLS and _auto_memory_file(tool_input, event, cwd):
        return approval_state.permission_allow()
    if outcome.kind == "pass":
        if tool_name in EDIT_TOOLS:
            return _edit_permission(session, tool_input, tool_name, cwd)
        if tool_name == "Read" and _plugin_file(tool_input, cwd):
            return approval_state.permission_allow()
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if tool_name == "Bash" and outcome.exe == TEMP_WRITE_EXE:
            return approval_state.permission_allow()
        if tool_name == "Bash" and isinstance(command, str) and _plain_command(command) and (
                _session_covered(session) or approval_state.is_approved("claude", session, [approval_state.WRITE_KEY])):
            return approval_state.permission_allow()
        if tool_name == "Bash" and isinstance(command, str) and _removes_only_inside_temporary_root(command, cwd):
            return approval_state.permission_allow()
        return None
    if approval_state.all_granted("claude", session, outcome):
        return approval_state.permission_allow()
    once_keys, session_keys = approval_state.split_outcome(outcome)
    if outcome.kind == "read" or outcome.every_time or once_keys or not session_keys:
        return None
    return approval_state.permission_allow() if approval_state.is_approved("claude", session, session_keys) else None


@functools.lru_cache(maxsize=None)
def _codex_config(path, mtime, size):
    try:
        import tomllib
    except ImportError:
        return None
    try:
        with open(path, "rb") as stream:
            config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError, UnicodeError):
        return None
    return config if isinstance(config, dict) else None


def _tool_label(value):
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)


def _mcp_prompt_mode(home, tool):
    """Whether the tool's effective approval mode in Codex's config.toml is prompt, so the native window asks."""
    first = tool.find("__")
    second = tool.find("__", first + 2) if first >= 0 else -1
    if second < 0:
        return False
    server_label, tool_label = tool[first + 2:second], tool[second + 2:]
    path = home / "config.toml"
    try:
        stat = path.stat()
    except OSError:
        return False
    servers = (_codex_config(str(path), stat.st_mtime_ns, stat.st_size) or {}).get("mcp_servers")
    if not isinstance(servers, dict):
        return False
    for name, server in servers.items():
        if not isinstance(server, dict) or _tool_label(name) != server_label:
            continue
        tools = server.get("tools")
        settings = [setting for key, setting in (tools.items() if isinstance(tools, dict) else [])
                    if _tool_label(key) == tool_label and isinstance(setting, dict) and "approval_mode" in setting]
        mode = settings[0]["approval_mode"] if settings else server.get("default_tools_approval_mode")
        return mode == "prompt"
    return False


def native_ready(event):
    """Whether Codex's own approval window can ask for this call: native approval is on, the session is interactive
    and not a child, the plugin-owned rules file is current, and an MCP tool's approval mode is prompt."""
    if not isinstance(event, dict) or event.get("permission_mode") != "default":
        return False
    if os.environ.get("HEI5ENBUG_PARENT_SESSION"):
        return False
    try:
        import host_settings
        if not host_settings.CODEX_NATIVE_APPROVAL:
            return False
        home = host_settings.resolve_codex_home()
        current = (home / "rules" / host_settings.RULES_NAME).read_text(encoding="utf-8")
        if current != host_settings.rules_text(host_settings.ROOT):
            return False
        tool = event.get("tool_name")
        return _mcp_prompt_mode(home, tool) if isinstance(tool, str) and tool.startswith("mcp__") else True
    except (OSError, UnicodeError, ImportError, ValueError):
        return False


def _native_tool(tool_name):
    return isinstance(tool_name, str) and (tool_name == "Bash" or tool_name.startswith("mcp__"))


def _native_covers(tool_name, outcome):
    """Whether the native window may stand in for the code flow: a Bash call always, an MCP or DataGrip call only when
    it asks once per session, because the window's mode comes from a file that a CLI override can change."""
    if not _native_tool(tool_name):
        return False
    return tool_name == "Bash" or not approval_state.split_outcome(outcome)[0]


def _native_pre(session, outcome, tool_input, wrapped):
    """Codex PreToolUse while the native window can ask: a Bash call that needs approval runs through the wrapper,
    whose prefix rule shows the window. MCP calls and wrapper calls need no change, and no code is issued."""
    once_keys, session_keys = approval_state.split_outcome(outcome)
    if wrapped or not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        return None
    if approval_state.all_granted("codex", session, outcome) or (
            not once_keys and approval_state.is_approved("codex", session, session_keys)):
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "Approval needed: " + approval_state.describe(outcome),
        "updatedInput": {**tool_input, "command": wrap_command(tool_input["command"])},
    }}


def codex_permission(session, outcome, tool_use_id, tool_input, tool_name, event):
    """Codex PermissionRequest: allow what is already approved; otherwise let the native window ask and remember
    which session keys that window grants once the call completes."""
    if outcome.kind == "read" or approval_state.permission_allowed("codex", session, outcome, tool_use_id):
        return approval_state.permission_allow()
    once_keys, session_keys = approval_state.split_outcome(outcome)
    if (outcome.kind not in ("write", "always", "sensitive", "request") or not (once_keys or session_keys)
            or not _native_covers(tool_name, outcome) or approval_state.session_key(session) is None
            or not native_ready(event)):
        return None
    request_id = "pr:" + approval_state.permission_digest(tool_name, tool_input)
    grants = approval_state.scope_keys(outcome, session_keys)
    if not approval_state.request_ask("codex", session, once_keys, session_keys, request_id, grants):
        return approval_state.permission_deny(approval_state.stop_reason("codex"))
    return None


def _decide(name, host, session, outcome, tool_use_id=None, tool_input=None, tool_name=None, cwd=None, event=None,
            wrapped=False):
    if name in POST_EVENTS:
        approval_state.after_call(host, session, outcome, tool_use_id, tool_name, tool_input)
        return None
    if outcome.kind == "forbidden":
        return approval_state.pre_output("deny", "; ".join(outcome.descriptions)) if name == "PreToolUse" else None
    if outcome.kind == "secret":
        return _deny_secret() if name == "PreToolUse" else None
    if name == "PreToolUse":
        if outcome.kind == "read":
            return _read_decision(host, outcome, tool_input)
        if outcome.kind in ("write", "always", "sensitive", "request"):
            if host == "codex" and _native_covers(tool_name, outcome) \
                    and approval_state.session_key(session) is not None and native_ready(event):
                return _native_pre(session, outcome, tool_input, wrapped) if tool_name == "Bash" else None
            return approval_state.pre_decision(host, session, outcome, tool_use_id)
        return None
    if name == "PermissionRequest":
        if host == "claude":
            return _claude_permission(session, outcome, tool_input, tool_name, cwd, event)
        return codex_permission(session, outcome, tool_use_id, tool_input, tool_name, event)
    return None


def handle(event, host):
    if not isinstance(event, dict):
        return None
    name = event.get("hook_event_name")
    session = event.get("session_id")
    approval_state.heartbeat(host, session, name)
    tool = event.get("tool_name")
    tool_use_id = event.get("tool_use_id")
    if name == "UserPromptSubmit":
        approval_state.reset_request_counts(host, session)
        output = approval_state.approve_prompt(host, session, event.get("prompt"))
        warning = approval_state.hooks_warning(host, session)
        if warning:
            if output is None:
                return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": warning}}
            context = output["hookSpecificOutput"]["additionalContext"]
            output["hookSpecificOutput"]["additionalContext"] = warning + "\n" + context
        return output
    if name not in EVENTS or not isinstance(tool, str):
        return None
    if name == "PostToolUse" and tool in (DATAGRIP_TOOL, TABULARIS_TOOL):
        _capture_plan(host, session, tool, event)
    if tool == DATAGRIP_TOOL:
        if name in POST_EVENTS:
            outcome = _classify_safely(lambda: _datagrip().classify_query(event.get("tool_input")), tool)
            approval_state.after_call(host, session, outcome, tool_use_id, tool, event.get("tool_input"))
        elif name == "PreToolUse" and host == "claude" and enabled("datagrip_guard"):
            outcome = _classify_safely(lambda: _datagrip().classify_query(event.get("tool_input")), tool)
            _record_risk(host, session, tool_use_id, tool, outcome)
            if outcome.kind == "always":
                return approval_state.pre_decision(host, session, outcome, tool_use_id)
        return None
    tool_input = event.get("tool_input")
    wrapped = None
    if tool == "Bash":
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            return None
        wrapped = unwrap_wrapper(command)
        if wrapped is not None:
            command = wrapped
        outcome = _request_outcome(command, _cwd(event))
        reason = _self_approval_reason(command) if name == "PreToolUse" and outcome is None else None
        if reason:
            return approval_state.pre_output("deny", reason)
        outcome = outcome or _classify_safely(lambda: classify_text(command, _cwd(event)), command)
        limits = _limits_command_outcome(command, _cwd(event))
        if limits is not None and outcome.kind not in ("forbidden", "secret"):
            outcome = _merge("always", [outcome, limits]) if outcome.kind == "always" else limits
    elif tool.startswith("mcp__"):
        outcome = _classify_safely(lambda: classify_mcp(tool, tool_input, _cwd(event), host, session), tool)
    elif tool in FILE_TOOLS:
        outcome = _classify_safely(lambda: classify_file_tool(tool, tool_input, _cwd(event)), tool)
    else:
        return None
    if name == "PreToolUse":
        _record_risk(host, session, tool_use_id, tool, outcome)
    return _decide(name, host, session, outcome, tool_use_id, tool_input, tool, _cwd(event), event,
                   wrapped is not None)


def _record_risk(host, session, tool_use_id, tool, outcome):
    """Record the call's kind for the Claude Code mod's transcript marker; a file edit is the session write it asks for.
    A failure here never changes the decision."""
    try:
        if host != "claude":
            return
        if isinstance(tool, str) and tool in EDIT_TOOLS and outcome.kind == "pass":
            outcome = outcome._replace(kind="write")
        approval_state.record_risk(host, session, tool_use_id, outcome)
    except Exception:
        return


LIMITS_READS = frozenset({"ls", "cat", "head", "tail", "grep", "wc", "stat", "file", "jq"})


LIMITS_WRITERS = frozenset({"tee", "mv", "cp", "install", "ln", "truncate", "rm", "rmdir", "unlink", "shred"})
LIMITS_REMOVERS = frozenset({"rm", "rmdir", "mv", "unlink", "shred"})
QUOTE_MARKS = re.compile(r"[\"'\\]")
DYNAMIC_MARKS = ("$", "`", "<(", ">(")


def _limits_write_form(segment, words):
    """Whether a simple command writes: an output redirection, or a writing program."""
    program, _ = strip_prefix(words)
    name = os.path.basename(program[0]) if program else ""
    return (any(">" in operator and target != "/dev/null" for _, operator, target in segment.redirects)
            or name in LIMITS_WRITERS or name == "dd" and any(word.startswith("of=") for word in program[1:])
            or name == "sed" and any(re.fullmatch(r"-[A-Za-z]*i[A-Za-z]*|--in-place(?:=.*)?", word)
                                     for word in program[1:]))


def _limits_command_outcome(command, cwd=None):
    """An every-time outcome for a command that touches the database read limits file or its folder, unless it only
    reads. Words and redirection targets are compared after quote and escape removal, simple joins through fixed
    variables are followed, and a write whose path cannot be resolved counts when the folder is the working folder."""
    path = db_read_policy.limits_path()
    folder = path.parent
    ask = Outcome("always", [f"db-limits:{_digest(command)}"], ["Change to the database read limits file"],
                  every_time=True)

    def mentions(text):
        text = QUOTE_MARKS.sub("", text)
        expanded = os.path.expandvars(text).replace("~/", f"{Path.home()}/")
        return any(name in value for value in (text, expanded) for name in (path.name, str(folder)))

    try:
        segments = tokenize(command)
    except ParseError:
        return ask if mentions(command) else None
    home = folder.resolve()

    def within(candidate):
        return candidate == home or home in candidate.parents

    statics, directory = {}, Path(cwd or os.getcwd()).resolve()
    named = dynamic = writes = False
    inside = within(directory)
    for segment in segments:
        words = _expand_segment_words(segment, statics)
        if all(ASSIGNMENT.match(word) for word in words):
            for word in words:
                key, _, value = word.partition("=")
                fixed = _static_value(os.path.expandvars(value), statics, os.environ)
                if fixed is None:
                    statics.pop(key, None)
                else:
                    statics[key] = fixed
            continue
        targets = [_expand_path_variables(target, statics) for _, operator, target in segment.redirects
                   if "<<" not in operator]
        program, _ = strip_prefix(words)
        name = os.path.basename(program[0]) if program else ""
        for text in (*words, *targets):
            plain = QUOTE_MARKS.sub("", os.path.expandvars(text))
            dynamic = dynamic or any(mark in plain for mark in DYNAMIC_MARKS)
            named = named or mentions(text)
            for candidate in {plain, plain.partition("=")[2]} - {""}:
                if any(mark in candidate for mark in DYNAMIC_MARKS) or candidate.startswith("-") or " " in candidate:
                    continue
                try:
                    resolved = (directory / os.path.expanduser(candidate)).resolve()
                except (OSError, RuntimeError, ValueError):
                    continue
                if within(resolved):
                    named = inside = True
                elif name in LIMITS_REMOVERS and resolved != Path("/") and home.is_relative_to(resolved):
                    named = True
        writes = writes or _limits_write_form(segment, words)
        if name == "cd" and len(program) == 2 and not any(mark in program[1] for mark in DYNAMIC_MARKS):
            try:
                directory = (directory / os.path.expanduser(QUOTE_MARKS.sub("", program[1]))).resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            inside = inside or within(directory)
    if named:
        plain_read = not any(mark in command for mark in ("$(", "`", "<(", ">(")) and all(
            segment.words and os.path.basename(segment.words[0]) in LIMITS_READS and not any(
                ">" in operator and target != "/dev/null" for _, operator, target in segment.redirects)
            for segment in segments if not all(ASSIGNMENT.match(word) for word in segment.words))
        return None if plain_read else ask
    return ask if dynamic and writes and inside else None


def _capture_plan(host, session, tool, event):
    """After a successful PostgreSQL plan statement on a production connection, record its estimate for the session."""
    try:
        tool_input = event.get("tool_input")
        datagrip = _datagrip()
        if tool == DATAGRIP_TOOL:
            target = datagrip.database_target(tool_input)
        else:
            connection = tabularis_connection(tool_input.get("connection_id")) if isinstance(tool_input, dict) else None
            sql = tool_input.get("query") if isinstance(tool_input, dict) else None
            target = (connection[0], connection[1], connection[2] == "postgresql", sql) \
                if connection and isinstance(sql, str) else None
        if target is None or not target[2] or not db_read_policy.is_production(target[1]):
            return
        kind, read = datagrip.read_shape(target[3])
        if kind == "plan":
            db_read_policy.record_plan(host, session, "datagrip" if tool == DATAGRIP_TOOL else "tabularis", target[0],
                                       read, event.get("tool_response"))
    except Exception as error:
        _report_error(error)


def _report_error(error):
    print(f"approval_guard: classifier error: {type(error).__name__}", file=sys.stderr)


def _classify_safely(classifier, identity):
    try:
        return classifier()
    except Exception as error:
        _report_error(error)
        return Outcome("always", ["guard:unclassified:" + _digest(identity)], [FAILURE_REASON], every_time=True,
                       critical=True)


def classify_file_tool(tool, tool_input, cwd):
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool == "apply_patch":
        patch = tool_input.get("command", tool_input.get("patch", tool_input.get("input", "")))
        paths = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", patch, re.M)
    else:
        paths = [tool_input[key] for key in ("file_path", "notebook_path") if isinstance(tool_input.get(key), str)]
    if tool != "Read" and any(_state_path(path, cwd) for path in paths):
        return Outcome("forbidden", [], [SELF_APPROVAL_REASON])
    if tool != "Read" and any(_resolved(path, cwd) == db_read_policy.limits_path().resolve() for path in paths):
        return Outcome("always", [f"db-limits:{_digest(' '.join(paths))}"], ["Change to the database read limits file"],
                       every_time=True)
    if tool == "Read" and any(_protected_path(path, cwd) for path in paths):
        return _sensitive(" ".join(paths))
    return Outcome("pass", [], [])


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
        if _resolved(words[1], cwd) != Path(__file__).resolve() or words[2] != "request":
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


TEXT_METHODS = frozenset({
    "replace", "write", "format", "count", "startswith", "endswith", "find", "rfind", "index", "join", "strip", "lstrip",
    "rstrip", "split", "splitlines", "lower", "upper", "encode", "removeprefix", "removesuffix", "center",
})
TEXT_CALLS = frozenset({"print", "len", "str", "repr"})
DYNAMIC_NAMES = frozenset({"eval", "exec", "compile", "__import__", "getattr", "setattr", "globals", "vars", "locals"})
PROCESS_MODULES = frozenset({"subprocess", "importlib", "runpy", "ctypes", "multiprocessing", "pty", "socket"})


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


PYTHON_DOCUMENT = re.compile(r"(?m)^([^\n]*?)<<[ \t]*(['\"])([A-Za-z_]\w*)\2[^\n]*\n")


def _text_only_python_documents(text):
    """Spans of quoted-delimiter heredoc bodies that a plain `python3 -` reads and that carry state spellings only as text."""
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
        body_end = match.end() + end.start()
        if _state_text_only_python(text[match.end():body_end]):
            spans.append((match.end(), body_end))
    return spans


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


def _self_approval_reason(command):
    """Return why a command is self-approval, or None. A command that names the state folders may use only a path prefix variable."""
    if _runs_guard(command):
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


def main() -> int:
    if len(sys.argv) > 1:
        try:
            if sys.argv[1] != "request" or approval_state.parent_session():
                raise ValueError("Only a main-session approval request is supported")
            outcome = _request_args(sys.argv[2:])
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        print("Recorded session approval keys: " + "; ".join(outcome.keys))
        return 0
    try:
        event = json.loads(sys.stdin.buffer.read())
        host = detect_host()
        if isinstance(event, dict):
            approval_state.heartbeat(host, event.get("session_id"), event.get("hook_event_name"))
        if not enabled("approval_guard"):
            return 0
        output = handle(event, host)
    except Exception as error:
        if not isinstance(locals().get("event"), dict):
            return 0
        _report_error(error)
        if event.get("hook_event_name") != "PreToolUse":
            return 0
        outcome = Outcome("always", ["guard:unclassified:" + _digest(json.dumps(event, sort_keys=True))], [FAILURE_REASON],
                          every_time=True, critical=True)
        _record_risk(host, event.get("session_id"), event.get("tool_use_id"), event.get("tool_name"), outcome)
        output = approval_state.pre_decision(host, event.get("session_id"), outcome, event.get("tool_use_id"))
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
