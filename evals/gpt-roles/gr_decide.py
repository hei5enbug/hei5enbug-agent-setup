"""The owner's efficiency rule and the 2026-11-20 replacement rules, applied to the result files. No model call."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

DROP_RATIO = 1.5
DROP_SECONDS = 60.0
TIE_PERCENT = 0.10
TIE_DOLLARS = 0.05

SOL_BASELINE, SOL_NEW = "gpt-6.1-sol", "gpt-6.2-sol"
LUNA_BASELINE, LUNA_NEW = "gpt-5.6-luna", "gpt-6-luna"
SOL_CANDIDATES = (SOL_BASELINE, SOL_NEW, "gpt-6.1-terra", LUNA_NEW)
LUNA_CANDIDATES = (LUNA_BASELINE, LUNA_NEW)

SOL_ROLES = ("reviewer", "text_review", "language", "opponent", "worker")
LUNA_ROLES = ("scout", "researcher", "worker")

SOL_ROWS = {
    "reviewer": ["capabilities.review.codex.fallback.model", "codex_agents.reviewer.model",
                 "claude_agents.hei5enbug-agent-setup:reviewer.fallback.model", "runner.independent_review.claude[0]"],
    "text_review": ["scripts/text_review.py REVIEW_MODELS"],
    "language": ["capabilities.language.claude.primary.model", "capabilities.language.codex.primary.model"],
    "opponent": ["opponents.codex.model"],
    "worker": ["capabilities.implementation.claude.fallback.model", "claude_agents.hei5enbug-agent-setup:worker.fallback.model",
               "claude_agents.hei5enbug-agent-setup:sonnet-worker.fallback.model"],
}
LUNA_ROWS = {
    "scout": ["capabilities.investigation.claude.primary.model", "capabilities.investigation.codex.primary.model",
              "claude_agents.hei5enbug-agent-setup:scout.fallback.model", "codex_agents.scout.model"],
    "researcher": [],
    "worker": ["capabilities.implementation.codex.fallback.model", "codex_agents.worker.model"],
}
LUNA_DEFAULT_ROW = "runner.role_model"


def tied(first: float, second: float) -> bool:
    gap = abs(first - second)
    return gap <= TIE_DOLLARS or gap <= TIE_PERCENT * min(first, second)


def cells(results: Iterable[dict[str, Any]], role: str) -> dict[str, dict[str, dict[str, Any]]]:
    """model -> case -> {passed, cost, wall} over the role's result files; several reps pass only when all reps pass and
    count by their mean cost and wall time."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for result in results:
        if result["role"] == role:
            grouped[result["model"]][result["case"]].append(result)
    table: dict[str, dict[str, dict[str, Any]]] = {}
    for model, by_case in grouped.items():
        table[model] = {
            case: {"passed": all(item["passed"] for item in items), "cost": sum(item["cost_usd"] for item in items) / len(items),
                   "wall": sum(item["wall_seconds"] for item in items) / len(items)}
            for case, items in by_case.items()
        }
    return table


def role_decision(table: dict[str, dict[str, dict[str, Any]]], candidates: Iterable[str], cases: list[str]) -> dict[str, Any]:
    """Apply the efficiency rule: pass every case, drop a candidate over 1.5 times and 60 seconds slower on a case than the
    fastest remaining one, take the lowest cost, and let candidates within 10 percent or $0.05 of it go to the faster."""
    present = [model for model in candidates if model in table and all(case in table[model] for case in cases)]
    eligible = [model for model in present if all(table[model][case]["passed"] for case in cases)]
    kept = list(eligible)
    dropped: dict[str, str] = {}
    for case in cases:
        fastest = min((table[model][case]["wall"] for model in kept), default=0.0)
        for model in list(kept):
            wall = table[model][case]["wall"]
            if wall > DROP_RATIO * fastest and wall - fastest > DROP_SECONDS:
                kept.remove(model)
                dropped[model] = f"{case}: {wall:.0f}s against {fastest:.0f}s"
    totals = {model: (sum(table[model][case]["cost"] for case in cases), sum(table[model][case]["wall"] for case in cases)) for model in kept}
    if not totals:
        return {"status": "none", "winner": None, "eligible": eligible, "dropped": dropped, "totals": {}, "tie_group": []}
    lowest = min(cost for cost, _ in totals.values())
    group = [model for model, (cost, _) in totals.items() if tied(cost, lowest)]
    by_wall = sorted(group, key=lambda model: totals[model][1])
    status = "winner" if len(by_wall) == 1 or totals[by_wall[0]][1] < totals[by_wall[1]][1] else "tie"
    return {"status": status, "winner": by_wall[0], "eligible": eligible, "dropped": dropped,
            "totals": {model: {"cost": round(cost, 6), "wall": round(wall, 1)} for model, (cost, wall) in totals.items()},
            "tie_group": by_wall if len(by_wall) > 1 else []}


