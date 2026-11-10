"""Writer and grader jobs with resume, one retry budget, left-out models, and a wall-time limit."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kw_models import parse_spec, run_model, slug
from kw_prompts import grader_prompt, load_cases, load_rules, parse_json, shuffle_key, writer_prompt

LEFT_OUT_AFTER = 2
RETRY_BUDGET = 10
QUOTA_WORDS = ("quota", "usage limit", "rate limit exhausted", "credit")


def draft_path(out: Path, task_id: str, run: int, writer: str) -> Path:
    return out / "drafts" / f"{task_id}_r{run}_{slug(writer)}.json"


def grade_path(out: Path, task_id: str, run: int, grader: str) -> Path:
    return out / "grades" / f"{task_id}_r{run}_{slug(grader)}.json"


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def prepare(out: Path) -> None:
    for name in ("drafts", "grades", "prompts", "raw", "work", "seeded"):
        (out / name).mkdir(parents=True, exist_ok=True)


class Tracker:
    """Shared failure bookkeeping for the worker threads."""

    def __init__(self, deadline: float):
        self.lock = threading.Lock()
        self.deadline = deadline
        self.retries = 0
        self.consecutive: dict = {}
        self.left_out: dict = {}
        self.stop_reason = ""
        self.failed: list = []

    def should_stop(self) -> bool:
        if not self.stop_reason and time.time() > self.deadline:
            self.stop_reason = "wall time limit"
        return bool(self.stop_reason)

    def record(self, job: tuple, model: str, ok: bool, error: str) -> bool:
        """Return True when the job should be tried again."""
        with self.lock:
            if ok:
                self.consecutive[model] = 0
                return False
            self.consecutive[model] = self.consecutive.get(model, 0) + 1
            lowered = error.lower()
            if any(word in lowered for word in QUOTA_WORDS):
                self.stop_reason = f"quota: {lowered[:100]}"
            if self.consecutive[model] >= LEFT_OUT_AFTER:
                self.left_out[model] = f"two consecutive infrastructure failures: {error[:150]}"
            if self.retries < RETRY_BUDGET and model not in self.left_out and not self.stop_reason:
                self.retries += 1
                return True
            self.failed.append(list(job))
            return False


def run_writer(out: Path, specs: dict, rules: str, cases: dict, task_id: str, run: int, writer: str, timeout: int) -> tuple:
    prompt = writer_prompt(cases[task_id], rules)
    (out / "prompts" / f"writer_{task_id}.txt").write_text(prompt, encoding="utf-8")
    result = run_model(specs[writer], prompt, out, f"w_{task_id}_r{run}_{slug(writer)}", timeout)
    if result["ok"] and not result.get("model_ok", True):
        result = {**result, "ok": False, "err": "modelUsage does not name the requested model"}
    record = {**result, "writer": writer, "spec": specs[writer], "task": task_id, "run": run}
    draft_path(out, task_id, run, writer).write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return result["ok"], result.get("err", "")


def draft_files(out: Path, task_id: str, run: int) -> dict:
    drafts = {}
    for path in sorted((out / "drafts").glob(f"{task_id}_r{run}_*.json")):
        record = read_json(path)
        if record:
            drafts[record["writer"]] = record["text"] if record["ok"] else None
    return drafts


def run_grader(out: Path, specs: dict, rules: str, cases: dict, seed: str, task_id: str, run: int, grader: str, timeout: int) -> tuple:
    drafts = draft_files(out, task_id, run)
    key = shuffle_key(seed, task_id, run, list(drafts))
    shown = {label: drafts[writer] for label, writer in key.items() if drafts[writer]}
    prompt = grader_prompt(cases[task_id], shown, rules)
    (out / "prompts" / f"grader_{task_id}_r{run}.txt").write_text(prompt, encoding="utf-8")
    result = run_model(specs[grader], prompt, out, f"g_{task_id}_r{run}_{slug(grader)}", timeout)
    record = {"task": task_id, "run": run, "grader": grader, "spec": specs[grader], "key": key, "res": result}
    if result["ok"]:
        try:
            record["grade"] = parse_json(result["text"])
        except (json.JSONDecodeError, ValueError) as error:
            record["parse_err"] = str(error)
    grade_path(out, task_id, run, grader).write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = result["ok"] and "grade" in record
    return ok, record.get("parse_err") or result.get("err", "")


def writer_done(out: Path, task_id: str, run: int, writer: str) -> bool:
    record = read_json(draft_path(out, task_id, run, writer))
    return bool(record and record.get("ok"))


def grade_done(out: Path, task_id: str, run: int, grader: str) -> bool:
    record = read_json(grade_path(out, task_id, run, grader))
    return bool(record and record.get("res", {}).get("ok") and "grade" in record)


def writer_jobs(out: Path, task_ids: list, runs: int, writers: list) -> list:
    jobs = []
    for run in range(1, runs + 1):
        for index, task_id in enumerate(task_ids):
            shift = (run - 1 + index) % len(writers)
            for writer in writers[shift:] + writers[:shift]:
                if not writer_done(out, task_id, run, writer):
                    jobs.append(("w", task_id, run, writer))
    return jobs


def grader_jobs(out: Path, task_ids: list, runs: int, graders: list) -> list:
    jobs = []
    for run in range(1, runs + 1):
        for task_id in task_ids:
            if sum(1 for text in draft_files(out, task_id, run).values() if text) < 2:
                continue
            jobs.extend(("g", task_id, run, grader) for grader in graders if not grade_done(out, task_id, run, grader))
    return jobs


def execute_all(jobs: list, execute, tracker: Tracker, parallel: int, log) -> None:
    def work(job):
        model = job[3]
        while not tracker.should_stop() and model not in tracker.left_out:
            started = time.time()
            try:
                ok, error = execute(job)
            except Exception as exc:  # a failed job must not stop the others
                ok, error = False, repr(exc)
            log(("OK   " if ok else "FAIL ") + f"{job} {round(time.time() - started)}s {error[:200]}")
            if not tracker.record(job, model, ok, error):
                return
    with ThreadPoolExecutor(parallel) as pool:
        list(pool.map(work, jobs))


def run_campaign(out: Path, specs: dict, writers: list, graders: list, task_ids: list, runs: int,
                 parallel: int, max_hours: float, timeout: int, seed: str, log) -> dict:
    prepare(out)
    cases, rules = load_cases(), load_rules()
    tracker = Tracker(time.time() + max_hours * 3600)
    writing = lambda job: run_writer(out, specs, rules, cases, job[1], job[2], job[3], timeout)
    grading = lambda job: run_grader(out, specs, rules, cases, seed, job[1], job[2], job[3], timeout)
    execute_all(writer_jobs(out, task_ids, runs, writers), writing, tracker, parallel, log)
    execute_all(grader_jobs(out, task_ids, runs, graders), grading, tracker, parallel, log)
    summary = {"retries": tracker.retries, "left_out": tracker.left_out, "stop": tracker.stop_reason, "failed": tracker.failed}
    (out / "campaign.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def spec_map(specs: list) -> dict:
    return {parse_spec(spec)[1]: spec for spec in specs}
