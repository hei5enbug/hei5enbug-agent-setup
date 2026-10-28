"""Name-only reads, xargs inputs, and output filters that the approval guard passes as reads."""
import os
import re
import approval_state
from guard_shell import ASSIGNMENT, ParseError, SHELLS, _helper_args, _lex, _read, _shell_c, strip_prefix, tokenize
from guard_paths import _expand_path_variables, _sensitive, _temp_path
from guard_expand import ENVIRONMENT_CHANGERS, VARIABLE_REFERENCE, _expand_segment_words


AWK_PRINT = re.compile(
    r"(?:NR\s*(?:==|!=|>=|<=|>|<)\s*\d+\s*)?\{\s*print(?:\s+(?:\$\d+|\$NF)(?:\s*,\s*(?:\$\d+|\$NF))*)?\s*\}"
)
SECRET_NAME = approval_state.SECRET_NAME
XARGS_FLAGS = frozenset({
    "-0", "-r", "-t", "-x", "-p", "-o", "--null", "--no-run-if-empty", "--verbose", "--exit", "--interactive",
    "--open-tty",
})
XARGS_VALUE_OPTIONS = frozenset({"-n", "-L", "-P", "-s", "-d", "-E", "-a", "-I", "-J"})
XARGS_ATTACHED_OPTIONS = ("-n", "-L", "-P", "-s", "-d", "-E", "-a", "-l", "-e")
XARGS_LONG_VALUES = ("--max-args", "--max-procs", "--delimiter", "--max-lines", "--arg-file", "--eof", "--max-chars")
XARGS_ARGUMENT = "$XARGS_ARGUMENT"
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


GIT_HARMLESS_CONFIG = frozenset({"credential.interactive", "credential.guiprompt"})
PATH_ALTERING_NAMES = re.compile(r"PATH|IFS|ENV|BASH_ENV|SHELLOPTS|BASHOPTS|PROMPT_COMMAND|PS4|LD_\w*|DYLD_\w*")
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


def _plain_assignment_segment(segment):
    """Whether a segment only assigns, or exports with `NAME=value` or `NAME`, variables whose names are neither secret
    names nor names that change how later commands are found or started."""
    words = list(segment.words)
    if words[:1] == ["export"]:
        words = words[1:]
        if not words or any(word.startswith("-") for word in words):
            return False
    elif not all(ASSIGNMENT.match(word) for word in words):
        return False
    names = [word.partition("=")[0] for word in words]
    return all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and not SECRET_NAME.search(name)
               and not PATH_ALTERING_NAMES.fullmatch(name) for name in names)


def _only_plain_environment_changes(segments):
    return all(_plain_assignment_segment(segment) for segment in segments if _changes_environment(segment))


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


def _environment_filter(text, names_only=False):
    """The read outcome of an `env` listing through filters, or None. With `names_only`, only a listing that prints
    nothing but variable names qualifies."""
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
    if names_only:
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
        if (bool(regex.search(name + "=" + value)) != invert and SECRET_NAME.search(name)
                and not _inert_variable(name, value)):
            return _sensitive(text)
    return _read()
