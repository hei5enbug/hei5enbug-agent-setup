"""Grade seeded evidence in a research document without prescribing its prose."""

import re
from pathlib import Path

RULE = "instructions/research-documents.md"
REFERENCE = "docs-rewrite/references/research-documents.md"
BAD_HEADING = "demo-b는 demo-a보다 느리다"
READER = re.compile(r"(?:^|[\s;&|(])(?:cat|sed|rg|grep|head|tail|nl|awk|bat)\s")
ASKS = re.compile(r"[?？]|할까요|할지|해도\s*될|주시겠|would you|should (?:I|we)", re.I)
RULE_TITLES = {RULE: "# Research and verification documents", REFERENCE: "# Rewriting research and verification documents"}
MAJORITY = re.compile(r"대부분|대다수|거의\s*모든")
UNCONFIRMED = re.compile(
    r"(?:확인|판단|검증|단정|입증)\w*\s*(?:할\s*수\s*없|하지\s*못|하기\s*어렵|되지\s*않|되지\s*못|불가)"
    r"|근거\w*\s*없|(?:cannot|could not)\s+(?:confirm|verify|determine)", re.I
)
LIMITATION_LINK = re.compile(
    r"따라서|그러므로|그러나|다만|하지만|때문에|이에 따라|이로 인해|그 결과|\b(?:therefore|however|thus|because|so)\b", re.I
)
SLOWER_OBSERVATION = re.compile(
    r"demo-b(?!\s*보다)[^.!?]*?(?:느[리린렸려]|길[었다어고게]|긴|오래|높[았은]|slower|longer|higher|more time)", re.I
)


def read(ctx, path):
    file = Path(ctx.repo) / path
    return file.read_text(encoding="utf-8") if file.is_file() else ""


def answer(ctx):
    return str(ctx.view.get("final_answer", ""))


def instruction_read(ctx, path):
    for call in ctx.view.get("tool_calls", []):
        if call.get("is_error"):
            continue
        fields = call.get("input") or {}
        if call.get("name") == "Read" and path in str(fields.get("file_path", "")):
            return True
        command = str(fields.get("command", ""))
        output = str(call.get("result_text") or "")
        matched = path in command or ("research-documents.md" in command and RULE_TITLES[path] in output)
        if call.get("name") == "Bash" and matched and READER.search(command):
            if output and not re.search(r"no such file|file not found|permission denied|exit code [1-9]", output, re.I):
                return True
    return False


def result(ok, success, failure):
    return bool(ok), success if ok else failure, {}


def headings(text):
    return [match.group(1).strip() for match in re.finditer(r"^#{1,6}\s+(.+)$", text, re.M)]


def phrase_headings(text):
    titles = headings(text)
    sentence_end = re.compile(r"(?:이다|있다|없다|였다|한다|했다|된다|됐다|느리다|빠르다|길다|짧다|넘는다|[습입합됩]니다|[!?])\.?$")
    return titles and all(not sentence_end.search(title) for title in titles)


def table_has(text, rows):
    table_rows = [line for line in text.splitlines() if line.count("|") >= 2]
    return all(any(label in row and re.search(rf"(?<![\d.]){value}(?![\d.])", row) for row in table_rows)
               for label, value in rows)


def related_blocks(text):
    return [block for block in re.split(r"\n\s*\n|\n(?=\s*[-*]\s)", text)
            if any("demo-b" in line and "|" not in line and not line.startswith("#")
                   for line in block.splitlines())]


def research_rules_read(ctx):
    return result(instruction_read(ctx, RULE), "research rules read", "research rules were not read")


def observed_table_kept(ctx):
    text = read(ctx, "out/report.md")
    return result(table_has(text, (("demo-a", "172"), ("demo-b", "348"))),
                  "both observations are in the table", "the observed table or a row is missing")


def seeded_noise_removed(ctx):
    text = read(ctx, "out/report.md")
    blocks = "\n".join(line for line in text.splitlines() if line.count("|") < 2)
    excluded = (
        "핵심은", "이것은", "demo-clock-old", "demo-ttl-v2", "TTL", "demo-weekend-boost", BAD_HEADING,
    )
    unwanted = [item for item in excluded if item in blocks]
    sentences = re.split(r"(?<=[.!?])\s+|\n\s*\n|지만\s+|[,，;]\s*(?:그러나|다만|하지만)\s+", blocks)
    unwanted.extend(match.group() for sentence in sentences for match in MAJORITY.finditer(sentence)
                    if not UNCONFIRMED.search(sentence, match.end()))
    unwanted.extend(re.findall(r"(?<!\d)(?:172|348)\s*(?:ms|밀리초)", blocks, re.I))
    return result(text and not unwanted, "seeded noise and repeated values are absent", f"unwanted items: {unwanted}")


def table_interpreted(ctx):
    text = read(ctx, "out/report.md")
    interpretation = any(
        re.search(r"목표|기준|한도|threshold|target", block, re.I)
        and re.search(r"넘|초과|상회|exceed|above|over", block, re.I)
        for block in related_blocks(text)
    )
    return result(phrase_headings(text) and interpretation, "a noun-phrase heading and the target comparison are present",
                  "the target comparison or replacement heading is missing")


def limitation_with_conclusion(ctx):
    text = read(ctx, "out/report.md")
    prose = "\n".join(line for line in text.splitlines() if line.count("|") < 2)
    blocks = re.split(r"\n\s*\n|\n(?=\s*[-*]\s)", prose)

    def gives_limitation(block):
        weekday = re.search(r"평일|2026-10-07|weekday", block, re.I)
        one_day = re.search(r"하루|한\s*(?:날|날짜|번)|(?<!\d)1\s*일|2026-10-07|single|one.day", block, re.I)
        weekend = re.search(r"주말|weekend", block, re.I)
        coverage = re.search(r"않|못|제외|빠[졌진]|없|어렵|불가|except|not|outside|lack|omit|unmeasured", block, re.I)
        return weekday and one_day and weekend and coverage

    for index, block in enumerate(blocks):
        if not related_blocks(block) or not SLOWER_OBSERVATION.search(block):
            continue
        if gives_limitation(block) or any(
            (LIMITATION_LINK.search(adjacent) or LIMITATION_LINK.search(block)) and gives_limitation(adjacent)
            and not re.search(r"^\s*#", adjacent, re.M)
            for adjacent in blocks[max(0, index - 1):index] + blocks[index + 1:index + 2]
        ):
            return True, "sample limitation and its effect accompany the conclusion", {}
    return False, "no comparison block gives both the weekday sample and its effect on weekend coverage", {}
