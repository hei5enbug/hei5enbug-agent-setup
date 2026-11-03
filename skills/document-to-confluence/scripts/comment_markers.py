#!/usr/bin/env python3
"""Restore and check Confluence inline comment markers in storage-format bodies.

restore PREVIOUS NEW --output FILE [--anchor REF BEFORE SELECTION AFTER]... [--anchors FILE]
    PREVIOUS is the stored body that holds the markers; NEW is the storage body built from the source.
    Each marker reference found in PREVIOUS is re-wrapped around its original selection in NEW:

    - one occurrence of the selection: wrapped in place;
    - several occurrences: the previous text around the selection picks the one whose surroundings match
      best, and only when that match is clear and unique;
    - markers that were nested are restored in the same nesting order;
    - a selection that crosses inline formatting is split into pieces that share the reference;
    - a selection never matches across block boundaries;
    - text inside an ac:parameter element is neither searched nor wrapped.

    A selection that is gone, still ambiguous after narrowing by context, or made of separated parts is
    not guessed. The command then exits 1, writes no output file, and prints each reference with its old
    context (a block boundary shows as the pilcrow sign). Re-run with an explicit anchor chosen by the
    agent: BEFORE, SELECTION, and AFTER are plain text of the new body (a pilcrow sign stands for a block
    boundary); BEFORE + SELECTION + AFTER must match exactly one place. --anchors takes the same data as a
    JSON list of objects with ref, before, selection, and after.
    A reference that NEW already marks is kept untouched.

check PREVIOUS READBACK
    Compares marker references and tag-pair counts of the body read back after a save with PREVIOUS and
    lists every reference missing from READBACK.

Both commands print a JSON report on standard output.
Exit codes: 0 success, 1 unresolved references (restore) or missing references (check), 2 usage, read,
or malformed-marker error.
"""

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

MARKER_TAG = "ac:inline-comment-marker"
PARAMETER_TAG = "ac:parameter"
CLOSE_TAG = f"</{MARKER_TAG}>"
SENTINEL = "\x00"
DISPLAY_SENTINEL = "¶"
CONTEXT_CHARS = 40
MIN_CONTEXT_SCORE = 3
INLINE_TAGS = frozenset({
    "strong", "b", "em", "i", "u", "s", "del", "ins", "sub", "sup", "code", "span", "a",
    "ac:link", "ac:link-body", MARKER_TAG,
})
TOKEN = re.compile(
    r"<!\[CDATA\[.*?\]\]>|<!--.*?-->|<\?.*?\?>"
    r"|</?[A-Za-z][^\s/>]*(?:[^>\"']|\"[^\"]*\"|'[^']*')*>|[^<]+|<",
    re.DOTALL,
)
ENTITY = re.compile(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);")
TAG_NAME = re.compile(r"</?([^\s/>]+)")
REF_ATTRIBUTE = re.compile(r"""ac:ref\s*=\s*(?:"([^"]*)"|'([^']*)')""")


class MarkerError(Exception):
    """A body or an argument cannot be processed."""


class Item(NamedTuple):
    char: str
    start: int
    end: int


SEPARATOR = Item(SENTINEL, -1, -1)


class Piece(NamedTuple):
    ref: str
    open_tag: str
    start: int
    end: int
    depth: int


@dataclass(frozen=True)
class Selection:
    ref: str
    open_tag: str
    text: str
    before: str
    after: str
    depth: int
    contiguous: bool


@dataclass(frozen=True)
class RestoreResult:
    body: str
    restored: list
    kept: list
    unresolved: list


def text_items(text: str, offset: int):
    items = []
    position = 0
    for match in ENTITY.finditer(text):
        items.extend(Item(c, offset + position + i, offset + position + i + 1) for i, c in enumerate(text[position:match.start()]))
        decoded = html.unescape(match.group(0))
        start, end = offset + match.start(), offset + match.end()
        if len(decoded) == 1:
            items.append(Item(decoded, start, end))
        else:
            items.extend(Item(c, start + i, start + i + 1) for i, c in enumerate(match.group(0)))
        position = match.end()
    items.extend(Item(c, offset + position + i, offset + position + i + 1) for i, c in enumerate(text[position:]))
    return items


def add_separator(items: list) -> None:
    if items and items[-1] is not SEPARATOR:
        items.append(SEPARATOR)


def marker_ref(open_tag: str) -> str:
    match = REF_ATTRIBUTE.search(open_tag)
    if not match:
        raise MarkerError(f"marker without ac:ref: {open_tag}")
    return match.group(1) if match.group(1) is not None else match.group(2)


def scan(body: str):
    """Return the searchable text stream of a body and its marker pieces."""
    items, pieces, open_stack = [], [], []
    parameter_depth = 0
    for token in TOKEN.finditer(body):
        raw = token.group(0)
        if not raw.startswith("<") or raw == "<":
            if parameter_depth == 0:
                items.extend(text_items(raw, token.start()))
            continue
        name_match = TAG_NAME.match(raw)
        if not name_match or raw.startswith(("<!", "<?")):
            add_separator(items)
            continue
        name = name_match.group(1).lower()
        if name == MARKER_TAG:
            update_markers(raw, items, pieces, open_stack)
        elif name == PARAMETER_TAG:
            parameter_depth = next_parameter_depth(raw, parameter_depth)
            add_separator(items)
        elif name not in INLINE_TAGS:
            add_separator(items)
    if open_stack:
        raise MarkerError(f"{len(open_stack)} marker start tag(s) are never closed, first: {open_stack[0][1]}")
    return items, pieces


