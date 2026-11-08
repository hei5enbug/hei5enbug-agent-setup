#!/usr/bin/env python3
"""Check a draft text for patterns the text alone decides, then have a context-free reviewer read it."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KINDS = (
    "pr-description", "review-reply", "issue-body", "ticket-comment", "commit-message",
    "chat-message", "shared-document", "final-report", "other",
)
REVIEW_MODELS = {kind: "gpt-6.1-sol" for kind in KINDS}
DEFAULT_TIMEOUT = 600
DEFAULT_REVIEWS = 1
RUNNER_GRACE_SECONDS = 60
EXIT_OK, EXIT_FINDINGS, EXIT_USAGE, EXIT_REVIEW_FAILED = 0, 1, 2, 3
FINDING_TYPES = ("removable", "missing", "ambiguous")
LINE_TEXT_LIMIT = 160
IDENTIFIER_MAX_LENGTH = 80
IDENTIFIER_LIST_MINIMUM = 3
LABEL_MAX_LENGTH = 40
AGENT_FACING_KINDS = ("issue-body",)

UNCHANGED_PATTERNS = (
    r"\b(?:is|are|was|were|stays?|remains?)\s+(?:still\s+)?unchanged\b",
    r"\b(?:does|did|do)(?:\s+not|n't)\s+change\b",
    r"\bno\s+changes?\s+(?:to|in)\b",
    r"\bnothing\s+changes\b",
    r"변경(?:이|은)?\s*없",
    r"바뀌지\s*않",
    r"그대로(?:이다|다|입니다|예요|이에요|임)",
)

REVIEWER_INSTRUCTIONS = """\
You have no conversation context. Review the draft below, which is addressed to a reader who will decide or act on \
it. Run two passes over the whole draft, not only a changed part.

Cut pass: report each sentence or link that can be deleted without the reader losing a fact needed to decide or act. \
This includes a sentence or link that restates a linked source, an adjacent table or figure, another section, or a \
diff the reader sees with the text; a list of names such a diff shows; the reason behind a check item; a statement that something does not change, \
unless a reader would otherwise act wrongly; a link whose target another listed link already covers; and items of \
one kind that should be one line.

Completeness pass: report each decision, condition, prerequisite, order, or completion criterion that the sources or \
the request require and the draft lacks, and each sentence with two readings.

When a length budget is given and the draft exceeds it, also list each fact that cutting to the budget would lose. An \
author's note gives the author's reason for keeping a sentence that an earlier run flagged; accept or reject each \
note on its merits.

Report nothing else, and report no finding you cannot quote or point to. The destination's writing rules take \
precedence: never report as removable what they require. Judge each finding for the reader named below; a fact that \
reader has not seen, such as a change made beyond the request, is not a restatement. Report only a finding a careful \
editor would make on any reading, not a matter of taste; a careful draft should get an empty list.

Answer with one JSON object in a ```json fence and nothing after it:
{"findings": [{"type": "removable" | "missing" | "ambiguous", "quote": "...", "reason": "..."}], \
"over_budget_facts": ["..."]}
An empty findings list means the draft passes.
"""

READERS = {
    "pr-description": "a reviewer who sees the diff next to this text.",
    "review-reply": "the reviewer who asked, who sees the diff and the review thread.",
    "issue-body": "someone who reads only this issue and its links, not the conversation or a diff.",
    "ticket-comment": "someone who reads the ticket and this comment, not a diff.",
    "commit-message": "someone reading history, who sees the diff of this commit.",
    "chat-message": "a teammate who reads only this message.",
    "shared-document": "a colleague who reads only this document and its links.",
    "final-report": (
        "the user who asked for the work and has not read the diff, the logs, or the tool output. What is left for "
        "them, such as an uncommitted change, a skipped step, or a failing check, is a fact they need."
    ),
    "other": "someone who reads only this text and its links.",
}

LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
FENCE_OPEN = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
LINK_TARGET = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
BARE_URL = re.compile(r"https?://[^\s<>)\]]+")
URL_TRAILING = ".,;:!?"
TICKET_KEY = re.compile(r"(?<![A-Za-z0-9_-])([A-Z][A-Z0-9]{1,9})-[0-9]+(?![A-Za-z0-9_-])")
STANDARD_PREFIXES = frozenset({"UTF", "SHA", "ISO", "RFC", "IEEE", "HTTP", "TLS", "MD", "AES", "RSA", "CVE", "GPT"})
LABEL = re.compile(r"^([^:：]{1,%d}?)\s*[:：](?!//)" % LABEL_MAX_LENGTH)
BACKTICK_RUN = re.compile(r"`+")
JSON_FENCE = re.compile(r"(`{3,})json[ \t]*\n(.*?)\n\1", re.DOTALL)


