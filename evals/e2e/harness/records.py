"""Records of a measured comparison, written to evals/e2e/records/<issue number>.json, and their validator.

A record holds measurements and run facts only: the cases, each variant's revision, and per run the host, the model
and effort of every role, pass or fail per check, wall seconds, cost, and the verdicts with their steps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import codex_host, collect, summarize, transcript
from .caps import MODEL_CAP as ALLOWED_MODELS
from .caps import normalize
from .command import ConfigError
from .config import FINISHED_STATUSES, HOST_CODEX, RUBRIC_EFFORT, RUBRIC_FALLBACK_EFFORT
from .matrix import campaign_dir, make_spec, read_json
from .verdict import (
    ACCEPT, BASELINE, CONTINUE_TO_FIVE, FAIL, HOSTS, INVESTIGATE, MEASURES, NOT_MEASURED, PASS, REJECT, REPEAT, SECOND_PAIR,
    claim_verdict, compare, with_claims,
)

RECORDS_DIR = Path(__file__).resolve().parent.parent / "records"
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
UNKNOWN_EFFORT = "not measured"
VERDICTS = frozenset({PASS, FAIL, REPEAT, NOT_MEASURED, INVESTIGATE, BASELINE, ACCEPT, REJECT, CONTINUE_TO_FIVE, SECOND_PAIR})
VERDICT_SUBJECTS = frozenset({"quality", "wall_seconds", "cost_usd", "claim"})
TOP_FIELDS = ("issue", "cases", "variants", "runs", "verdicts")
RUN_REQUIRED = ("case", "variant", "host", "models", "checks", "wall_seconds", "cost_usd")
RUN_OPTIONAL = ("rep", "reviews")
VERDICT_REQUIRED = ("case", "verdict", "step")
VERDICT_OPTIONAL = ("measure",)
LOCAL_PATH = re.compile(r"(?<![\w.:/-])(?:/[\w.@+-]+){2,}|(?<![\w.])~/|\b[A-Za-z]:[\\/]|(?<![\w.:/-])/(?:Users|home|tmp|var|private|etc)\b")


class RecordError(ValueError):
    pass


def record_path(issue: int, root: Path = RECORDS_DIR) -> Path:
    return root / f"{issue}.json"


def strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from strings(key)
            yield from strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings(item)


def is_number(value: Any, allow_zero: bool = False) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (value >= 0 if allow_zero else value > 0)


def run_problems(position: str, run: Any, cases: Sequence[str], variants: Mapping[str, Any]) -> list[str]:
    if not isinstance(run, Mapping):
        return [f"{position} is not an object"]
    problems = [f"{position} lacks {field}" for field in RUN_REQUIRED if field not in run]
    problems += [f"{position} has unknown field {field}" for field in run if field not in RUN_REQUIRED + RUN_OPTIONAL]
    if "case" in run and run["case"] not in cases:
        problems.append(f"{position} names a case that is not in cases")
    if "variant" in run and run["variant"] not in variants:
        problems.append(f"{position} names a variant that is not in variants")
    if "host" in run and run["host"] not in HOSTS:
        problems.append(f"{position} host is not one of {', '.join(HOSTS)}")
    if "rep" in run and not (isinstance(run["rep"], int) and not isinstance(run["rep"], bool) and run["rep"] >= 1):
        problems.append(f"{position} rep is not a positive integer")
    if "models" in run:
        models = run["models"]
        if not isinstance(models, Mapping) or not models:
            problems.append(f"{position} models names no role")
        else:
            for role, entry in models.items():
                if not isinstance(entry, Mapping) or entry.get("model") not in ALLOWED_MODELS:
                    problems.append(f"{position} role {role} uses a model outside the allowed models")
                elif entry.get("effort") not in EFFORTS and entry.get("effort") != UNKNOWN_EFFORT:
                    problems.append(f"{position} role {role} has an unknown effort")
    if "checks" in run:
        checks = run["checks"]
        if not isinstance(checks, Mapping) or not checks or not all(isinstance(v, bool) for v in checks.values()):
            problems.append(f"{position} checks must map each check to pass or fail")
    if "wall_seconds" in run and run["wall_seconds"] is not None and not is_number(run["wall_seconds"]):
        problems.append(f"{position} wall_seconds is not a positive number or null")
    if "cost_usd" in run and run["cost_usd"] is not None and not is_number(run["cost_usd"], allow_zero=True):
        problems.append(f"{position} cost_usd is not a number or null")
    return problems


def verdict_problems(position: str, item: Any, cases: Sequence[str]) -> list[str]:
    if not isinstance(item, Mapping):
        return [f"{position} is not an object"]
    problems = [f"{position} lacks {field}" for field in VERDICT_REQUIRED if field not in item]
    problems += [f"{position} has unknown field {field}" for field in item if field not in VERDICT_REQUIRED + VERDICT_OPTIONAL]
    if "case" in item and item["case"] not in cases:
        problems.append(f"{position} names a case that is not in cases")
    if "verdict" in item and item["verdict"] not in VERDICTS:
        problems.append(f"{position} verdict is not a known verdict")
    if "step" in item and not (isinstance(item["step"], str) and item["step"].strip()):
        problems.append(f"{position} step is empty")
    if "measure" in item and item["measure"] not in VERDICT_SUBJECTS:
        problems.append(f"{position} measure is not a known subject")
    return problems


def validate_record(record: Any) -> list[str]:
    """Every problem of a record; an empty list means the record is complete and holds no absolute local path."""
    if not isinstance(record, Mapping):
        return ["the record is not an object"]
    problems = [f"the record lacks {field}" for field in TOP_FIELDS if field not in record]
    problems += [f"the record has unknown field {field}" for field in record if field not in TOP_FIELDS]
    issue = record.get("issue")
    if "issue" in record and not (isinstance(issue, int) and not isinstance(issue, bool) and issue > 0):
        problems.append("issue is not a positive integer")
    cases = record.get("cases")
    if "cases" in record and not (isinstance(cases, list) and cases and all(isinstance(c, str) and c for c in cases)):
        problems.append("cases is not a non-empty list of names")
        cases = []
    variants = record.get("variants")
    if "variants" in record:
        if not isinstance(variants, Mapping) or not variants:
            problems.append("variants is not a non-empty object")
            variants = {}
        else:
            for name, entry in variants.items():
                revision = entry.get("revision") if isinstance(entry, Mapping) else None
                if not (isinstance(revision, str) and revision.strip() and not re.search(r"\s", revision)):
                    problems.append(f"variant {name} has no revision")
    for key, check in (("runs", run_problems), ("verdicts", verdict_problems)):
        if key not in record:
            continue
        items = record[key]
        if not isinstance(items, list) or not items:
            problems.append(f"{key} is not a non-empty list")
            continue
        for index, item in enumerate(items):
            extra = (variants or {},) if key == "runs" else ()
            problems += check(f"{key}[{index}]", item, cases or [], *extra)
    if any(LOCAL_PATH.search(text) for text in strings(record)):
        problems.append("the record contains an absolute local path")
    return problems


def check_record(record: Any) -> None:
    problems = validate_record(record)
    if problems:
        raise RecordError("; ".join(problems))


def build_record(issue: int, cases: Sequence[str], variants: Mapping[str, str], runs: Sequence[Mapping[str, Any]],
                 verdicts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The record dict for one comparison; `variants` maps each variant name to its revision."""
    record = {
        "issue": issue,
        "cases": list(cases),
        "variants": {name: {"revision": revision} for name, revision in variants.items()},
        "runs": [{field: run[field] for field in (*RUN_REQUIRED, *RUN_OPTIONAL) if field in run} for run in runs],
        "verdicts": [{field: item[field] for field in (*VERDICT_REQUIRED, *VERDICT_OPTIONAL) if field in item}
                     for item in verdicts],
    }
    check_record(record)
    return record


