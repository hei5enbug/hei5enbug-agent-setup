#!/usr/bin/env python3
"""List what a change did to the test files that existed at a base revision.

Prints a JSON list with one entry per such test file that has a finding: the assertion lines removed or changed, the skip
markers added, and the test functions removed. It lists and never judges, so it cannot say whether a change is justified.
New test files and added assertions are not listed. A change that touches no existing test prints `[]`.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

MAX_SPAN = 40
SIMILAR = 0.5
TEST_PATH = re.compile(
    r"(?:^|/)(?:tests?|__tests__|spec)/"
    r"|(?:^|/)(?:test_[^/]*|[^/]*_test\.[^/]+|[^/]*\.(?:test|spec)\.[^/]+|[^/]*Tests?\.(?:java|kt|cs|scala|swift))$")
ASSERTION = re.compile(
    r"^\s*(?:assert\b|assert\w*!?\(|self\.assert\w*\(|self\.fail\(|Assert\.\w+\(|with\s+(?:pytest\.raises|self\.assertRaises)\b"
    r"|pytest\.raises\(|expect\w*\(|\w[\w.]*\.should\b|should\.|require\.\w+\(|assert\.\w+\(|t\.(?:Error|Errorf|Fatal|Fatalf)\()")
SKIP_MARKER = re.compile(
    r"pytest\.mark\.(?:skip|skipif|xfail)\b|unittest\.(?:skip|skipIf|skipUnless|expectedFailure)\b|pytest\.(?:skip|xfail|importorskip)\("
    r"|\.skipTest\(|@(?:Disabled|Ignore)\b|\b(?:it|test|describe|context)\.(?:skip|todo|failing|only)\b"
    r"|\b(?:xit|xdescribe|xtest|xcontext)\(|\bt\.Skip(?:f|Now)?\(|\[(?:Fact|Theory)\(Skip")
PYTHON_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\(")
GO_TEST = re.compile(r"^\s*func\s+(Test\w+)\s*\(")
SCRIPT_TEST = re.compile(r"^\s*(?:it|test|specify)(?:\.each\([^)]*\))?\s*\(\s*(['\"`])(.*?)\1")
TEST_ANNOTATION = re.compile(r"^\s*(?:@Test\b|@ParameterizedTest\b|@RepeatedTest\b|#\[test\]|\[Fact|\[Theory|\[Test\])")
ANNOTATED_METHOD = re.compile(r"\b(\w+)\s*\(")
STRING = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")


class GitError(Exception):
    pass


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise GitError(done.stderr.strip() or f"git {args[0]} failed")
    return done.stdout


def depth(line: str) -> int:
    code = STRING.sub("", line)
    return sum(code.count(opener) for opener in "([{") - sum(code.count(closer) for closer in ")]}")


def statements(text: str) -> list[tuple[int, str]]:
    """The assertion statements of a text as (first line, whitespace-joined text); a statement runs over the lines that
    keep a bracket open and over lines that continue a call chain."""
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if not ASSERTION.match(lines[index]):
            index += 1
            continue
        start, open_brackets, parts = index, depth(lines[index]), [lines[index].strip()]
        index += 1
        while index < len(lines) and index - start < MAX_SPAN and (open_brackets > 0 or lines[index].lstrip().startswith(".")):
            open_brackets += depth(lines[index])
            parts.append(lines[index].strip())
            index += 1
        found.append((start + 1, " ".join(parts)))
    return found


def skip_lines(text: str) -> list[tuple[int, str]]:
    return [(number, line.strip()) for number, line in enumerate(text.splitlines(), start=1) if SKIP_MARKER.search(line)]


def test_names(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        for pattern, group in ((PYTHON_TEST, 1), (GO_TEST, 1), (SCRIPT_TEST, 2)):
            matched = pattern.match(line)
            if matched:
                found.append((index + 1, matched.group(group)))
                break
        else:
            if TEST_ANNOTATION.match(line):
                for offset, follower in enumerate(lines[index + 1:index + 4], start=index + 2):
                    method = None if follower.lstrip().startswith(("@", "#[", "[")) else ANNOTATED_METHOD.search(follower)
                    if method:
                        found.append((offset, method.group(1)))
                        break
    return found


def pair_changed(before: list[tuple[int, str]], after: list[tuple[int, str]]) -> tuple[list[dict], list[tuple[int, str]]]:
    """Match each replaced base statement with the most similar new statement above the similarity floor, and return the
    pairs as changes and the base statements left unpaired."""
    free, changes, leftover = list(after), [], []
    for line, text in before:
        scored = [(difflib.SequenceMatcher(None, text, candidate, autojunk=False).ratio(), position)
                  for position, (_, candidate) in enumerate(free)]
        best = max(scored, default=(0.0, -1))
        if best[0] >= SIMILAR:
            new_line, new_text = free.pop(best[1])
            changes.append({"line": line, "new_line": new_line, "before": text, "after": new_text})
        else:
            leftover.append((line, text))
    return changes, leftover


def compare_assertions(before: list[tuple[int, str]], after: list[tuple[int, str]]) -> tuple[list[dict], list[dict]]:
    """The base assertions that are removed and the ones that are changed; an assertion that only moved is neither."""
    matcher = difflib.SequenceMatcher(None, [text for _, text in before], [text for _, text in after], autojunk=False)
    changed: list[dict] = []
    gone: list[tuple[int, str]] = []
    unmatched_after: list[tuple[int, str]] = []
    for tag, b1, b2, a1, a2 in matcher.get_opcodes():
        if tag == "delete":
            gone += before[b1:b2]
        elif tag == "insert":
            unmatched_after += after[a1:a2]
        elif tag == "replace":
            pairs, leftover = pair_changed(before[b1:b2], after[a1:a2])
            changed += pairs
            gone += leftover
            paired = {pair["new_line"] for pair in pairs}
            unmatched_after += [item for item in after[a1:a2] if item[0] not in paired]
    still_there = Counter(text for _, text in unmatched_after)
    removed = []
    for line, text in gone:
        if still_there[text] > 0:
            still_there[text] -= 1
        else:
            removed.append({"line": line, "text": text})
    return removed, changed


def removed_tests(before: list[tuple[int, str]], after: list[tuple[int, str]]) -> list[dict]:
    kept = Counter(name for _, name in after)
    found = []
    for line, name in before:
        if kept[name] > 0:
            kept[name] -= 1
        else:
            found.append({"line": line, "name": name})
    return found


def added_skips(before: str, after: str) -> list[dict]:
    already = Counter(text for _, text in skip_lines(before))
    found = []
    for line, text in skip_lines(after):
        if already[text] > 0:
            already[text] -= 1
        else:
            found.append({"line": line, "text": text})
    return found


def entry(path: str, status: str, before: str, after: str) -> dict | None:
    removed, changed = compare_assertions(statements(before), statements(after))
    result = {"file": path, "status": status, "removed_assertions": removed, "changed_assertions": changed,
              "added_skips": added_skips(before, after), "removed_tests": removed_tests(test_names(before), test_names(after))}
    return result if any(result[key] for key in ("removed_assertions", "changed_assertions", "added_skips", "removed_tests")) else None


def changed_assertions(repo: Path, base: str) -> list[dict]:
    """One entry for each test file that existed at `base` and shows a finding in the working tree."""
    listing = git(repo, "diff", "--name-status", "-M", "--no-color", base, "--")
    found = []
    for row in listing.splitlines():
        fields = row.split("\t")
        status, old, new = fields[0][:1], fields[1], fields[-1]
        if status not in ("M", "D", "R", "T") or not (TEST_PATH.search(old) or TEST_PATH.search(new)):
            continue
        before = git(repo, "show", f"{base}:{old}")
        target = repo / new
        after = target.read_text(encoding="utf-8", errors="replace") if status != "D" and target.is_file() else ""
        item = entry(new, {"D": "deleted", "R": "renamed"}.get(status, "modified"), before, after)
        if item:
            found.append(item)
    return sorted(found, key=lambda item: item["file"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List the assertions, skip markers, and test functions a change touched in existing test files.")
    parser.add_argument("base", help="the revision the task started from")
    parser.add_argument("--repo", default=".", help="the repository to read (default: the current folder)")
    args = parser.parse_args(argv)
    try:
        report = changed_assertions(Path(args.repo).resolve(), args.base)
    except GitError as error:
        print(f"changed_assertions: cannot compare with {args.base}: {error}. Pass a revision that exists in this repository.", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
