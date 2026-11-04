#!/usr/bin/env python3
"""Count how often session records show a written rule being missed, and list candidates for a person to classify."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

KINDS = ("reminder", "stop", "denial", "user", "final")
UNMATCHED_KINDS = ("reminder", "stop", "denial")
STOP_PREFIX = "Stop hook feedback:"
DENIAL_PATTERN = re.compile(r"denied by|blocked by|hook error", re.IGNORECASE)
CORRECTION_PATTERN = r"왜\s?.{0,40}?(안\s?했|안\s?한|않았|빠뜨|생략|건너)|규칙|AGENTS|지침|why didn't you|you skipped|you forgot"
NOT_DONE_PATTERN = (
    r"(실행하지 않았|돌리지 않았|하지 않았습니다|건너뛰었|생략했|not run|did not run|skipped|(실행|진행|평가)할까요|shall i run)"
)
EXAMPLE_LIMIT = 3
UNMATCHED_LIMIT = 20
EXAMPLE_TEXT = 160
CANDIDATE_TEXT = 300
EXCERPT_CONTEXT = 150
ELLIPSIS = "…"
SIGNATURE_TEXT = 100


class AuditError(Exception):
    pass


@dataclass(frozen=True)
class Signal:
    kind: str
    session: str
    timestamp: str
    text: str
    previous: str = ""
    file: str = ""
    line: int = 0


def parse_moment(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise AuditError(f"not a date: {value!r}") from error
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def content_text(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
    return "\n".join(part for part in parts if isinstance(part, str))


def tool_result_blocks(content) -> list[dict]:
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict) and block.get("type") == "tool_result"]


def reminder_text(entry: dict) -> str:
    attachment = entry.get("attachment")
    response = attachment.get("response") if isinstance(attachment, dict) else None
    output = response.get("hookSpecificOutput") if isinstance(response, dict) else None
    text = output.get("additionalContext") if isinstance(output, dict) else None
    return text if isinstance(text, str) else ""


def denial_texts(content) -> list[str]:
    texts = []
    for block in tool_result_blocks(content):
        text = content_text(block.get("content"))
        if block.get("is_error") is True and DENIAL_PATTERN.search(text):
            texts.append(text)
    return texts


def entry_signals(entry: dict) -> list[tuple[str, str]]:
    if entry.get("type") != "user":
        return [("reminder", reminder_text(entry))] if reminder_text(entry) else []
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if entry.get("isMeta") is True:
        starts = isinstance(content, str) and content.startswith(STOP_PREFIX)
        return [("stop", content)] if starts else []
    found = [("denial", text) for text in denial_texts(content)]
    text = content_text(content).strip()
    if not tool_result_blocks(content) and text and not text.startswith("<"):
        found.append(("user", text))
    return found


def assistant_text(entry: dict) -> str:
    if entry.get("type") != "assistant":
        return ""
    message = entry.get("message")
    return content_text(message.get("content") if isinstance(message, dict) else None).strip()


def iter_entries(path: Path):
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            yield number, entry


def in_window(entry: dict, since: datetime, until: datetime) -> bool:
    if entry.get("isSidechain") is True or not isinstance(entry.get("timestamp"), str):
        return False
    try:
        moment = parse_moment(entry["timestamp"])
    except AuditError:
        return False
    return since <= moment < until


@dataclass
class FileScan:
    signals: list[Signal]
    sessions: set[str]
    replies: int
    prompts: int


def scan_file(path: Path, since: datetime, until: datetime, label: str) -> FileScan:
    """Scan one record file; label names it relative to its records folder, so no home path reaches a candidate."""
    scan = FileScan([], set(), 0, 0)
    last_reply = Signal("final", "", "", "")
    for number, entry in iter_entries(path):
        if not in_window(entry, since, until):
            continue
        session = entry.get("sessionId") if isinstance(entry.get("sessionId"), str) else path.stem
        scan.sessions.add(session)
        stamp = entry["timestamp"]
        reply = assistant_text(entry)
        if reply:
            scan.replies += 1
            last_reply = Signal("final", session, stamp, reply, "", label, number)
        for kind, text in entry_signals(entry):
            if kind == "user":
                scan.prompts += 1
                if last_reply.text:
                    scan.signals.append(last_reply)
                scan.signals.append(Signal(kind, session, stamp, text, last_reply.text[-CANDIDATE_TEXT:], label, number))
                last_reply = Signal("final", "", "", "")
            else:
                scan.signals.append(Signal(kind, session, stamp, text, "", label, number))
    if last_reply.text:
        scan.signals.append(last_reply)
    return scan


def record_files(folders: list[Path]) -> list[tuple[Path, str]]:
    """Return each main-session record file with its path relative to the records folder that holds it."""
    files = []
    for folder in folders:
        if not folder.is_dir():
            raise AuditError(f"records folder not found: {folder}")
        files.extend(
            (path, path.relative_to(folder).as_posix())
            for path in folder.rglob("*.jsonl")
            if "subagents" not in path.relative_to(folder).parts
        )
    return sorted(files)


def load_rules(path: Path) -> list[dict]:
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AuditError(f"rules file unreadable or invalid: {path}: {error}") from error
    if not isinstance(rules, list):
        raise AuditError("rules file must hold a JSON list")
    return [compile_rule(rule) for rule in rules]


def compile_rule(rule) -> dict:
    valid = isinstance(rule, dict) and isinstance(rule.get("id"), str) and isinstance(rule.get("source"), str)
    kinds, patterns = (rule.get("kinds"), rule.get("patterns")) if valid else (None, None)
    if not (isinstance(kinds, list) and set(kinds) <= set(KINDS) and isinstance(patterns, list)):
        raise AuditError(f"invalid rule entry: {rule!r}")
    try:
        compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    except (re.error, TypeError) as error:
        raise AuditError(f"invalid pattern in rule {rule['id']}: {error}") from error
    return {"id": rule["id"], "source": rule["source"], "kinds": set(kinds), "patterns": compiled}


def matches(rule: dict, signal: Signal) -> bool:
    return signal.kind in rule["kinds"] and any(pattern.search(signal.text) for pattern in rule["patterns"])


def signature(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\d+", "N", re.sub(r"`[^`]*`", "`X`", collapsed))[:SIGNATURE_TEXT]


def rule_report(rule: dict, signals: list[Signal], replies: int) -> dict:
    hits = [signal for signal in signals if matches(rule, signal)]
    return {
        "id": rule["id"],
        "source": rule["source"],
        "sessions": len({signal.session for signal in hits}),
        "hits": len(hits),
        "per_100_replies": round(len(hits) * 100 / replies, 2) if replies else 0.0,
        "examples": [
            {"session": s.session[:8], "timestamp": s.timestamp, "kind": s.kind, "text": s.text[:EXAMPLE_TEXT]}
            for s in hits[:EXAMPLE_LIMIT]
        ],
    }


def unmatched_report(rules: list[dict], signals: list[Signal]) -> list[dict]:
    groups: dict[tuple[str, str], list[Signal]] = defaultdict(list)
    for signal in signals:
        if signal.kind in UNMATCHED_KINDS and not any(matches(rule, signal) for rule in rules):
            groups[(signal.kind, signature(signal.text))].append(signal)
    rows = [
        {"signature": sig, "kind": kind, "sessions": len({s.session for s in group}), "hits": len(group)}
        for (kind, sig), group in groups.items()
    ]
    rows.sort(key=lambda row: (-row["sessions"], -row["hits"], row["signature"], row["kind"]))
    return rows[:UNMATCHED_LIMIT]


def excerpt(text: str, pattern: re.Pattern) -> str:
    found = pattern.search(text)
    if found is None:
        return text[:CANDIDATE_TEXT]
    start, end = max(0, found.start() - EXCERPT_CONTEXT), min(len(text), found.end() + EXCERPT_CONTEXT)
    return f"{ELLIPSIS if start else ''}{text[start:end]}{ELLIPSIS if end < len(text) else ''}"


def candidate_rows(signals: list[Signal], correction: re.Pattern, not_done: re.Pattern) -> list[dict]:
    rows = []
    for signal in signals:
        kind = {"user": "correction", "final": "not-done"}.get(signal.kind)
        pattern = {"correction": correction, "not-done": not_done}.get(kind)
        if pattern is None or not pattern.search(signal.text):
            continue
        rows.append(
            {
                "id": f"cand-{len(rows) + 1:03d}",
                "session": signal.session,
                "timestamp": signal.timestamp,
                "kind": kind,
                "text": excerpt(signal.text, pattern),
                "locator": {"file": signal.file, "line": signal.line},
                "previous": signal.previous if kind == "correction" else "",
            }
        )
    return rows


def audit(args: argparse.Namespace) -> tuple[dict, list[dict]]:
    since, until = parse_moment(args.since), parse_moment(args.until)
    rules = load_rules(Path(args.rules))
    correction, not_done = re.compile(args.correction_pattern, re.IGNORECASE), re.compile(args.not_done_pattern, re.IGNORECASE)
    files = record_files([Path(folder) for folder in args.records])
    scans = [scan_file(path, since, until, label) for path, label in files]
    signals = [signal for scan in scans for signal in scan.signals]
    replies = sum(scan.replies for scan in scans)
    report = {
        "window": {"since": since.isoformat(), "until": until.isoformat()},
        "totals": {
            "files": len(files),
            "sessions": len(set().union(*(scan.sessions for scan in scans))) if scans else 0,
            "replies": replies,
            "prompts": sum(scan.prompts for scan in scans),
        },
        "rules": [rule_report(rule, signals, replies) for rule in rules],
        "unmatched": unmatched_report(rules, signals),
    }
    return report, candidate_rows(signals, correction, not_done)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Count written-rule misses in Claude Code session records.")
    parser.add_argument("--records", action="append", required=True, metavar="DIR", help="a Claude Code projects folder")
    parser.add_argument("--since", required=True, help="YYYY-MM-DD or ISO date-time, UTC, inclusive")
    parser.add_argument("--until", required=True, help="YYYY-MM-DD or ISO date-time, UTC, exclusive")
    parser.add_argument("--rules", required=True, metavar="RULES.json")
    parser.add_argument("--candidates", metavar="OUT.json")
    parser.add_argument("--correction-pattern", default=CORRECTION_PATTERN)
    parser.add_argument("--not-done-pattern", default=NOT_DONE_PATTERN)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report, candidates = audit(args)
        if args.candidates:
            Path(args.candidates).write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (AuditError, re.error, OSError) as error:
        print(f"rule_misses: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
