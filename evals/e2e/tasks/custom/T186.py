"""Grade which seeded claims, references, and headings survive a wording edit."""

import re
import runpy

AMBIGUOUS_RESULT = re.compile(r"(?:해당|이|그)\s*(?:측정\s*)?(?:결과|측정값)|\b(?:this|that|the)\s+result\b", re.I)
MEETING = re.compile(r"회의|논의|meeting|discuss", re.I)
RETEST = re.compile(r"재측정|두\s*번째|2차|retest|second", re.I)


def shared(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T182.py"))


def rewrite_reference_read(ctx):
    common = shared(ctx)
    ok = common["instruction_read"](ctx, common["REFERENCE"])
    return common["result"](ok, "rewrite reference read", "rewrite reference was not read")


def wording_and_scope_preserved(ctx):
    common = shared(ctx)
    text = common["read"](ctx, "out/rewrite.md")
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    recording_unresolved = any("817" in sentence and AMBIGUOUS_RESULT.search(sentence)
                               and re.search(r"기록|record", sentence, re.I) for sentence in sentences)
    named = not recording_unresolved and any(
        "817" in part and "617" not in part and RETEST.search(part) for part in re.split(r"\n\s*\n", text)
    )
    meeting_unresolved = any(AMBIGUOUS_RESULT.search(sentence) and MEETING.search(sentence)
                             for sentence in sentences)
    recording_reported = False
    if ctx.task["id"] == "T187" and recording_unresolved:
        answer = common["answer"](ctx)
        names_recording = re.search(r"기록|817|첫\s*(?:번째|문장|인용)|record|first", answer, re.I)
        names_meeting = MEETING.search(answer) or re.search(r"두\s*번째|second", answer, re.I)
        names_both = re.search(r"두\s*(?:곳|군데|지시|표현|문장)|둘\s*다|\bboth\b", answer, re.I)
        recording_reported = unresolved_reference_reported(ctx)[0] and (names_both or (names_recording and names_meeting))
    ok = ((named or recording_reported) and meeting_unresolved
          and "주목할 점은" not in text and "demo-ttl-v2" in text)
    return common["result"](ok, "the reference handling and proposal wording preserve the source's scope",
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
