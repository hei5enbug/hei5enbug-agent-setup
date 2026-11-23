"""The `rules` command: list the rule groups of the always-loaded session instructions with their bytes."""

from __future__ import annotations

import argparse
import json
from typing import TextIO

from . import rule_groups as rg
from .config import HarnessConfig


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print the groups and totals as JSON, with each group's `remove` entry")
    parser.add_argument("--min-bytes", type=int, default=0, help="list only groups of at least this many bytes")


def print_table(out: TextIO, groups: list[rg.Group], totals: dict[str, int]) -> None:
    out.write(f"{len(groups)} rule groups; file bytes per context: claude {totals['claude']}, codex {totals['codex']}, "
              f"worker core {totals['worker']}\n")
    for group in sorted(groups, key=lambda item: -item.size):
        hosts = "+".join(group.hosts) + ("+worker" if group.in_worker_context else "")
        out.write(f"{group.size:5d} B  {group.slug}  [{hosts}]  start={group.start!r}\n")


def run(args: argparse.Namespace, cfg: HarnessConfig, out: TextIO) -> int:
    groups = rg.list_groups(rg.read_texts(cfg.repo_root))
    totals = rg.host_totals(groups)
    shown = [group for group in groups if group.size >= args.min_bytes]
    if args.json:
        rows = [{"slug": g.slug, "bytes": g.size, "kind": g.kind, "hosts": list(g.hosts), "worker": g.in_worker_context,
                 "remove": g.removal} for g in shown]
        out.write(json.dumps({"totals": totals, "groups": rows}, indent=2) + "\n")
    else:
        print_table(out, shown, totals)
    return 0
