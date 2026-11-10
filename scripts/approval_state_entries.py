"""Declared-write entries of a plugin skill: placeholders, the values each accepts, and token and JSON matching.

An entry is a command example or an MCP tool entry. Placeholders are `<name>` (any value), `<name:a|b>` (listed values),
`<name:glob>` (values that match the glob), and `<name:@grant>` (values a grant passed). Nothing here reads a file or
the session state; the caller passes the grants it holds.
"""
import fnmatch
import json
import re
from dataclasses import dataclass, field
from typing import Collection, Mapping, Optional

PLACEHOLDER = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)(?::([^<>]*))?>")
GRANT = "@grant"
GLOB_CHARACTERS = frozenset("*?[")
SAMPLE_A = "demo-a"
SAMPLE_B = "demo-b"
GRANT_SAMPLE = "demo"


@dataclass(frozen=True)
class Entry:
    """One declared write of a skill: a command example, or an MCP tool with the argument values a call must carry."""
    skill: str
    command: Optional[str] = None
    tool: Optional[str] = None
    arguments: Mapping[str, object] = field(default_factory=dict)
    never: Mapping[str, tuple] = field(default_factory=dict)
    destructive: bool = False

    @property
    def is_mcp(self) -> bool:
        return self.tool is not None


@dataclass(frozen=True)
class Rule:
    """What one placeholder name accepts: every listed set, every glob, and, with `grant`, the granted values."""
    lists: tuple = ()
    globs: tuple = ()
    grant: bool = False

    @property
    def restricted(self) -> bool:
        """Whether the accepted values are listed or come from the grant, which a target part of a key requires."""
        return bool(self.lists) or self.grant


def entry_strings(entry: Entry) -> list:
    """Every text of the entry that may hold a placeholder."""
    if not entry.is_mcp:
        return [entry.command or ""]
    found = []

    def walk(value):
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, Mapping):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
    walk(dict(entry.arguments))
    return found


def _spec_rule(name: str, spec: str, rule: Rule) -> Rule:
    if spec == GRANT:
        return Rule(rule.lists, rule.globs, True)
    if not spec or spec.startswith("@"):
        raise ValueError(f"placeholder {name} has an empty or unknown accepted-value form")
    if GLOB_CHARACTERS & set(spec):
        if "|" in spec:
            raise ValueError(f"placeholder {name} mixes a list with a glob")
        return Rule(rule.lists, (*rule.globs, spec), rule.grant)
    values = spec.split("|")
    if not all(values):
        raise ValueError(f"placeholder {name} lists an empty value")
    return Rule((*rule.lists, frozenset(values)), rule.globs, rule.grant)


def rules_of(entry: Entry) -> dict:
    """The rule of every placeholder name in the entry; raises ValueError when a placeholder is malformed."""
    rules: dict = {}
    for text in entry_strings(entry):
        for match in PLACEHOLDER.finditer(text):
            name, spec = match.groups()
            rule = rules.get(name, Rule())
            rules[name] = rule if spec is None else _spec_rule(name, spec, rule)
    return rules


def listed_values(rule: Rule, granted: Collection, never: Collection) -> Optional[frozenset]:
    """The values a restricted rule names, or None when the rule is open or glob-only."""
    if not rule.restricted:
        return None
    values = set(granted) if rule.grant else None
    for listed in rule.lists:
        values = set(listed) if values is None else values & listed
    return frozenset(values - set(never))


def accepts(rule: Rule, value: str, granted: Collection, never: Collection) -> bool:
    if not value or value in never:
        return False
    if any(value not in listed for listed in rule.lists):
        return False
    if any(not fnmatch.fnmatchcase(value, glob) for glob in rule.globs):
        return False
    return not rule.grant or value in granted


def _pattern(rule: Rule, granted: Collection, never: Collection) -> str:
    values = listed_values(rule, granted, never)
    if values is None:
        return ".+?"
    if not values:
        return "(?!)"
    return "(?:" + "|".join(re.escape(value) for value in sorted(values, key=len, reverse=True)) + ")"


def merge_captures(first: Optional[dict], second: Optional[dict]) -> Optional[dict]:
    """Both captures joined, or None when either is None or one name has two values."""
    if first is None or second is None:
        return None
    if any(second.get(name, value) != value for name, value in first.items()):
        return None
    return {**first, **second}


def match_text(example: str, actual: str, rules: Mapping, grants: Mapping, never: Mapping) -> Optional[dict]:
    """The values `actual` gives the placeholders of `example`, or None when a literal differs or a value is not
    accepted."""
    matches = list(PLACEHOLDER.finditer(example))
    if not matches:
        return {} if example == actual else None
    pattern, position, groups = "", 0, []
    for index, match in enumerate(matches):
        name = match.group(1)
        pattern += re.escape(example[position:match.start()])
        pattern += f"(?P<g{index}>{_pattern(rules[name], grants.get(name, ()), never.get(name, ()))})"
        groups.append((f"g{index}", name))
        position = match.end()
    found = re.fullmatch(pattern + re.escape(example[position:]), actual, re.DOTALL)
    if found is None:
        return None
    captured: dict = {}
    for group, name in groups:
        value = found.group(group)
        if captured.setdefault(name, value) != value:
            return None
        if not accepts(rules[name], value, grants.get(name, ()), never.get(name, ())):
            return None
    return captured


def _no_duplicate_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def json_object(text: str, strict: bool = False) -> Optional[dict]:
    """The JSON object a text holds, or None for anything else; `strict` also refuses a repeated key."""
    if not isinstance(text, str) or not text.lstrip().startswith("{"):
        return None
    try:
        value = json.loads(text, object_pairs_hook=_no_duplicate_keys if strict else None)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def match_json(example, actual, rules: Mapping, grants: Mapping, never: Mapping) -> Optional[dict]:
    """Match a JSON value against an example with exactly the same keys and lengths at every depth. A string of the
    example takes placeholders; every other value must be equal and of the same type."""
    if isinstance(example, Mapping):
        if not isinstance(actual, Mapping) or set(example) != set(actual):
            return None
        captured: Optional[dict] = {}
        for key, value in example.items():
            captured = merge_captures(captured, match_json(value, actual[key], rules, grants, never))
        return captured
    if isinstance(example, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(example) != len(actual):
            return None
        captured = {}
        for left, right in zip(example, actual):
            captured = merge_captures(captured, match_json(left, right, rules, grants, never))
        return captured
    if isinstance(example, str):
        return match_text(example, actual, rules, grants, never) if isinstance(actual, str) else None
    return {} if type(example) is type(actual) and example == actual else None
