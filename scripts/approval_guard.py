#!/usr/bin/env python3
"""Approval guard for covered CLI, MCP, and DataGrip writes, shared by Claude Code and Codex.

Reads run without approval, writes and sensitive reads ask once per session, and always calls ask every time.
Requests bundle session keys, secrets and forbidden state edits are denied, and pass leaves the host in charge.
Every verb and CLI table lives in this module. DataGrip queries are classified
by datagrip_guard, which makes its own PreToolUse decision; this entry point records and consumes their approvals.
The guard always exits 0; covered calls fail closed when their classification fails.
"""
import argparse
import ast
import fnmatch
import functools
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

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugin_toggles import detect_host, enabled  # noqa: E402
import approval_state  # noqa: E402
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
GUARD_SCRIPTS = frozenset({"approval_guard.py", "approval_state.py", "datagrip_guard.py", "hook_python.sh"})
GUARD_MODULES = frozenset({"approval_guard", "approval_state", "datagrip_guard"})
GUARD_CODE = re.compile(
    r"\bimport\s+[\w.,\s]*?\b(?:approval_guard|approval_state|datagrip_guard)\b"
    r"|\bfrom\s+(?:[\w.]+\.)?(?:approval_guard|approval_state|datagrip_guard)\b"
    r"|(?:__import__|import_module)\(\s*['\"](?:[\w.]+\.)?(?:approval_guard|approval_state|datagrip_guard)['\"]"
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
Rules = namedtuple("Rules", "secret dry_run always read target sensitive write",
                   defaults=(False, False, False, False, None, False, False))


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


def _unclassified(cli, command):
    kind = "always" if _destructive_text(command) and not _local_docker_only(command) else "write"
    return Outcome(kind, [f"{cli}:unclassified:{_digest(command)}"], ["Unclassified command: " + _one_line(command)],
                   every_time=kind == "always")


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


def _call(kind_name, cli, kind, target_fn, command):
    if not kind:
        return _unclassified(cli, command)
    target = target_fn()
    label = " ".join(kind)
    return Outcome(kind_name, [f"{cli}:{label}@{target}"], [f"{cli} {label} on {target}"],
                   every_time=kind_name == "always")


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


def _kube_target(args, env, cwd, explicit_context):
    kubeconfig = option_value(args, longs=("--kubeconfig",)) or env.get("KUBECONFIG") or "(default)"
    argv = ["kubectl"]
    if option_value(args, longs=("--kubeconfig",)):
        argv += ["--kubeconfig", option_value(args, longs=("--kubeconfig",))]
    context = explicit_context or _lookup([*argv, "config", "current-context"], env, cwd) or "(current)"
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

    def target():
        return _kube_target(args, env, cwd, option_value(args, longs=("--context",)))

    return Rules(secret=secret, dry_run=dry_run, always=forced, read=_matches(kind, KUBECTL_READS), target=target,
                 write=kind[:1] == ["config"])


HELM_READS = (
    ("list",), ("ls",), ("status",), ("history",), ("show",), ("search",), ("template",), ("lint",), ("version",),
    ("env",), ("get", "notes"), ("get", "hooks"), ("get", "metadata"), ("repo", "list"), ("dependency", "list"),
    ("plugin", "list"),
)
HELM_SENSITIVE = (("get", "all"), ("get", "manifest"), ("get", "values"))


def _helm_rules(kind, args, env, cwd):
    def target():
        return _kube_target(args, env, cwd, option_value(args, longs=("--kube-context",)))

    sensitive = _matches(kind, HELM_SENSITIVE)
    return Rules(always=sensitive, read=_matches(kind, HELM_READS), target=target, sensitive=sensitive,
                 write=kind[:2] in (["repo", "remove"], ["repo", "rm"]))


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

    def target():
        subscription = option_value(args, longs=("--subscription",)) or _lookup(
            ["az", "account", "show", "--query", "id", "-o", "tsv"], env, cwd) or "(current)"
        group = option_value(args, "-g", ("--resource-group",)) or "(default)"
        return f"{subscription}/{group}"

    return Rules(secret=secret, always=rest and method == "DELETE", read=read, target=target)


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

    return Rules(always=always, read=read, target=target, sensitive=sensitive)


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

    return Rules(secret=secret, always=kind[:2] == ["s3", "sync"] and _has_flag(args, "--delete"), read=read, target=target)


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
    return Rules(secret=secret, read=_gcloud_verb_read(kind), target=lambda: _project_target(args, env))


def _gsutil_rules(kind, args, env, cwd):
    return Rules(read=_gcloud_verb_read(kind), target=lambda: _project_target(args, env))


DOCKER_READ_FIRST = frozenset({"ps", "images", "inspect", "logs", "version", "info"})
DOCKER_OBJECTS = frozenset({
    "container", "image", "network", "volume", "context", "plugin", "node", "service", "stack", "secret", "config",
})
DOCKER_READS = (("context", "show"), ("compose", "ps"), ("compose", "logs"), ("compose", "config"))


def _docker_rules(kind, args, env, cwd, engine="docker"):
    read = (
        (bool(kind) and kind[0] in DOCKER_READ_FIRST)
        or (len(kind) >= 2 and kind[0] in DOCKER_OBJECTS and kind[1] in ("ls", "inspect"))
        or _matches(kind, DOCKER_READS)
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
        host = option_value(args, "-h", ("--host",)) or "(default)"
        database = option_value(args, "-d", ("--dbname",)) or "(default)"
    else:
        commands = option_values(args, "-Q") + option_values(args, "-q")
        files = option_values(args, "-i")
        host = option_value(args, "-S") or "(default)"
        database = option_value(args, "-d") or "(default)"
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
                   every_time=kind_name == "always")


def classify_cli(cli, args, env, cwd, command, depth=0):
    if cli in ("git", "gh"):
        return _git_gh(cli, args, command, cwd, env)
    if cli == "curl":
        return _classify_curl(args, command)
    kind = subcommand_words(args)
    if ((cli in ("docker", "podman") and "inspect" in kind[:2])
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
        return _call("write" if local and not rules.always else "always", cli, kind, rules.target, command)
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


def _state_path(path, cwd):
    candidate = _resolved(path, cwd)
    return any(candidate == directory or directory in candidate.parents for directory in (
        approval_state.state_dir().resolve(), (approval_state.state_dir().parent / "heartbeats").resolve(),
    ))


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
    destructive = _destructive_text(content)
    return Outcome("always" if destructive else "write", ["script:" + hashlib.sha256(identity.encode()).hexdigest()],
                   [f"Script {path} contains a covered CLI or SDK call that cannot be classified"], every_time=destructive)


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
    resolved = _mktemp_directory(value, environment)
    if resolved is not None:
        return resolved
    expanded = _expand_path_variables(value, statics)
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


def _unconditional_assignment(segment, operators, after_assignment):
    """Whether a standalone assignment always runs in the current shell: it follows nothing, `;`, or another assignment
    joined by `&&`, and it is not sent to the background or a pipe."""
    before = max((op for op in operators if op[3] <= segment.start), key=lambda op: op[3], default=None)
    after = min((op for op in operators if op[2] >= segment.end), key=lambda op: op[2], default=None)
    return ((before is None or before[1] == ";" or (before[1] == "&&" and after_assignment))
            and (after is None or after[1] in (";", "&&")))


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
    if any(name.startswith("GIT_") and name not in GIT_HARMLESS_ENV and not name.startswith("GIT_TRACE") for name in env):
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
        if destructive and verb in ("reset", "checkout", "restore") and _clean_tracked_tree(
                global_args, cwd or os.getcwd(), dict(os.environ if env is None else env)):
            destructive, write = False, True
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
                       every_time=destructive)
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


def _execution_policy(cli, args, cwd, env, variables, command):
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
    if cli == "rm":
        flags = [arg for arg in args if arg.startswith("-")]
        recursive = "--recursive" in flags or any(not arg.startswith("--") and set(arg[1:]) & {"r", "R"} for arg in flags)
        if not recursive:
            return Outcome("pass", [], [])
        values = {**env, **variables}
        for operand in (arg for arg in args if not arg.startswith("-")):
            expanded = (_mktemp_directory(operand, values)
                        or _mktemp_directory(_expand_path_variables(operand, values), values)
                        or _expand_path_variables(_tmpdir_default(operand, values), values))
            if "$" in expanded or "`" in expanded:
                return target("always", "Recursive removal with an unresolved target", True)
            head, tail = os.path.split(expanded)
            if re.search(r"[*?\[]", tail) and not re.search(r"[*?\[]", head) and re.search(r"[^*?.\[\]]", tail):
                if fnmatch.fnmatch(".git", tail):
                    return target("always", "Recursive removal of a protected or external path", True)
                path = (Path(cwd) / os.path.expanduser(head or ".")).resolve() / "_"
            else:
                fixed = re.split(r"[*?\[]", expanded, maxsplit=1)[0]
                if fixed != expanded and not fixed.endswith("/"):
                    fixed = str(Path(fixed).parent)
                path = (Path(cwd) / os.path.expanduser(fixed or ".")).resolve()
            temporary = _temporary(path, env)
            if (path == Path("/") or path == Path.home() or path == session or path in session.parents
                    or ".git" in path.parts or not (path.is_relative_to(session) or temporary)):
                return target("always", "Recursive removal of a protected or external path", True)
        return Outcome("pass", [], [])
    return None


READONLY_MODULES = frozenset({
    "sys", "os", "os.path", "re", "json", "csv", "argparse", "collections", "collections.abc", "itertools", "functools",
    "math", "statistics", "datetime", "time", "pathlib", "typing", "dataclasses", "textwrap", "string", "glob", "fnmatch",
    "hashlib", "base64", "enum", "decimal", "fractions", "heapq", "bisect", "copy", "pprint", "io", "difflib",
    "unicodedata", "uuid", "random", "platform", "shlex", "urllib.parse", "html", "zoneinfo",
    "calendar", "numbers", "abc", "contextlib", "struct", "binascii", "ipaddress", "tomllib", "configparser", "ast",
    "stat", "errno", "__future__", "shutil",
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


def _read_only_python(tree):
    """A conservative, exact test for Python code that cannot change anything: only listed standard modules, no process,
    network, environment, dynamic execution, or file mutation, and every `open` in a literal read mode. Anything that the
    test cannot decide is not read-only."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    bound = {}
    openers = {"open"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in READONLY_MODULES:
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
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and READONLY_SECRET_TEXT.search(node.value):
            return False
        if isinstance(node, ast.Attribute):
            if (node.attr in READONLY_BLOCKED or READONLY_PROCESS.fullmatch(node.attr)
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


def _python_policy(content, cwd, depth, env, readonly=False):
    if _code_runs_guard(content):
        return Outcome("forbidden", [], [SELF_APPROVAL_REASON])
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _unclassified("python", content) if PYTHON_EXEC.search(content) or SDK_IMPORT.search(content) else Outcome("pass", [], [])
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


def _classify_script(words, cwd, depth, env, variables=None):
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
        content = _script_content(resolved)
        if mode == "executable":
            header = content.splitlines()[0] if content else ""
            if re.match(r"#!.*\bpython[\d.]*\b", header):
                mode = "python"
            elif re.match(r"#!.*\b(?:sh|bash|zsh)\b", header) or resolved.suffix in (".sh", ".bash", ".zsh"):
                mode = "shell"
            else:
                return Outcome("pass", [], [])
        if mode == "python":
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


def _classify_argv(words, heredoc, cwd, depth, command, inherited_env=None, variables=None):
    helper = _helper_args(words)
    if helper is not None:
        return _classify_helper(helper, cwd, depth, command, inherited_env)
    stripped, assignments = strip_prefix(words)
    if not stripped:
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
    policy = _execution_policy(cli, stripped[1:], cwd, env, variables or {}, command)
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
    script = _classify_script(stripped, cwd, depth, env, variables)
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
    return Outcome(kind, keys, descriptions, None, writes, every_time)


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
        verdict = _python_policy(text[match.end():body_end], cwd, depth, env, stdin_code)
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
    if any(not words or words[0] not in ("grep", "rg", "head", "sort", "wc", "cut", "awk", "sed") for words in rest):
        return None
    name_only = [_name_only_stage(words) for words in rest]
    if any(words[0] in ("cut", "awk", "sed") and not named for words, named in zip(rest, name_only)):
        return None
    numeric_options = {"-n", "--lines", "-c", "--bytes", "-k", "--key", "--parallel", "--batch-size", "-S", "--buffer-size"}
    for words in rest:
        if words[0] in ("head", "sort", "wc"):
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
        if bool(regex.search(name + "=" + value)) != invert and SECRET_NAME.search(name):
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
                   every_time=True)


def classify_text(text, cwd, depth=0, env=None, variables=None, statics=None):
    """Classify a shell command string; the secret helper's own inner command is classified separately."""
    if depth > MAX_DEPTH:
        return _unclassified("bash", text if isinstance(text, str) else "")
    if not isinstance(text, str) or not text.strip():
        return Outcome("pass", [], [])
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
    text = _heredoc_data(text)
    text, python_verdicts = _python_documents(text, cwd, depth, environment)
    try:
        segments = tokenize(text)
        operators = [token for token in _lex(text) if token[0] == "op"]
    except ParseError:
        match = COVERED_WORD.search(_without_data(text))
        return _unclassified(match.group(0), text) if match else Outcome("pass", [], [])
    filtered_segments = {}
    start = 0
    boundaries = [(token[2], token[3]) for token in operators if token[1] in (";", "&&", "||")]
    changes_environment = "()" in text or any(
        segment.words and (ASSIGNMENT.match(segment.words[0]) or os.path.basename(segment.words[0]) in ENVIRONMENT_CHANGERS)
        for segment in segments
    )
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
    for segment in segments:
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
        region = checked[segment.start:segment.end]
        substitutions = list(_substitution_spans(region))
        scoped_env = current_env if files_stable else {**current_env, FILES_MAY_CHANGE: "1"}
        for _, _, body in substitutions:
            verdicts.append(classify_text(body, cwd, depth + 1, scoped_env, variables, statics))
            files_stable = files_stable and verdicts[-1].kind == "read"
        scoped_env = current_env if files_stable else {**current_env, FILES_MAY_CHANGE: "1"}
        for body in _indirect_regions(region, [segment]):
            verdict = classify_text(body, cwd, depth + 1, {**scoped_env, **assignments})
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
                    verdicts.append(verdict if pure_python or verdict.kind == "read" and shell else _unclassified(match.group(0), body))
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
        if (name in ENVIRONMENT_CHANGERS or name in VARIABLE_WRITERS or name == "printf" and "-v" in program
                or ":=" in region or "((" in region):
            statics.clear()
        elif name in ("for", "select") and len(program) > 1:
            statics.pop(program[1], None)
        if name == "cd" and len(program) == 2:
            if _cd_changes_directory(segment, operators):
                directory = _script_path(program[1], cwd, variables)
                if directory is not None and directory.is_dir():
                    cwd = str(directory)
            continue
        if not program and assignments:
            standalone = all(ASSIGNMENT.match(word) for word in segment.words)
            fixed = (standalone and recording and block_depth == 0
                     and _unconditional_assignment(segment, operators, was_assignment))
            if standalone:
                for key, value in assignments.items():
                    variables[key] = _expand_path_variables(value, variables)
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
                   else _classify_argv(argv or segment.words, segment.heredoc and not argv, cwd, depth, text, scoped_env,
                                       variables))
        if argv and (verdict.kind == "read" or verdict.kind == "pass" and os.path.basename(
                (strip_prefix(argv)[0] or [""])[0]) in OPERAND_READERS):
            verdict = _sensitive(text)
        files_stable = files_stable and verdict.kind == "read" and _redirects_allowed([segment])
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


def classify_tabularis(tool_input):
    arguments = tool_input if isinstance(tool_input, dict) else {}
    identifier, sql = arguments.get("connection_id"), arguments.get("query")
    connection = tabularis_connection(identifier)
    connection_id = connection[0] if connection else identifier if isinstance(identifier, str) else "unknown"
    name = connection[1] if connection else "an unidentified connection"
    text = sql if isinstance(sql, str) else ""
    always = Outcome("always", [f"sql:always:tabularis:{connection_id}:{_digest(text)}"],
                     [f"tabularis query on {name}"], every_time=True)
    write = Outcome("write", ["mcp:session"], [f"tabularis query on {name}"])
    datagrip = _datagrip()
    if datagrip.RAW_DESTRUCTIVE.search(text) or any(datagrip.query_facts(text, pg)[1] for pg in (True, False)):
        return always
    if not connection or "승인" in name or connection[2] not in ("postgresql", "sqlserver", "sqlserver-entra"):
        return write
    if not isinstance(sql, str):
        return write
    postgres = connection[2] == "postgresql"
    if datagrip.is_read(sql, postgres):
        return _read()
    keywords, destructive = datagrip.query_facts(sql, postgres)
    if destructive:
        return always
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


def classify_mcp(tool, tool_input=None, cwd=None):
    if tool == TABULARIS_TOOL:
        return classify_tabularis(tool_input)
    part = mcp_tool_part(tool)
    words = tool_words(part) if part else []
    sql = list(_input_strings(tool_input, sql_only=True))
    datagrip = _datagrip() if sql else None
    if any(datagrip.RAW_DESTRUCTIVE.search(text) or any(
            datagrip.query_facts(text, postgres)[1] for postgres in (True, False)) for text in sql):
        return Outcome("always", [f"mcp:{tool}:{_digest(json.dumps(sql))}"], [f"destructive SQL in MCP tool {tool}"],
                       every_time=True)
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


def _read_decision(host, outcome, tool_input):
    """A psql read runs with the server enforcing read-only mode; when that cannot be applied, it runs as before."""
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


def _edit_permission(session, tool_input, tool_name, cwd):
    paths = [tool_input.get(key) for key in ("file_path", "notebook_path")] if isinstance(tool_input, dict) else []
    paths = [path for path in paths if path is not None]
    if not paths or not all(isinstance(path, str) and path for path in paths):
        return None
    roots = _edit_roots(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
    if not all(_editable_path(path, cwd, roots) for path in paths):
        return None
    if approval_state.is_approved("claude", session, [approval_state.WRITE_KEY]):
        return approval_state.permission_allow()
    if not approval_state.parent_session():
        digest = approval_state.permission_digest(tool_name, tool_input)
        if not approval_state.request_ask("claude", session, [], [approval_state.WRITE_KEY], "pr:" + digest):
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


def _claude_permission(session, outcome, tool_input, tool_name, cwd):
    """Claude's PermissionRequest answers `allow` only for what the session's write approval already covers."""
    if outcome.kind == "pass":
        if tool_name in EDIT_TOOLS:
            return _edit_permission(session, tool_input, tool_name, cwd)
        if tool_name == "Read" and _plugin_file(tool_input, cwd):
            return approval_state.permission_allow()
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if tool_name == "Bash" and outcome.exe == TEMP_WRITE_EXE:
            return approval_state.permission_allow()
        if tool_name == "Bash" and isinstance(command, str) and _plain_command(command) and approval_state.is_approved(
                "claude", session, [approval_state.WRITE_KEY]):
            return approval_state.permission_allow()
        return None
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
    if not once_keys and approval_state.is_approved("codex", session, session_keys):
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
    if not approval_state.request_ask("codex", session, once_keys, session_keys, request_id, session_keys):
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
            return _claude_permission(session, outcome, tool_input, tool_name, cwd)
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
    if tool == DATAGRIP_TOOL:
        if name in POST_EVENTS:
            outcome = _classify_safely(lambda: _datagrip().classify_query(event.get("tool_input")), tool)
            approval_state.after_call(host, session, outcome, tool_use_id, tool, event.get("tool_input"))
        elif name == "PreToolUse" and host == "claude" and enabled("datagrip_guard"):
            outcome = _classify_safely(lambda: _datagrip().classify_query(event.get("tool_input")), tool)
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
    elif tool.startswith("mcp__"):
        outcome = _classify_safely(lambda: classify_mcp(tool, tool_input, _cwd(event)), tool)
    elif tool in FILE_TOOLS:
        outcome = _classify_safely(lambda: classify_file_tool(tool, tool_input, _cwd(event)), tool)
    else:
        return None
    return _decide(name, host, session, outcome, tool_use_id, tool_input, tool, _cwd(event), event,
                   wrapped is not None)


def _report_error(error):
    print(f"approval_guard: classifier error: {type(error).__name__}", file=sys.stderr)


def _classify_safely(classifier, identity):
    try:
        return classifier()
    except Exception as error:
        _report_error(error)
        return Outcome("always", ["guard:unclassified:" + _digest(identity)], [FAILURE_REASON], every_time=True)


def classify_file_tool(tool, tool_input, cwd):
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool == "apply_patch":
        patch = tool_input.get("command", tool_input.get("patch", tool_input.get("input", "")))
        paths = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", patch, re.M)
    else:
        paths = [tool_input[key] for key in ("file_path", "notebook_path") if isinstance(tool_input.get(key), str)]
    if tool != "Read" and any(_state_path(path, cwd) for path in paths):
        return Outcome("forbidden", [], [SELF_APPROVAL_REASON])
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


def _self_approval_reason(command):
    """Return why a command is self-approval, or None. A command that names the state folders may use only a path prefix variable."""
    if _runs_guard(command):
        return SELF_APPROVAL_REASON
    if (str(approval_state.state_dir()) in command or "hei5enbug-agent-setup/approvals" in command
            or str(approval_state.state_dir().parent / "heartbeats") in command
            or "hei5enbug-agent-setup/heartbeats" in command):
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
                          every_time=True)
        output = approval_state.pre_decision(host, event.get("session_id"), outcome, event.get("tool_use_id"))
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
