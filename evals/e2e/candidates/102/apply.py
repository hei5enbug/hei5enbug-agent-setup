#!/usr/bin/env python3
"""Apply one candidate loop shape of issue 102 to a checkout of the plugin, or show what it would change.

a  worker-run loop: the independent text review of `instructions/shared-text.md` is handed to a `language` worker.
b  two reviewers per run: `scripts/text_review.py` runs two reviewers by default.
c  changed-sentence trims: from the second run of a draft on, `scripts/text_review.py` lists the sentences changed since
   the previous run and drops a `removable` finding outside them, except in a sentence an earlier run flagged.
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trim_code import CODE as TRIM_CODE  # noqa: E402

SCRIPT = "scripts/text_review.py"
RULES = "instructions/shared-text.md"
COUNT_BULLET = (
    "- Count only runs that reach the reviewer. When the fourth such run for one draft still returns findings, post\n"
    "  nothing, show the user the remaining findings, and ask.\n"
)
WORKER_BULLET = """- A session that must run this review on a text it wrote hands the draft, `--kind`, the `--rules` and `--source` files,
  any `--budget`, `--no-ticket-keys`, or `--runner` option, and the stop rules above to a worker of the `language`
  capability, and names the file where the worker saves the reviewed text. The worker applies each run's findings, or
  passes its reason with `--note`, and runs the review again until a run returns no findings or a stop rule applies;
  it never posts. It returns the reviewed text or the stop, with each finding and how it was applied or why it was
  kept. Read the change from your draft to the reviewed text once, post a clean text, and on a stop follow the stop
  rules above as they stand.
"""
HISTORY_BULLET = """- Pass the same `--history <file>` on every run of one draft, so that from the second run on the review lists the
  sentences changed since the previous run and drops a `removable` finding outside them, except in a sentence an
  earlier run flagged.
"""
COMPARE_BULLET = "- Compare each finding with the findings of the earlier runs of the same draft."
SCRIPT_EDITS = {
    "b": (("DEFAULT_REVIEWS = 1\n", "DEFAULT_REVIEWS = 2\n"),),
    "c": (
        ("import argparse\nimport hashlib\n", "import argparse\nimport difflib\nimport hashlib\n"),
        ("def build_assignment(", TRIM_CODE + "def build_assignment("),
        ("                     advisories: list[dict]) -> str:\n",
         "                     advisories: list[dict], trim: dict | None = None) -> str:\n"),
        ("    parts += flagged_section(advisories)\n", "    parts += flagged_section(advisories)\n    parts += trim_section(trim)\n"),
        ('    review.add_argument("--reviews", type=positive, default=DEFAULT_REVIEWS)\n',
         '    review.add_argument("--reviews", type=positive, default=DEFAULT_REVIEWS)\n    review.add_argument("--history")\n'),
        ("    assignment = build_assignment(args.kind, draft, rules, sources, args.note, args.budget, advisories)\n",
         "    trim = load_trim(args.history, draft)\n"
         "    assignment = build_assignment(args.kind, draft, rules, sources, args.note, args.budget, advisories, trim)\n"),
        ('    errors = [outcome["error"] for outcome in outcomes if "error" in outcome]\n',
         '    findings, dropped = trim_findings(findings, trim)\n'
         '    errors = [outcome["error"] for outcome in outcomes if "error" in outcome]\n'
         '    if findings or not errors:\n        save_history(trim, findings)\n'),
        ('        emit({**base, "findings": findings, "over_budget_facts": facts, **status, **({"errors": errors} if errors else {})})\n',
         '        emit({**base, "findings": findings, "over_budget_facts": facts, **status, **({"errors": errors} if errors else {}),\n'
         '              **({"dropped": dropped} if dropped else {})})\n'),
        ('    emit({**base, "findings": [], "over_budget_facts": facts, **status, **passed_digest(args.kind, draft)})\n',
         '    emit({**base, "findings": [], "over_budget_facts": facts, **status, **passed_digest(args.kind, draft),\n'
         '          **({"dropped": dropped} if dropped else {})})\n'),
    ),
}
RULE_EDITS = {
    "a": ((COUNT_BULLET, COUNT_BULLET + WORKER_BULLET),),
    "c": ((COMPARE_BULLET, HISTORY_BULLET + COMPARE_BULLET),),
}
CANDIDATES = ("a", "b", "c")


class AnchorError(Exception):
    pass


def patched(source: str, edits) -> str:
    """The source with the edits applied; an edit whose replacement is already in the source changes nothing."""
    for anchor, replacement in edits:
        if replacement in source:
            continue
        if source.count(anchor) != 1:
            raise AnchorError(f"anchor found {source.count(anchor)} times, expected once: {anchor[:80]!r}")
        source = source.replace(anchor, replacement)
    return source


def edits_for(candidates: list[str]) -> list[tuple[str, tuple]]:
    """The files a set of candidates changes with every edit, in candidate order."""
    found: dict[str, list] = {}
    for name in candidates:
        for relative, table in ((SCRIPT, SCRIPT_EDITS), (RULES, RULE_EDITS)):
            found.setdefault(relative, []).extend(table.get(name, ()))
    return [(relative, tuple(edits)) for relative, edits in found.items() if edits]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("checkout", help="root of a checkout that holds scripts/text_review.py and instructions/shared-text.md")
    parser.add_argument("--candidate", required=True, help="a, b, c, or several joined with +, such as a+c")
    parser.add_argument("--dry-run", action="store_true", help="print the diffs and write nothing")
    args = parser.parse_args(argv)
    names = args.candidate.split("+")
    if any(name not in CANDIDATES for name in names) or len(set(names)) != len(names):
        print(f"--candidate takes {', '.join(CANDIDATES)} or a distinct list joined with +", file=sys.stderr)
        return 2
    changes = []
    try:
        for relative, edits in edits_for(names):
            target = Path(args.checkout) / relative
            before = target.read_text(encoding="utf-8")
            changes.append((relative, target, before, patched(before, edits)))
    except (OSError, AnchorError) as error:
        print(f"apply failed: {error}", file=sys.stderr)
        return 2
    changed = [item for item in changes if item[2] != item[3]]
    if not changed:
        print("already applied")
        return 0
    for relative, target, before, after in changed:
        if args.dry_run:
            sys.stdout.writelines(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{relative}", f"b/{relative}"))
        else:
            target.write_text(after, encoding="utf-8")
            print(f"applied to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