def next_parameter_depth(raw: str, depth: int) -> int:
    if raw.startswith("</"):
        return max(0, depth - 1)
    return depth if raw.endswith("/>") else depth + 1


def update_markers(raw: str, items: list, pieces: list, open_stack: list) -> None:
    if raw.startswith("</"):
        if not open_stack:
            raise MarkerError("marker end tag without a start tag")
        ref, open_tag, start, depth = open_stack.pop()
        pieces.append(Piece(ref, open_tag, start, len(items), depth))
    elif not raw.endswith("/>"):
        open_stack.append((marker_ref(raw), raw, len(items), len(open_stack)))


def stream_text(items) -> str:
    return "".join(item.char for item in items)


def previous_selections(previous: str) -> list:
    items, pieces = scan(previous)
    ordered_refs = list(dict.fromkeys(piece.ref for piece in sorted(pieces, key=lambda p: p.start)))
    by_ref = {ref: [p for p in pieces if p.ref == ref] for ref in ordered_refs}
    selections = [build_selection(items, group) for group in by_ref.values()]
    return sorted(selections, key=lambda s: s.depth)


def build_selection(items: list, group: list) -> Selection:
    first = min(group, key=lambda p: (p.start, p.depth))
    start, end = min(p.start for p in group), max(p.end for p in group)
    while start < end and items[start] is SEPARATOR:
        start += 1
    while end > start and items[end - 1] is SEPARATOR:
        end -= 1
    covered = {index for p in group for index in range(p.start, p.end)}
    contiguous = all(index in covered or items[index] is SEPARATOR for index in range(start, end))
    return Selection(
        ref=first.ref,
        open_tag=first.open_tag,
        text=stream_text(items[start:end]),
        before=stream_text(items[max(0, start - CONTEXT_CHARS):start]),
        after=stream_text(items[end:end + CONTEXT_CHARS]),
        depth=first.depth,
        contiguous=contiguous,
    )


def occurrences(items, needle: str) -> list:
    text, found, index = stream_text(items), [], 0
    while needle:
        index = text.find(needle, index)
        if index < 0:
            break
        found.append(index)
        index += 1
    return found


def common_prefix(a: str, b: str) -> int:
    count = 0
    for left, right in zip(a, b):
        if left != right:
            break
        count += 1
    return count


def context_score(selection: Selection, items, start: int) -> int:
    end = start + len(selection.text)
    before = stream_text(items[max(0, start - CONTEXT_CHARS):start])
    after = stream_text(items[end:end + CONTEXT_CHARS])
    return common_prefix(selection.before[::-1], before[::-1]) + common_prefix(selection.after, after)


def choose_start(selection: Selection, items, candidates: list):
    """Return (start, reason); start is None when the place is not clear."""
    if not candidates:
        return None, "missing"
    if len(candidates) == 1:
        return candidates[0], ""
    scored = sorted(((context_score(selection, items, c), c) for c in candidates), reverse=True)
    best, runner_up = scored[0][0], scored[1][0]
    if best >= MIN_CONTEXT_SCORE and best > runner_up:
        return scored[0][1], ""
    return None, "ambiguous"


def wrap(body: str, items: list, ref_tag: str, start: int, end: int) -> str:
    """Wrap items[start:end] in marker pieces, split wherever a tag or block boundary intervenes."""
    groups, current = [], []
    for item in items[start:end]:
        if item is SEPARATOR:
            current = flush(groups, current)
        elif current and current[-1].end != item.start:
            current = flush(groups, current)
            current.append(item)
        else:
            current.append(item)
    flush(groups, current)
    insertions = sorted(
        [(g[0].start, ref_tag) for g in groups] + [(g[-1].end, CLOSE_TAG) for g in groups],
        key=lambda pair: pair[0],
        reverse=True,
    )
    result = body
    for position, text in insertions:
        result = result[:position] + text + result[position:]
    return result


def flush(groups: list, current: list) -> list:
    if current:
        groups.append(current)
    return []


def anchor_start(anchor: dict, items) -> tuple:
    needle = anchor["before"] + anchor["selection"] + anchor["after"]
    found = occurrences(items, needle)
    if len(found) == 1:
        return found[0] + len(anchor["before"]), ""
    return None, "missing" if not found else "ambiguous"


def unresolved_entry(selection: Selection, reason: str, candidates: int, anchored: bool) -> dict:
    show = lambda text: text.replace(SENTINEL, DISPLAY_SENTINEL)
    entry = {
        "ref": selection.ref,
        "reason": reason,
        "selection": show(selection.text),
        "before": show(selection.before),
        "after": show(selection.after),
        "candidates": candidates,
    }
    return {**entry, "anchor": True} if anchored else entry


