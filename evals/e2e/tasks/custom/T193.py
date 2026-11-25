"""Check only seeded evidence in the document shown for blind comparison."""

import re
import runpy

STAGE_NAMES = {
    "Capture inputs": r"Capture inputs|입력(?:값| 데이터)?\s*(?:수집|확보|캡처)",
    "Aggregate samples": r"Aggregate samples|(?:표본|샘플|측정값)\s*(?:집계|합산)",
    "Reconcile totals": r"Reconcile totals|(?:합계|총계|총합)\s*(?:대조|확인|검증|정합성 확인)",
}


def common(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T191.py"))


def options_and_measures_present(ctx):
    helpers = common(ctx)
    text = helpers["report"](ctx)
    table_text = "\n".join(line for line in text.splitlines() if line.count("|") >= 2)
    options = [row for row in helpers["seed"](ctx, "notes/options.csv") if row["verification"] == "complete"]
    missing = [row["method"] for row in options if not (
        helpers["token"](table_text, row["method"])
        and helpers["number"](table_text, row["success_count"])
        and helpers["number"](table_text, row["p95_ms"])
    )]
    return helpers["value"](text and not missing, "the seeded options and both measures are present",
                            f"absent option data: {missing}")


def stage_titles_and_timings_present(ctx):
    helpers = common(ctx)
    text = helpers["report"](ctx)
    missing = []
    for row in helpers["seed"](ctx, "notes/stages.csv"):
        found = any(
            re.search(STAGE_NAMES[row["title"]], line, re.I)
            and helpers["number"](line, row["before_s"])
            and helpers["number"](line, row["after_s"])
            for line in re.split(r"\n\s*\n|\n(?=\s*(?:[-*]|\|))", text)
        )
        if not found:
            missing.append(row["title"])
    return helpers["value"](text and not missing, "all seeded stage titles and timing pairs are present",
                            f"absent stage data: {missing}")


def departure_present(ctx):
    helpers = common(ctx)
    text = helpers["report"](ctx)
    proposal = re.search(r"SHA[- ]?256|체크섬|해시|checksum", text, re.I)
    return helpers["value"]("demo-complete.marker" in text and proposal, "both the proposal and observed marker are present",
                            "the proposed checksum or observed marker is absent")


def case_and_figure_present(ctx):
    helpers = common(ctx)
    text = helpers["report"](ctx)
    case = any(helpers["token"](text, row["case_id"]) for row in helpers["seed"](ctx, "notes/cases.csv"))
    return helpers["value"](case and helpers["case_has_figure"](ctx, text), "a seeded case and an embedded figure are present",
                            "the seeded case or any embedded figure is absent")


def seeded_exclusions_absent(ctx):
    helpers = common(ctx)
    text = helpers["report"](ctx)
    omitted = ("demo-ticker-lib", "demo-shadow")
    retained = [item for item in omitted if helpers["token"](text, item)]
    body = "\n".join(line for line in text.splitlines() if "|" not in line)
    for row in helpers["seed"](ctx, "notes/options.csv"):
        if row["verification"] == "complete" and helpers["number"](body, row["p95_ms"]):
            retained.append(f"{row['method']} p95")
    return helpers["value"](text and not retained, "unrelated and failed items and repeated table values are absent",
                            f"seeded exclusions in the report: {retained}")


def weekday_scope_present(ctx):
    helpers = common(ctx)
    text = helpers["report"](ctx)
    weekday = re.search(r"2026-10-07|평일|weekday", text, re.I)
    weekend = re.search(r"주말|weekend", text, re.I)
    return helpers["value"](weekday and weekend, "both the weekday sample and weekend scope are mentioned",
                            "the weekday sample or weekend scope is absent")
