"""Declared writes of a plugin skill: which entries a grant keeps, which values it accepts, and which write or MCP call
an entry matches.

The entry model and its placeholders live in approval_state_entries. This module classifies with the guard's own
classifiers (guard_dispatch.classify_text and guard_tools.classify_mcp) and never decides an approval or touches state:
`keep_verdict` and `grant_values` serve the grant, `match_command` and `match_mcp` serve a write or call that needs
approval. Grants are passed in as {skill: {placeholder name: values}}.
"""
import fnmatch
import itertools
import os
import re
import shlex
from dataclasses import dataclass
from typing import Mapping, Optional

import guard_dispatch
import guard_tools
from approval_state_entries import (
    Entry, GRANT_SAMPLE, PLACEHOLDER, SAMPLE_A, SAMPLE_B, Rule, json_object, listed_values, match_json, match_text,
    merge_captures, rules_of,
)
from guard_git import PUSH_PLAIN_FLAGS
from guard_shell import tokenize

MAX_SAMPLE_SETS = 32
DIGEST_KEY = re.compile(r"[a-z]+:[0-9a-f]{12}")
GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"})
GH_TARGET_OPTIONS = frozenset({"-R", "--repo", "--hostname"})
PLAIN_SHORT_FLAGS = re.compile(r"-[uvnq]+")
UNSAFE_WORD = re.compile(r"[$`]")
GRANT_VALUE = re.compile(r"[^\s$`]+")


@dataclass(frozen=True)
class Verdict:
    kept: bool
    reason: str = ""


@dataclass(frozen=True)
class GrantResult:
    accepted: Mapping
    refused: tuple


def _usable(outcome, destructive_allowed: bool) -> bool:
    """Whether the guard's classification is a non-critical write, or a destructive one the entry declares."""
    if outcome.critical or len(outcome.keys) != 1:
        return False
    return outcome.kind == "write" or (outcome.kind == "always" and destructive_allowed)


def _target(key: str) -> str:
    return key.partition("@")[2]


def _arguments(tokens: list) -> list:
    """Split words into ("pos", None, word) and ("opt", name, value or None); `--name=value` equals `--name value`."""
    items, index = [], 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("--") and "=" in token:
            name, _, value = token.partition("=")
            items.append(("opt", name, value))
        elif token.startswith("-") and len(token) > 1:
            follows = index + 1 < len(tokens) and not tokens[index + 1].startswith("-")
            items.append(("opt", token, tokens[index + 1] if follows else None))
            index += 1 if follows else 0
        else:
            items.append(("pos", None, token))
        index += 1
    return items


def _git_push(tokens: list) -> Optional[list]:
    """The words after `push` when the words are a `git push`, else None."""
    if not tokens or os.path.basename(tokens[0]) != "git":
        return None
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in GIT_VALUE_OPTIONS else 1
    return tokens[index + 1:] if index < len(tokens) and tokens[index] == "push" else None


def _push_problem(tokens: list, rules: Mapping) -> Optional[str]:
    """Why a push example is ignored: it must name its remote and every refspec, with no force or deletion form."""
    after = _git_push(tokens)
    if after is None:
        return None
    options = [word for word in after if word.startswith("-")]
    operands = [word for word in after if not word.startswith("-")]
    if any(word not in PUSH_PLAIN_FLAGS and not PLAIN_SHORT_FLAGS.fullmatch(word) for word in options):
        return "a push option other than a plain flag"
    if len(operands) < 2:
        return "a push that does not name its remote and a refspec"
    if any(word.startswith(("+", ":")) for word in operands[1:]):
        return "a refspec with a force or deletion form"
    if any(not rules[name].restricted for name in _names(operands[0])):
        return "a push remote that is not listed or taken from the grant"
    return None


def _names(text: str) -> list:
    return [match.group(1) for match in PLACEHOLDER.finditer(text)]


def _gh_problem(tokens: list, rules: Mapping) -> Optional[str]:
    if not tokens or os.path.basename(tokens[0]) != "gh":
        return None
    for kind, name, value in _arguments(tokens[1:]):
        if kind == "opt" and name in GH_TARGET_OPTIONS and value is not None:
            if any(not rules[placeholder].restricted for placeholder in _names(value)):
                return f"a {name} value that is not listed or taken from the grant"
    return None


def _witness(rule: Rule, sample: str) -> str:
    """A value that every glob of the rule accepts, or ValueError when the first glob's witness fails another one."""
    text = re.sub(r"\[!?([^\]])[^\]]*\]", r"\1", rule.globs[0].replace("*", sample).replace("?", "a"))
    if any(not fnmatch.fnmatchcase(text, glob) for glob in rule.globs):
        raise ValueError("a glob has no value to check")
    return text


def _sample_values(rule: Rule, never: tuple, sample: str) -> list:
    values = listed_values(rule, set().union({GRANT_SAMPLE}, *rule.lists), never)
    if values is not None:
        return sorted(values)
    return [_witness(rule, sample)] if rule.globs else [sample]


def _fill_text(text: str, values: Mapping) -> str:
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], text)


