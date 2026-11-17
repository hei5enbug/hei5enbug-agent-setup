"""Apply the Opus worker candidate to a plugin checkout.

Run it only after `worker-results` has written a measurement whose rule returns at least one hard criterion:

    python3 evals/e2e/worker-cases/opus_candidate.py <repository root> <criterion>[,<criterion>...]

It adds `agents/opus-worker.md` and its Korean mirror from the candidate files beside it, registers the agent in
`claude_agents` with the runner fallback of `sonnet-worker`, and rewrites the route sentences of
`instructions/claude-agents.md` and `instructions/model-routing.md` to name the criteria. It changes nothing else:
the English route sentences' Korean mirrors, the documents that list the worker agents, the `AGENTS.md` worker table,
the manifest description, and the tests that pin the earlier sentences follow in the same change.
"""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from harness.worker_cases import CRITERIA, CRITERION_PHRASES  # noqa: E402

AGENT = "agents/opus-worker.md"
MIRROR = "docs/ko/agents/opus-worker.ko.md"
REGISTRY = "config/model-registry.json"
CLAUDE_AGENTS = "instructions/claude-agents.md"
MODEL_ROUTING = "instructions/model-routing.md"
SONNET_ENTRY = "hei5enbug-agent-setup:sonnet-worker"
OPUS_ENTRY = "hei5enbug-agent-setup:opus-worker"

AUTO_OLD = (
    "When it says `auto`, choose per assignment: the `worker` agent for easy work (one cohesive change with a stated "
    "edit and checks that cover it fully) and the Sonnet worker for normal or hard work (a behavioral change, several "
    "files, parsing, security, or concurrency)."
)
AUTO_NEW = (
    "When it says `auto`, choose per assignment: the `worker` agent for easy work (one cohesive change with a stated "
    "edit and checks that cover it fully), `hei5enbug-agent-setup:opus-worker` for hard work (an assignment that "
    "carries {criteria}), and the Sonnet worker for all other work."
)
CLAUDE_OLD = (
    "choose per assignment by the same difficulty rule between `hei5enbug-agent-setup:worker` and "
    "`hei5enbug-agent-setup:sonnet-worker`,"
)
CLAUDE_NEW = (
    "choose per assignment by the same difficulty rule among `hei5enbug-agent-setup:worker`, "
    "`hei5enbug-agent-setup:sonnet-worker`, and `hei5enbug-agent-setup:opus-worker`,"
)
ROW_OLD = "for easy work and `sonnet-worker` with `claude-sonnet-5-5`, `high` for normal or hard work;"
ROW_NEW = (
    "for easy work, `opus-worker` with `claude-opus-5-5`, `high` for hard work ({criteria}), and `sonnet-worker` with "
    "`claude-sonnet-5-5`, `high` for all other work;"
)
ROUTE_OLD = "`claude` (the same difficulty rule between `worker` and `sonnet-worker`, never a GPT worker,"
ROUTE_NEW = "`claude` (the same difficulty rule among `worker`, `sonnet-worker`, and `opus-worker`, never a GPT worker,"


class ApplyError(ValueError):
    pass


def criteria_text(criteria: list[str]) -> str:
    return ", ".join(CRITERION_PHRASES[item] for item in criteria)


def replace_once(text: str, old: str, new: str, wrap: bool) -> str:
    """Replace one sentence, matching it across the line wraps of the file; reflow the new text when the file is prose."""
    pattern = re.compile(r"\s+".join(re.escape(word) for word in old.split()))
    found = pattern.findall(text)
    if len(found) != 1:
        raise ApplyError(f"expected one match for {old[:50]!r}, found {len(found)}")
    replacement = textwrap.fill(new, width=118, subsequent_indent="  ", break_long_words=False) if wrap else new
    return pattern.sub(lambda _match: replacement, text, count=1)


def apply(root: Path, criteria: list[str]) -> list[str]:
    """Write the candidate into `root` and return the changed paths."""
    root = Path(root)
    unknown = sorted(set(criteria) - set(CRITERIA))
    if not criteria or unknown:
        raise ApplyError(f"name one or more of {', '.join(CRITERIA)}; unknown {unknown}")
    if (root / AGENT).exists():
        raise ApplyError(f"{AGENT} already exists")
    ordered = [item for item in CRITERIA if item in criteria]
    registry = (root / REGISTRY).read_text(encoding="utf-8")
    sonnet_line = next((line for line in registry.splitlines() if line.lstrip().startswith(f'"{SONNET_ENTRY}":')), None)
    if sonnet_line is None or OPUS_ENTRY in registry:
        raise ApplyError("the registry must hold the sonnet-worker entry and no opus-worker entry")
    opus_line = sonnet_line.replace(SONNET_ENTRY, OPUS_ENTRY).replace("claude-sonnet-5-5", "claude-opus-5-5")
    new_registry = registry.replace(sonnet_line + "\n", sonnet_line + "\n" + opus_line + "\n", 1)
    text = criteria_text(ordered)
    agents = replace_once((root / CLAUDE_AGENTS).read_text(encoding="utf-8"), AUTO_OLD, AUTO_NEW.format(criteria=text), True)
    agents = replace_once(agents, CLAUDE_OLD, CLAUDE_NEW, True)
    routing = (root / MODEL_ROUTING).read_text(encoding="utf-8")
    routing = replace_once(routing, ROW_OLD, ROW_NEW.format(criteria=text), False)
    routing = replace_once(routing, ROUTE_OLD, ROUTE_NEW, False)
    (root / AGENT).write_text((HERE / "opus-candidate" / "opus-worker.md.candidate").read_text(encoding="utf-8"), encoding="utf-8")
    (root / MIRROR).write_text((HERE / "opus-candidate" / "opus-worker.ko.md.candidate").read_text(encoding="utf-8"), encoding="utf-8")
    (root / REGISTRY).write_text(new_registry, encoding="utf-8")
    (root / CLAUDE_AGENTS).write_text(agents, encoding="utf-8")
    (root / MODEL_ROUTING).write_text(routing, encoding="utf-8")
    return [AGENT, MIRROR, REGISTRY, CLAUDE_AGENTS, MODEL_ROUTING]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(__doc__ or "")
        return 2
    try:
        changed = apply(Path(argv[0]), [item for item in argv[1].split(",") if item])
    except (ApplyError, OSError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    sys.stdout.write("".join(f"{path}\n" for path in changed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