def write_record(record: Mapping[str, Any], root: Path = RECORDS_DIR) -> Path:
    check_record(record)
    path = record_path(int(record["issue"]), root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def validate_directory(root: Path = RECORDS_DIR) -> dict[str, list[str]]:
    """Problems per record file under a records folder; a file named other than <issue>.json is itself a problem."""
    found: dict[str, list[str]] = {}
    for path in sorted(root.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            found[path.name] = [f"not valid JSON: {error}"]
            continue
        problems = validate_record(record)
        named = f"{record.get('issue')}.json" if isinstance(record, Mapping) else None
        if path.name != named:
            problems.append("the file name is not <issue number>.json")
        if problems:
            found[path.name] = problems
    return found


MAIN_ROLE = "main"
ROLE_RUNNER_PREFIX = "role_runner:"
SUBAGENT_PREFIX = "subagent:"
CODEX_CHILD_PREFIX = "codex_child:"
RUBRIC_ROLE = "rubric grader"
MODEL_NAME = re.compile(r"^(claude|gpt)-[\w.-]+$")


def known_model(value: Any) -> str | None:
    text = normalize(value) if value else ""
    return text if MODEL_NAME.match(text) else None


def known_effort(value: Any) -> str:
    return value if value in EFFORTS else UNKNOWN_EFFORT


def command_effort(result_dir: Path) -> str | None:
    argv = (read_json(result_dir / "command.json", {}) or {}).get("argv") or []
    return str(argv[argv.index("--effort") + 1]) if "--effort" in argv[:-1] else None


def main_role(result_dir: Path, host: str, metrics: Mapping[str, Any]) -> tuple[str | None, Any]:
    """The main session's model and effort from the host's own records: the Claude stream and command line, or the
    Codex session facts the harness read from the rollout."""
    if host == HOST_CODEX:
        env = read_json(result_dir / "env.json", {}) or {}
        session = metrics.get("session") or {}
        return env.get("codex_session_model") or session.get("model"), env.get("codex_session_effort") or session.get("effort")
    init = transcript.init_event(transcript.read_jsonl(result_dir / "stream.jsonl")) or {}
    return init.get("model"), command_effort(result_dir)


def rollout_part(rollout: Mapping[str, Any], kind: str) -> dict[str, Any]:
    """The payload of the first event of one type in a rollout."""
    for event in rollout.get("events", []):
        if event.get("type") == kind:
            return event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return {}


def codex_children(result_dir: Path, runner_rollouts: set[str]) -> dict[str, dict[str, str]]:
    """Role, model, and effort of every Codex child session, read from its rollout: the role from `session_meta`, the model
    and effort from the first `turn_context`. A second session of one role is kept as its own invocation. A child that a role
    runner status line already names is left to that entry."""
    rollouts = sorted(collect.load_rollouts(result_dir / "codex", {}), key=codex_host.session_start)[1:]
    found: dict[str, dict[str, str]] = {}
    counts: dict[str, int] = {}
    for rollout in rollouts:
        context = rollout_part(rollout, "turn_context")
        if rollout["name"] in runner_rollouts or not known_model(context.get("model")):
            continue
        role = str(rollout_part(rollout, "session_meta").get("agent_role") or "unknown")
        counts[role] = counts.get(role, 0) + 1
        name = f"{CODEX_CHILD_PREFIX}{role}" + (f"#{counts[role]}" if counts[role] > 1 else "")
        found[name] = {"model": known_model(context["model"]), "effort": known_effort(context.get("effort"))}
    return found


def run_models(result_dir: Path, host: str, metrics: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Model and effort of every role the run's records show; an effort no record states reads "not measured"."""
    roles: dict[str, dict[str, str]] = {}
    model, effort = main_role(result_dir, host, metrics)
    if known_model(model):
        roles[MAIN_ROLE] = {"model": known_model(model), "effort": known_effort(effort)}
    for agent, agent_model in sorted(((metrics.get("plugin") or {}).get("subagent_models") or {}).items()):
        if known_model(agent_model):
            roles[f"{SUBAGENT_PREFIX}{agent}"] = {"model": known_model(agent_model), "effort": UNKNOWN_EFFORT}
    calls = (read_json(result_dir / "view.json", {}) or {}).get("tool_calls") or []
    for call in calls:
        status = transcript.role_runner_status(str(call.get("result_text", "")))
        if status and known_model(status.get("model")):
            roles.setdefault(f"{ROLE_RUNNER_PREFIX}{status.get('role') or 'unknown'}",
                             {"model": known_model(status["model"]), "effort": known_effort(status.get("effort"))})
    if host == HOST_CODEX:
        roles.update(codex_children(result_dir, set(collect.rollout_roles(calls))))
    rubric = read_json(result_dir / "grade" / "rubric.json", {}) or {}
    if known_model(rubric.get("grader")):
        effort = RUBRIC_FALLBACK_EFFORT if rubric.get("fallback") else RUBRIC_EFFORT
        roles[RUBRIC_ROLE] = {"model": known_model(rubric["grader"]), "effort": effort}
    return roles


def run_cost(row: Mapping[str, Any]) -> float | None:
    """List-price spend of the whole run, including archived attempts: Claude spend as the summary computes it plus the
    Codex list estimate. None when the records show none."""
    total = float(row.get("spend_claude") or 0.0) + float(row.get("spend_codex") or 0.0)
    return total if total > 0 else None


def positive(value: Any) -> float | None:
    return float(value) if is_number(value) else None


def unmeasured(row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """A run that exists but cannot be judged; it stays in its case as "not measured" instead of being dropped."""
    summary = {"rep": int(row["rep"]), "measured": False, "reason": reason, "passed": None, "wall_seconds": None, "cost_usd": None}
    return {"case": row["task"], "variant": row["variant"], "host": row["host"], "summary": summary, "entry": None}


def campaign_runs(run_root: Path, campaign: str, variants: Sequence[str], tasks: Sequence[str] | None) -> list[dict[str, Any]]:
    """Every run of the named variants on either host: a finished, graded run with its summary and record entry, and any
    other run, whether unfinished, without metrics, ungraded, or with a grading error, as a "not measured" summary."""
    found = []
    for row in summarize.load_results(run_root, campaign):
        if row["variant"] not in variants or (tasks and row["task"] not in tasks) or row["host"] not in HOSTS:
            continue
        host = row["host"]
        if row.get("status") not in FINISHED_STATUSES:
            found.append(unmeasured(row, f"run status {row.get('status')}"))
            continue
        if not row.get("has_metrics") or row.get("grade_error"):
            found.append(unmeasured(row, "grading failed" if row.get("grade_error") else "no metrics"))
            continue
        result_dir = make_spec(run_root, campaign, row["task"], row["variant"], int(row["rep"]), host).result_dir
        grade = read_json(result_dir / "grade" / "grade.json", None)
        if not isinstance(grade, Mapping) or not grade.get("checks"):
            found.append(unmeasured(row, "no grade"))
            continue
        summary = {"rep": int(row["rep"]), "passed": bool(row.get("success")), "wall_seconds": positive(row.get("wall_total")),
                   "cost_usd": run_cost(row)}
        checks = {str(check["id"]): bool(check["passed"]) for check in grade["checks"]}
        entry = {"case": row["task"], "variant": row["variant"], "host": host, "rep": int(row["rep"]),
                 "models": run_models(result_dir, host, row), "checks": checks,
                 "wall_seconds": summary["wall_seconds"], "cost_usd": summary["cost_usd"]}
        reviews = next((check["data"]["reviews"] for check in grade["checks"]
                        if check.get("id") == "text-review-clean" and (check.get("data") or {}).get("reviews")), None)
        if reviews:
            entry["reviews"] = reviews
        found.append({"case": row["task"], "variant": row["variant"], "host": host, "summary": summary, "entry": entry})
    return found


def expected_tasks(run_root: Path, campaign: str, requested: Sequence[str] | None, runs: Sequence[Mapping[str, Any]]) -> list[str]:
    """The cases a comparison must answer for: the requested tasks, else the tasks the campaign ran, else those of its runs."""
    if requested:
        return sorted(set(requested))
    stored = (read_json(campaign_dir(run_root, campaign) / "campaign.json", {}) or {}).get("tasks")
    named = [task for task in stored if isinstance(task, str)] if isinstance(stored, list) else []
    return sorted({*named, *(run["case"] for run in runs)})


def build_cases(runs: Sequence[Mapping[str, Any]], before: str, after: str, tasks: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """One case per expected task with the run summaries of each side by host in repetition order, each with its `rep`;
    a task with no run on a side stays in its case with an empty list."""
    cases = []
    for task in sorted(set(tasks) if tasks else {run["case"] for run in runs}):
        case: dict[str, Any] = {"id": task, "before": {}, "after": {}}
        for side, variant in (("before", before), ("after", after)):
            for host in HOSTS:
                chosen = sorted((run for run in runs if (run["case"], run["variant"], run["host"]) == (task, variant, host)),
                                key=lambda run: run["summary"]["rep"])
                case[side][host] = [run["summary"] for run in chosen]
        cases.append(case)
    return cases


def variant_revision(run_root: Path, campaign: str, variant: str) -> str:
    shas = ((read_json(campaign_dir(run_root, campaign) / "campaign.json", {}) or {}).get("inputs") or {}).get("variant_shas") or {}
    revision = str(shas.get(variant) or "")[:12]
    if not revision:
        raise ConfigError(f"campaign {campaign} stores no revision for variant {variant}")
    return revision


def verdict_entries(compared: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Every verdict of a comparison with the step that decided it: per case, quality, each measure, and the case as a whole."""
    entries: list[dict[str, str]] = []
    for item in compared["cases"]:
        case = item["case"]
        entries.append({"case": case, "measure": "quality", "verdict": item["quality"]["verdict"], "step": item["quality"]["reason"]})
        entries += [{"case": case, "measure": m["measure"], "verdict": m["verdict"], "step": m["step"]} for m in item["measures"]]
        entries.append({"case": case, "verdict": item["verdict"],
                        "step": "quality, every measure, and the claim of the case" if claims else "quality and every measure of the case"})
    for claim in claims:
        steps = ", ".join(f"{host}: {data['step']}" for host, data in claim["hosts"].items())
        entries.append({"case": claim["case"], "measure": "claim", "verdict": claim["verdict"],
                        "step": f"{','.join(claim['claimed'])}; {steps}"})
    return entries


def record_campaign(
    run_root: Path, campaign: str, issue: int, before: str, after: str, claimed: Sequence[str] = (),
    tasks: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Judge a before and an after variant on both hosts and build its record. Returns the record, the `compare` result with
    every claimed case and the overall verdict decided together with its claim, and the claim verdicts. A missing run or
    value reads "not measured", never a pass."""
    unknown = [measure for measure in claimed if measure not in MEASURES]
    if unknown or before == after:
        raise ConfigError("--claim takes " + ", ".join(MEASURES) + "; --before and --after name two different variants")
    runs = campaign_runs(run_root, campaign, (before, after), tasks)
    cases = build_cases(runs, before, after, expected_tasks(run_root, campaign, tasks, runs))
    if not cases or not any(run["entry"] for run in runs):
        raise ConfigError(f"campaign {campaign} holds no finished graded run of {before} or {after}")
    claims = [claim_verdict(case, claimed) for case in cases] if claimed else []
    compared = with_claims(compare(cases), claims)
    revisions = {name: variant_revision(run_root, campaign, name) for name in (before, after)}
    record = build_record(issue, [case["id"] for case in cases], revisions, [run["entry"] for run in runs if run["entry"]],
                          verdict_entries(compared, claims))
    return {"record": record, "compared": compared, "claims": claims}


def repeat_lines(compared: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]) -> list[str]:
    """Which cases need more runs: a measure whose gap grew, or a claim that has not reached its decision."""
    lines = [f"repeat: {item['case']} {m['measure']}: {m['step']}" for item in compared["cases"]
             for m in item["measures"] if m["verdict"] == REPEAT]
    lines += [f"repeat: {claim['case']} claim: {claim['verdict']}" for claim in claims if claim["verdict"] in (CONTINUE_TO_FIVE, SECOND_PAIR)]
    return lines


def report_lines(result: Mapping[str, Any]) -> list[str]:
    """One verdict line per case, then the investigate lines, the repeat lines, and the overall verdict."""
    compared, claims = result["compared"], result["claims"]
    lines = []
    claim_state = {claim["case"]: claim["verdict"] for claim in claims}
    for item in compared["cases"]:
        parts = [f"quality {item['quality']['verdict']}"] + [f"{m['measure']} {m['verdict']}" for m in item["measures"]]
        if item["case"] in claim_state:
            parts.append(f"claim {claim_state[item['case']]}")
        lines.append(f"{item['case']}: {item['verdict']} ({'; '.join(parts)})")
    lines += compared["lines"] + repeat_lines(compared, claims)
    lines += [f"claim {claim['case']}: {claim['verdict']}" for claim in claims]
    return lines + [f"overall: {compared['verdict']}"]
