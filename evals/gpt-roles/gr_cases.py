"""The case table of the GPT role comparison: which existing case or new case each role runs, how it is seeded, what the
assignment is, and how a result is graded. Reused: model-roles T89 to T91, role-runner-scratch cases 5 and 7, and the scout-demo
fixture of T103 to T105. New: TR1, TR2, W1 to W3, SC1 to SC3 (graders written for the role runner), and R1."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import gr_research_cases
import gr_text_cases
import gr_worker_cases

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals" / "model-roles"))
import mr_cases  # noqa: E402
import mr_grading  # noqa: E402

DEMO_PATH = REPO_ROOT / "evals" / "role-runner-scratch" / "demo.py"
SCOUT_FIXTURE = REPO_ROOT / "evals" / "e2e" / "fixtures" / "scout-demo"
EXISTING = "existing"
NEW = "new"


@dataclass(frozen=True)
class Case:
    id: str
    role: str
    kind: str
    source: str
    effort: str = "high"
    note: str = ""


CASES = {case.id: case for case in (
    Case("T89", "reviewer", "mr-review", EXISTING), Case("T90", "reviewer", "mr-review", EXISTING),
    Case("T91", "reviewer", "mr-review", EXISTING), Case("S5", "reviewer", "scratch-validation", EXISTING, note="role-runner-scratch case 5"),
    Case("TR1", "text_review", "text-review", NEW), Case("TR2", "text_review", "text-review", NEW),
    Case("W1", "worker", "worker", NEW), Case("W2", "worker", "worker", NEW), Case("W3", "worker", "worker", NEW),
    Case("S7", "scout", "scratch-scout", EXISTING, note="role-runner-scratch case 7"),
    Case("SC1", "scout", "scout-demo", NEW, note="question of T103 on the scout-demo fixture"),
    Case("SC2", "scout", "scout-demo", NEW, note="question of T104"), Case("SC3", "scout", "scout-demo", NEW, note="question of T105"),
    Case("R1", "researcher", "researcher", NEW),
    Case("W4", "worker", "worker", NEW, note="harder: pagination across two modules"),
    Case("W5", "worker", "worker", NEW, note="harder: thread races in two modules"),
    Case("W6", "worker", "worker", NEW, note="harder: one precedence rule in three modules"),
    Case("R2", "researcher", "researcher", NEW, note="harder: several exact facts"),
    Case("R3", "researcher", "researcher", NEW, note="harder: several exact facts"),
)}
ROLE_CASES = {role: [case.id for case in CASES.values() if case.role == role] for role in ("reviewer", "text_review", "worker", "scout", "researcher")}

REVIEW_ASSIGNMENT = (
    "Review pricing.py in the current repository for correctness against its docstring. "
    "Confirm any defect you report by running the repository's tests. Change no file.\n"
)
SCOUT_ASSIGNMENTS = {
    "SC1": "Scope: demo-lib/src/parser.py only. Question: how does `parse_pair` choose the delimiter that splits a line? Quote the code with its path and line numbers. Change no file.\n",
    "SC2": "Scope: demo-lib/docs/missing.md only. Question: which deployment steps does that file list? Change no file.\n",
    "SC3": "Scope: demo-lib/src/tokens.py and demo-lib/docs/overview.md only. Question: which delimiters does the library accept, and what maximum line length does it allow? Change no file.\n",
}
RESEARCH_ASSIGNMENT = (
    "Use only the web search tool. Find the publication year of RFC 2119 and its exact title, and give the URL of the page you used. Change no file.\n"
)
CONTENT_CLAIM = re.compile(r"(?i)(no deployment steps|does not (?:list|contain|describe|mention)|is empty|empty file|steps? (?:are|is) (?:not )?(?:listed|documented))")


def load_demo():
    spec = importlib.util.spec_from_file_location("role_runner_scratch_demo", DEMO_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_scout_demo(repo: Path) -> None:
    shutil.copytree(SCOUT_FIXTURE, repo, dirs_exist_ok=True)
    for arguments in (("init", "-q", "-b", "main"), ("add", "-A"), ("-c", "user.name=demo", "-c", "user.email=demo@example.com", "commit", "-q", "-m", "seed")):
        subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, check=True)


def scout_failures(case_id: str, answer: str) -> list[str]:
    found = []
    if case_id == "SC1":
        if not re.search(r"parser\.py\W{0,3}(?:lines?\s*)?\d+", answer, re.IGNORECASE):
            found.append("no path with line numbers")
        if "for delimiter in DELIMITERS" not in answer and "def parse_pair" not in answer:
            found.append("no quoted source")
        if not re.search(r"(?i)first|in order|order", answer):
            found.append("does not say the delimiters are tried in order")
    elif case_id == "SC2":
        if "missing.md" not in answer:
            found.append("does not name the missing file")
        if not re.search(r"(?i)missing|not found|does not exist|no such file|cannot|blocked", answer):
            found.append("does not say the file is missing")
        if CONTENT_CLAIM.search(answer):
            found.append("claims something about the content of a file that is not there")
    elif case_id == "SC3":
        if not (("`=`" in answer and "`:`" in answer) or ('"="' in answer and '":"' in answer) or "DELIMITERS" in answer):
            found.append("does not state both delimiters")
        if not (re.search(r"(?i)\bunknown\b|not (?:stated|specified|defined|documented|found)|no (?:maximum|max|limit)", answer)
                and re.search(r"(?i)\b(length|maximum|max)\b", answer)):
            found.append("does not say the maximum line length is unknown")
    return found


def researcher_failures(answer: str, records: str, case_id: str = "R1") -> list[str]:
    if case_id != "R1":
        return gr_research_cases.failures(case_id, answer, records)
    found = []
    if "1997" not in answer:
        found.append("the year 1997 is missing")
    if not re.search(r"(?i)key words for use in rfcs to indicate requirement levels", answer):
        found.append("the exact title is missing")
    if not re.search(r"https?://\S+", answer):
        found.append("no URL")
    if not re.search(r"web_search|web\.search|tools\.web__run", records):
        found.append("the rollout shows no web search call")
    return found


def mr_failures(case_id: str, answer: str) -> tuple[list[str], dict]:
    grade = mr_grading.grade(mr_cases.load_cases()[case_id], answer)
    reasons = []
    if grade.get("error"):
        reasons.append(grade["error"])
    reasons += [f"missed {item}" for item in grade.get("missed", [])]
    reasons += [f"finding outside the list at {item['location']}" for item in grade.get("outside", [])]
    return reasons, grade


def researcher_assignment(case_id: str) -> str:
    return RESEARCH_ASSIGNMENT if case_id == "R1" else gr_research_cases.ASSIGNMENTS[case_id]


def worker_assignment(case_id: str) -> str:
    return gr_worker_cases.CASES[case_id]["assignment"]
