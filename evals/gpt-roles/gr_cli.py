#!/usr/bin/env python3
"""GPT role comparison: run one case with one candidate, build the language results, and decide from the result files.

  python3 evals/gpt-roles/gr_cli.py plan
  python3 evals/gpt-roles/gr_cli.py run <case> <model> --out <folder> [--rep 1]
  python3 evals/gpt-roles/gr_cli.py language-results --out <folder>
  python3 evals/gpt-roles/gr_cli.py decide --out <folder>
  python3 evals/gpt-roles/gr_cli.py ties --out <folder> --role <role>

`run` writes <folder>/results/<role>__<case>__<model>__r<rep>.json and exits 0 whenever it wrote one, whether the case passed or
not; it exits 3 when the run could not be graded. Starting `run` or the language writers is the only step that costs model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gr_cases  # noqa: E402
import gr_core  # noqa: E402
import gr_decide  # noqa: E402
import gr_language  # noqa: E402
import gr_run  # noqa: E402

EXIT_UNGRADED = 3
ROLE_CANDIDATES = {
    "reviewer": gr_core.SOL_CANDIDATES, "text_review": gr_core.SOL_CANDIDATES, "opponent": gr_core.SOL_CANDIDATES,
    "language": gr_core.SOL_CANDIDATES, "worker": gr_core.ALL_CANDIDATES, "scout": gr_core.LUNA_CANDIDATES,
    "researcher": gr_core.LUNA_CANDIDATES,
}


def command_plan(args: argparse.Namespace) -> int:
    rows = []
    for role, cases in gr_cases.ROLE_CASES.items():
        for case_id in cases:
            case = gr_cases.CASES[case_id]
            rows.append({"role": role, "case": case_id, "source": case.source, "effort": case.effort, "models": list(ROLE_CANDIDATES[role])})
    rows.append({"role": "language", "case": "t1,t3,t5", "source": "existing", "effort": gr_language.EFFORT, "models": list(ROLE_CANDIDATES["language"])})
    print(json.dumps(rows, indent=1))
    return 0


def command_run(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    plugin = out / "plugin"
    if not (plugin / "scripts" / "role_runner.py").is_file():
        gr_core.plugin_copy(plugin, args.ref)
    try:
        result = gr_run.execute(args.case, args.model, out, args.rep, plugin)
    except gr_run.CaseError as error:
        print(json.dumps({"case": args.case, "model": args.model, "error": str(error)}))
        return EXIT_UNGRADED
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_language_results(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    found = gr_language.results(out / "kw")
    for result in found:
        gr_core.write_result(out, result)
    print(json.dumps({"written": len(found)}))
    return 0


def command_decide(args: argparse.Namespace) -> int:
    print(json.dumps(gr_decide.registry_plan(gr_core.load_results(Path(args.out).resolve())), indent=1))
    return 0


def command_ties(args: argparse.Namespace) -> int:
    group = gr_decide.tie_models(gr_core.load_results(Path(args.out).resolve()), args.role, ROLE_CANDIDATES[args.role])
    print(json.dumps(group))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan").set_defaults(handler=command_plan)
    run = commands.add_parser("run")
    run.add_argument("case", choices=sorted(gr_cases.CASES))
    run.add_argument("model", choices=gr_core.ALL_CANDIDATES)
    run.add_argument("--out", required=True)
    run.add_argument("--rep", type=int, default=1)
    run.add_argument("--ref", default="HEAD", help="revision exported for the plugin copy")
    run.set_defaults(handler=command_run)
    for name, handler in (("language-results", command_language_results), ("decide", command_decide), ("ties", command_ties)):
        sub = commands.add_parser(name)
        sub.add_argument("--out", required=True)
        if name == "ties":
            sub.add_argument("--role", required=True, choices=sorted(ROLE_CANDIDATES))
        sub.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
