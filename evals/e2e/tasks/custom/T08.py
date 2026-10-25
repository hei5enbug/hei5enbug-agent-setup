"""Custom check for T08: the whole change is exactly one replaced line."""

from __future__ import annotations


def single_line_changed(ctx):
    stat = [line.split("\t") for line in ctx.git("diff", "--numstat", ctx.base).splitlines() if line]
    ok = len(stat) == 1 and stat[0][:2] == ["1", "1"]
    return ok, f"numstat: {stat}", {"numstat": stat}