def restore_one(body: str, selection: Selection, anchor):
    """Return (new body, unresolved entry or None)."""
    items, _ = scan(body)
    if anchor is not None:
        start, reason = anchor_start(anchor, items)
        length = len(anchor["selection"])
        candidates = len(occurrences(items, anchor["before"] + anchor["selection"] + anchor["after"]))
    elif not selection.contiguous:
        return body, unresolved_entry(selection, "noncontiguous", 0, False)
    else:
        found = occurrences(items, selection.text)
        start, reason = choose_start(selection, items, found)
        length, candidates = len(selection.text), len(found)
    if start is None:
        return body, unresolved_entry(selection, reason, candidates, anchor is not None)
    return wrap(body, items, selection.open_tag, start, start + length), None


def restore_markers(previous: str, new: str, anchors: list) -> RestoreResult:
    selections = previous_selections(previous)
    known = {s.ref for s in selections}
    by_ref = {}
    for anchor in anchors:
        if anchor["ref"] not in known:
            raise MarkerError(f"anchor reference {anchor['ref']} is not a marker in the previous body")
        by_ref[anchor["ref"]] = anchor
    _, present = scan(new)
    present_refs = {piece.ref for piece in present}
    body, restored, kept, unresolved = new, [], [], []
    for selection in selections:
        if selection.ref in present_refs:
            kept.append(selection.ref)
            continue
        body, problem = restore_one(body, selection, by_ref.get(selection.ref))
        if problem:
            unresolved.append(problem)
        else:
            restored.append(selection.ref)
    return RestoreResult(body, restored, kept, unresolved)


def summarize(body: str) -> dict:
    _, pieces = scan(body)
    return {"references": len({p.ref for p in pieces}), "pairs": len(pieces)}


def check_markers(previous: str, readback: str) -> dict:
    _, before = scan(previous)
    _, after = scan(readback)
    previous_refs = list(dict.fromkeys(p.ref for p in sorted(before, key=lambda p: p.start)))
    readback_refs = {p.ref for p in after}
    return {
        "previous": summarize(previous),
        "readback": summarize(readback),
        "missing": [ref for ref in previous_refs if ref not in readback_refs],
        "added": sorted(readback_refs - set(previous_refs)),
    }


def read_text(name: str) -> str:
    try:
        return Path(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise MarkerError(f"cannot read {name}: {error}") from error


def normalize_anchor(raw: dict) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("ref"), str) or not isinstance(raw.get("selection"), str):
        raise MarkerError("each anchor needs string fields ref and selection")
    if not raw["selection"]:
        raise MarkerError(f"anchor {raw['ref']} has an empty selection")
    fields = {key: raw.get(key, "") for key in ("before", "after")}
    if not all(isinstance(value, str) for value in fields.values()):
        raise MarkerError(f"anchor {raw['ref']} before and after must be strings")
    return {
        "ref": raw["ref"],
        "selection": raw["selection"].replace(DISPLAY_SENTINEL, SENTINEL),
        **{key: value.replace(DISPLAY_SENTINEL, SENTINEL) for key, value in fields.items()},
    }


def load_anchors(args) -> list:
    raw = [dict(zip(("ref", "before", "selection", "after"), values)) for values in args.anchor or []]
    if args.anchors:
        try:
            loaded = json.loads(read_text(args.anchors))
        except json.JSONDecodeError as error:
            raise MarkerError(f"{args.anchors} is not JSON: {error}") from error
        if not isinstance(loaded, list):
            raise MarkerError(f"{args.anchors} must hold a JSON list of anchors")
        raw.extend(loaded)
    return [normalize_anchor(item) for item in raw]


def print_report(report: dict) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))


def run_restore(args) -> int:
    result = restore_markers(read_text(args.previous), read_text(args.new), load_anchors(args))
    report = {
        "status": "unresolved" if result.unresolved else "restored",
        "restored": result.restored,
        "kept": result.kept,
        "unresolved": result.unresolved,
    }
    print_report(report)
    if result.unresolved:
        return 1
    Path(args.output).write_text(result.body, encoding="utf-8")
    return 0


def run_check(args) -> int:
    report = check_markers(read_text(args.previous), read_text(args.readback))
    print_report(report)
    return 1 if report["missing"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Restore and check Confluence inline comment markers.")
    commands = parser.add_subparsers(dest="command", required=True)
    restore = commands.add_parser("restore", help="re-wrap marker selections in a new storage body")
    restore.add_argument("previous", help="previous stored body that holds the markers")
    restore.add_argument("new", help="new storage body without markers")
    restore.add_argument("--output", required=True, help="file to write the restored body to")
    restore.add_argument("--anchor", nargs=4, action="append", metavar=("REF", "BEFORE", "SELECTION", "AFTER"))
    restore.add_argument("--anchors", help="JSON file with a list of anchors")
    restore.set_defaults(run=run_restore)
    check = commands.add_parser("check", help="list markers missing from a read-back body")
    check.add_argument("previous", help="previous stored body that holds the markers")
    check.add_argument("readback", help="stored body read back after the save")
    check.set_defaults(run=run_check)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except (MarkerError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
