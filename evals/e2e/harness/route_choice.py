"""Choose how a change that touches three to five files is carried out: by the main session or by the implementation worker.

A route is a way of doing the work. A candidate is a route with its runs in every case, a case being a task on a host. The
choice follows the repository's efficiency rule: keep the routes that pass every case under the comparison rule of the
harness, drop a route that is slower than the fastest remaining one by more than 1.5 times and by more than 60 seconds in
any case, then take the lowest list-price cost per passing case, treating costs within 10 percent or within 0.05 dollars of
the lowest as a tie that the faster route wins. A run with no wall time or cost value leaves the choice not measured.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Mapping, Sequence

ROUTES = ("main", "delegate")
SLOWER_FACTOR = 1.5
SLOWER_SECONDS = 60.0
COST_TIE_RATIO = 0.10
COST_TIE_DOLLARS = 0.05

WINNER = "winner"
NO_WINNER = "no winner"
NOT_MEASURED = "not measured"
CHOICE_VERDICTS = (WINNER, NO_WINNER, NOT_MEASURED)
PASS = "pass"

Cell = tuple[str, str]
Runs = Mapping[Cell, Sequence[Mapping[str, Any]]]


def usable(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def missing_values(candidates: Mapping[str, Runs]) -> str | None:
    """The first route, case, and host that has no run, or a run without a wall time or a cost, or None when all are there."""
    cells = sorted({cell for runs in candidates.values() for cell in runs})
    for route, runs in sorted(candidates.items()):
        for cell in cells:
            held = runs.get(cell) or []
            if not held:
                return f"route {route} has no run for {cell[0]} on {cell[1]}"
            if any(not usable(run.get("wall_seconds")) or run.get("cost_usd") is None or not usable(run.get("cost_usd")) for run in held):
                return f"route {route} has a run without a wall time or cost for {cell[0]} on {cell[1]}"
    return None


def cell_seconds(runs: Runs) -> dict[Cell, float]:
    return {cell: float(median(run["wall_seconds"] for run in held)) for cell, held in runs.items()}


def too_slow(seconds: Mapping[Cell, float], fastest: Mapping[Cell, float]) -> Cell | None:
    """The first case where a route is slower than the fastest remaining one by more than 1.5 times and by more than 60 seconds."""
    return next((cell for cell in sorted(seconds)
                 if seconds[cell] > SLOWER_FACTOR * fastest[cell] and seconds[cell] - fastest[cell] > SLOWER_SECONDS), None)


def cost_per_pass(runs: Runs) -> float:
    held = [run for cell_runs in runs.values() for run in cell_runs]
    return sum(float(run["cost_usd"]) for run in held) / sum(1 for run in held if run.get("passed"))


def tied(cost: float, lowest: float) -> bool:
    return cost - lowest <= COST_TIE_DOLLARS or cost - lowest <= COST_TIE_RATIO * lowest


def outcome(verdict: str, route: str | None, steps: Sequence[str], table: Mapping[str, Any]) -> dict[str, Any]:
    return {"verdict": verdict, "route": route, "steps": list(steps), "table": dict(table)}


def choose_route(candidates: Mapping[str, Runs], comparisons: Mapping[str, str]) -> dict[str, Any]:
    """Pick the route for implementation that changes three to five files.

    `candidates` maps each route to its runs per case; a run holds `passed`, `wall_seconds`, and `cost_usd`. `comparisons`
    maps each route to the verdict of the harness comparison of that route against the before variant. The result holds the
    verdict (`winner`, `no winner`, or `not measured`), the route, the steps that decided it, and a table per route."""
    steps: list[str] = []
    table: dict[str, Any] = {route: {} for route in sorted(candidates)}
    if len(candidates) < 2:
        return outcome(NOT_MEASURED, None, ["fewer than two routes were measured"], table)
    gap = missing_values(candidates)
    if gap:
        return outcome(NOT_MEASURED, None, [gap], table)
    open_routes = sorted(route for route in candidates if comparisons.get(route) not in (PASS, "fail"))
    if open_routes:
        return outcome(NOT_MEASURED, None, [f"route {route} comparison is {comparisons.get(route)}" for route in open_routes], table)
    remaining = []
    for route in sorted(candidates):
        failing = [cell for cell, held in candidates[route].items() if not all(run.get("passed") for run in held)]
        if comparisons[route] == PASS and not failing:
            remaining.append(route)
            continue
        table[route]["dropped"] = "a case fails" if failing else "the comparison fails"
        steps.append(f"route {route} dropped: {table[route]['dropped']}" + (f" ({failing[0][0]} on {failing[0][1]})" if failing else ""))
    if not remaining:
        return outcome(NO_WINNER, None, [*steps, "no route passes every case"], table)
    seconds = {route: cell_seconds(candidates[route]) for route in remaining}
    for route in remaining:
        table[route].update(wall_seconds=sum(seconds[route].values()), cost_per_pass=cost_per_pass(candidates[route]))
    if len(remaining) == 1:
        return outcome(WINNER, remaining[0], [*steps, f"route {remaining[0]} is the only route that passes every case"], table)
    fastest = {cell: min(seconds[route][cell] for route in remaining) for cell in seconds[remaining[0]]}
    kept = []
    for route in remaining:
        cell = too_slow(seconds[route], fastest)
        if cell is None:
            kept.append(route)
            continue
        table[route]["dropped"] = f"slower than the fastest by more than 1.5 times and 60 seconds in {cell[0]} on {cell[1]}"
        steps.append(f"route {route} dropped: {table[route]['dropped']}")
    lowest = min(table[route]["cost_per_pass"] for route in kept)
    near = [route for route in kept if tied(table[route]["cost_per_pass"], lowest)]
    pick = min(near, key=lambda route: (table[route]["wall_seconds"], table[route]["cost_per_pass"], route))
    reason = "lowest cost per passing case" if len(near) == 1 else "costs within the tie band; the faster route wins"
    return outcome(WINNER, pick, [*steps, f"route {pick} chosen: {reason}"], table)


def validate_choice(choice: Any, routes: Mapping[str, str]) -> list[str]:
    """Problems of the `route_choice` section of a record."""
    if not isinstance(choice, Mapping):
        return ["route_choice is not an object"]
    problems = [f"route_choice lacks {field}" for field in ("verdict", "route", "steps") if field not in choice]
    if choice.get("verdict") not in CHOICE_VERDICTS:
        problems.append("route_choice verdict is not a known verdict")
    if choice.get("route") is not None and choice.get("route") not in set(routes.values()):
        problems.append("route_choice route is not a measured route")
    if (choice.get("verdict") == WINNER) != (choice.get("route") is not None):
        problems.append("route_choice names a route exactly when its verdict is winner")
    steps = choice.get("steps")
    if not (isinstance(steps, list) and steps and all(isinstance(step, str) and step.strip() for step in steps)):
        problems.append("route_choice steps is not a non-empty list of text")
    return problems


def validate_routes(routes: Any, variants: Mapping[str, Any]) -> list[str]:
    if not isinstance(routes, Mapping) or not routes:
        return ["routes is not a non-empty object"]
    return [f"routes names {name}, which is not a variant, or a route outside {', '.join(ROUTES)}"
            for name, route in routes.items() if name not in variants or route not in ROUTES]
