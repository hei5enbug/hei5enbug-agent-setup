"""Rule groups of the session instructions: the parts of a Markdown file, removal of named parts from an export, the
group map with bytes and mapped checks, and the decision that removes a group only when its checks keep passing.

A part is one bullet or one paragraph. A bullet runs from its `- ` line to the next blank line, bullet, or heading; a
paragraph is a run of lines between blank lines and headings; a fenced block is one paragraph. A section is a heading
line with everything below it up to the next heading of the same or a higher level."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SESSION_FILES = (
    "instructions/session/core.md", "instructions/session/common.md",
    "instructions/session/claude-code.md", "instructions/session/codex.md",
)
HEADING = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*\s*$")
BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
FENCE = re.compile(r"^\s*(```|~~~)")
MIN_LEAD_WORDS = 4
MAX_LEAD_WORDS = 14
MAX_REMOVAL_RUNS = 2
MAX_GROUPS = 10
MAX_TASKS = 3
HOSTS = ("claude", "codex")

REMOVED = "removed"
NEEDED = "kept as needed"
UNMEASURED = "kept as unmeasured"
NOT_YET = "not yet measured"
VERDICTS = (REMOVED, NEEDED, UNMEASURED, NOT_YET)


class RemovalError(ValueError):
    pass


@dataclass(frozen=True)
class Part:
    kind: str
    start: int
    end: int
    section: str
    text: str
    lead: str

    @property
    def bytes(self) -> int:
        return len(self.text.encode("utf-8"))


@dataclass(frozen=True)
class Section:
    title: str
    level: int
    start: int
    end: int


def words(text: str) -> str:
    return " ".join(text.split())


def begins(lead: str, prefix: str) -> bool:
    """Whether a part's text begins with the given first words."""
    return bool(prefix) and lead.startswith(prefix)


def lead_of(kind: str, lines: Sequence[str]) -> str:
    plain = [re.sub(r"^\s*>\s?", "", line) for line in lines]
    joined = words(" ".join(plain))
    return BULLET.sub("", joined, count=1) if kind == "bullet" else joined


def parse(text: str) -> tuple[list[Part], list[Section], list[str]]:
    """The parts, the sections, and the lines of a Markdown text."""
    lines = text.split("\n")
    parts: list[Part] = []
    headings: list[tuple[int, int, str]] = []
    stack: list[tuple[int, str]] = []
    block: dict[str, Any] | None = None
    fenced = False

    def close(end: int) -> None:
        nonlocal block
        if block is not None:
            body = lines[block["start"]:end]
            parts.append(Part(block["kind"], block["start"], end, " > ".join(title for _, title in stack), "\n".join(body),
                              lead_of(block["kind"], body)))
            block = None

    for index, line in enumerate(lines):
        if fenced:
            fenced = not FENCE.match(line)
            continue
        heading = HEADING.match(line)
        if heading:
            close(index)
            level = len(heading.group(1))
            stack = [item for item in stack if item[0] < level] + [(level, heading.group(2))]
            headings.append((index, level, heading.group(2)))
        elif not line.strip():
            close(index)
        elif BULLET.match(line):
            close(index)
            block = {"kind": "bullet", "start": index}
        elif FENCE.match(line):
            close(index)
            block = {"kind": "paragraph", "start": index}
            fenced = True
        elif block is None:
            block = {"kind": "paragraph", "start": index}
    close(len(lines))
    sections = []
    for position, (index, level, title) in enumerate(headings):
        end = next((later for later, deeper, _ in headings[position + 1:] if deeper <= level), len(lines))
        sections.append(Section(title, level, index, end))
    return parts, sections, lines


def shortest_leads(parts: Sequence[Part]) -> list[str]:
    """For each part, its shortest word prefix of at least four words that no other part of the file starts with."""
    leads = []
    for part in parts:
        tokens = part.lead.split(" ")
        chosen = part.lead
        for count in range(min(MIN_LEAD_WORDS, len(tokens)), min(MAX_LEAD_WORDS, len(tokens)) + 1):
            prefix = " ".join(tokens[:count])
            if sum(1 for other in parts if begins(other.lead, prefix)) == 1:
                chosen = prefix
                break
        leads.append(chosen)
    return leads


