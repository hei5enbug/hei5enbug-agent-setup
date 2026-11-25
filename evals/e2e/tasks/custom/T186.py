"""Grade which seeded claims, references, and headings survive a wording edit."""

import re
import runpy


def shared(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T182.py"))


def rewrite_reference_read(ctx):
    common = shared(ctx)
    ok = common["instruction_read"](ctx, common["REFERENCE"])
    return common["result"](ok, "rewrite reference read", "rewrite reference was not read")


def wording_and_scope_preserved(ctx):
    common = shared(ctx)
    text = common["read"](ctx, "out/rewrite.md")
    paragraphs = re.split(r"\n\s*\n", text)
    named = any("817" in part and "617" not in part
                and re.search(r"재측정|두\s*번째|2차|retest|second", part, re.I) for part in paragraphs)
    unresolved = any("해당 결과" in part and "817" not in part for part in paragraphs)
    ok = named and unresolved and text.count("해당 결과") == 1 and "주목할 점은" not in text and "demo-ttl-v2" in text
    return common["result"](ok, "the supported reference was named and the unresolved claim was preserved",
                            "the seeded reference, importance wording, or proposal was mishandled")


def unresolved_reference_reported(ctx):
    common = shared(ctx)
    answer = common["answer"](ctx)
    refers = re.search(r"해당\s*결과|다음\s*회의|가리키|지칭|refer", answer, re.I)
    uncertainty = re.search(r"확인|불명|모호|명확하지|어느|어떤|unclear|ambigu", answer, re.I)
    return common["result"](refers and uncertainty, "the unresolved reference is reported",
                            "the reply does not identify the unresolved reference")


def heading_retained_and_suggestion_reported(ctx):
    common = shared(ctx)
    text = common["read"](ctx, "out/rewrite.md")
    answer = common["answer"](ctx)
    suggestions = re.search(r"제목|표제|heading", answer, re.I)
    has_proposal = re.search(r"제안|추천|명사구|권장|바꾸|suggest|noun phrase", answer, re.I)
    ok = common["BAD_HEADING"] in common["headings"](text) and suggestions and has_proposal
    return common["result"](ok, "the source heading stays and the notes suggest a change",
                            "the source heading changed or its suggested replacement is missing")


def heading_changed(ctx):
    common = shared(ctx)
    text = common["read"](ctx, "out/rewrite.md")
    titles = common["headings"](text)
    ok = common["phrase_headings"](text) and common["BAD_HEADING"] not in titles
    return common["result"](ok, "the seeded heading was replaced", "the seeded heading remains or the title was removed")
