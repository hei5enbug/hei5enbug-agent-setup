"""Grade seeded options and case figures in the research-report skill cases."""

import csv
import re
from pathlib import Path

IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^>\s)]+)>?(?:\s+[^)]*)?\s*\)|<img\b[^>]*\bsrc=['\"]([^'\"]+)", re.I)
LONGEST = re.compile(r"가장\s*(?:긴|길|오래|큰)|최장|최대|제일\s*(?:긴|길|오래)|longest|max(?:imum)?", re.I)
CRITERION = re.compile(r"기준|선정|가장|최장|최대|대표|선택|큰|긴|짧|높|낮|criterion|longest|highest|lowest", re.I)
UNVERIFIED = re.compile(r"미검증|검증[^.\n]{0,20}(?:실패|않|못|미완료)|확인되지|unverified|not\s+verified|incomplete", re.I)
NEXT_CANDIDATE = re.compile(r"다음\s*후보|후속\s*(?:후보|작업)|추가\s*검토\s*후보|future\s*work|next\s*candidate", re.I)


def report(ctx):
    path = ctx.repo / "out/report.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def seed(ctx, relative):
    with (ctx.repo / relative).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def token(text, item):
    return re.search(rf"(?<![A-Za-z0-9_-]){re.escape(item)}(?![A-Za-z0-9_-])", text)


def number(text, amount):
    return re.search(rf"(?<![\d.]){re.escape(amount)}(?![\d.])", text)


def value(ok, passed, failed):
    return bool(ok), passed if ok else failed, {}


def tables(text):
    for block in re.split(r"\n\s*\n", text):
        rows = [line.strip().strip("|").split("|") for line in block.splitlines() if line.count("|") >= 2]
        if len(rows) > 2 and any(all(re.fullmatch(r"\s*:?-+:?\s*", cell) for cell in row) for row in rows):
            yield rows


def matching_columns(table, option):
    for row in table:
        if not any(token(cell, option["option"]) for cell in row):
            continue
        success = {i for i, cell in enumerate(row) if number(cell, option["success_pct"])}
        latency = {i for i, cell in enumerate(row) if number(cell, option["p95_ms"])}
        if success and latency:
            yield from ((a, b) for a in success for b in latency if a != b)


def verified_tables(ctx, text):
    verified = [option for option in seed(ctx, "notes/options.csv") if option["verification"] == "complete"]
    for table in tables(text):
        for oriented in (table, tuple(zip(*table))):
            columns = [set(matching_columns(oriented, option)) for option in verified]
            if set.intersection(*columns):
                yield table
                break


def options_share_table(ctx):
    ok = any(verified_tables(ctx, report(ctx)))
    return value(ok, "all verified options share both measure columns", "no table aligns both measures for A, B, and C")


def unverified_option_omitted(ctx):
    text = report(ctx)
    ok = bool(text) and not token(text, "D") and not NEXT_CANDIDATE.search(text)
    return value(ok, "D and future-candidate content are absent", "unchecked D or a future-candidate line remains")


def requested_option_marked(ctx):
    text = report(ctx)
    mixed = any(token(cell, "D") for table in verified_tables(ctx, text) for row in table for cell in row)
    sections = re.split(r"\n(?=#{1,6}\s)", text)
    marked = any(token(section, "D") and UNVERIFIED.search(section) for section in sections)
    return value(marked and not mixed, "D is present and marked apart from verified options",
                 "D is missing, unmarked, or mixed into the verified table")


def case_has_figure(ctx, fragment):
    for markdown_path, html_path in IMAGE.findall(fragment):
        target = markdown_path or html_path
        if re.match(r"^[a-z]+:", target, re.I):
            continue
        path = (ctx.repo / "out" / target).resolve()
        if path.is_relative_to(ctx.repo.resolve()) and path.is_file():
            return True
    return "<svg" in fragment and "</svg>" in fragment


def longest_case_illustrated(ctx):
    text = report(ctx)
    cases = seed(ctx, "notes/cases.csv")
    longest = max(cases, key=lambda case: int(case["duration_ms"]))["case_id"]
    positions = []
    for case in cases:
        label = case["case_id"]
        match = token(text, label)
        if match:
            positions.append((text.rfind("\n", 0, match.start()) + 1, label))
    positions.sort()
    correct_longest = False
    for index, (start, label) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        fragment = text[start:end]
        heading = text[max(0, text.rfind("\n\n", 0, start - 1)):start]
        context = heading + fragment
        if not CRITERION.search(context) or not case_has_figure(ctx, fragment):
            return False, f"{label} has no criterion or embedded figure", {}
        if LONGEST.search(context):
            if label != longest:
                return False, f"{label} is not the longest seeded case", {}
            correct_longest = True
    return value(correct_longest, "the longest seeded case has its criterion and a figure",
                 "the longest seeded case or its selection criterion is missing")
