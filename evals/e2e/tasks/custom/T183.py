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
    replies = [common["answer"](ctx)]
    replies.extend(str(call.get("input") or {}) for call in ctx.view.get("tool_calls", [])
                   if call.get("name") in ("AskUserQuestion", "request_user_input", "request_user_input_async"))
    ok = any(re.search(r"표|테이블|table", reply, re.I)
             and re.search(r"빼|뺄|지울|지워|삭제|제거|제외|유지|남길|remove|delete|omit|keep", reply, re.I)
             and common["ASKS"].search(reply) for reply in replies)
    return common["result"](ok, "the user is asked about the table", "the user was not asked about the table")
