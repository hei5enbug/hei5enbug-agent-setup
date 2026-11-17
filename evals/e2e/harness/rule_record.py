"""Assemble the `rule_groups` section of a record from the stock, plugin, and removal runs of campaigns.

The stock and plugin variants are the before and after of the record. A removal variant is any variant of the named
campaigns whose file lists `remove` entries; its entries must resolve to exactly one rule group, and its revision must be
the plugin variant's. Its runs are read from the run folders the harness wrote, in the campaign that holds them, next to the
plugin variant's runs of the same campaign, which the host comparison of that group judges."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import plugin_export, records, rule_groups
from .command import ConfigError, load_variant, loads_plugin
from .config import FINISHED_STATUSES, HOSTS
from .matrix import campaign_dir, read_json
from .verdict import FAIL, PASS, compare

REFERENCE_EXCLUDES = ("evals", "docs")
TEXT_SUFFIXES = frozenset({".md", ".py", ".json", ".toml", ".yaml", ".yml", ".txt", ".sh", ".mjs", ".js"})


def task_checks(tasks: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """The required checks of each task, as `<task>/<check>`."""
    return {str(task["id"]): [f"{task['id']}/{check['id']}" for check in task["checks"] if check.get("required")] for task in tasks}


def group_tasks(group: Mapping[str, Any]) -> list[str]:
    return sorted({check.split("/", 1)[0] for check in group["checks"]})


def stock_results(runs: Sequence[Mapping[str, Any]], variant: str, group: Mapping[str, Any]) -> dict[str, dict[str, bool | None]]:
    """For each host and mapped check: whether every stock run passed it; None when no stock run holds the check."""
    found: dict[str, dict[str, bool | None]] = {}
    for host in HOSTS:
        found[host] = {}
        for check in group["checks"]:
            task, name = check.split("/", 1)
            values = [run["checks"].get(name) for run in runs
                      if (run["variant"], run["host"], run["case"]) == (variant, host, task)]
            found[host][check] = None if not values or None in values else all(values)
    return found


def resolve_variant(groups: Sequence[Mapping[str, Any]], variant: Mapping[str, Any]) -> str:
    """The one group id a removal variant's entries name; a variant that names none or several is an error."""
    ids: list[str] = []
    for entry in variant["remove"]:
        if "starts_with" in entry:
            ids += rule_groups.locate_group([item for item in groups if item["kind"] != "section"], entry["file"], entry["starts_with"])
        else:
            wanted = rule_groups.words(entry["heading"])
            ids += [item["id"] for item in groups if item["kind"] == "section" and item["file"] == entry["file"]
                    and rule_groups.words(item["heading"]) == wanted]
    if len(set(ids)) != 1 or len(ids) != len(variant["remove"]):
        raise ConfigError(f"variant {variant['name']}: its remove entries must name exactly one rule group, and it names {sorted(set(ids)) or 'none'}")
    return ids[0]


def removal_runs(
    run_root: Path, campaign: str, variant: str, plugin: str, group: Mapping[str, Any], required: Mapping[str, Sequence[str]],
) -> tuple[list[dict[str, Any]], bool | None]:
    """The removal runs of one group in one campaign, and whether the host comparison against the plugin variant holds.

    A repetition's `checks` hold every required check of the group's tasks: `null` for a run that did not finish or was not
    graded, so a missing run is never read as measured. The comparison is None unless the plugin variant ran every task of the
    group on both hosts in the same campaign, and it is True only when every case passes."""
    tasks = group_tasks(group)
    found = records.campaign_runs(run_root, campaign, (variant, plugin), tasks)
    entries: list[dict[str, Any]] = []
    for host in HOSTS:
        reps = sorted({run["summary"]["rep"] for run in found if (run["variant"], run["host"]) == (variant, host)})
        for rep in reps:
            checks: dict[str, bool | None] = {name: None for task in tasks for name in required[task]}
            for run in found:
                if (run["variant"], run["host"], run["summary"]["rep"]) == (variant, host, rep) and run["entry"]:
                    checks.update({f"{run['case']}/{name}": passed for name, passed in run["entry"]["checks"].items()
                                   if f"{run['case']}/{name}" in checks})
            entries.append({"host": host, "rep": rep, "variant": variant, "checks": checks})
    complete = all(any((run["variant"], run["host"], run["case"]) == (plugin, host, task) and run["entry"] for run in found)
                   for host in HOSTS for task in tasks)
    if not complete:
        return entries, None
    cases = records.build_cases(found, plugin, variant, tasks, records.planned_runs(run_root, campaign))
    states = [item["verdict"] for item in compare(cases)["cases"]]
    return entries, True if all(state == PASS for state in states) else False if FAIL in states else None