def matching_ranges(text: str, entry: Mapping[str, Any]) -> list[tuple[int, int]]:
    """Line ranges of the parts that begin with `starts_with`, or of the sections whose heading is `heading`."""
    parts, sections, _ = parse(text)
    if "starts_with" in entry:
        prefix = words(str(entry["starts_with"]))
        return [(part.start, part.end) for part in parts if begins(part.lead, prefix)]
    wanted = words(str(entry["heading"]))
    shown = HEADING.match(wanted)
    level, title = (len(shown.group(1)), words(shown.group(2))) if shown else (None, wanted)
    return [(item.start, item.end) for item in sections if item.title == title and level in (None, item.level)]


def describe(entry: Mapping[str, Any]) -> str:
    return f"{entry['file']}: " + (f"starts with \"{entry['starts_with']}\"" if "starts_with" in entry else f"heading \"{entry['heading']}\"")


def validate_entries(entries: Any) -> list[dict[str, str]]:
    """The `remove` entries of a variant, each a file with `starts_with` or `heading`; anything else is an error."""
    if not isinstance(entries, list) or not entries:
        raise RemovalError("remove must be a non-empty list of entries")
    checked, seen = [], set()
    for entry in entries:
        keys = set(entry) if isinstance(entry, dict) else set()
        file = entry.get("file") if isinstance(entry, dict) else None
        valid = (isinstance(file, str) and file and not Path(file).is_absolute() and ".." not in Path(file).parts
                 and keys in ({"file", "starts_with"}, {"file", "heading"}) and all(isinstance(v, str) and v.strip() for v in entry.values()))
        if not valid:
            raise RemovalError(f"a remove entry needs a relative file and exactly one of starts_with or heading, as strings: {entry!r}")
        normal = {key: words(value) for key, value in entry.items()}
        if (marker := tuple(sorted(normal.items()))) in seen:
            raise RemovalError(f"remove names {describe(normal)} twice")
        seen.add(marker)
        checked.append(normal)
    return checked


def remove_ranges(text: str, ranges: Iterable[tuple[int, int]]) -> str:
    """The text without the given line ranges. A removal between two blank lines, or after the start of the file, takes one of
    them with it, so it leaves no double blank line; the rest of the text stays byte for byte."""
    lines = text.split("\n")
    gone: set[int] = set()
    for start, end in ranges:
        gone.update(range(start, end))
        if end < len(lines) and not lines[end].strip() and (start == 0 or not lines[start - 1].strip()):
            gone.add(end)
    return "\n".join(line for number, line in enumerate(lines) if number not in gone)


