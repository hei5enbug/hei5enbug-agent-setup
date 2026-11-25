"""Grade disposition of two seeded review findings."""

import re
import runpy


def shared(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T182.py"))


def wording_fixed(ctx):
    common = shared(ctx)
    text = common["read"](ctx, "out/report.md")
    ok = "demo-cache" in text and "설정" in text and "반영을 수행" not in text
    return common["result"](ok, "the seeded wording was revised", "the wording fix or its subject is missing")


def regional_table_kept(ctx):
    common = shared(ctx)
    text = common["read"](ctx, "out/report.md")
    ok = common["table_has"](text, (("demo-north", "241"), ("demo-south", "382")))
    return common["result"](ok, "the required regional table is present", "a regional observation is missing")


def asks_about_table(ctx):
    common = shared(ctx)
    if not regional_table_kept(ctx)[0]:
        return common["result"](False, "", "the required regional table was removed")
    answer = common["answer"](ctx)
    replies = [answer]
    replies.extend(str(call.get("input") or {}) for call in ctx.view.get("tool_calls", [])
                   if call.get("name") in ("AskUserQuestion", "request_user_input", "request_user_input_async"))
    table = re.compile(r"표|테이블|\btable\b", re.I)
    asked = any(table.search(reply)
                and re.search(r"빼|뺄|지울|지워|삭제|제거|제외|유지|남길|remove|delete|omit|keep", reply, re.I)
                and common["ASKS"].search(reply) for reply in replies)
    kept_as_requested = any(
        table.search(paragraph)
        and re.search(r"요청|asked|requested", paragraph, re.I)
        and re.search(
            r"유지|보존|남겼|그대로\s*(?:두|뒀)|(?:반영|적용|삭제|제거)하지\s*않"
            r"|kept|retained|left\s+in|did\s+not\s+(?:remove|delete)", paragraph, re.I
        )
        for paragraph in re.split(r"\n\s*\n", answer)
    )
    return common["result"](asked or kept_as_requested, "the reply addresses whether to remove the table",
                            "the reply neither asks about the table nor explains why it was kept")
