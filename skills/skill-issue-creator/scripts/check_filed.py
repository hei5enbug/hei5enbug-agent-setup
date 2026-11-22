#!/usr/bin/env python3
"""Check a filed skill-gap issue: its title, tags, section order, and raw markup.

Usage:
  check_filed.py github --repo <owner/name> --number <n> --title <title> [--label <label>]...
  check_filed.py body --format <markdown|html|jira|plain> < body

`github` reads the issue and its rendered body through gh. `body` checks a body read from another tracker, given on
stdin. Prints one JSON object. Exit 0 when every check passes, 1 when any check fails, 3 when no check fails but one
could not run, 2 on a usage error. A check that cannot run is reported as unverified, never as passed.

Given only an existing folder, as skill packaging runs every `scripts/check_*.py` detector, it finds no violation in the
folder, because it checks filed issues and not skills, and exits 0.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

SECTIONS = (
    ("Summary",),
    ("Observations",),
    ("Gap in current rules", "Why no existing skill covers it"),
    ("Proposal",),
    ("Acceptance criteria",),
    ("Evidence",),
)
FORMATS = ("markdown", "html", "jira", "plain")
GH_TIMEOUT_SECONDS = 60
PASS, FAIL, UNVERIFIED = "pass", "fail", "unverified"
EXIT_CODES = {PASS: 0, FAIL: 1, UNVERIFIED: 3}
CODE_BLOCK = re.compile(r"<(pre|code)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
FENCE = re.compile(r"^(```|~~~)")
INLINE_CODE = re.compile(r"`[^`\n]*`")
ESCAPED_TAG = re.compile(r"&(?:amp;)*(?:lt|gt);/?[A-Za-z]", re.IGNORECASE)
ESCAPED_LINE_BREAK = re.compile(r"(?:\\r)?\\n")
RENDERED_MARKERS = (
    ("heading_marker", re.compile(r"(?:^|\s)#{1,6}\s+\S")),
    ("bold_marker", re.compile(r"\*\*[^*\n]+\*\*")),
    ("escaped_line_break", ESCAPED_LINE_BREAK),
)
SOURCE_MARKERS = (
    ("escaped_line_break", ESCAPED_LINE_BREAK),
    ("escaped_marker", re.compile(r"\\#|\\\*\\\*")),
)
HEADING_PATTERNS = {
    "markdown": re.compile(r"^#{2}\s+(.+?)\s*#*\s*$"),
    "jira": re.compile(r"^h2\.\s+(.+?)\s*$"),
    "html": re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL),
}


def check(identifier: str, status: str, detail: str) -> dict[str, str]:
    return {"id": identifier, "status": status, "detail": detail}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def section_names(fmt: str, body: str) -> list[str]:
    if fmt == "html":
        return [normalize(TAG.sub("", match)) for match in HEADING_PATTERNS["html"].findall(body)]
    if fmt == "plain":
        known = {normalize(name) for names in SECTIONS for name in names}
        lines = body.splitlines()
        return [normalize(line) for index, line in enumerate(lines)
                if normalize(line) in known and (index + 1 == len(lines) or not lines[index + 1].strip())]
    pattern, names, in_fence = HEADING_PATTERNS[fmt], [], False
    for line in body.splitlines():
        if FENCE.match(line.strip()):
            in_fence = not in_fence
        match = None if in_fence else pattern.match(line)
        if match:
            names.append(normalize(match.group(1)))
    return names


def section_order(fmt: str, body: str) -> dict[str, str]:
    names = section_names(fmt, body)
    positions, missing = [], []
    for options in SECTIONS:
        found = [names.index(normalize(name)) for name in options if normalize(name) in names]
        if found:
            positions.append(min(found))
        else:
            missing.append(options[0])
    if missing:
        return check("section_order", FAIL, "missing section headings: " + ", ".join(missing))
    if positions != sorted(positions):
        return check("section_order", FAIL, "the six section headings are not in the required order")
    return check("section_order", PASS, "the six section headings are in order")


def visible_lines(text: str, fmt: str) -> list[tuple[int, str]]:
    """The lines a reader sees as text: code is removed, and for html the tags are stripped."""
    if fmt == "html":
        text = TAG.sub("\n", CODE_BLOCK.sub("", text))
        return [(number, line) for number, line in enumerate(text.splitlines(), start=1) if line.strip()]
    lines, in_fence = [], False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line.strip()):
            in_fence = not in_fence
        elif not in_fence:
            lines.append((number, INLINE_CODE.sub("", line)))
    return lines


def markup_findings(text: str, fmt: str, markers: tuple[tuple[str, re.Pattern[str]], ...],
                    entities: bool) -> list[dict[str, Any]]:
    found = [{"kind": kind, "line": number} for number, line in visible_lines(text, fmt)
             for kind, pattern in markers if pattern.search(line)]
    if entities:
        found += [{"kind": "escaped_entity", "line": number} for number, line in enumerate(text.splitlines(), start=1)
                  if ESCAPED_TAG.search(CODE_BLOCK.sub("", line))]
    return sorted(found, key=lambda item: (item["line"], item["kind"]))


def raw_markup(text: str, fmt: str, markers: tuple[tuple[str, re.Pattern[str]], ...],
               entities: bool = False) -> tuple[dict[str, str], list]:
    found = markup_findings(text, fmt, markers, entities)
    if found:
        kinds = ", ".join(sorted({item["kind"] for item in found}))
        return check("raw_markup", FAIL, f"raw markup in the body: {kinds}"), found
    return check("raw_markup", PASS, "no raw markup found"), []


def body_checks(fmt: str, body: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    results = [section_order(fmt, body)]
    if fmt in ("jira", "plain"):
        results.append(check("raw_markup", UNVERIFIED, f"raw markup cannot be checked in {fmt} text"))
        return results, []
    markers = RENDERED_MARKERS if fmt == "html" else SOURCE_MARKERS
    verdict, found = raw_markup(body, fmt, markers, entities=fmt == "html")
    return [*results, verdict], found


def run_gh(arguments: list[str], runner: Callable[..., Any] = subprocess.run) -> tuple[str | None, str]:
    try:
        completed = runner(["gh", *arguments], capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, f"gh could not run ({type(error).__name__})"
    if completed.returncode != 0:
        return None, f"gh exited with {completed.returncode}"
    return completed.stdout, ""


def read_issue(repo: str, number: int) -> tuple[dict[str, Any] | None, str]:
    output, problem = run_gh(["issue", "view", str(number), "--repo", repo, "--json", "number,title,labels,body,url"])
    if output is None:
        return None, problem
    try:
        issue = json.loads(output)
    except ValueError:
        return None, "gh printed no JSON for the issue"
    return (issue, "") if isinstance(issue, dict) else (None, "gh printed no issue object")


def read_rendered(repo: str, number: int) -> tuple[str | None, str]:
    return run_gh(["api", f"repos/{repo}/issues/{number}", "-H", "Accept: application/vnd.github.html+json",
                   "--jq", ".body_html"])


def label_names(issue: dict[str, Any]) -> set[str]:
    return {item.get("name") if isinstance(item, dict) else item for item in issue.get("labels") or []}


def issue_checks(issue: dict[str, Any], title: str, labels: list[str]) -> list[dict[str, str]]:
    matched = issue.get("title") == title
    missing = [label for label in labels if label not in label_names(issue)]
    results = [check("title", PASS if matched else FAIL, "the title matches" if matched else "the title differs")]
    if missing:
        results.append(check("tags", FAIL, "missing tags: " + ", ".join(missing)))
    else:
        results.append(check("tags", PASS, "every tag is present" if labels else "no tag was expected"))
    return [*results, section_order("markdown", str(issue.get("body") or ""))]


def github(repo: str, number: int, title: str, labels: list[str]) -> dict[str, Any]:
    issue, problem = read_issue(repo, number)
    if issue is None:
        results = [check(name, UNVERIFIED, problem) for name in ("title", "tags", "section_order")]
    else:
        results = issue_checks(issue, title, labels)
    rendered, problem = read_rendered(repo, number)
    if rendered is None:
        return report([*results, check("raw_markup", UNVERIFIED, problem)], [])
    verdict, found = raw_markup(rendered, "html", RENDERED_MARKERS)
    return report([*results, verdict], found)


def report(results: list[dict[str, str]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = {item["status"] for item in results}
    status = FAIL if FAIL in statuses else UNVERIFIED if UNVERIFIED in statuses else PASS
    return {"status": status, "checks": results, "findings": findings}


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="check_filed.py", description="Check a filed issue.")
    modes = parser.add_subparsers(dest="mode", required=True)
    remote = modes.add_parser("github", help="read the issue through gh")
    remote.add_argument("--repo", required=True)
    remote.add_argument("--number", required=True, type=int)
    remote.add_argument("--title", required=True)
    remote.add_argument("--label", action="append", default=[])
    local = modes.add_parser("body", help="check a body given on stdin")
    local.add_argument("--format", required=True, choices=FORMATS)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    if len(argv) == 1 and Path(argv[0]).is_dir():
        print(json.dumps(report([], [])))
        return EXIT_CODES[PASS]
    args = parse(argv)
    if args.mode == "github":
        outcome = github(args.repo, args.number, args.title, args.label)
    else:
        results, found = body_checks(args.format, sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        outcome = report(results, found)
    print(json.dumps(outcome))
    return EXIT_CODES[outcome["status"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
