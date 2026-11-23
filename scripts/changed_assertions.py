#!/usr/bin/env python3
"""List what a change removed or changed in the test files that existed at a base revision.

Usage: changed_assertions.py BASE_REVISION

Prints a JSON list with one entry per test file that existed at BASE_REVISION and whose working tree differs from it,
with the assertion lines removed or changed, the skip markers added, and the test functions removed. Each item names its
line: the line at the base revision for a removal, the line in the working tree for an addition. A new test file and an
added assertion are never listed. The script lists and never judges; an empty list means no test file changed.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

TEST_FILE = re.compile(
    r"(^|/)(test_[^/]*\.py|[^/]*_test\.(?:py|go|rs|rb|exs?)|[^/]*\.(?:test|spec)\.[cm]?[jt]sx?|[^/]*_spec\.rb"
    r"|[^/]*Tests?\.(?:java|kt|cs|swift|scala))$|(^|/)(?:tests?|__tests__|spec)/[^/]+\.(?:py|go|rs|rb|[jt]sx?|java|kt|cs)$")
ASSERTION = re.compile(
    r"\bassert\w*\b|\bexpect\s*\(|\.should\b|\bverify\s*\(|\.to(?:Be|Equal|Have|Throw|Match|Contain)\w*\(|\bpytest\.raises\b"
    r"|\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b|\brequire\.\w+\(|\bassertThat\b")
SKIP = re.compile(r"\bskip\w*\b|\bxfail\b|@Disabled\b|@Ignore\b|\bxit\s*\(|\bxtest\s*\(|\bxdescribe\s*\(|#\[ignore\]|\bpending\b|importorskip")
TEST_NAME = [re.compile(pattern) for pattern in (
    r"^\s*(?:async\s+)?def\s+(test\w*)\s*\(", r"^\s*(?:it|test)(?:\.\w+)?\s*\(\s*['\"`]([^'\"`]+)", r"^\s*func\s+(Test\w+)\s*\(",
    r"^\s*(?:public\s+)?(?:async\s+)?fn\s+(test\w*)\s*\(")]
MARKED_TEST = re.compile(r"^\s*(?:@Test\b|#\[test\])")
MARKED_NAME = re.compile(r"\b(?:fun|void|fn)\s+(\w+)\s*\(")


def git(*args: str) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise SystemExit(f"changed_assertions: git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def normal(line: str) -> str:
    return " ".join(line.split())


def test_names(lines: list[str]) -> dict[str, int]:
    """Test function names with their first line number."""
    found: dict[str, int] = {}
    marked = False
    for number, line in enumerate(lines, start=1):
        match = next((m for m in (pattern.match(line) for pattern in TEST_NAME) if m), None)
        if match:
            found.setdefault(match.group(1), number)
        if marked and (named := MARKED_NAME.search(line)):
            found.setdefault(named.group(1), number)
            marked = False
        elif MARKED_TEST.match(line):
            marked = True
        elif line.strip() and not line.lstrip().startswith(("@", "#", "//")):
            marked = False
    return found


def assertion_changes(before: list[str], after: list[str]) -> tuple[list[dict], list[dict]]:
    """Removed and changed assertion lines. A line that only moved, or only changed its indentation, is not listed."""
    old, new = [normal(line) for line in before], [normal(line) for line in after]
    gone = Counter(line for line in old if ASSERTION.search(line)) - Counter(line for line in new if ASSERTION.search(line))
    removed, changed = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag not in ("delete", "replace"):
            continue
        lost = [(i + 1, old[i]) for i in range(i1, i2) if ASSERTION.search(old[i]) and gone[old[i]] > 0]
        added = [(j + 1, new[j]) for j in range(j1, j2) if ASSERTION.search(new[j])] if tag == "replace" else []
        for index, (number, text) in enumerate(lost):
            gone[text] -= 1
            if index < len(added) and added[index][1] != text:
                changed.append({"line": number, "before": text, "after": added[index][1], "after_line": added[index][0]})
            else:
                removed.append({"line": number, "text": text})
    return removed, changed


def file_report(path: str, before: list[str], after: list[str]) -> dict | None:
    removed, changed = assertion_changes(before, after)
    old_skips = Counter(normal(line) for line in before if SKIP.search(line))
    skips = []
    for number, line in enumerate(after, start=1):
        text = normal(line)
        if SKIP.search(line):
            if old_skips[text] > 0:
                old_skips[text] -= 1
            else:
                skips.append({"line": number, "text": text})
    tests = test_names(after)
    gone = [{"line": number, "name": name} for name, number in test_names(before).items() if name not in tests]
    if not (removed or changed or skips or gone):
        return None
    return {"file": path, "removed_assertions": removed, "changed_assertions": changed, "added_skip_markers": skips,
            "removed_tests": gone}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1].startswith("-"):
        sys.stderr.write(__doc__ or "")
        return 2
    base = argv[1]
    os.chdir(git("rev-parse", "--show-toplevel").strip())
    changed = git("diff", "--name-status", "--no-renames", base, "--").splitlines()
    reports = []
    for entry in changed:
        status, _, path = entry.partition("\t")
        if status[:1] not in ("M", "D") or not TEST_FILE.search(path):
            continue
        before = git("show", f"{base}:{path}").splitlines()
        target = Path(path)
        after = target.read_text(encoding="utf-8", errors="replace").splitlines() if target.is_file() else []
        report = file_report(path, before, after)
        if report:
            reports.append(report)
    json.dump(sorted(reports, key=lambda item: item["file"]), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
