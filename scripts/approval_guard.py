#!/usr/bin/env python3
"""Approval guard for covered CLI, MCP, and DataGrip writes, shared by Claude Code and Codex.

Reads run without approval, writes ask once per session per key, and always/sensitive calls ask every time.
Requests bundle session keys, secrets and forbidden state edits are denied, and pass leaves the host in charge.
Every verb and CLI table lives in this module. DataGrip queries are classified
by datagrip_guard, which makes its own PreToolUse decision; this entry point records and consumes their approvals.
The guard always exits 0; covered calls fail closed when their classification fails.
"""
import argparse
import ast
import fnmatch
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
import datagrip_guard  # noqa: E402
from approval_state import Outcome  # noqa: E402

DATAGRIP_TOOL = datagrip_guard.TOOL_NAME
TABULARIS_TOOL = "mcp__tabularis__run_query"
POST_EVENTS = ("PostToolUse", "PostToolUseFailure")
EVENTS = ("PreToolUse", "PermissionRequest", *POST_EVENTS)
MAX_DEPTH = 4
LOOKUP_TIMEOUT_SECONDS = 3
COVERED = frozenset({
    "kubectl", "oc", "helm", "kustomize", "az", "terraform", "tofu", "aws", "gcloud", "gsutil",
    "docker", "podman", "psql", "sqlcmd", "mysql", "mongosh", "redis-cli", "curl", "git", "gh",
})
PYTHON = re.compile(r"python(?:\d+(?:\.\d+)*)?")
SHELLS = frozenset({"sh", "bash", "zsh"})
FILTERS = frozenset({"grep", "egrep", "fgrep", "rg", "head", "tail", "wc", "sort", "uniq", "jq", "cut", "tr", "column"})
WRAPPER_VALUE_OPTIONS = {
    "sudo": frozenset({"-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U", "-D", "-T"}),
    "env": frozenset({"-u", "-C", "-S"}),
    "command": frozenset(),
    "time": frozenset({"-f", "-o"}),
    "nice": frozenset({"-n"}),
    "nohup": frozenset(),
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
COVERED_WORD = re.compile(r"(?<![\w-])(?:" + "|".join(sorted(COVERED, key=len, reverse=True)) + r")(?![\w-])")
OPAQUE_CONSTRUCT = re.compile(r"\b(?:eval|xargs)\b|\b(?:sh|bash|zsh)\b[^;&|\n]*?\s-[A-Za-z]*c[A-Za-z]*\b")
SHELL_C_FLAG = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
GUARD_SCRIPTS = frozenset({"approval_guard.py", "approval_state.py", "datagrip_guard.py"})
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
SENSITIVE_REASON = "This may expose a protected value; prefer secret_exec.py to pass it without printing it."
FAILURE_REASON = "The approval guard failed to check this call"
FILE_TOOLS = frozenset({"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"})
FILE_READS = frozenset({"cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg"})
EXEC_WORDS = frozenset({"repl", "exec", "execute", "eval", "run", "code", "script", "command"})
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASS|PWD|CRED|AUTH|COOKIE|PRIVATE|CERT|SAS|CONN|SIGNATURE|OTP", re.I)


def read_only_command(command):
    """Run a psql read in a subshell so the read-only option never outlives this call."""
    return "( " + READ_ONLY_PREFIX + command + "\n)"
SEPARATOR_OPERATORS = ("&&", "||", "|&", ";;", ";", "|", "&", "(", ")")
REDIRECT_OPERATORS = ("&>>", "&>", ">>", ">&", ">|", "<<<", "<<", "<&", "<>", ">", "<")
OPERATORS = tuple(sorted(SEPARATOR_OPERATORS + REDIRECT_OPERATORS, key=len, reverse=True))

Segment = namedtuple("Segment", "words redirects heredoc start end")
Rules = namedtuple("Rules", "secret dry_run always read target", defaults=(False, False, False, False, None))


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
        redirects = []
        heredoc = False
        index = 0
        plain_before = False
        while index < len(group):
            kind, value, start, end = group[index]
            if kind == "word":
                words.append(value)
                plain_before = True
                index += 1
                continue
            fd = None
            previous = group[index - 1] if index > 0 else None
            if plain_before and previous[3] == start and previous[1].isdigit():
                fd = words.pop()
            if index + 1 >= len(group) or group[index + 1][0] != "word":
                raise ParseError("redirection without a target")
            redirects.append((fd, value, group[index + 1][1]))
            heredoc = heredoc or value in ("<<", "<<<")
            plain_before = False
            index += 2
        if words or redirects:
            segments.append(Segment(words, redirects, heredoc, group[0][2], group[-1][3]))
    return segments


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _read():
    return Outcome("read", [], [])


def _unclassified(cli, command):
    kind = "always" if _destructive_text(command) else "write"
    return Outcome(kind, [f"{cli}:unclassified:{_digest(command)}"], [f"{cli} call that cannot be classified"])


def _destructive_text(text):
    text = _heredoc_data(text)
    names = "|".join(re.escape(name) for name in COVERED - {"git", "gh"})
    destructive = "|".join(CLI_DESTRUCTIVE_WORDS)
    return bool(re.search(r"\b(?:" + names + r")\b[^\n;&|]*\b(?:" + destructive + r")\b", text, re.I)
                or re.search(r"\b(?:delete\s+from|drop\s+(?:table|database|schema)|truncate\s+table)\b", text, re.I))


def _call(kind_name, cli, kind, target_fn, command):
    if not kind:
        return _unclassified(cli, command)
    target = target_fn()
    label = " ".join(kind)
    return Outcome(kind_name, [f"{cli}:{label}@{target}"], [f"{cli} {label} on {target}"])


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
KUBECTL_READS = (
    ("get",), ("describe",), ("logs",), ("top",), ("explain",), ("api-resources",), ("api-versions",),
    ("version",), ("cluster-info",), ("events",), ("diff",), ("auth", "can-i"), ("auth", "whoami"),
    ("config", "view"), ("config", "get-contexts"), ("config", "current-context"), ("config", "get-clusters"),
    ("rollout", "status"), ("rollout", "history"),
)


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
        secret = secret or (raw is not None and "secrets" in raw) or (_secret_resource(args) and output_secret)
    dry_run = _has_flag(args, "--dry-run=client", "--dry-run=server") or option_value(
        args, longs=("--dry-run",)) in ("client", "server")
    forced = any(arg in ("--force", "--prune") or arg.startswith(("--force=", "--prune=")) for arg in args)

    def target():
        return _kube_target(args, env, cwd, option_value(args, longs=("--context",)))

    return Rules(secret=secret, dry_run=dry_run, always=forced, read=_matches(kind, KUBECTL_READS), target=target)


HELM_READS = (
    ("list",), ("ls",), ("status",), ("history",), ("show",), ("search",), ("template",), ("lint",), ("version",),
    ("env",), ("get", "notes"), ("get", "hooks"), ("get", "metadata"), ("repo", "list"), ("dependency", "list"),
    ("plugin", "list"),
)
HELM_SENSITIVE = (("get", "all"), ("get", "manifest"), ("get", "values"))


def _helm_rules(kind, args, env, cwd):
    def target():
        return _kube_target(args, env, cwd, option_value(args, longs=("--kube-context",)))

    return Rules(always=_matches(kind, HELM_SENSITIVE), read=_matches(kind, HELM_READS), target=target)


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
        parsed = urlsplit(lowered)
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
    always = _matches(kind, TF_SENSITIVE) or sensitive_output or (kind[:1] == ["apply"] and _has_flag(args, "-destroy"))
    plain_output = kind[:1] == ["output"] and not sensitive_output
    read = _matches(kind, TF_READS) or plain_output or (kind[:1] == ["fmt"] and _has_flag(args, "-check"))

    def target():
        chdir = option_value(args, longs=("-chdir",))
        directory = os.path.normpath(os.path.join(cwd, chdir)) if chdir else cwd
        workspace = env.get("TF_WORKSPACE") or _read_workspace(directory) or "default"
        return f"{directory}:{workspace}"

    return Rules(always=always, read=read, target=target)


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


def _docker_rules(kind, args, env, cwd):
    read = (
        (bool(kind) and kind[0] in DOCKER_READ_FIRST)
        or (len(kind) >= 2 and kind[0] in DOCKER_OBJECTS and kind[1] in ("ls", "inspect"))
        or _matches(kind, DOCKER_READS)
    )
    always = kind[:2] == ["compose", "down"] and (_has_flag(args, "-v") or _has_flag(args, "--volumes"))

    def target():
        return (option_value(args, longs=("--context",)) or env.get("DOCKER_CONTEXT")
                or env.get("DOCKER_HOST") or "(current)")

    return Rules(always=always, read=read, target=target)


CLI_RULES = {
    "kubectl": _kubectl_rules, "oc": _kubectl_rules, "helm": _helm_rules, "az": _az_rules,
    "terraform": _terraform_rules, "tofu": _terraform_rules, "aws": _aws_rules, "gcloud": _gcloud_rules,
    "gsutil": _gsutil_rules, "docker": _docker_rules, "podman": _docker_rules,
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
    if all(datagrip_guard.is_read(value, postgres) for value in commands):
        return Outcome("read", [], [], "psql" if postgres else None)
    facts = [datagrip_guard.query_facts(value, postgres) for value in commands]
    if any(keywords is None for keywords, _ in facts):
        return _unclassified(cli, command)
    label = "+".join(sorted(set().union(*(keywords for keywords, _ in facts))))
    target = f"{host}/{database}"
    kind_name = "always" if any(destructive for _, destructive in facts) else "write"
    return Outcome(kind_name, [f"{cli}:{label}@{target}"], [f"{cli} {label} on {target}"])


def classify_cli(cli, args, env, cwd, command, depth=0):
    if cli in ("git", "gh"):
        return _git_gh(cli, args, command)
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
        verdict = classify_text(inner, cwd, depth + 1, env)
        if verdict.kind in ("secret", "always"):
            return verdict
        if (re.search(r"(?:^|[\s;&|('\"`])(?:rm|rmdir|shred|mkfs(?:\.\w+)?|truncate)(?=\s|$)", inner)
                or re.search(r"\bdd\b[^;&|]*\bof=", inner) or _destructive_text(inner)):
            return _call("always", cli, kind, rules.target, command)
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
    if rules.always or _destructive(kind):
        return _call("always", cli, kind, rules.target, command)
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
    return Outcome("sensitive", ["sensitive:" + _digest(text)], [SENSITIVE_REASON])


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
    if candidate.name.startswith(".env") or candidate in protected:
        return True
    return any(candidate == directory or directory in candidate.parents for directory in (
        home / ".azure", home / ".config/gcloud",
    ))


def _classify_curl(args, command):
    headers = option_values(args, "-H", ("--header",))
    if (_has_flag(args, "-u", "--user") or option_values(args, "-u", ("--user",))
            or any(value and re.match(r"authorization\s*:", value, re.I) for value in headers)):
        return _sensitive(command)
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
        parsed = urlsplit(url) if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*://", url) else None
        if parsed and parsed.hostname:
            host = parsed.hostname
            if ":" in host:
                host = "[" + host + "]"
            targets.add(f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else ""))
        index += 1
    if not targets:
        return _unclassified("curl", command)
    return Outcome("always" if _destructive([method]) else "write", [f"curl:{method}@{target}" for target in sorted(targets)],
                   [f"curl {method} on {target}" for target in sorted(targets)])


def _script_unknown(path, args, env, content):
    identity = json.dumps([str(path), args, {key: env.get(key, "") for key in (
        "KUBECONFIG", "AWS_PROFILE", "CLOUDSDK_CORE_PROJECT", "DOCKER_CONTEXT",
    )}, content], ensure_ascii=False)
    return Outcome("always" if _destructive_text(content) else "write", ["script:" + hashlib.sha256(identity.encode()).hexdigest()],
                   [f"Script {path} contains a covered CLI or SDK call that cannot be classified"])


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
        host = urlsplit(url).hostname if url else host
    if cli in ("psql", "mongosh", "mysql"):
        for arg in args:
            if "://" in arg:
                host = urlsplit(arg).hostname
            elif cli == "psql":
                match = re.search(r"(?:^|\s)host=([^\s]+)", arg)
                if match:
                    host = match[1]
    if cli == "mysql":
        host = option_value(args, "-S", ("--socket",)) or host
    return isinstance(host, str) and (host.lower() in ("localhost", "127.0.0.1", "::1") or host.startswith("/"))


def _git_gh(cli, args, command):
    if cli == "gh" and any(arg in ("--help", "--version") for arg in args):
        return _read()
    global_values = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"} if cli == "git" else {"-R", "--repo", "--hostname"}
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in global_values else 1
    args = args[index:]
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
            destructive = _has_flag(args, "--delete", "--force") or any(set(arg[1:]) & {"d", "f"} for arg in short)
            listing = _has_flag(args, "-l", "--list", "-v", "--verify", "--format", "--contains", "--no-contains",
                                "--points-at", "--merged", "--no-merged", "--column", "--sort")
            listing = listing or any(arg.startswith("-n") and not arg.startswith("--") for arg in args)
            write = destructive or (bool(operands) and not listing
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
        return Outcome("always" if destructive else "write", [f"{cli}:{_digest(command)}"], [f"{cli} {' '.join(words[:2])}"])
    read_verbs = {"status", "show", "log", "diff", "ls-remote", "describe", "rev-parse"}
    gh_read = cli == "gh"
    if gh_read or cli == "git" and (verb in read_verbs or verb == "tag"):
        return _read()
    return Outcome("pass", [], [])


def _execution_policy(cli, args, cwd, env, variables, command):
    session = Path(env.get("_APPROVAL_SESSION_DIR", env.get("CLAUDE_PROJECT_DIR") or cwd)).resolve()
    target = lambda kind, label: Outcome(kind, [f"{cli}:{_digest(command)}"], [label])
    positional = [arg for arg in args if not arg.startswith("-")]
    if (cli in ("npm", "pnpm", "yarn", "uv", "poetry", "cargo") and "publish" in positional
            or cli == "twine" and "upload" in positional or cli == "gem" and "push" in positional):
        return target("always", f"{cli} package publishing")
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
            return target("always", "Codex access without sandbox protection")
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
        roots = [Path(path).resolve() for path in ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders",
                                                 env.get("TMPDIR") or "/tmp", str(Path.home() / ".cache"))]
        for operand in (arg for arg in args if not arg.startswith("-")):
            expanded = _expand_path_variables(operand, {**env, **variables})
            if "$" in expanded or "`" in expanded:
                return target("always", "Recursive removal with an unresolved target")
            head, tail = os.path.split(expanded)
            if re.search(r"[*?\[]", tail) and not re.search(r"[*?\[]", head) and re.search(r"[^*?.\[\]]", tail):
                if fnmatch.fnmatch(".git", tail):
                    return target("always", "Recursive removal of a protected or external path")
                path = (Path(cwd) / os.path.expanduser(head or ".")).resolve() / "_"
            else:
                fixed = re.split(r"[*?\[]", expanded, maxsplit=1)[0]
                if fixed != expanded and not fixed.endswith("/"):
                    fixed = str(Path(fixed).parent)
                path = (Path(cwd) / os.path.expanduser(fixed or ".")).resolve()
            temporary = any(path.is_relative_to(root) for root in roots)
            if (path == Path("/") or path == Path.home() or path == session or path in session.parents
                    or ".git" in path.parts or not (path.is_relative_to(session) or temporary)):
                return target("always", "Recursive removal of a protected or external path")
        return Outcome("pass", [], [])
    return None


def _python_policy(content, cwd, depth, env):
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
    return Outcome("always" if destructive else "write", ["python:" + _digest(content)], ["Python process or SDK execution"])


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
            verdict = _python_policy(content, cwd, depth, env)
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
        if PYTHON.fullmatch(cli) and "--execute" in stripped[1:] and script.kind == "pass":
            return Outcome("write", ["python:execute"], ["Python execution with --execute"])
        return script
    if PYTHON.fullmatch(cli) and "--execute" in stripped[1:]:
        return Outcome("write", ["python:execute"], ["Python execution with --execute"])
    if heredoc and (cli in COVERED or COVERED_WORD.search(command)):
        return _unclassified(cli, command)
    if cli not in COVERED:
        return Outcome("pass", [], [], cli)
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
    writes = sorted({key for verdict in extra_writes for key in verdict.keys})
    descriptions = list(dict.fromkeys(
        text for verdict in [*verdicts, *extra_writes] for text in verdict.descriptions
    ))
    return Outcome(kind, keys, descriptions, None, writes)


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
        elif name in ("eval", "xargs"):
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
        if not words or not PYTHON.fullmatch(os.path.basename(words[0])) or "-c" in words:
            continue
        end = re.search(r"(?m)^" + re.escape(match[3]) + r"[ \t]*\r?$", text[match.end():])
        if end is None:
            continue
        body_end = match.end() + end.start()
        verdict = _python_policy(text[match.end():body_end], cwd, depth, env)
        if verdict.kind == "pass" and "--execute" in words:
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


def _environment_filter(text):
    try:
        segments = tokenize(text)
        operators = [token[1] for token in _lex(text) if token[0] == "op"]
    except ParseError:
        return None
    if not segments or any(op != "|" for op in operators) or any(segment.redirects for segment in segments):
        return None
    if any("$" in word or "`" in word for segment in segments for word in segment.words):
        return None
    first = segments[0].words
    if not first or first[0] not in ("env", "printenv") or len(first) != 1:
        return None
    if len(segments) < 2:
        return None
    rest = [segment.words for segment in segments[1:]]
    if any(not words or words[0] not in ("grep", "rg", "head", "sort", "wc") for words in rest):
        return None
    numeric_options = {"-n", "--lines", "-c", "--bytes", "-k", "--key", "--parallel", "--batch-size", "-S", "--buffer-size"}
    for words in rest:
        if words[0] in ("head", "sort", "wc"):
            for index, word in enumerate(words[1:], 1):
                if not word.startswith("-") and not (word.isdigit() and words[index - 1] in numeric_options):
                    return None
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


def classify_text(text, cwd, depth=0, env=None, variables=None):
    """Classify a shell command string; the secret helper's own inner command is classified separately."""
    if depth > MAX_DEPTH:
        return _unclassified("bash", text if isinstance(text, str) else "")
    if not isinstance(text, str) or not text.strip():
        return Outcome("pass", [], [])
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
        match = COVERED_WORD.search(text)
        return _unclassified(match.group(0), text) if match else Outcome("pass", [], [])
    spans = [(segment.start, segment.end) for segment in segments if _helper_args(segment.words) is not None]
    checked = _blank(text, spans)
    verdicts = list(python_verdicts)
    variables = dict(variables or {})
    substitution_names = set()
    current_env = environment
    for segment in segments:
        program, assignments = strip_prefix(segment.words)
        region = checked[segment.start:segment.end]
        substitutions = list(_substitution_spans(region))
        for _, _, body in substitutions:
            verdicts.append(classify_text(body, cwd, depth + 1, current_env, variables))
        for body in _indirect_regions(region, [segment]):
            verdict = classify_text(body, cwd, depth + 1, current_env)
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
        if PYTHON.fullmatch(name) and "-c" not in program and "-m" not in program:
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
        if name == "cd" and len(program) == 2:
            if _cd_changes_directory(segment, operators):
                directory = _script_path(program[1], cwd, variables)
                if directory is not None and directory.is_dir():
                    cwd = str(directory)
            continue
        if not program and assignments:
            if all(ASSIGNMENT.match(word) for word in segment.words):
                for key, value in assignments.items():
                    variables[key] = _expand_path_variables(value, variables)
                    if key != "_APPROVAL_SESSION_DIR":
                        current_env[key] = variables[key]
                    if "$(" in value or "`" in value:
                        substitution_names.add(key)
                    else:
                        substitution_names.discard(key)
            continue
        dynamic_program = program and re.search(r"\$\(|`|\$\{|\$[A-Za-z_]", program[0])
        verdict = (_unclassified(name, text) if dynamic_program and COVERED_WORD.search(region)
                   else _classify_argv(segment.words, segment.heredoc, cwd, depth, text, current_env, variables))
        output = name in ("echo", "printf") and (substitutions or any(
            re.search(r"\$(?:" + re.escape(key) + r"\b|\{" + re.escape(key) + r"\})", region)
            for key in substitution_names
        ))
        if verdict.kind != "pass" or not output:
            verdicts.append(verdict)
    return _aggregate(verdicts, segments)


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
                     [f"tabularis query on {name}"])
    write = Outcome("write", ["mcp:session"], [f"tabularis query on {name}"])
    if datagrip_guard.RAW_DESTRUCTIVE.search(text) or any(datagrip_guard.query_facts(text, pg)[1] for pg in (True, False)):
        return always
    if not connection or "승인" in name or connection[2] not in ("postgresql", "sqlserver", "sqlserver-entra"):
        return write
    if not isinstance(sql, str):
        return write
    postgres = connection[2] == "postgresql"
    if datagrip_guard.is_read(sql, postgres):
        return _read()
    keywords, destructive = datagrip_guard.query_facts(sql, postgres)
    if destructive:
        return always
    return Outcome("write", ["mcp:session"], [f"tabularis write on {name}"])


