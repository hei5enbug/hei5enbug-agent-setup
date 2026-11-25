"""Grade seeded options and case figures in the research-report skill cases."""

import csv
import re
from pathlib import Path

IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^>\s)]+)>?(?:\s+[^)]*)?\s*\)|<img\b[^>]*\bsrc=['\"]([^'\"]+)", re.I)
LONGEST = re.compile(r"(?:가장|제일)\s*(?:긴|길|오래|큰)|최장|최대|\b(?:longest|slowest|largest|max(?:imum)?)\b", re.I)
CRITERION = re.compile(r"기준|선정|가장|최장|최대|대표|선택|큰|긴|짧|높|낮|criteri(?:on|a)|highest|lowest", re.I)
ALL_RECORDED_CASES = re.compile(
    r"(?=.*(?:모두|전부|전체|빠짐없이|\ball\b|\bevery\b))(?=.*(?:기록|자료|제공|\brecord|\blog|\bsource|\.csv))"
    r"(?=.*(?:사례|요청|\bcase|\brequest))", re.I,
)
CASE_BLOCK_BOUNDARY = re.compile(
    r"\n[ \t]*\n|\n(?=[ \t]*(?:\||!\[|<img\b|<svg\b))", re.I,
)
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


def case_evidence(ctx, text, labels):
    identifier = re.compile(rf"(?<![A-Za-z0-9_-])(?:{'|'.join(map(re.escape, labels))})(?![A-Za-z0-9_-])")
    shown, criteria, figures, longest_claims = set(), set(), set(), set()
    coverage_scopes, coverage_groups = [], []
    for section in re.split(r"(?m)(?=^#{1,6}[ \t])", text):
        heading, content = "", section
        if section.startswith("#"):
            heading, _, content = section.partition("\n")
        level = len(heading) - len(heading.lstrip("#"))
        blocks = CASE_BLOCK_BOUNDARY.split(content)
        section_cases = set(identifier.findall(section))
        shown.update(section_cases)

        coverage_scopes = [(depth, cases) for depth, cases in coverage_scopes if depth < level]
        if any(ALL_RECORDED_CASES.search(block.replace("\n", " ")) for block in blocks):
            coverage = set()
            coverage_groups.append(coverage)
            coverage_scopes.append((level, coverage))
        for _, coverage in coverage_scopes:
            coverage.update(section_cases)

        if len(section_cases) == 1:
            case = next(iter(section_cases))
        else:
            case = None
        for block in [heading, *blocks]:
            named = set(identifier.findall(block))
            if named:
                case = next(iter(named)) if len(named) == 1 else None
            if case is None:
                continue
            if case_has_figure(ctx, block):
                figures.add(case)
            if named or (block == heading and len(section_cases) == 1):
                if LONGEST.search(block):
                    longest_claims.add(case)
                    criteria.add(case)
                elif CRITERION.search(block):
                    criteria.add(case)

    if any(labels <= coverage for coverage in coverage_groups):
        criteria.update(labels)
    return shown, criteria, figures, longest_claims


def longest_case_illustrated(ctx):
    text = report(ctx)
    cases = seed(ctx, "notes/cases.csv")
    longest = max(cases, key=lambda case: int(case["duration_ms"]))["case_id"]
    shown, criteria, figures, longest_claims = case_evidence(ctx, text, {case["case_id"] for case in cases})
    for label in sorted(shown):
        if label not in criteria:
            return False, f"{label} has no selection criterion", {}
        if label not in figures:
            return False, f"{label} has no embedded figure", {}
    for label in sorted(longest_claims - {longest}):
        return False, f"{label} is not the longest seeded case", {}
    return value(longest in longest_claims, "the longest seeded case has its criterion and a figure",
                 "the longest seeded case or its selection criterion is missing")
