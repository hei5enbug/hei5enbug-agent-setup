"""Seeded check pairs: a grader must catch a dropped fact and a literal translation, in both draft orders."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kw_jobs import prepare
from kw_models import run_model, slug
from kw_prompts import grader_prompt, load_cases, load_rules, load_seeded, parse_json

ORDERS = ("good_first", "bad_first")


def drafts_for(pair: dict, order: str) -> tuple:
    """Return the shown drafts and the labels of the good and the bad draft."""
    if order == "good_first":
        return {"A": pair["good"], "B": pair["bad"]}, "A", "B"
    return {"A": pair["bad"], "B": pair["good"]}, "B", "A"


def check_pair(pair: dict, order: str, grade: dict) -> tuple:
    """Return whether the grade catches the seeded flaw, and why not when it does not."""
    _, good, bad = drafts_for(pair, order)
    entries = grade["drafts"]
    ranking = grade.get("ranking") or []
    if pair["check"] == "missing_fact":
        if pair["fact"] not in entries[bad]["missing_facts"]:
            return False, f"fact {pair['fact']} not reported missing in the bad draft"
        if entries[good]["missing_facts"]:
            return False, "the good draft was reported to miss a fact"
        if ranking != [good]:
            return False, f"ranking {ranking} is not only the good draft"
        return True, ""
    if any(entries[label]["missing_facts"] or entries[label]["added_facts"] for label in (good, bad)):
        return False, "a fact problem was reported on a pair that differs only in wording"
    if ranking != [good, bad]:
        return False, f"ranking {ranking} does not put the good draft first"
    if len(entries[good]["unnatural"]) >= len(entries[bad]["unnatural"]):
        return False, "the bad draft does not list more unnatural phrasings than the good one"
    return True, ""


def run_one(out: Path, specs: dict, rules: str, cases: dict, pair: dict, order: str, grader: str, timeout: int) -> dict:
    drafts, _, _ = drafts_for(pair, order)
    prompt = grader_prompt(cases[pair["task"]], drafts, rules)
    result = run_model(specs[grader], prompt, out, f"seeded_{pair['id']}_{order}_{slug(grader)}", timeout)
    record = {"pair": pair["id"], "order": order, "grader": grader, "res": result, "passed": False}
    if result["ok"]:
        try:
            record["grade"] = parse_json(result["text"])
            record["passed"], record["why"] = check_pair(pair, order, record["grade"])
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as error:
            record["why"] = f"unusable grade: {error!r}"
    else:
        record["why"] = result.get("err", "")
    path = out / "seeded" / f"{pair['id']}_{order}_{slug(grader)}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


def run_seeded(out: Path, specs: dict, graders: list, parallel: int, timeout: int, log) -> list:
    prepare(out)
    cases, rules = load_cases(), load_rules()
    work = [(pair, order, grader) for pair in load_seeded() for order in ORDERS for grader in graders]
    with ThreadPoolExecutor(parallel) as pool:
        records = list(pool.map(lambda item: run_one(out, specs, rules, cases, *item, timeout), work))
    for record in records:
        log(f"seeded {record['pair']} {record['order']} {record['grader']}: "
            f"{'caught' if record['passed'] else 'MISSED ' + record.get('why', '')}")
    caught = sum(record["passed"] for record in records)
    log(f"seeded checks caught: {caught} of {len(records)}")
    return records
