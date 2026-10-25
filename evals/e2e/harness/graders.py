"""Deterministic grading of one finished run: fixture materialization, the check library, and grade_run.

grade_run never touches the run repository. It copies it (with `.git`) to `work/repo`, records the git facts there
once, and runs the pytest suites in further copies under `work/suites/` so that restoring the original tests or
adding the hidden ones cannot hide what the agent changed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

try:
    from . import coverage_tool
except ImportError:
    import coverage_tool  # type: ignore[no-redef]

IDENTITY = {"name": "Demo Dev", "email": "dev@example.com"}
FIXED_DATE = "2026-01-15T09:00:00+00:00"
NOISE_PARTS = ("__pycache__", ".pytest_cache")
PYTEST_TIMEOUT_SECONDS = 600
TEXT_FILE_LIMIT = 2_000_000
SUITES = ("preexisting", "hidden", "all")
SUMMARY_LINE = re.compile(r"^(?:=+ )?(?P<body>(?:\d+ [a-z]+(?:, )?)+|no tests ran)(?: \(.*?\))? in [\d.]+s", re.MULTILINE)
SUMMARY_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)")
FAILED_ID = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)

class GradingError(RuntimeError):
    """A grading copy cannot be written without leaving its root."""


CheckResult = tuple[bool, str, dict[str, Any]]
CheckFunction = Callable[["GradeContext", Mapping[str, Any]], CheckResult]


def git_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "XDG_CONFIG_HOME": os.devnull,
                "GIT_TERMINAL_PROMPT": "0"})
    env.update(extra or {})
    return env


def identity_environment() -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": IDENTITY["name"], "GIT_AUTHOR_EMAIL": IDENTITY["email"],
        "GIT_COMMITTER_NAME": IDENTITY["name"], "GIT_COMMITTER_EMAIL": IDENTITY["email"],
        "GIT_AUTHOR_DATE": FIXED_DATE, "GIT_COMMITTER_DATE": FIXED_DATE,
    }


def git(repo: Path, *args: str, env: Mapping[str, str] | None = None, check: bool = True) -> str:
    command = ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args]
    completed = subprocess.run(command, cwd=repo, env=git_environment(env), capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
    if check and completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def contained(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _replace_with_directory(path: Path) -> None:
    path.unlink()
    path.mkdir()


def prepare_destination(root: Path, relative: str) -> Path:
    """Make `root/relative` writable without following a link: turn every symlinked component into a plain directory
    and drop every symlink below the destination, then verify that the result is inside `root`."""
    if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
        raise GradingError(f"destination {relative!r} leaves the grading copy")
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            _replace_with_directory(current)
    current.mkdir(parents=True, exist_ok=True)
    for directory, names, files in os.walk(current):
        for name in [*names, *files]:
            entry = Path(directory) / name
            if entry.is_symlink():
                entry.unlink()
    if not contained(root, current):
        raise GradingError(f"destination {relative!r} resolves outside the grading copy")
    return current


def is_noise(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return any(part in NOISE_PARTS for part in parts) or path.endswith(".pyc")


def materialize_fixture(task: Mapping[str, Any], fixtures_root: Path, tasks_root: Path, dest: Path) -> str:
    """Copy the task's fixture into `dest`, commit it as the base, run the setup script, and return HEAD."""
    source = Path(fixtures_root).resolve() / task["fixture"]
    target = Path(dest).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ValueError(f"{target} is not empty")
    shutil.copytree(source, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git"))
    env = identity_environment()
    git(target, "init", "-q", "-b", "main", env=env)
    git(target, "config", "--local", "user.name", IDENTITY["name"], env=env)
    git(target, "config", "--local", "user.email", IDENTITY["email"], env=env)
    git(target, "add", "-A", env=env)
    git(target, "commit", "-q", "-m", "Initial commit", env=env)
    setup = task.get("setup")
    if setup:
        completed = subprocess.run([sys.executable, str(Path(tasks_root).resolve() / setup), str(target)], cwd=target,
                                   env={**git_environment(env)}, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"setup {setup} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return git(target, "rev-parse", "HEAD").strip()


def glob_regex(pattern: str) -> re.Pattern[str]:
    pattern = pattern.rstrip("/") + "/**" if pattern.endswith("/") else pattern
    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(out) + r"\Z")


def matches(path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        regex = glob_regex(pattern)
        if regex.match(path) or ("/" not in pattern and regex.match(PurePosixPath(path).name)):
            return True
    return False


def walk_files(root: Path) -> list[str]:
    found: list[str] = []
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name != ".git" and name not in NOISE_PARTS]
        for name in files:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if not is_noise(relative):
                found.append(relative)
    return sorted(found)


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > TEXT_FILE_LIMIT:
            return None
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def parse_pytest_output(text: str) -> dict[str, Any]:
    """Read the counts from pytest's final summary line and the failing ids from the short summary."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    summaries = list(SUMMARY_LINE.finditer(text))
    if summaries:
        for number, word in SUMMARY_COUNT.findall(summaries[-1].group("body")):
            key = "errors" if word.startswith("error") else word
            if key in counts:
                counts[key] = int(number)
    counts["total"] = sum(counts.values())
    counts["summary_found"] = bool(summaries)
    counts["failing"] = sorted(set(FAILED_ID.findall(text)))[:20]
    return counts


def pytest_passed(counts: Mapping[str, Any], returncode: int, suite: str) -> bool:
    if returncode != 0 or not counts["summary_found"] or counts["passed"] == 0:
        return False
    if counts["failed"] or counts["errors"]:
        return False
    return suite == "all" or not (counts["skipped"] or counts["xfailed"])


@dataclass
class GradeContext:
    task: Mapping[str, Any]
    repo: Path
    base: str
    view: Mapping[str, Any]
    tasks_root: Path
    work: Path
    changes: dict[str, str] = field(default_factory=dict)
    porcelain: str = ""
    suite_results: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def fixtures_root(self) -> Path:
        return self.tasks_root.parent / "fixtures"

    def git(self, *args: str) -> str:
        return git(self.repo, *args, check=False)

    def test_env(self, root: Path) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        for key, value in (self.task.get("test_env") or {}).items():
            env[key] = str(root / value) if (root / value).exists() else str(value)
        return env

    def snapshot_git_facts(self) -> None:
        self.porcelain = self.git("status", "--porcelain", "--untracked-files=all")
        index = self.work / "grade.index"
        env = {"GIT_INDEX_FILE": str(index)}
        git(self.repo, "read-tree", self.base, env=env)
        git(self.repo, "add", "-A", env=env)
        listing = git(self.repo, "diff", "--cached", "--no-renames", "--name-status", self.base, env=env)
        for line in listing.splitlines():
            status, _, path = line.partition("\t")
            if path and not is_noise(path):
                self.changes[path] = status[:1]

    def suite_copy(self, name: str) -> Path:
        target = self.work / "suites" / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.repo, target, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"))
        return target

    def hidden_spec(self) -> Mapping[str, str] | None:
        return self.task.get("hidden_tests")

    def install_hidden(self, root: Path) -> str | None:
        spec = self.hidden_spec()
        if not spec:
            return None
        source = self.tasks_root / spec["source"]
        destination = prepare_destination(root, spec["dest"])
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return spec["dest"]

    def restore_preexisting(self, root: Path) -> list[str]:
        original = self.fixtures_root / self.task["fixture"] / "tests"
        if not original.is_dir():
            return []
        restored = prepare_destination(root, "tests")
        shutil.copytree(original, restored, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
        return [f"tests/{path}" for path in walk_files(original) if re.search(r"(^|/)(test_[^/]*|[^/]*_test)\.py$", path)]

    def run_suite(self, suite: str, files: Sequence[str] = ()) -> dict[str, Any]:
        key = f"{suite}:{','.join(files)}" if files else suite
        if key in self.suite_results:
            return self.suite_results[key]
        root = self.suite_copy(key.replace(":", "-").replace(",", "+").replace("/", "_"))
        command = [sys.executable if part == "python3" else part for part in self.task["test_command"]]
        if suite == "preexisting":
            targets = self.restore_preexisting(root)
        elif suite == "hidden":
            self.restore_preexisting(root)
            destination = self.install_hidden(root) or "tests/hidden"
            targets = [f"{destination}/{name}" for name in files] or [destination]
        else:
            targets = []
        result = self.execute_tests([*command, "-rfE", *targets], root)
        self.suite_results[key] = result
        return result

    def execute_tests(self, command: Sequence[str], root: Path) -> dict[str, Any]:
        try:
            completed = subprocess.run(list(command), cwd=root, env=self.test_env(root), capture_output=True,
                                       text=True, encoding="utf-8", errors="replace", timeout=PYTEST_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            counts = parse_pytest_output("")
            return {**counts, "returncode": -1, "timed_out": True, "output_tail": ""}
        counts = parse_pytest_output(completed.stdout)
        return {**counts, "returncode": completed.returncode, "timed_out": False,
                "output_tail": completed.stdout[-1500:] + completed.stderr[-500:]}


def check_pytest(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    suite = spec.get("suite", "all")
    if suite not in SUITES:
        raise ValueError(f"unknown pytest suite: {suite}")
    if suite == "hidden" and not ctx.hidden_spec():
        return False, "the task has no hidden tests", {}
    result = ctx.run_suite(suite, tuple(spec.get("files", ())))
    ok = pytest_passed(result, result["returncode"], suite)
    detail = (f"{suite}: {result['passed']} passed, {result['failed']} failed, {result['errors']} errors, "
              f"{result['skipped']} skipped (exit {result['returncode']})")
    data = {key: result[key] for key in ("passed", "failed", "errors", "skipped", "total", "failing", "timed_out")}
    if not ok:
        data["output_tail"] = result["output_tail"]
    return ok, detail, data


def paths_for(spec: Mapping[str, Any], ctx: GradeContext) -> list[str]:
    patterns = spec.get("paths") or [spec.get("path") or spec.get("glob")]
    files = walk_files(ctx.repo)
    return [path for path in files if matches(path, [p for p in patterns if p])]


def exists_nonempty(ctx: GradeContext, target: str) -> bool:
    path = ctx.repo / target
    if path.is_file():
        return True
    return path.is_dir() and bool(walk_files(path))


def check_file_exists(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    target = spec.get("path")
    found = [target] if target and (ctx.repo / target).is_file() else ([] if target else paths_for(spec, ctx))
    return bool(found), f"found {found[:5]}" if found else f"missing {target or spec.get('glob')}", {"found": found}


def check_file_absent(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    target = spec.get("path")
    present = ([target] if exists_nonempty(ctx, target) else []) if target else paths_for(spec, ctx)
    return not present, f"still present: {present[:5]}" if present else "absent", {"present": present}


def check_file_contains(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    pattern = re.compile(spec["pattern"], re.MULTILINE)
    minimum = int(spec.get("min_count", 1))
    candidates = [spec["path"]] if "/" in spec["path"] or "*" not in spec["path"] else paths_for(spec, ctx)
    counts: dict[str, int] = {}
    for candidate in candidates:
        text = read_text(ctx.repo / candidate)
        counts[candidate] = len(pattern.findall(text)) if text is not None else 0
    ok = any(count >= minimum for count in counts.values())
    return ok, f"matches per file: {counts}", {"counts": counts}


def check_file_not_contains(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    pattern = re.compile(spec["pattern"], re.MULTILINE)
    offenders = [path for path in paths_for(spec, ctx) if pattern.search(read_text(ctx.repo / path) or "")]
    return not offenders, f"matches in {offenders[:5]}" if offenders else "no match", {"offenders": offenders}


def check_grep_absent(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    pattern = re.compile(spec["pattern"], re.MULTILINE)
    exclude = spec.get("exclude", [])
    hits: list[str] = []
    for path in walk_files(ctx.repo):
        if not matches(path, [spec["glob"]]) or matches(path, exclude):
            continue
        for number, line in enumerate((read_text(ctx.repo / path) or "").splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path}:{number}")
    return not hits, f"found at {hits[:8]}" if hits else "no match", {"hits": hits[:50], "count": len(hits)}


def check_unchanged(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    changed = sorted(path for path in ctx.changes if matches(path, spec["paths"]))
    return not changed, f"changed: {changed[:8]}" if changed else "unchanged", {"changed": changed}


def check_only_changed(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    outside = sorted(path for path in ctx.changes if not matches(path, spec["allow"]))
    return not outside, f"changed outside the allowed paths: {outside[:8]}" if outside else "ok", {
        "outside": outside, "changed": sorted(ctx.changes)}


def check_no_changes(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    changed = sorted(ctx.changes)
    return not changed, f"changed: {changed[:8]}" if changed else "tree identical to base", {"changed": changed}


def check_git_commits(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    raw = ctx.git("log", "--reverse", "--format=%H%x1f%s%x1f%B%x1e", f"{ctx.base}..HEAD")
    commits = []
    for record in filter(None, (part.strip("\n") for part in raw.split("\x1e"))):
        sha, subject, message = (record.split("\x1f") + ["", ""])[:3]
        commits.append({"sha": sha[:12], "subject": subject, "message": message})
    problems: list[str] = []
    if len(commits) < spec.get("min", 0) or len(commits) > spec.get("max", 10**6):
        problems.append(f"{len(commits)} commits, expected {spec.get('min', 0)}..{spec.get('max', 'any')}")
    subject_regex = spec.get("subject_regex")
    for commit in commits:
        if subject_regex and not re.search(subject_regex, commit["subject"]):
            problems.append(f"subject does not match: {commit['subject']!r}")
        if "subject_max" in spec and len(commit["subject"]) > spec["subject_max"]:
            problems.append(f"subject longer than {spec['subject_max']}: {len(commit['subject'])}")
        forbid = spec.get("body_forbid")
        if forbid and re.search(forbid, commit["message"], re.IGNORECASE | re.MULTILINE):
            problems.append(f"forbidden text in the message of {commit['sha']}")
    return not problems, "; ".join(problems) or f"{len(commits)} commit(s) ok", {
        "commits": [{"sha": c["sha"], "subject": c["subject"]} for c in commits]}


def check_git_clean(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    lines = [line for line in ctx.porcelain.splitlines() if not is_noise(line[3:])]
    return not lines, f"not clean: {lines[:8]}" if lines else "clean", {"porcelain": lines}


def check_coverage(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    root = ctx.suite_copy("coverage")
    tests = spec.get("tests") or ["tests"]
    args = ["-q", "-p", "no:cacheprovider", *tests]
    result = coverage_tool.measure(root, spec["module"], args, env=ctx.test_env(root))
    percent = float(result.get("percent", 0.0))
    detail = result.get("error") or f"{spec['module']}: {percent}% ({result.get('executed')}/{result.get('executable')})"
    return percent >= float(spec["min_percent"]) and "error" not in result, detail, {
        key: result.get(key) for key in ("percent", "executable", "executed", "missing", "pytest_returncode", "error")}


def bash_commands(view: Mapping[str, Any]) -> list[str]:
    return [str(call.get("input", {}).get("command", "")) for call in view.get("tool_calls", [])
            if call.get("name") == "Bash"]


def scope_texts(view: Mapping[str, Any], scope: str) -> list[str]:
    if scope == "assistant_text":
        return list(view.get("assistant_texts", []))
    if scope == "final_answer":
        return [view.get("final_answer", "")]
    if scope == "bash_commands":
        return bash_commands(view)
    if scope == "tool_results":
        return [str(call.get("result_text", "")) for call in view.get("tool_calls", [])]
    raise ValueError(f"unknown transcript scope: {scope}")


def check_transcript_absent(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    pattern = re.compile(spec["pattern"])
    leaked = [scope for scope in spec["scope"] if any(pattern.search(text) for text in scope_texts(ctx.view, scope))]
    return not leaked, f"pattern found in {leaked}" if leaked else "not found", {"leaked_scopes": leaked}


def check_forbidden_commands(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    patterns = [re.compile(pattern) for pattern in spec["patterns"]]
    offenders = [command[:200] for command in bash_commands(ctx.view) if any(p.search(command) for p in patterns)]
    return not offenders, f"forbidden: {offenders[:3]}" if offenders else "none used", {"offenders": offenders}


def check_committed_absent(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    pattern = re.compile(spec["pattern"])
    history = ctx.git("log", "--all", "-p", "-m", "--root", "--format=%H%n%B", f"^{ctx.base}")
    staged = ctx.git("diff", "--cached", ctx.base)
    where = [name for name, text in (("commits or stash", history), ("index", staged)) if pattern.search(text)]
    return not where, f"pattern found in {where}" if where else "not found", {"where": where}


def check_answer_contains(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    answer = ctx.view.get("final_answer", "")
    hit = [pattern for pattern in spec["patterns"] if re.search(pattern, answer, re.IGNORECASE | re.MULTILINE)]
    minimum = int(spec.get("min", len(spec["patterns"])))
    return len(hit) >= minimum, f"{len(hit)} of {len(spec['patterns'])} patterns found, need {minimum}", {"hit": hit}


def review_completed(delegation: Mapping[str, Any]) -> bool:
    """A role_runner review needs exit 0; an agent review needs a completed result that is not an error."""
    if delegation.get("kind") == "role_runner":
        return delegation.get("exit") == 0
    return delegation.get("kind") == "agent" and not delegation.get("is_error") and delegation.get("completed", True)


def check_review_before_report(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    limit = ctx.view.get("final_answer_order")
    reviews = [d for d in ctx.view.get("delegations", [])
               if d.get("class") == "review" and review_completed(d) and (limit is None or d.get("order", 0) < limit)]
    return bool(reviews), f"{len(reviews)} completed review delegation(s) before the final answer", {
        "reviews": [d.get("tool_use_id") for d in reviews]}


def load_custom(ctx: GradeContext, function: str) -> Callable[[Any], CheckResult]:
    path = ctx.tasks_root / "custom" / f"{ctx.task['id']}.py"
    module = types.ModuleType(f"e2e_custom_{ctx.task['id']}")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return getattr(module, function)


def check_custom(ctx: GradeContext, spec: Mapping[str, Any]) -> CheckResult:
    function = load_custom(ctx, spec.get("function", "check"))
    context = types.SimpleNamespace(repo=ctx.repo, base=ctx.base, view=ctx.view, task=ctx.task, work=ctx.work,
                                    changes=dict(ctx.changes), git=ctx.git, porcelain=ctx.porcelain)
    ok, detail, data = function(context)
    return bool(ok), str(detail), dict(data or {})


CHECKS: dict[str, CheckFunction] = {
    "pytest": check_pytest, "file_exists": check_file_exists, "file_absent": check_file_absent,
    "file_contains": check_file_contains, "file_not_contains": check_file_not_contains,
    "unchanged": check_unchanged, "only_changed": check_only_changed, "no_changes": check_no_changes,
    "grep_absent": check_grep_absent, "git_commits": check_git_commits, "git_clean": check_git_clean,
    "coverage": check_coverage, "transcript_absent": check_transcript_absent,
    "forbidden_commands": check_forbidden_commands, "committed_absent": check_committed_absent,
    "answer_contains": check_answer_contains, "review_before_report": check_review_before_report,
    "custom": check_custom,
}


def run_check(ctx: GradeContext, spec: Mapping[str, Any]) -> dict[str, Any]:
    try:
        ok, detail, data = CHECKS[spec["kind"]](ctx, spec)
    except Exception as exc:  # a broken check must fail visibly, not stop the grade
        ok, detail, data = False, f"check error: {type(exc).__name__}: {exc}", {}
    return {"id": spec["id"], "kind": spec["kind"], "required": bool(spec.get("required", False)),
            "weight": spec.get("weight", 1), "passed": bool(ok), "detail": detail, "data": data}


def evaluate_constraints(task: Mapping[str, Any], view: Mapping[str, Any],
                         checks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    failed = {check["id"] for check in checks if not check["passed"]}
    results = []
    for constraint in task.get("constraints", []):
        keywords = [keyword.lower() for keyword in constraint.get("keywords", [])]
        missing = [d.get("tool_use_id") for d in view.get("delegations", [])
                   if d.get("class") in constraint.get("applies_to", [])
                   and not any(keyword in str(d.get("prompt", "")).lower() for keyword in keywords)]
        traced = sorted(failed & set(constraint.get("check_ids", []))) if missing else []
        results.append({"id": constraint["id"], "missing_in": missing, "traced_failures": traced})
    return results


def summarize_tests(suites: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    return {name: {"passed": result["passed"], "failed": result["failed"], "errors": result["errors"],
                   "total": result["total"], "skipped": result["skipped"]} for name, result in suites.items()}


def merge_suites(results: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold the per-file hidden runs into one `hidden` entry by summing their counts."""
    merged: dict[str, dict[str, Any]] = {}
    for key, result in results.items():
        name = key.split(":")[0]
        current = merged.setdefault(name, {field: 0 for field in ("passed", "failed", "errors", "skipped", "total")})
        for field in current:
            current[field] += result[field]
    return merged


def pass_rate(tests: Mapping[str, Mapping[str, int]]) -> float | None:
    chosen = [tests[name] for name in ("preexisting", "hidden") if name in tests] or (
        [tests["all"]] if "all" in tests else [])
    total = sum(item["total"] for item in chosen)
    return round(sum(item["passed"] for item in chosen) / total, 4) if total else None


def grade_run(task: Mapping[str, Any], repo: Path, base_commit: str, view: Mapping[str, Any], tasks_root: Path,
              work: Path) -> dict[str, Any]:
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    copy = work / "repo"
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(Path(repo).resolve(), copy, symlinks=True)
    ctx = GradeContext(task=task, repo=copy, base=base_commit, view=view, tasks_root=Path(tasks_root).resolve(),
                       work=work)
    ctx.snapshot_git_facts()
    checks = [run_check(ctx, spec) for spec in task["checks"]]
    tests = summarize_tests(merge_suites(ctx.suite_results))
    total_weight = sum(check["weight"] for check in checks)
    earned = sum(check["weight"] for check in checks if check["passed"])
    preexisting = tests.get("preexisting")
    return {
        "checks": checks,
        "tests": tests,
        "success": all(check["passed"] for check in checks if check["required"]),
        "correctness": round(earned / total_weight, 4) if total_weight else 0.0,
        "test_pass_rate": pass_rate(tests),
        "regressions": preexisting["failed"] + preexisting["errors"] if preexisting else 0,
        "constraints": evaluate_constraints(task, view, checks),
    }


def load_task(tasks_root: Path, task_id: str) -> dict[str, Any]:
    return json.loads((Path(tasks_root) / f"{task_id}.json").read_text(encoding="utf-8"))
