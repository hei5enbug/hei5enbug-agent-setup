"""Shell lexing and tokenizing, heredoc and expansion regions, wrapper unwrapping, option parsing, and the result helpers every approval guard module shares."""
import hashlib
import os
import re
import shlex
import subprocess
from collections import namedtuple
from pathlib import Path
import approval_state
from approval_state import Outcome


WRAPPER = str(Path(__file__).resolve().parents[1] / "scripts" / "approve_wrapper.sh")
LOOKUP_TIMEOUT_SECONDS = 3
COVERED = frozenset({
    "kubectl", "oc", "helm", "kustomize", "az", "terraform", "tofu", "aws", "gcloud", "gsutil",
    "docker", "podman", "psql", "sqlcmd", "mysql", "mongosh", "redis-cli", "curl", "git", "gh",
})
PYTHON = re.compile(r"python(?:\d+(?:\.\d+)*)?")
SHELLS = frozenset({"sh", "bash", "zsh"})
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
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
OPAQUE_CONSTRUCT = re.compile(r"\b(?:eval|xargs)\b|\b(?:sh|bash|zsh)\b[^;&|\n]*?\s-[A-Za-z]*c[A-Za-z]*\b")
SHELL_C_FLAG = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
READ_ONLY_PREFIX = (
    'export PGOPTIONS="${PGOPTIONS:+$PGOPTIONS }-c default_transaction_read_only=on -c statement_timeout=60000"; '
)


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


def _unrecognized_wrapper(text):
    return Outcome("always", ["wrapper:unrecognized:" + _digest(text)], ["Unrecognized approval wrapper call"],
                   every_time=True, critical=True)


def tool_words(part):
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", part)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", spaced)
    return [word for word in re.split(r"[_\-\s]+", spaced.lower()) if word]