class TextReviewError(Exception):
    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.code = code


class ReviewFailure(TextReviewError):
    def __init__(self, message: str, runner: dict) -> None:
        super().__init__(message, EXIT_REVIEW_FAILED)
        self.runner = runner


def read_input(path: str) -> str:
    try:
        if path == "-":
            return sys.stdin.read()
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise TextReviewError(f"cannot read {path}: {error}") from error


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Return the numbered lines outside fenced code blocks."""
    kept: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        opening = FENCE_OPEN.match(line)
        if fence is None:
            if opening:
                fence = opening.group(1)
            else:
                kept.append((number, line))
        elif opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence) and not line.strip().strip(fence[0]):
            fence = None
    return kept


def code_spans(line: str) -> list[str]:
    return [match.group(2) for match in CODE_SPAN.finditer(line)]


def without_code(line: str) -> str:
    return CODE_SPAN.sub(" ", line)


def collect_items(lines: list[tuple[int, str]]) -> list[dict]:
    """Group list items with their indented continuation lines, resetting at headings and prose."""
    items: list[dict] = []
    stack: list[dict] = []
    group = 0
    current: dict | None = None
    for number, line in lines:
        match = LIST_ITEM.match(line)
        if match:
            indent = len(match.group(1).expandtabs(4))
            while stack and stack[-1]["indent"] >= indent:
                stack.pop()
            current = {"line": number, "indent": indent, "text": match.group(2), "group": group,
                       "parent": stack[-1]["line"] if stack else 0, "raw": line}
            items.append(current)
            stack.append(current)
        elif not line.strip():
            continue
        elif HEADING.match(line) or not line[0].isspace():
            group += 1
            stack.clear()
            current = None
        elif current is not None:
            current["text"] += " " + line.strip()
    return items


def finding(rule: str, number: int, line: str) -> dict:
    return {"rule": rule, "line": number, "text": line.rstrip()[:LINE_TEXT_LIMIT]}


def identifier_list(items: list[dict], lines: dict[int, str]) -> list[dict]:
    found = []
    for item in items:
        identifiers = [span for span in code_spans(item["text"]) if not any(c.isspace() for c in span) and len(span) <= IDENTIFIER_MAX_LENGTH]
        if len(identifiers) >= IDENTIFIER_LIST_MINIMUM:
            found.append(finding("identifier-list", item["line"], lines[item["line"]]))
    return found


def repeated_check(items: list[dict], lines: dict[int, str]) -> list[dict]:
    found = []
    seen_spans: set[tuple] = set()
    seen_labels: set[tuple] = set()
    for item in items:
        scope = (item["group"], item["parent"])
        spans = code_spans(item["text"])
        span_key = (scope, " ".join(spans[0].split())) if spans else None
        label = LABEL.match(without_code(item["text"]).strip())
        label_key = (scope, label.group(1).strip().lower()) if label and label.group(1).strip() else None
        if (span_key and span_key in seen_spans) or (label_key and label_key in seen_labels):
            found.append(finding("repeated-check", item["line"], lines[item["line"]]))
        if span_key:
            seen_spans.add(span_key)
        if label_key:
            seen_labels.add(label_key)
    return found


def ticket_key(lines: list[tuple[int, str]]) -> list[dict]:
    found = []
    for number, line in lines:
        bare = BARE_URL.sub(" ", LINK_TARGET.sub("] ", without_code(line)))
        if any(match.group(1) not in STANDARD_PREFIXES for match in TICKET_KEY.finditer(bare)):
            found.append(finding("ticket-key", number, line))
    return found


def unchanged_only(lines: list[tuple[int, str]]) -> list[dict]:
    patterns = [re.compile(pattern, re.IGNORECASE) for pattern in UNCHANGED_PATTERNS]
    return [finding("unchanged-only", number, line) for number, line in lines
            if any(pattern.search(without_code(line)) for pattern in patterns)]


def links_of(line: str) -> list[tuple[int, str]]:
    plain = without_code(line)
    found = [(match.start(1), match.group(1)) for match in LINK_TARGET.finditer(plain)]
    blanked = LINK_TARGET.sub(lambda match: " " * len(match.group(0)), plain)
    found += [(match.start(), match.group(0).rstrip(URL_TRAILING)) for match in BARE_URL.finditer(blanked)]
    return sorted(found)


def same_page_links(lines: list[tuple[int, str]]) -> list[dict]:
    found = []
    earlier: dict[str, list[bool]] = {}
    for number, line in lines:
        flagged = False
        for _, url in links_of(line):
            base, _, fragment = url.partition("#")
            if not base:
                continue
            seen = earlier.setdefault(base, [])
            if seen and (fragment or any(seen)):
                flagged = True
            seen.append(bool(fragment))
        if flagged:
            found.append(finding("same-page-links", number, line))
    return found


def check_text(text: str, kind: str | None, no_ticket_keys: bool) -> list[dict]:
    lines = prose_lines(text)
    numbered = dict(lines)
    items = collect_items(lines)
    found = repeated_check(items, numbered) + unchanged_only(lines) + same_page_links(lines)
    if kind not in AGENT_FACING_KINDS:
        found += identifier_list(items, numbered)
    if no_ticket_keys:
        found += ticket_key(lines)
    return sorted(found, key=lambda item: (item["line"], item["rule"]))


def fenced(content: str) -> str:
    longest = max((len(run) for run in BACKTICK_RUN.findall(content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{content.rstrip(chr(10))}\n{fence}"


def named_files(heading: str, files: list[tuple[str, str]]) -> list[str]:
    if not files:
        return []
    return [f"## {heading}\n", *[f"### {name}\n\n{fenced(content)}\n" for name, content in files]]


def build_assignment(kind: str, draft: str, rules: list, sources: list, notes: list[str], budget: int | None) -> str:
    parts = [REVIEWER_INSTRUCTIONS, f"Text kind: {kind}\n", f"Reader: {READERS[kind]}\n"]
    parts += named_files("Destination writing rules", rules)
    parts += named_files("Sources", sources)
    if notes:
        parts += ["## Author's notes", *[f"{number}. {fenced(note)}\n" for number, note in enumerate(notes, start=1)]]
    if budget is not None:
        parts.append(f"## Length budget\n\nLength budget: {budget} characters. The draft is {len(draft)} characters.\n")
    parts.append(f"## Draft\n\n{fenced(draft)}\n")
    return "\n".join(parts)


def parse_status(stdout: str) -> bool | None:
    for line in reversed(stdout.splitlines()):
        if line.strip():
            try:
                verified = json.loads(line).get("verified")
            except (ValueError, AttributeError):
                return None
            return verified if isinstance(verified, bool) else None
    return None


def parse_result(text: str) -> dict:
    blocks = JSON_FENCE.findall(text)
    candidate = blocks[-1][1] if blocks else text
    try:
        data = json.loads(candidate)
    except ValueError as error:
        raise TextReviewError(f"the reviewer's JSON cannot be parsed: {error}", EXIT_REVIEW_FAILED) from error
    findings = data.get("findings") if isinstance(data, dict) else None
    facts = data.get("over_budget_facts", []) if isinstance(data, dict) else None
    valid = (
        isinstance(findings, list) and isinstance(facts, list) and all(isinstance(fact, str) for fact in facts)
        and all(isinstance(item, dict) and item.get("type") in FINDING_TYPES and isinstance(item.get("quote"), str)
                and isinstance(item.get("reason"), str) for item in findings)
    )
    if not valid:
        raise TextReviewError("the reviewer's JSON lacks the findings structure", EXIT_REVIEW_FAILED)
    return {"findings": findings, "over_budget_facts": facts}


def run_reviewer(args: argparse.Namespace, assignment: str, model: str) -> dict:
    work = Path(tempfile.mkdtemp(prefix="text-review-"))
    try:
        if subprocess.run(["git", "init", "-q", str(work)], capture_output=True, check=False).returncode != 0:
            raise ReviewFailure("git init failed for the reviewer's folder", {"exit": None, "verified": None})
        assignment_file, result_file = work / "assignment.md", work / "result.md"
        assignment_file.write_text(assignment, encoding="utf-8")
        command = [sys.executable, str(Path(args.runner).resolve()), "reviewer", "--model", model, "--timeout", str(args.timeout),
                   "--assignment", str(assignment_file), "--result", str(result_file)]
        try:
            done = subprocess.run(command, cwd=work, capture_output=True, text=True,
                                  timeout=args.timeout + RUNNER_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TextReviewError(f"the runner did not finish: {error}", EXIT_REVIEW_FAILED) from error
        runner = {"exit": done.returncode, "verified": parse_status(done.stdout)}
        try:
            if done.returncode != 0:
                raise TextReviewError(f"the runner exited with {done.returncode}: {done.stderr.strip()[-500:]}", EXIT_REVIEW_FAILED)
            if not result_file.is_file():
                raise TextReviewError("the runner wrote no result file", EXIT_REVIEW_FAILED)
            return {**parse_result(result_file.read_text(encoding="utf-8")), "runner": runner}
        except (TextReviewError, OSError, UnicodeDecodeError) as error:
            raise ReviewFailure(str(error), runner) from error
    finally:
        shutil.rmtree(work, ignore_errors=True)


def positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="report patterns decidable from the text alone")
    check.add_argument("--kind", choices=KINDS)
    check.add_argument("--no-ticket-keys", action="store_true")
    check.add_argument("file")
    review = commands.add_parser("review", help="check, then run a context-free reviewer")
    review.add_argument("--kind", choices=KINDS, required=True)
    review.add_argument("--draft", required=True)
    review.add_argument("--rules", action="append", default=[])
    review.add_argument("--source", action="append", default=[])
    review.add_argument("--note", action="append", default=[])
    review.add_argument("--budget", type=positive)
    review.add_argument("--no-ticket-keys", action="store_true")
    review.add_argument("--model")
    review.add_argument("--timeout", type=positive, default=DEFAULT_TIMEOUT)
    review.add_argument("--reviews", type=positive, default=DEFAULT_REVIEWS)
    review.add_argument("--runner", default=str(Path(__file__).resolve().with_name("role_runner.py")))
    return parser


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def command_check(args: argparse.Namespace) -> int:
    found = check_text(read_input(args.file), args.kind, args.no_ticket_keys)
    emit({"findings": found})
    return EXIT_FINDINGS if found else EXIT_OK


def command_review(args: argparse.Namespace) -> int:
    draft = read_input(args.draft)
    rules = [(Path(path).name, read_input(path)) for path in args.rules]
    sources = [(Path(path).name, read_input(path)) for path in args.source]
    found = check_text(draft, args.kind, args.no_ticket_keys)
    if found:
        emit({"stage": "check", "findings": found})
        return EXIT_FINDINGS
    model = args.model or REVIEW_MODELS[args.kind]
    base = {"stage": "review", "kind": args.kind, "model": model}
    assignment = build_assignment(args.kind, draft, rules, sources, args.note, args.budget)
    with ThreadPoolExecutor(max_workers=args.reviews) as pool:
        outcomes = list(pool.map(lambda _: review_once(args, assignment, model), range(args.reviews)))
    runners = [outcome["runner"] for outcome in outcomes]
    findings = unique(item for outcome in outcomes for item in outcome.get("findings", []))
    facts = unique(fact for outcome in outcomes for fact in outcome.get("over_budget_facts", []))
    errors = [outcome["error"] for outcome in outcomes if "error" in outcome]
    status = {"runner": runners[0], "runners": runners}
    if findings:
        emit({**base, "findings": findings, "over_budget_facts": facts, **status, **({"errors": errors} if errors else {})})
        return EXIT_FINDINGS
    if errors:
        emit({**base, "error": "; ".join(errors), **status})
        return EXIT_REVIEW_FAILED
    emit({**base, "findings": [], "over_budget_facts": facts, **status})
    return EXIT_OK


def review_once(args: argparse.Namespace, assignment: str, model: str) -> dict:
    try:
        return run_reviewer(args, assignment, model)
    except ReviewFailure as failure:
        return {"error": str(failure), "runner": failure.runner}
    except TextReviewError as failure:
        return {"error": str(failure), "runner": {"exit": None, "verified": None}}


def unique(items) -> list:
    seen, kept = set(), []
    for item in items:
        key = (item.get("type"), item.get("quote")) if isinstance(item, dict) else item
        if key not in seen:
            seen.add(key)
            kept.append(item)
    return kept


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return command_check(args) if args.command == "check" else command_review(args)
    except TextReviewError as error:
        print(f"text_review: {error}", file=sys.stderr)
        return error.code


if __name__ == "__main__":
    sys.exit(main())
