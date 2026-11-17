"""The record of the route measurement of #109: each route against the before variant on both hosts, and the route chosen.

A route variant names `route` in its variant file, so the harness tells the run which route to take and grades
`route-followed`. Each route is judged against the before variant by the comparison rule of the harness; the routes that
pass go to `route_choice.choose_route`, and the record holds every run, every verdict with its variant, the routes, and the
choice."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from . import records, route_choice
from .command import ConfigError, load_variant
from .config import HOSTS
from .verdict import compare


def route_candidates(runs: Sequence[Mapping[str, Any]], variant: str, cases: Sequence[str]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    """The run summaries of one route variant per (case, host) in repetition order; a case with no run is left out of the map."""
    found: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for case in cases:
        for host in HOSTS:
            chosen = sorted((run for run in runs if (run["case"], run["variant"], run["host"]) == (case, variant, host)),
                            key=lambda run: run["summary"]["rep"])
            if chosen:
                found[(case, host)] = [run["summary"] for run in chosen]
    return found


def variant_routes(variants_root: Path, names: Sequence[str]) -> dict[str, str]:
    """The route each variant file names; a variant that names none is not a route variant."""
    found = {name: load_variant(variants_root, name).get("route") for name in names}
    unset = sorted(name for name, route in found.items() if not route)
    if unset or len(set(found.values())) != len(found):
        raise ConfigError(f"--routes takes variants that each force a different route; {', '.join(unset) or 'two share a route'}")
    return found  # type: ignore[return-value]


def record_routes(
    run_root: Path, campaign: str, issue: int, before: str, routes: Mapping[str, str], tasks: Sequence[str] | None = None,
    after: str | None = None,
) -> dict[str, Any]:
    """Judge each route variant against the before variant on both hosts, choose the route, and build the record.

    `after` names the variant that carries the chosen rule, run without a forced route; it is judged against the before
    variant like a route but never enters the choice. Returns the record, the harness comparison of each judged variant, and
    the choice."""
    names = list(routes)
    judged = [*names, *([after] if after else [])]
    if len({before, *judged}) != len(judged) + 1 or len(names) < 2:
        raise ConfigError("--routes takes two or more variants, and --before and --after name variants that differ from them and each other")
    runs = records.campaign_runs(run_root, campaign, (before, *judged), tasks)
    expected = records.expected_tasks(run_root, campaign, tasks, runs)
    planned = records.planned_runs(run_root, campaign)
    if not expected or not any(run["entry"] for run in runs):
        raise ConfigError(f"campaign {campaign} holds no finished graded run of {before} or of a route")
    compared = {name: compare(records.build_cases(runs, before, name, expected, planned)) for name in judged}
    verdicts = {name: item["verdict"] for name, item in compared.items()}
    choice = route_choice.choose_route(
        {routes[name]: route_candidates(runs, name, expected) for name in names},
        {routes[name]: verdicts[name] for name in names})
    revisions = {name: records.variant_revision(run_root, campaign, name, runs) for name in (before, *judged)}
    entries = [{**item, "variant": name} for name in judged for item in records.verdict_entries(compared[name], [])]
    record = records.build_record(
        issue, expected, revisions, [run["entry"] for run in runs if run["entry"]], entries,
        {"routes": dict(routes), "route_choice": {k: choice[k] for k in ("verdict", "route", "steps")}})
    return {"record": record, "compared": compared, "choice": choice}


def report_lines(result: Mapping[str, Any]) -> list[str]:
    """One line per route and case, then the cost and time of each route and the choice."""
    lines = [f"{name} {item['case']}: {item['verdict']}" for name, compared in result["compared"].items() for item in compared["cases"]]
    for route, row in sorted(result["choice"]["table"].items()):
        lines.append(f"route {route}: " + ", ".join(f"{key} {value}" for key, value in row.items()))
    choice = result["choice"]
    return lines + [*(f"step: {step}" for step in choice["steps"]), f"route choice: {choice['verdict']}" + (f" {choice['route']}" if choice["route"] else "")]