def apply_removals(root: Path, entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Remove each entry's part or section from the plugin files under `root`. An entry that matches nothing, or more than one
    part or section, or a file that is missing, raises RemovalError before any file changes. Returns what was removed."""
    by_file: dict[str, list[Mapping[str, Any]]] = {}
    for entry in entries:
        by_file.setdefault(str(entry["file"]), []).append(entry)
    results: list[dict[str, Any]] = []
    rewritten: dict[Path, str] = {}
    for file, group in by_file.items():
        path = root / file
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise RemovalError(f"remove: cannot read {file}: {error}") from error
        ranges: list[tuple[int, int]] = []
        for entry in group:
            found = matching_ranges(text, entry)
            if len(found) != 1:
                raise RemovalError(f"remove: {describe(entry)} matches {len(found)} parts, not exactly one")
            ranges += found
            start, end = found[0]
            removed = "\n".join(text.split("\n")[start:end])
            results.append({**entry, "lines": end - start, "bytes": len(removed.encode("utf-8"))})
        rewritten[path] = remove_ranges(text, ranges)
    for path, text in rewritten.items():
        path.write_text(text, encoding="utf-8")
    return results


def read_groups(read: Callable[[str], str | None], files: Sequence[str] = SESSION_FILES) -> list[dict[str, Any]]:
    """One group per bullet or paragraph of each file: id, file, section, kind, first words, its own bytes, and its whole
    text as `lead`. A file `read` cannot return is an error, never an empty file."""
    groups: list[dict[str, Any]] = []
    for file in files:
        text = read(file)
        if text is None:
            raise RemovalError(f"cannot read {file}")
        parts = parse(text)[0]
        for part, lead in zip(parts, shortest_leads(parts)):
            groups.append({"id": f"{file}::{lead}", "file": file, "section": part.section, "kind": part.kind, "starts_with": lead,
                           "bytes": part.bytes, "members": [f"{file}::{lead}"], "lead": part.lead})
    return groups


def locate_group(groups: Sequence[Mapping[str, Any]], file: str, starts_with: str) -> list[str]:
    """Ids of the groups of `file` that begin with `starts_with`; a rule names one rule, so one id is expected."""
    prefix = words(starts_with)
    return [group["id"] for group in groups if group["file"] == file and begins(group["lead"], prefix)]


def tree_reader(root: Path) -> Callable[[str], str | None]:
    """A reader of the files under `root`; a file that cannot be read gives None."""
    def read(file: str) -> str | None:
        try:
            return (root / file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    return read


def revision_reader(repo_root: Path, ref: str) -> Callable[[str], str | None]:
    """A reader of the files of a git revision; a file the revision lacks gives None."""
    def read(file: str) -> str | None:
        done = subprocess.run(["git", "show", f"{ref}:{file}"], cwd=repo_root, capture_output=True, check=False)
        return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None
    return read


def load_tasks(tasks_root: Path) -> list[dict[str, Any]]:
    """Every task file of a folder, in task order."""
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(tasks_root.glob("T*.json"))]


def task_rules(tasks: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Every `rules` entry of the given tasks as {task, check, file, starts_with}."""
    return [{"task": str(task["id"]), "check": str(rule["check"]), "file": str(rule["file"]), "starts_with": str(rule["starts_with"])}
            for task in tasks for rule in task.get("rules") or []]


def rules_problems(
    tasks: Iterable[Mapping[str, Any]], current: Callable[[str], str | None], baseline: Callable[[str], str | None] | None = None,
    removed: Iterable[str] = (),
) -> list[str]:
    """Problems of the tasks' `rules` lists: a check that is not a required check of its task, a required check of a task that
    has a `rules` list but no rule, and a rule that does not resolve to exactly one part in the baseline revision, or in the
    current one unless the record marks its group removed."""
    problems: list[str] = []
    gone = set(removed)
    for task in tasks:
        if "rules" not in task:
            continue
        required = {check["id"] for check in task["checks"] if check.get("required")}
        named = {rule["check"] for rule in task["rules"]}
        problems += [f"{task['id']}: rule names {check}, which is not a required check" for check in sorted(named - required)]
        problems += [f"{task['id']}: required check {check} has no rule" for check in sorted(required - named)]
        for rule in task["rules"]:
            label = f"{task['id']}: {rule['check']} -> {rule['file']} \"{rule['starts_with']}\""
            for revision, read in (("baseline", baseline), ("current", current)):
                if read is None:
                    continue
                matched = matching_ranges(read(rule["file"]) or "", {"starts_with": rule["starts_with"]})
                if len(matched) == 1 or (revision == "current" and not matched and removed_rule(rule, baseline, gone)):
                    continue
                problems.append(f"{label} matches {len(matched)} parts in the {revision} revision")
    return problems


def removed_rule(rule: Mapping[str, str], baseline: Callable[[str], str | None] | None, gone: set[str]) -> bool:
    """Whether the rule's group is one the record marks removed, by the group id the baseline text gives it."""
    if baseline is None:
        return False
    text = baseline(rule["file"]) or ""
    parts = parse(text)[0]
    prefix = words(rule["starts_with"])
    leads = shortest_leads(parts)
    return any(f"{rule['file']}::{lead}" in gone for part, lead in zip(parts, leads) if begins(part.lead, prefix))


def group_checks(groups: Sequence[Mapping[str, Any]], rules: Sequence[Mapping[str, str]]) -> dict[str, list[str]]:
    """The checks mapped to each group id, as `<task>/<check>` in task and check order. A rule that matches no group or
    more than one raises RemovalError."""
    mapped: dict[str, list[str]] = {group["id"]: [] for group in groups}
    for rule in rules:
        ids = locate_group(groups, rule["file"], rule["starts_with"])
        if len(ids) != 1:
            raise RemovalError(f"{rule['task']}: {rule['check']} names {rule['file']} \"{rule['starts_with']}\", which matches {len(ids)} groups")
        name = f"{rule['task']}/{rule['check']}"
        if name not in mapped[ids[0]]:
            mapped[ids[0]].append(name)
    return mapped


def section_groups(
    read: Callable[[str], str | None], groups: Sequence[Mapping[str, Any]], mapped: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    """A heading's whole section is one more group only when it holds at least two parts and every one of them is mapped."""
    found: list[dict[str, Any]] = []
    for file in sorted({group["file"] for group in groups}):
        parts, sections, lines = parse(read(file) or "")
        ids = {part.start: group["id"] for part, group in zip(parts, [g for g in groups if g["file"] == file])}
        for section in sections:
            inside = [ids[part.start] for part in parts if section.start <= part.start and part.end <= section.end]
            if len(inside) < 2 or not all(mapped.get(item) for item in inside):
                continue
            body = "\n".join(lines[section.start:section.end]).rstrip("\n")
            found.append({"id": f"{file}::# {section.title}", "file": file, "section": section.title, "kind": "section",
                          "starts_with": None, "heading": "#" * section.level + " " + section.title,
                          "bytes": len(body.encode("utf-8")), "members": inside})
    return found


def group_map(
    read: Callable[[str], str | None], rules: Sequence[Mapping[str, str]], files: Sequence[str] = SESSION_FILES,
) -> list[dict[str, Any]]:
    """Every bullet and paragraph of the files as a group with its bytes and mapped checks, then the sections whose parts are
    all mapped. A group with no mapped check has status `unmeasured`; the others `pending` until their stock run is recorded."""
    groups = read_groups(read, files)
    mapped = group_checks(groups, rules)
    groups = groups + section_groups(read, groups, mapped)
    result = []
    for group in groups:
        checks = mapped.get(group["id"]) or sorted({name for member in group["members"] for name in mapped.get(member, [])})
        result.append({key: value for key, value in group.items() if key != "lead"} | {
            "checks": checks, "status": "pending" if checks else "unmeasured"})
    return result


def task_count(checks: Iterable[str]) -> int:
    return len({check.split("/", 1)[0] for check in checks})


def host_values(table: Any, host: str) -> Mapping[str, Any]:
    return table.get(host) if isinstance(table, Mapping) and isinstance(table.get(host), Mapping) else {}


def decide_group(group: Mapping[str, Any], slots_left: int) -> tuple[str, str, bool]:
    """(verdict, step, whether the group used one of the removal slots) of one group, by the rule of the issue."""
    checks = list(group.get("checks") or [])
    if not checks:
        return UNMEASURED, "no check maps to the group", False
    if task_count(checks) > MAX_TASKS:
        return NOT_YET, f"its checks lie in {task_count(checks)} tasks, more than {MAX_TASKS}", False
    stock = {host: host_values(group.get("stock"), host) for host in HOSTS}
    results = [stock[host].get(check) for host in HOSTS for check in checks]
    if any(value is False for value in results):
        return NEEDED, "a mapped check fails in the stock run", False
    if any(value is not True for value in results):
        return NOT_YET, "a mapped check has no stock result on one host", False
    if group.get("relied_on"):
        return NEEDED, "another rule, hook, or script relies on it", False
    if slots_left <= 0:
        return NOT_YET, f"more than {MAX_GROUPS} candidates came before it", False
    runs = group.get("removal") or {}
    if any(len(runs.get(host) or []) < MAX_REMOVAL_RUNS for host in HOSTS):
        return NOT_YET, f"fewer than {MAX_REMOVAL_RUNS} removal runs on a host", True
    passed = all(run.get(check) is True for host in HOSTS for run in runs[host] for check in checks)
    if not passed:
        return NEEDED, "a mapped check fails in a removal run", True
    if group.get("host_comparison") is None:
        return NOT_YET, "the host comparison is not decided", True
    if group["host_comparison"] is not True:
        return NEEDED, "the host comparison does not hold without it", True
    return REMOVED, "every mapped check passes in both removal runs on both hosts and the host comparison holds", True


def decide(groups: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One verdict per group, largest group first, at most ten groups taking removal runs; a group that overlaps a removed
    group is not yet measured. Input order breaks ties in bytes. Returns the groups in that order with `verdict` and `step`."""
    order = sorted(range(len(groups)), key=lambda index: (-int(groups[index].get("bytes") or 0), index))
    slots, removed_members, decided = MAX_GROUPS, set(), {}
    for index in order:
        group = groups[index]
        members = set(group.get("members") or [group.get("id")])
        if members & removed_members:
            verdict, step, used = NOT_YET, "overlaps a group already removed", False
        else:
            verdict, step, used = decide_group(group, slots)
        slots -= 1 if used else 0
        removed_members |= members if verdict == REMOVED else set()
        decided[index] = {**group, "verdict": verdict, "step": step}
    return [decided[index] for index in order]


def section_problems(section: Any, tasks: Iterable[str] = ()) -> list[str]:
    """Problems of a record's `rule_groups` section: each group needs its id, file, bytes, checks, stock result per host,
    removal runs, one of the four verdicts, and, for a removed group, the references searched and no reliance."""
    if not isinstance(section, Mapping) or not isinstance(section.get("groups"), list) or not section["groups"]:
        return ["rule_groups needs a non-empty groups list"]
    problems = [f"rule_groups lacks {key}" for key in ("stock", "plugin") if not isinstance(section.get(key), str)]
    seen: set[str] = set()
    for index, group in enumerate(section["groups"]):
        name = f"rule_groups.groups[{index}]"
        if not isinstance(group, Mapping):
            problems.append(f"{name} is not an object")
            continue
        problems += [f"{name} lacks {key}" for key in ("id", "file", "bytes", "checks", "stock", "removal_runs", "verdict") if key not in group]
        if group.get("id") in seen:
            problems.append(f"{name} repeats an id")
        seen.add(str(group.get("id")))
        if group.get("verdict") not in VERDICTS:
            problems.append(f"{name} verdict is not one of {', '.join(VERDICTS)}")
        if not (isinstance(group.get("bytes"), int) and not isinstance(group.get("bytes"), bool) and group["bytes"] > 0):
            problems.append(f"{name} bytes is not a positive integer")
        if not (isinstance(group.get("checks"), list) and all(isinstance(item, str) for item in group.get("checks") or [])):
            problems.append(f"{name} checks is not a list of names")
        elif tasks and any(check.split("/", 1)[0] not in set(tasks) for check in group["checks"]):
            problems.append(f"{name} names a check of a task that is not a case")
        if group.get("verdict") == UNMEASURED and group.get("checks"):
            problems.append(f"{name} is kept as unmeasured but has mapped checks")
        if group.get("verdict") == REMOVED:
            references = group.get("references") if isinstance(group.get("references"), Mapping) else {}
            if not references.get("searched") or references.get("relied_on") is not None:
                problems.append(f"{name} is removed without a record of the references searched and of no reliance")
            runs = group.get("removal_runs") if isinstance(group.get("removal_runs"), list) else []
            if any(sum(1 for run in runs if isinstance(run, Mapping) and run.get("host") == host) < MAX_REMOVAL_RUNS for host in HOSTS):
                problems.append(f"{name} is removed without {MAX_REMOVAL_RUNS} removal runs on each host")
    return problems