def reference_hits(repo_root: Path, revision: str, groups: Sequence[Mapping[str, Any]]) -> tuple[list[str], dict[str, list[str]]]:
    """The top-level folders and files of the revision that were searched, and per group id the files other than the group's
    own that hold its first words, or for a section its heading line. The `evals` and `docs` folders are left out, as the
    mirrors and the harness are not plugin text; a hit in a script, a test, a skill, or another instruction may rely on the group."""
    excludes = [f":(exclude){name}" for name in REFERENCE_EXCLUDES]
    archive = plugin_export._git(repo_root, "archive", "--format=tar", revision, "--", ".", *excludes)
    texts: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for member in bundle.getmembers():
            if member.isfile() and Path(member.name).suffix in TEXT_SUFFIXES:
                try:
                    texts[member.name] = rule_groups.words(bundle.extractfile(member).read().decode("utf-8"))  # type: ignore[union-attr]
                except UnicodeDecodeError:
                    continue
    searched = sorted({name.split("/", 1)[0] for name in texts})
    hits: dict[str, list[str]] = {}
    for group in groups:
        needle = rule_groups.words(group["heading"] if group["kind"] == "section" else group["starts_with"])
        hits[group["id"]] = sorted(name for name, text in texts.items() if name != group["file"] and needle in text)
    return searched, hits


def build_section(
    run_root: Path, campaign: str, record: Mapping[str, Any], before: str, after: str, removal_campaigns: Sequence[str],
    tasks: Sequence[Mapping[str, Any]], variants_root: Path, repo_root: Path,
) -> dict[str, Any]:
    """The `rule_groups` section: every group of the session files at the plugin revision with its bytes, mapped checks and
    tasks, stock result per host, removal runs, the references searched, and the verdict that `rule_groups.decide` gives."""
    revision = record["variants"][after]["revision"]
    groups = rule_groups.group_map(rule_groups.revision_reader(repo_root, revision), rule_groups.task_rules(tasks))
    required = task_checks(tasks)
    searched, hits = reference_hits(repo_root, revision, groups)
    by_id: dict[str, dict[str, Any]] = {}
    for name in dict.fromkeys([campaign, *removal_campaigns]):
        listed = (read_json(campaign_dir(run_root, name) / "campaign.json", {}) or {}).get("variants") or []
        for variant_name in listed:
            if variant_name in (before, after):
                continue
            variant = load_variant(variants_root, variant_name)
            if not variant["remove"]:
                continue
            if not loads_plugin(variant) or not plugin_export.resolve_ref(repo_root, variant["ref"]).startswith(revision):
                raise ConfigError(f"variant {variant_name} must remove parts of the plugin revision {revision}, not of another one")
            group = next(item for item in groups if item["id"] == resolve_variant(groups, variant))
            if group["id"] in by_id:
                raise ConfigError(f"two variants remove the group {group['id']}")
            entries, comparison = removal_runs(run_root, name, variant_name, after, group, required)
            by_id[group["id"]] = {"runs": entries, "host_comparison": comparison, "variant": variant_name}
    inputs = []
    for group in groups:
        removal = by_id.get(group["id"], {"runs": [], "host_comparison": None})
        inputs.append({
            **{key: group[key] for key in ("id", "file", "bytes", "checks", "kind", "members")}, "tasks": group_tasks(group),
            "stock": stock_results(record["runs"], before, group),
            "removal": {host: [run["checks"] for run in removal["runs"] if run["host"] == host] for host in HOSTS},
            "removal_runs": removal["runs"], "host_comparison": removal["host_comparison"],
            "references": {"searched": searched, "relied_on": ", ".join(hits[group["id"]]) or None},
            "relied_on": ", ".join(hits[group["id"]]) or None,
        })
    kept = ("id", "file", "bytes", "checks", "tasks", "stock", "removal_runs", "host_comparison", "references", "verdict", "step")
    return {"stock": before, "plugin": after,
            "groups": [{key: item[key] for key in kept} for item in rule_groups.decide(inputs)]}
