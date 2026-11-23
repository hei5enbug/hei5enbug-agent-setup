"""Entry point: run | summarize | regrade | export-plugin | pilot-check | record."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path[0] = str(Path(__file__).resolve().parents[1])

from harness import campaign, command, measure_lock, plugin_export, records, summarize  # noqa: E402
from harness.config import (  # noqa: E402
    DEFAULT_PARALLEL, DEFAULT_RUN_ROOT, EXIT_FAILURE, EXIT_LOCK_HELD, HOST_CLAUDE, MEASURE_LOCK, HarnessConfig,
)
from harness.pilot_check import pilot_check  # noqa: E402


def split(value: str | None) -> list[str]:
    return [item for item in (value or "").split(",") if item]


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--tasks-root", type=Path, default=None)
    parser.add_argument("--variants-root", type=Path, default=None)
    parser.add_argument("--fixtures-root", type=Path, default=None)


def add_review_stand_in(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--claude-review-stand-in", action="store_true",
                        help="export the plugin with the text reviewer model replaced by claude-sonnet-5-5, for Claude-only runs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="e2e-harness", description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="run or resume a campaign")
    add_common(run)
    add_review_stand_in(run)
    run.add_argument("--campaign", default="default")
    run.add_argument("--tasks", help="comma-separated task ids; default all")
    run.add_argument("--variants", default="baseline", help="comma-separated variant names")
    run.add_argument("--hosts", default=HOST_CLAUDE, help="comma-separated hosts that run each task: claude, codex")
    run.add_argument("--reps", type=int, default=1)
    run.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    run.add_argument("--only-rerun", help="comma-separated run ids to rerun even when complete")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--wait-lock", type=float, default=0.0, metavar="SECONDS",
                     help="wait up to this long for the machine-wide measurement lock instead of exiting at once")
    run.add_argument("--lock-file", type=Path, default=MEASURE_LOCK, help="measurement lock file; the default is shared by every campaign")
    run.add_argument("--allow-changed-inputs", action="store_true",
                     help="resume although a variant ref, task, hidden test, or custom check changed since the campaign began")
    summary = sub.add_parser("summarize", help="print campaign tables")
    add_common(summary)
    summary.add_argument("--campaign", required=True)
    summary.add_argument("--compare", help="two variant names, A,B")
    summary.add_argument("--out", type=Path)
    regrade = sub.add_parser("regrade", help="re-grade finished runs from their saved work repos")
    add_common(regrade)
    regrade.add_argument("--campaign", required=True)
    regrade.add_argument("--run-ids", help="comma-separated run ids; default all")
    regrade.add_argument("--recollect", action="store_true", help="copy the host records again before grading")
    export = sub.add_parser("export-plugin", help="export a plugin revision")
    add_common(export)
    add_review_stand_in(export)
    export.add_argument("--ref", required=True)
    check = sub.add_parser("pilot-check", help="validate finished runs")
    add_common(check)
    check.add_argument("--campaign", required=True)
    check.add_argument("--run-ids", help="comma-separated run ids; default all")
    record = sub.add_parser("record", help="judge a before and an after variant on both hosts and write its record")
    add_common(record)
    record.add_argument("--campaign", required=True)
    record.add_argument("--issue", type=int, required=True, help="issue number; the record is records/<issue>.json")
    record.add_argument("--before", required=True, help="variant name of the before side")
    record.add_argument("--after", required=True, help="variant name of the after side")
    record.add_argument("--claim", help="comma-separated measures the change claims to lower: wall_seconds, cost_usd")
    record.add_argument("--claim-cases", help="comma-separated cases the claim applies to; every case without it")
    record.add_argument("--tasks", help="comma-separated task ids; default every task with a finished run")
    record.add_argument("--hook-facts", action="store_true",
                        help="add the informational hook time and denials of each run, replayed from its recorded tool calls")
    record.add_argument("--records-dir", type=Path, default=records.RECORDS_DIR)
    return parser


def absolute(path: Path) -> Path:
    return path.expanduser().resolve()


def config_from(args: argparse.Namespace) -> HarnessConfig:
    base = HarnessConfig()
    return HarnessConfig(
        run_root=absolute(args.run_root),
        tasks_root=absolute(args.tasks_root or base.tasks_root),
        fixtures_root=absolute(args.fixtures_root or base.fixtures_root),
        variants_root=absolute(args.variants_root or base.variants_root),
        review_stand_in=bool(getattr(args, "claude_review_stand_in", False)),
        codex_bin=shutil.which(base.codex_bin) or base.codex_bin,
    )


def do_run(args: argparse.Namespace, cfg: HarnessConfig) -> int:
    task_ids = split(args.tasks) or campaign.discover_tasks(cfg)
    variant_names = split(args.variants)
    hosts = command.validate_hosts(split(args.hosts))
    cfg = command.resolve_host_binaries(cfg, hosts)
    if not task_ids or not variant_names or args.reps < 1:
        raise command.ConfigError("need at least one task, one variant, and reps >= 1")
    if args.dry_run:
        tasks, variants = campaign.load_plan(cfg, task_ids, variant_names)
        campaign.print_plan(sys.stdout, cfg, campaign.build_specs(cfg, args.campaign, task_ids, variant_names, args.reps, hosts), tasks, variants)
        return 0
    with measure_lock.hold(args.command_line, absolute(args.lock_file), args.wait_lock):
        return campaign.run_campaign(
            cfg, args.campaign, task_ids, variant_names, args.reps, args.parallel, frozenset(split(args.only_rerun)), sys.stdout,
            allow_changed_inputs=args.allow_changed_inputs, hosts=hosts,
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


def do_record(args: argparse.Namespace, cfg: HarnessConfig) -> int:
    if args.issue < 1:
        raise command.ConfigError("--issue takes a positive issue number")
    result = records.record_campaign(
        cfg.run_root, args.campaign, args.issue, args.before, args.after, split(args.claim), split(args.tasks) or None,
        args.hook_facts, split(args.claim_cases) or None,
    )
    path = records.write_record(result["record"], absolute(args.records_dir))
    sys.stdout.write("".join(f"{line}\n" for line in records.report_lines(result)))
    sys.stdout.write(f"record written: {path.name}\n")
    return 0


def dispatch(args: argparse.Namespace) -> int:
    cfg = config_from(args)
    if args.action == "run":
        return do_run(args, cfg)
    if args.action == "summarize":
        return do_summarize(args, cfg)
    if args.action == "record":
        return do_record(args, cfg)
    if args.action == "regrade":
        return campaign.regrade_campaign(
            cfg, args.campaign, frozenset(split(args.run_ids)), sys.stdout, recollect=args.recollect,
        )
    if args.action == "export-plugin":
        info = plugin_export.export_plugin(cfg.repo_root, cfg.run_root, args.ref, review_stand_in=cfg.review_stand_in)
        sys.stdout.write(f"{info['ref']} {info['sha']} {info['path']}\n")
        transform = info.get("cap_transform") or {}
        sys.stdout.write(f"cap transform: replaced {transform.get('count', 0)} model ids {transform.get('replaced', {})}\n")
        if info.get("review_stand_in"):
            sys.stdout.write(f"review stand-in: {info['review_stand_in']['model']}\n")
        return 0
    return pilot_check(cfg.run_root, args.campaign, frozenset(split(args.run_ids)), sys.stdout)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(arguments)
    args.command_line = "cli.py " + " ".join(arguments)
    try:
        return dispatch(args)
    except measure_lock.MeasureLockHeld as error:
        sys.stderr.write(f"error: {error}\n")
        return EXIT_LOCK_HELD
    except (command.ConfigError, plugin_export.ExportError, records.RecordError) as error:
        sys.stderr.write(f"error: {error}\n")
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
