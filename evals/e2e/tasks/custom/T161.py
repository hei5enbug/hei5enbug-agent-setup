"""Check the findings and tool calls of a Korean design document review."""

from __future__ import annotations

import re
import types
from pathlib import Path

SKILL = "technical-design-writer"
TRANSLATIONESE = "translationese.md"
PATTERNS = "patterns.md"
FORMAT_SCRIPT = "check_format.py"
READ_COMMAND = re.compile(r"(?:^|\s)(?:cat|sed|rg|grep|head|tail|nl|less|more|awk|bat)\s")
TRANSLATE_STYLE = (
    r"번역\s*투|직역|영어\s*(?:어순|식)|피동|수동|능동|어색|자연스럽|"
    r"translationese|literal translation|passive|active voice|reword|awkward"
)
QUOTED_WORDS = r"(?:종류|유형)\s*에\s*의해|[`'\"‘’“”]\s*~?에\s*의해\s*[`'\"‘’“”]"
EXPIRY = r"만료\s*(?:시간|기간|시각)|유효\s*기간|유효\s*시간|\bTTL\b|expir(?:y|ation)"
ITEM_TYPE = r"항목\s*(?:의\s*)?(?:종류|유형)|(?:품목|항목|종류|유형)\s*별|item\s*(?:type|kind)|categor(?:y|ies)"
BY_TYPE = rf"(?:{ITEM_TYPE})\s*(?:에\s*따라|별로|마다|로)"
DETERMINES = r"다르|달라|정(?:한다|합니다|해진|해집니다|해요|했다)|결정(?:된다|합니다|한다|됩니다)"
REWRITE = (
    rf"(?:{EXPIRY}).{{0,25}}{BY_TYPE}.{{0,12}}(?:{DETERMINES})|"
    rf"{BY_TYPE}.{{0,25}}(?:{EXPIRY}).{{0,12}}(?:{DETERMINES})|"
    rf"(?:{ITEM_TYPE})\s*(?:이|가)\s*(?:(?:{EXPIRY}).{{0,12}})?(?:{DETERMINES})|"
    rf"(?:{EXPIRY}).{{0,20}}(?:depends on|varies by|differs by|is set by).{{0,20}}(?:{ITEM_TYPE})"
)
LONG_LINE = (
    r"120\s*(?:자|characters?|chars?)|128\s*(?:자|characters?|chars?)|긴\s*줄|"
    r"(?:한\s*줄|줄\s*길이|한\s*행|prose line|line length).{0,35}"
    r"(?:길|초과|넘|한도|제한|limit|long|exceeds?)"
)
HEADING_LEVEL = (
    r"#{4}(?!#)|(?:네\s*번째|4\s*단계|4\s*레벨|4\s*수준)\s*(?:제목|헤딩|소제목)|"
    r"(?:제목|헤딩).{0,24}(?:4\s*(?:단계|레벨|수준)|(?:깊|계층).{0,10}(?:낮|올|깊))|"
    r"(?:fourth|level\s*[- ]?4|h4).{0,16}heading|heading.{0,16}(?:fourth|level\s*[- ]?4|h4)"
)


def mentions(pattern, text):
    return re.search(pattern, text, re.IGNORECASE) is not None


def location(line):
    return rf"(?<!\d){line}\s*(?:번째\s*)?(?:줄|행)|(?:\b(?:line|L)\s*|(?:줄|행)\s*|\.md:){line}(?!\d)"


def findings(ctx):
    return re.split(r"\n\s*\n", ctx.view.get("final_answer") or "")


def translationese_reported(ctx):
    for finding in findings(ctx):
        identifies_source = mentions(QUOTED_WORDS, finding)
        names_style = mentions(TRANSLATE_STYLE, finding)
        identifies_location = mentions(location(13), finding)
        suggests_rewrite = mentions(REWRITE, finding)
        if identifies_source or (names_style and identifies_location) or suggests_rewrite:
            return True, "identified the wording in the expiry rule", {}
    return False, "no translationese finding for the expiry rule", {}


def format_findings_reported(ctx):
    blocks = findings(ctx)
    long_line = any(
        mentions(LONG_LINE, finding)
        or (mentions(location(11), finding) and mentions(r"한도|제한|분량|너무\s*길|limit|too long", finding))
        for finding in blocks
    )
    deep_heading = any(
        mentions(HEADING_LEVEL, finding)
        or (mentions(location(19) + r"|시계\s*기준", finding)
            and mentions(r"상위|올리|올려|단계|계층|promote|depth|hierarchy", finding))
        for finding in blocks
    )
    passed = long_line and deep_heading
    detail = "review reports both format issues" if passed else "missing the long line or the deep heading"
    return passed, detail, {"long_line": long_line, "deep_heading": deep_heading}


def skill_invoked(ctx):
    path = Path(ctx.tasks_root) / "custom" / "skill_use_shared.py"
    module = types.ModuleType("skill_use_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module.skill_invoked(ctx, SKILL)


def reference_reads(ctx, filename):
    path = re.compile(rf"(?<![\w.-]){re.escape(filename)}(?![\w.-])")
    reads = 0
    for call in ctx.view.get("tool_calls", []):
        data = call.get("input") or {}
        if call.get("name") == "Read" and Path(str(data.get("file_path", ""))).name == filename:
            reads += 1
        if call.get("name") == "Bash":
            clauses = re.split(r"[;\n]|&&|\|\|", str(data.get("command", "")))
            reads += any(READ_COMMAND.search(clause) and path.search(clause) for clause in clauses)
    return reads


def read_translationese(ctx):
    count = reference_reads(ctx, TRANSLATIONESE)
    return bool(count), f"{count} read(s) of {TRANSLATIONESE}", {}


def patterns_not_read(ctx):
    count = reference_reads(ctx, PATTERNS)
    return not count, f"{count} read(s) of {PATTERNS}", {}


def format_script_ran(ctx):
    runs = [call for call in ctx.view.get("tool_calls", []) if call.get("name") == "Bash"
            and FORMAT_SCRIPT in str((call.get("input") or {}).get("command", ""))]
    return bool(runs), f"{len(runs)} run(s) of {FORMAT_SCRIPT}", {}