def classify_mcp(tool, tool_input=None):
    if tool == TABULARIS_TOOL:
        return classify_tabularis(tool_input)
    part = mcp_tool_part(tool)
    words = tool_words(part) if part else []
    if any(word in MCP_DESTRUCTIVE_WORDS for word in words):
        return Outcome("always", [f"mcp:{tool}"], [f"destructive MCP tool {tool}"])
    action = tool_input.get("action") if isinstance(tool_input, dict) else None
    action_words = tool_words(action) if isinstance(action, str) else []
    if set(action_words) & MCP_DESTRUCTIVE_WORDS:
        return Outcome("always", [f"mcp:{tool}"], [f"destructive MCP action via {tool}"])
    sql = list(_input_strings(tool_input, sql_only=True))
    if sql:
        if any(datagrip_guard.RAW_DESTRUCTIVE.search(text) or any(
                datagrip_guard.query_facts(text, postgres)[1] for postgres in (True, False)) for text in sql):
            return Outcome("always", [f"mcp:{tool}:{_digest(json.dumps(sql))}"], [f"destructive SQL in MCP tool {tool}"])
        if all(datagrip_guard.is_read(text, True) or datagrip_guard.is_read(text, False) for text in sql):
            return _read()
        return Outcome("write", ["mcp:session"], [f"MCP SQL write via {tool}"])
    if set(words) & EXEC_WORDS:
        text_words = set(re.findall(r"[a-z]+", " ".join(_input_strings(tool_input)).lower()))
        if text_words & (CLI_DESTRUCTIVE_WORDS | MCP_DESTRUCTIVE_WORDS):
            return Outcome("always", [f"mcp:{tool}:{_digest(json.dumps(tool_input, sort_keys=True))}"],
                           [f"destructive input in MCP tool {tool}"])
    if set(action_words) & (MCP_WRITE_WORDS | EXEC_WORDS):
        return Outcome("write", ["mcp:session"], [f"MCP write action via {tool}"])
    if set(action_words) & MCP_READ_VERBS:
        return _read()
    if set(words) & EXEC_WORDS:
        return Outcome("write", ["mcp:session"], [f"MCP execution tool {tool}"])
    if not words:
        return Outcome("write", [f"mcp:{tool}"], [f"MCP tool {tool}"])
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