def _fill_value(value, values: Mapping):
    if isinstance(value, str):
        return _fill_text(value, values)
    if isinstance(value, Mapping):
        return {key: _fill_value(item, values) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_fill_value(item, values) for item in value]
    return value


def _sample_sets(entry: Entry, rules: Mapping, sample: str = SAMPLE_A) -> list:
    names = sorted(rules)
    choices = [_sample_values(rules[name], tuple(entry.never.get(name, ())), sample) for name in names]
    if any(not values for values in choices):
        raise ValueError("a placeholder accepts no value")
    sets = [dict(zip(names, combination)) for combination in itertools.product(*choices)]
    if len(sets) > MAX_SAMPLE_SETS:
        raise ValueError("too many value combinations to check")
    return sets


def _classify_filled(entry: Entry, values: Mapping, cwd: str):
    if entry.is_mcp:
        return guard_tools.classify_mcp(entry.tool, _fill_value(dict(entry.arguments), values), cwd)
    return guard_dispatch.classify_text(_fill_text(entry.command, values), cwd)


def _command_shape_problem(entry: Entry, values: Mapping, cwd: str) -> Optional[str]:
    text = _fill_text(entry.command, values)
    try:
        words = shlex.split(text)
        segments = tokenize(text)
    except ValueError:
        return "an example the guard cannot read"
    if len(segments) != 1 or segments[0].redirects or segments[0].words != words:
        return "an example that is not one simple command"
    return None


def _variation_problem(entry: Entry, rules: Mapping, base: Mapping, cwd: str) -> Optional[str]:
    """Whether an open or glob placeholder changes the target part of the key."""
    reference = _classify_filled(entry, base, cwd)
    if DIGEST_KEY.fullmatch(reference.keys[0]):
        return None
    for name, rule in rules.items():
        if rule.restricted:
            continue
        varied = {**base, name: _sample_values(rule, (), SAMPLE_B)[0]}
        if _target(_classify_filled(entry, varied, cwd).keys[0]) != _target(reference.keys[0]):
            return f"placeholder {name} reaches the target of the key and is not listed or taken from the grant"
    return None


def keep_verdict(entry: Entry, cwd: Optional[str] = None) -> Verdict:
    """Whether a grant keeps the entry: the guard classifies it as a write, or as destructive with `destructive` set;
    every placeholder that reaches the target of its key lists its values or takes them from the grant; a push names
    its remote and refspecs without a force or deletion form."""
    cwd = cwd or os.getcwd()
    try:
        rules = rules_of(entry)
        sets = _sample_sets(entry, rules)
        if not entry.is_mcp:
            problem = _static_problem(entry, rules, sets[0], cwd)
            if problem:
                return Verdict(False, problem)
        for values in sets:
            outcome = _classify_filled(entry, values, cwd)
            if not _usable(outcome, entry.destructive):
                return Verdict(False, f"the guard classifies it as {outcome.kind}"
                               + (" (critical)" if outcome.critical else ""))
        if not entry.is_mcp:
            problem = _variation_problem(entry, rules, _sample_sets(entry, rules)[0], cwd)
            return Verdict(problem is None, problem or "")
    except ValueError as error:
        return Verdict(False, str(error))
    return Verdict(True)


def _static_problem(entry: Entry, rules: Mapping, values: Mapping, cwd: str) -> Optional[str]:
    problem = _command_shape_problem(entry, values, cwd)
    if problem:
        return problem
    tokens = shlex.split(entry.command)
    return _push_problem(tokens, rules) or _gh_problem(tokens, rules)


def grant_values(entries: list, requested: Mapping) -> GrantResult:
    """Split the values a grant passes for `@grant` placeholders into accepted ones and refused ones. A value on the
    never-accepted list of an entry that takes that name from the grant, an unusable value, and a name no entry takes
    from the grant are refused with a reason."""
    takers: dict = {}
    for entry in entries:
        for name, rule in rules_of(entry).items():
            if rule.grant:
                takers.setdefault(name, []).append(entry)
    accepted, refused = {}, []
    for name, values in requested.items():
        for value in values:
            reason = _grant_refusal(name, value, takers.get(name, []))
            if reason:
                refused.append((name, value, reason))
            else:
                accepted[name] = tuple(dict.fromkeys((*accepted.get(name, ()), value)))
    return GrantResult(accepted, tuple(refused))


def _grant_refusal(name: str, value: str, takers: list) -> Optional[str]:
    if not takers:
        return "no kept entry takes this name from the grant"
    if not isinstance(value, str) or not GRANT_VALUE.fullmatch(value):
        return "the value is empty or holds whitespace or a shell expansion"
    if any(value in entry.never.get(name, ()) for entry in takers):
        return "the value is on the never-accepted list"
    return None


def merge_grants(held: Mapping, added: Mapping) -> dict:
    """The grants of one skill after a later grant adds values to the ones already held."""
    names = {*held, *added}
    return {name: tuple(dict.fromkeys((*held.get(name, ()), *added.get(name, ())))) for name in names}


