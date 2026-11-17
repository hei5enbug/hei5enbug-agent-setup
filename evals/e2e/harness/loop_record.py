"""The record of issue 102: the baseline and every candidate loop shape on the writing tasks, with the measures of each run and the
adoption decision of each candidate."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import loop_decision, loop_measures, records
from .command import ConfigError
from .matrix import make_spec


def parse_variants(text: str) -> dict[str, str]:
    """`baseline=<variant>,a=<variant>,...` as a map from record label to campaign variant name."""
    mapping: dict[str, str] = {}
    for part in (item for item in text.split(",") if item.strip()):
        label, _, variant = part.partition("=")
        if not variant or label in mapping:
            raise ConfigError("--variants takes label=variant pairs with distinct labels, such as baseline=base,a=cand-a")
        mapping[label.strip()] = variant.strip()
    names = set(loop_decision.CANDIDATES)
    unknown = [label for label in mapping if label != loop_decision.BASELINE and not set(label.split("+")) <= names]
    if loop_decision.BASELINE not in mapping or unknown:
        raise ConfigError(f"--variants needs baseline and labels made of {', '.join(sorted(names))} joined with +; got {unknown or 'no baseline'}")
    return mapping


def record_loop(run_root: Path, campaign: str, issue: int, mapping: Mapping[str, str]) -> dict[str, Any]:
    """Collect every run of the mapped variants on the writing tasks, add the loop measures to each run, decide each candidate, and
    build the record."""
    runs = records.campaign_runs(run_root, campaign, list(mapping.values()), list(loop_decision.WRITING_TASKS))
    labels = {variant: label for label, variant in mapping.items()}
    entries = []
    for item in runs:
        if not item["entry"]:
            continue
        directory = make_spec(run_root, campaign, item["case"], item["variant"], item["summary"]["rep"], item["host"]).result_dir
        entries.append({**item["entry"], "variant": labels[item["variant"]], "passed": item["summary"]["passed"],
                        **loop_measures.measures(directory, item["host"])})
    if not entries:
        raise ConfigError(f"campaign {campaign} holds no finished graded run of {', '.join(mapping.values())}")
    revisions = {labels[name]: records.variant_revision(run_root, campaign, name, runs) for name in mapping.values()
                 if any(run["variant"] == name for run in runs)}
    decided = loop_decision.decide(entries)
    record = records.build_record(issue, list(loop_decision.WRITING_TASKS), revisions, entries, decided["entries"], decided["decisions"])
    return {"record": record, "decisions": decided["decisions"]}


def report_lines(result: Mapping[str, Any]) -> list[str]:
    return [f"{item['candidate']}: {item['verdict']} ({item['step']})" for item in result["decisions"]]
