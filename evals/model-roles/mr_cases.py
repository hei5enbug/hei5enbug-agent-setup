"""Load the seeded cases, and turn one into a repository and the prompt a candidate receives, with no model call."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from string import Template
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
CASES_ROOT = ROOT / "cases"
TEMPLATES_ROOT = ROOT / "templates"
VALIDATION_DOC = ROOT.parents[1] / "instructions" / "independent-model-validation.md"
ROLES = ("reviewer",)
GIT_ENVIRONMENT = {
    "GIT_AUTHOR_NAME": "demo", "GIT_AUTHOR_EMAIL": "demo@example.com",
    "GIT_COMMITTER_NAME": "demo", "GIT_COMMITTER_EMAIL": "demo@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}
SUBJECTS = {
    "diff": "the change below, the last commit of the repository, which holds the code after the change",
    "issue": "the issue body in `issue.md` of the repository, before it is filed",
}
IMPLEMENTATION_CHECKS = "For completed implementation, also check:"


def load_cases(root: Path = CASES_ROOT) -> dict[str, dict[str, Any]]:
    """Return every case definition by id, in id order."""
    cases = {}
    for path in sorted(root.glob("T*/case.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        cases[case["id"]] = case
    return cases


def roles_by_case(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    return {case_id: case["role"] for case_id, case in cases.items()}


def visible_files(case_id: str, root: Path = CASES_ROOT) -> dict[str, list[Path]]:
    """Return the relative paths of each commit's files: base (when the case has one), then head."""
    layers = {}
    for layer in ("base", "head"):
        folder = root / case_id / layer
        if folder.is_dir():
            layers[layer] = sorted(path.relative_to(folder) for path in folder.rglob("*") if path.is_file())
    return layers


def git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=repo, env={**os.environ, **GIT_ENVIRONMENT}, check=True, capture_output=True)


def seed_repository(case_id: str, repo: Path, root: Path = CASES_ROOT) -> None:
    """Create the case's repository: a base commit when the case has one, then the head commit with the change."""
    if repo.exists() and any(repo.iterdir()):
        raise FileExistsError(f"{repo} is not empty")
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    for layer, relatives in visible_files(case_id, root).items():
        for relative in relatives:
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / case_id / layer / relative, target)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", f"{case_id} {layer}")


def review_checks(kind: str, doc: Path = VALIDATION_DOC) -> str:
    """Return the review-check bullets the independent validation file lists for a deliverable of this kind."""
    section = doc.read_text(encoding="utf-8").split("## Review checks", 1)[1].split("\n## ", 1)[0]
    groups: list[tuple[str, list[str]]] = []
    for line in section.splitlines():
        if line.startswith("- "):
            groups[-1][1].append(line)
        elif line.startswith("  ") and groups and groups[-1][1]:
            groups[-1][1][-1] += " " + line.strip()
        elif line.strip().endswith(":"):
            groups.append((line.strip(), []))
    wanted = [groups[0]] + ([item for item in groups if item[0] == IMPLEMENTATION_CHECKS] if kind == "diff" else [])
    return "\n".join(bullet for _, bullets in wanted for bullet in bullets)


def change_diff(repo: Path) -> str:
    return subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD"], cwd=repo, env={**os.environ, **GIT_ENVIRONMENT}, check=True,
        capture_output=True, text=True,
    ).stdout


def material(case: Mapping[str, Any], repo: Path) -> str:
    """Return what the reviewer is given besides the repository: the complete change diff, or nothing for an issue body."""
    if case["kind"] != "diff":
        return "The issue body is the file `issue.md` of the repository."
    return f"Change diff:\n\n```diff\n{change_diff(repo)}```"


def prompt_for(case: Mapping[str, Any], repo: Path) -> str:
    """Return the prompt text for the case: the reviewer assignment."""
    template = Template((TEMPLATES_ROOT / "review.txt").read_text(encoding="utf-8"))
    return template.substitute(
        intent=case["intent"], subject=SUBJECTS[case["kind"]], repo=repo, checks=case["checks"],
        material=material(case, repo), review_checks=review_checks(case["kind"]),
    )


def seed(case_id: str, out: Path) -> dict[str, str]:
    """Create `out/repo` and `out/prompt.md` for a case and return their paths."""
    case = load_cases()[case_id]
    repo = (out / "repo").resolve()
    seed_repository(case_id, repo)
    prompt = out.resolve() / "prompt.md"
    prompt.write_text(prompt_for(case, repo), encoding="utf-8")
    return {"repo": repo.as_posix(), "prompt": prompt.as_posix()}


def problem_ranges(case: Mapping[str, Any]) -> list[tuple[str, str, int, int, str]]:
    """Return (problem id, file, start, end, anchor) for every location of every listed problem."""
    return [
        (problem["id"], place["file"], place["start"], place["end"], place["anchor"])
        for problem in case["problems"] for place in problem["locations"]
    ]


def head_text(case_id: str, relative: str, root: Path = CASES_ROOT) -> str:
    """Return a file as the candidate sees it: the head layer, else the base layer."""
    for layer in ("head", "base"):
        path = root / case_id / layer / relative
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(relative)