def _simple_words(text: str) -> Optional[list]:
    text = text.strip()
    if "\n" in text:
        return None
    try:
        segments = tokenize(text)
    except Exception:
        return None
    if len(segments) != 1 or segments[0].redirects:
        return None
    words = list(segments[0].words)
    return None if not words or any(UNSAFE_WORD.search(word) for word in words) else words


def _match_option_value(example: Optional[str], actual: Optional[str], context: tuple) -> Optional[dict]:
    if example is None or actual is None:
        return {} if example is None and actual is None else None
    body = json_object(example)
    if body is not None:
        parsed = json_object(actual, strict=True)
        return None if parsed is None else match_json(body, parsed, *context)
    return match_text(example, actual, *context)


EXTRA_OPTION_LOADS = re.compile(r"^-*(?:[Kf:o]|.*(?:config|file|input|kube|url|next|request|output).*)$", re.IGNORECASE)


def _loads_more(example: list, actual: list) -> bool:
    """Whether the write adds an option the example lacks that can change its operation or target from outside the
    command line, such as a config or input file, another URL, or a value read from a file."""
    named = {name for kind, name, _ in example if kind == "opt"}
    return any(kind == "opt" and name not in named and (EXTRA_OPTION_LOADS.match(name) or str(value or "").startswith(("@", "file:")))
               for kind, name, value in actual)


def _match_shape(example: list, actual: list, context: tuple) -> Optional[tuple]:
    """The captured values and the example filled from the write, matched by positional index and by option name. An
    extra option that loads settings or input from elsewhere never matches."""
    if _loads_more(example, actual):
        return None
    positionals = [item[2] for item in actual if item[0] == "pos"]
    if len([item for item in example if item[0] == "pos"]) != len(positionals):
        return None
    captured: Optional[dict] = {}
    filled, seen = [], {}
    for kind, name, value in example:
        if kind == "pos":
            index = sum(1 for item in filled if item[0] == "pos")
            captured = merge_captures(captured, match_text(value, positionals[index], *context))
            filled.append(("pos", None, positionals[index]))
            continue
        carried = [item[2] for item in actual if item[0] == "opt" and item[1] == name]
        wanted = len([item for item in example if item[0] == "opt" and item[1] == name])
        if len(carried) != wanted:
            return None
        position = seen[name] = seen.get(name, -1) + 1
        captured = merge_captures(captured, _match_option_value(value, carried[position], context))
        filled.append(("opt", name, carried[position]))
    return None if captured is None else (captured, filled)


def _filled_words(filled: list) -> list:
    return [word for kind, name, value in filled for word in ((value,) if kind == "pos" else
            (name,) if value is None else (name, value))]


def _push_value_problem(words: list, captured: Mapping) -> bool:
    return _git_push(words) is not None and any(
        ":" in value or value.startswith("+") for value in captured.values())


def _command_match(entry: Entry, words: list, outcome, grants: Mapping, cwd: str) -> bool:
    rules = rules_of(entry)
    context = (rules, grants.get(entry.skill, {}), entry.never)
    example = shlex.split(entry.command)
    if DIGEST_KEY.fullmatch(outcome.keys[0]):
        if len(example) != len(words):
            return False
        captured: Optional[dict] = {}
        for pattern, word in zip(example, words):
            captured = merge_captures(captured, match_text(pattern, word, *context))
        return captured is not None and not _push_value_problem(words, captured)
    matched = _match_shape(_arguments(example), _arguments(words), context)
    if matched is None or _push_value_problem(words, matched[0]):
        return False
    again = guard_dispatch.classify_text(shlex.join(_filled_words(matched[1])), cwd)
    return (again.kind, again.keys) == (outcome.kind, outcome.keys)


def match_command(text: str, entries: list, grants: Mapping, cwd: Optional[str] = None) -> Optional[Entry]:
    """The first kept command entry the write matches, else None. The write must be one simple command that the guard
    classifies as a non-critical write, or as destructive for an entry with `destructive`."""
    cwd = cwd or os.getcwd()
    words = _simple_words(text) if isinstance(text, str) else None
    if words is None:
        return None
    outcome = guard_dispatch.classify_text(text, cwd)
    if not _usable(outcome, True):
        return None
    for entry in entries:
        if entry.is_mcp or (outcome.kind == "always" and not entry.destructive):
            continue
        if _command_match(entry, words, outcome, grants, cwd):
            return entry
    return None


def match_mcp(tool: str, tool_input, entries: list, grants: Mapping, cwd: Optional[str] = None) -> Optional[Entry]:
    """The first kept MCP entry that names the tool and whose listed argument values the call carries."""
    if not isinstance(tool_input, Mapping):
        return None
    outcome = guard_tools.classify_mcp(tool, dict(tool_input), cwd or os.getcwd())
    if not _usable(outcome, True):
        return None
    for entry in entries:
        if not entry.is_mcp or entry.tool != tool or (outcome.kind == "always" and not entry.destructive):
            continue
        rules = rules_of(entry)
        context = (rules, grants.get(entry.skill, {}), entry.never)
        captured: Optional[dict] = {}
        for name, example in entry.arguments.items():
            captured = merge_captures(
                captured, match_json(example, tool_input[name], *context) if name in tool_input else None)
        if captured is not None:
            return entry
    return None