def _decide(name, host, session, outcome, tool_use_id=None, tool_input=None):
    if outcome.kind == "forbidden":
        return approval_state.pre_output("deny", "; ".join(outcome.descriptions)) if name == "PreToolUse" else None
    if outcome.kind == "secret":
        return _deny_secret() if name == "PreToolUse" else None
    if name == "PreToolUse":
        if outcome.kind == "read":
            return _read_decision(host, outcome, tool_input)
        if outcome.kind in ("write", "always", "sensitive", "request"):
            return approval_state.pre_decision(host, session, outcome, tool_use_id)
        return None
    if name == "PermissionRequest":
        if host != "codex":
            return None
        if outcome.kind == "read" or approval_state.permission_allowed(host, session, outcome, tool_use_id):
            return approval_state.permission_allow()
        return None
    if name in POST_EVENTS:
        approval_state.after_call(host, session, outcome, tool_use_id)
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
            approval_state.after_call(
                host, session, datagrip_guard.classify_query(event.get("tool_input")), tool_use_id)
        elif name == "PreToolUse" and host == "claude" and enabled("datagrip_guard"):
            outcome = _classify_safely(lambda: datagrip_guard.classify_query(event.get("tool_input")), tool)
            if outcome.kind == "always":
                return approval_state.pre_decision(host, session, outcome, tool_use_id)
        return None
    tool_input = event.get("tool_input")
    if tool == "Bash":
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            return None
        outcome = _request_outcome(command, _cwd(event))
        if name == "PreToolUse" and outcome is None and _self_approval(command):
            return approval_state.pre_output("deny", SELF_APPROVAL_REASON)
        outcome = outcome or _classify_safely(lambda: classify_text(command, _cwd(event)), command)
    elif tool.startswith("mcp__"):
        outcome = _classify_safely(lambda: classify_mcp(tool, tool_input), tool)
    elif tool in FILE_TOOLS:
        outcome = _classify_safely(lambda: classify_file_tool(tool, tool_input, _cwd(event)), tool)
    else:
        return None
    return _decide(name, host, session, outcome, tool_use_id, tool_input)


def _classify_safely(classifier, identity):
    try:
        return classifier()
    except Exception:
        return Outcome("always", ["guard:unclassified:" + _digest(identity)], [FAILURE_REASON])


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
    if key in ("mcp:session", approval_state.WRITE_KEY):
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


def _self_approval(command):
    if (str(approval_state.state_dir()) in command or "hei5enbug-agent-setup/approvals" in command
            or str(approval_state.state_dir().parent / "heartbeats") in command
            or "hei5enbug-agent-setup/heartbeats" in command):
        return True
    return _runs_guard(command)


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
    except Exception:
        if not isinstance(locals().get("event"), dict) or event.get("hook_event_name") != "PreToolUse":
            return 0
        outcome = Outcome("always", ["guard:unclassified:" + _digest(json.dumps(event, sort_keys=True))], [FAILURE_REASON])
        output = approval_state.pre_decision(host, event.get("session_id"), outcome, event.get("tool_use_id"))
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
