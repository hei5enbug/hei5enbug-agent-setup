"""Shell word expansion and variable value flow for the approval guard."""
import os
import re
from guard_shell import (
    ASSIGNMENT, COVERED, ParseError, SHELLS, SHELL_C_FLAG, SHELL_KEYWORDS, _shell_c, _substitution_end, _without_data,
    strip_prefix, tokenize,
)
from guard_paths import _expand_path_variables, _mktemp_directory, _tmpdir_default


ENVIRONMENT_CHANGERS = frozenset({
    "export", "declare", "typeset", "readonly", "local", "set", "unset", "source", ".", "eval", "exec", "alias",
    "function",
})
COVERED_WORD = re.compile(r"(?<![\w-])(?:" + "|".join(sorted(COVERED, key=len, reverse=True)) + r")(?![\w-])")
VARIABLE_REFERENCE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
VARIABLE_WRITERS = frozenset({"read", "mapfile", "readarray", "getopts", "let"})


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
FLOW_CLOSERS = {"then": "if", "else": "if", "elif": "if", "fi": "if", "do": "loop", "done": "loop", "esac": "case",
                "}": "brace"}
PIPE_OPERATORS = ("|", "|&")
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


def _narrow_effect(words, raw):
    """For a plain `export NAME[=value]...` or `unset NAME...` call: the literal names it writes and whether an argument
    of `unset` is not a literal name (so it may unset any variable). None for any other command."""
    if words[:1] not in (["export"], ["unset"]) or ":=" in raw or "((" in raw:
        return None
    names, dynamic = set(), False
    for word in words[1:]:
        name = word.partition("=")[0] if words[0] == "export" else word
        if words[0] == "unset" and word in ("-v", "-f"):
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            names.add(name)
        elif words[0] == "unset" and not word.startswith("-"):
            dynamic = True
        else:
            return None
    return names, dynamic


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
    """The names the body of the loop that segment `index` opens may write, whether anything in it may write any name, and
    whether it may unset any variable."""
    names, wide, depth, closed, dynamic = set(), False, 0, False, False
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
        narrow = _narrow_effect(words, " ".join(segment.raw)) if words else None
        if narrow is not None:
            names.update(narrow[0])
            dynamic = dynamic or narrow[1]
            continue
        effect = _wide_effect(words, " ".join(segment.raw)) if words else None
        if effect is not None:
            wide = True
            names.update(effect)
    return names, wide or not closed, dynamic


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

    def _tables(self):
        top = self.frames[-1] if self.frames else None
        tables = [self.state]
        if top is not None and top.get("phase") == "cond":
            tables += [top["entry"], *top["branches"]]
        return tables

    def _widen_unset(self, environment):
        """A command that may unset any variable: every resolved name may also be empty, as may the environment names
        the table reads when it holds no value."""
        for table in self._tables():
            for name, values in list(table.items()):
                if values is not None and not _positional(name):
                    table[name] = tuple(dict.fromkeys((*values, "")))
            for name in FLOW_ENVIRONMENT:
                if name not in table and environment.get(name):
                    table[name] = (environment[name], "")

    def _shift(self, words, before, after):
        """Follow a plain `shift [N]` that always runs, outside loops: the positional values move down by N. False when
        it cannot be followed: it may not run, runs in a pipe, a condition, or a loop, N is not a digit, or the values
        it would drop or the argument count are not known."""
        if (words[0] != "shift" or len(words) > 2 or len(words) == 2 and not re.fullmatch(r"[1-9]", words[1])
                or before in ("&&", "||", *PIPE_OPERATORS) or after in (*PIPE_OPERATORS, "&")
                or any(frame["kind"] == "loop" or frame.get("phase") == "cond" for frame in self.frames)):
            return False
        count = int(words[1]) if len(words) == 2 else 1
        old = [self.state.get(str(number)) for number in range(1, 10)]
        if old[count - 1] is None or any(not value for value in old[count - 1]):
            return False
        for number in range(1, 10):
            moved = old[number + count - 1] if number + count <= 9 else (old[8] if old[8] == ("",) else None)
            self.state[str(number)] = moved
        return True

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
                names, wide, dynamic = _loop_effects(segments, index)
                self._poison(names, everything=wide)
                if dynamic:
                    self._widen_unset(environment)
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
            if self._shift(words, before, after):
                return
            narrow = _narrow_effect(words, raw)
            if narrow is not None:
                self._poison(narrow[0])
                if narrow[1]:
                    self._widen_unset(environment)
                return
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
