"""Shared by the custom checks of T130 to T132: read the scripted review's run log and the agent's final report."""

from __future__ import annotations

import re
import types
from pathlib import Path

COUNTS_T130 = re.compile(r"(?<!\d)5(?!\d).*?(?<!\d)4(?!\d).*?(?<!\d)6(?!\d)", re.DOTALL)
GO_ON_OPTIONS = re.compile(r"계속|좁히|좁힐|좁혀|지금\s*(?:쓰|작성|반영|마무리)|멈추|멈출|멈춰|멈춘")
ASKS = re.compile(r"[?？]|할까요|할지|바랍니다|알려\s*주")
RECOMMENDS = re.compile(r"추천|권장|권합니다|권해|제안")
NONE_HIGH = re.compile(r"(?:높음|높은|high)[^.\n]{0,30}(?:없|아니|0건|0개|none)|(?:없|0건|none)[^.\n]{0,30}(?:높음|높은|high)",
                       re.IGNORECASE)


def common(ctx):
    path = Path(ctx.tasks_root) / "setup" / "review_loop_common.py"
    module = types.ModuleType("review_loop_common")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def state_of(ctx) -> Path:
    return Path(ctx.origin).parent / "review-state"


def runs_of(ctx) -> list[dict]:
    return common(ctx).log_lines(state_of(ctx))


def answer_of(ctx) -> str:
    return str(ctx.view.get("final_answer", ""))


def read(ctx, relative: str) -> str:
    path = Path(ctx.repo) / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def run_count(ctx, expected: int):
    count = len(runs_of(ctx))
    return count == expected, f"the review ran {count} times, expected exactly {expected}", {}