def passed_cases(table: dict[str, dict[str, dict[str, Any]]], model: str) -> set[str]:
    return {case for case, cell in table.get(model, {}).items() if cell["passed"]}


def total_cost(table: dict[str, dict[str, dict[str, Any]]], model: str) -> float:
    return sum(cell["cost"] for cell in table.get(model, {}).values())


def role_cases(results: list[dict[str, Any]], role: str) -> list[str]:
    return sorted({item["case"] for item in results if item["role"] == role})


def sol_decision(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace every gpt-6.1-sol by gpt-6.2-sol only when 6.2-sol passes every case 6.1-sol passes in every sol role, is
    not dropped on any case, and costs less over all sol-role cases outside the tie band; a role that gpt-6.1-terra or
    gpt-6-luna wins by the efficiency rule takes that model alone."""
    roles, tables = {}, {}
    for role in SOL_ROLES:
        table, cases = cells(results, role), role_cases(results, role)
        tables[role] = (table, cases)
        roles[role] = role_decision(table, SOL_CANDIDATES, cases) if cases else {"status": "not measured", "winner": None}
    blockers, old_cost, new_cost = [], 0.0, 0.0
    for role, (table, cases) in tables.items():
        if not cases:
            blockers.append(f"{role}: no results")
            continue
        missing = sorted(passed_cases(table, SOL_BASELINE) - passed_cases(table, SOL_NEW))
        if missing:
            blockers.append(f"{role}: {SOL_NEW} fails {', '.join(missing)}, which {SOL_BASELINE} passes")
        if SOL_NEW in roles[role].get("dropped", {}):
            blockers.append(f"{role}: {SOL_NEW} dropped as too slow ({roles[role]['dropped'][SOL_NEW]})")
        old_cost += total_cost(table, SOL_BASELINE)
        new_cost += total_cost(table, SOL_NEW)
    outside = new_cost < old_cost and not tied(new_cost, old_cost)
    if not blockers and not outside:
        blockers.append(f"cost {new_cost:.4f} against {old_cost:.4f} is not a win outside the tie band")
    singles = {role: decision["winner"] for role, decision in roles.items()
               if decision.get("status") == "winner" and decision["winner"] in ("gpt-6.1-terra", LUNA_NEW)}
    return {"roles": roles, "replace_all_with_6_2_sol": not blockers, "blockers": blockers,
            "cost_6_1_sol": round(old_cost, 4), "cost_6_2_sol": round(new_cost, 4), "single_role_winners": singles}


def luna_decision(results: list[dict[str, Any]]) -> dict[str, Any]:
    """gpt-6-luna replaces gpt-5.6-luna in a role when it passes every case 5.6 passes, is not dropped, and costs no more
    outside the tie band; otherwise the role keeps gpt-5.6-luna."""
    roles = {}
    for role in LUNA_ROLES:
        table, cases = cells(results, role), role_cases(results, role)
        if not cases or LUNA_NEW not in table or LUNA_BASELINE not in table:
            roles[role] = {"use": LUNA_BASELINE, "reason": "not measured"}
            continue
        decision = role_decision(table, LUNA_CANDIDATES, cases)
        old, new = total_cost(table, LUNA_BASELINE), total_cost(table, LUNA_NEW)
        ok = (passed_cases(table, LUNA_BASELINE) <= passed_cases(table, LUNA_NEW) and LUNA_NEW not in decision["dropped"]
              and (new <= old or tied(new, old)))
        roles[role] = {"use": LUNA_NEW if ok else LUNA_BASELINE, "cost_5_6": round(old, 4), "cost_6": round(new, 4),
                       "dropped": decision["dropped"], "reason": "equal or better" if ok else "worse on a case, speed, or cost"}
    return {"roles": roles, "role_model_row_to_6_luna": all(item["use"] == LUNA_NEW for item in roles.values())}


def registry_plan(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Which registry rows change and to what; the decision applies them in a later change, with a record."""
    sol, luna = sol_decision(results), luna_decision(results)
    changes: dict[str, str] = {}
    for role, rows in SOL_ROWS.items():
        model = sol["single_role_winners"].get(role) or (SOL_NEW if sol["replace_all_with_6_2_sol"] else None)
        if model and model != SOL_BASELINE:
            changes.update({row: model for row in rows})
    for role, rows in LUNA_ROWS.items():
        if luna["roles"][role]["use"] == LUNA_NEW:
            changes.update({row: LUNA_NEW for row in rows})
    if luna["role_model_row_to_6_luna"]:
        changes[LUNA_DEFAULT_ROW] = LUNA_NEW
    return {"sol": sol, "luna": luna, "changes": changes}


def tie_models(results: list[dict[str, Any]], role: str, candidates: Iterable[str]) -> list[str]:
    """The candidates of a role whose cost sits inside the tie band of the cheapest eligible one, after one rep."""
    table, cases = cells(results, role), role_cases(results, role)
    decision = role_decision(table, candidates, cases) if cases else {"tie_group": []}
    return decision["tie_group"]
