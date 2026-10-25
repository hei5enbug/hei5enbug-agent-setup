"""Entry point: run | summarize | regrade | export-plugin | pilot-check."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path[0] = str(Path(__file__).resolve().parents[1])

from harness import campaign, command, plugin_export, summarize  # noqa: E402
from harness.config import DEFAULT_PARALLEL, DEFAULT_RUN_ROOT, EXIT_FAILURE, HarnessConfig  # noqa: E402
from harness.pilot_check import pilot_check  # noqa: E402


def split(value: str | None) -> list[str]:
    return [item for item in (value or "").split(",") if item]


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--tasks-root", type=Path, default=None)
    parser.add_argument("--variants-root", type=Path, default=None)
    parser.add_argument("--fixtures-root", type=Path, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="e2e-harness", description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="run or resume a campaign")
    add_common(run)
    run.add_argument("--campaign", default="default")
    run.add_argument("--tasks", help="comma-separated task ids; default all")
    run.add_argument("--variants", default="baseline", help="comma-separated variant names")
    run.add_argument("--reps", type=int, default=1)
    run.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    run.add_argument("--only-rerun", help="comma-separated run ids to rerun even when complete")
    run.add_argument("--dry-run", action="store_true")
    summary = sub.add_parser("summarize", help="print campaign tables")
    add_common(summary)
    summary.add_argument("--campaign", required=True)
    summary.add_argument("--compare", help="two variant names, A,B")
    summary.add_argument("--out", type=Path)
    regrade = sub.add_parser("regrade", help="re-grade finished runs from their saved work repos")
    add_common(regrade)
    regrade.add_argument("--campaign", required=True)
    regrade.add_argument("--run-ids", help="comma-separated run ids; default all")
    export = sub.add_parser("export-plugin", help="export a plugin revision")
    add_common(export)
    export.add_argument("--ref", required=True)
    check = sub.add_parser("pilot-check", help="validate finished runs")
    add_common(check)
    check.add_argument("--campaign", required=True)
    check.add_argument("--run-ids", help="comma-separated run ids; default all")
    return parser


def config_from(args: argparse.Namespace) -> HarnessConfig:
    base = HarnessConfig()
    return HarnessConfig(
        run_root=args.run_root,
        tasks_root=args.tasks_root or base.tasks_root,
        fixtures_root=args.fixtures_root or base.fixtures_root,
        variants_root=args.variants_root or base.variants_root,
    )


def do_run(args: argparse.Namespace, cfg: HarnessConfig) -> int:
    task_ids = split(args.tasks) or campaign.discover_tasks(cfg)
    variant_names = split(args.variants)
    if not task_ids or not variant_names or args.reps < 1:
        raise command.ConfigError("need at least one task, one variant, and reps >= 1")
    if args.dry_run:
        tasks, variants = campaign.load_plan(cfg, task_ids, variant_names)
        campaign.print_plan(sys.stdout, cfg, campaign.build_specs(cfg, args.campaign, task_ids, variant_names, args.reps), tasks, variants)
        return 0
    return campaign.run_campaign(
        cfg, args.campaign, task_ids, variant_names, args.reps, args.parallel, frozenset(split(args.only_rerun)), sys.stdout,
    )


def do_summarize(args: argparse.Namespace, cfg: HarnessConfig) -> int:
    pair = split(args.compare)
    if pair and len(pair) != 2:
        raise command.ConfigError("--compare takes exactly two variant names, A,B")
    text = summarize.summarize(cfg.run_root, args.campaign, (pair[0], pair[1]) if pair else None)
    sys.stdout.write(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


def dispatch(args: argparse.Namespace) -> int:
    cfg = config_from(args)
    if args.action == "run":
        return do_run(args, cfg)
    if args.action == "summarize":
        return do_summarize(args, cfg)
    if args.action == "regrade":
        return campaign.regrade_campaign(cfg, args.campaign, frozenset(split(args.run_ids)), sys.stdout)
    if args.action == "export-plugin":
        info = plugin_export.export_plugin(cfg.repo_root, cfg.run_root, args.ref)
        sys.stdout.write(f"{info['ref']} {info['sha']} {info['path']}\n")
        return 0
    return pilot_check(cfg.run_root, args.campaign, frozenset(split(args.run_ids)), sys.stdout)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except (command.ConfigError, plugin_export.ExportError) as error:
        sys.stderr.write(f"error: {error}\n")
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
