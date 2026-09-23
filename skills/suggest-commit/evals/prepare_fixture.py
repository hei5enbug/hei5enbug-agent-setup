#!/usr/bin/env python3
"""Create isolated temporary Git repositories for suggest-commit evaluations."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_CASES = ("documented-ticket", "no-change", "unborn-mixed")
AUTHOR_NAME = "Suggest Commit Evaluation"
AUTHOR_EMAIL = "suggest-commit-eval@example.invalid"

HISTORY_SUBJECTS = (
    "fix(api): preserve HTTP error details",
    "test(api): check retry boundaries",
    "refactor(retry): isolate status rules",
    "docs(api): clarify response handling",
    "feat(api): add status mapping",
    "fix(retry): avoid duplicate requests",
    "test(retry): cover response codes",
    "chore(api): update fixture examples",
    "refactor(api): name status parser",
    "fix(api): handle empty responses",
    "test(api): verify error messages",
    "docs(retry): explain retry limits",
    "feat(retry): add response classification",
    "fix(api): preserve HTTP headers",
    "test(api): cover malformed payloads",
    "refactor(api): simplify status checks",
    "chore(retry): refresh local examples",
    "fix(retry): stop after the limit",
    "test(retry): assert request count",
    "docs(api): refine error guidance",
)


class FixtureError(ValueError):
    pass


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _git(repo: Path, *arguments: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _write(repo: Path, relative_path: str, content: str) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _initialize_repo(repo: Path, template_dir: Path, environment: dict[str, str]) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "--quiet", "--initial-branch=main", f"--template={template_dir}", environment=environment)
    _git(repo, "config", "user.name", AUTHOR_NAME, environment=environment)
    _git(repo, "config", "user.email", AUTHOR_EMAIL, environment=environment)
    _git(repo, "config", "commit.gpgsign", "false", environment=environment)
    _git(repo, "config", "core.hooksPath", str(template_dir), environment=environment)


def _commit(repo: Path, subject: str, environment: dict[str, str]) -> None:
    _git(repo, "add", "--all", environment=environment)
    _git(repo, "commit", "--quiet", "-m", subject, environment=environment)


def _create_documented_ticket(repo: Path, template_dir: Path, environment: dict[str, str]) -> None:
    _initialize_repo(repo, template_dir, environment)
    notes = ["# Commit guidance", ""]
    notes.extend(
        f"Commit format note {number:02d}: Keep the subject description concise."
        for number in range(1, 12)
    )
    notes.append("Commit convention: the ticket slot is required in `fix: [TICKET] description`.")
    _write(repo, "CONTRIBUTING.md", "\n".join(notes) + "\n")
    _write(repo, "HISTORY.md", "Evaluation history fixture.\n")
    _write(repo, "src/retry_policy.py", "RETRYABLE_HTTP_STATUS_CODES = {429}\n")
    _commit(repo, "chore: seed retry evaluation", environment)

    for number, subject in enumerate(HISTORY_SUBJECTS, start=1):
        with (repo / "HISTORY.md").open("a", encoding="utf-8") as history:
            history.write(f"sample {number:02d}\n")
        _commit(repo, subject, environment)

    _git(repo, "checkout", "--quiet", "-b", "feature/ABC-123", environment=environment)
    _write(repo, "src/retry_policy.py", "RETRYABLE_HTTP_STATUS_CODES = {429, 503}\n")


def _create_no_change(repo: Path, template_dir: Path, environment: dict[str, str]) -> None:
    _initialize_repo(repo, template_dir, environment)
    _write(repo, "README.md", "Clean repository for the no-change evaluation.\n")
    _commit(repo, "chore: seed clean evaluation repository", environment)


def _create_unborn_mixed(repo: Path, template_dir: Path, environment: dict[str, str]) -> None:
    _initialize_repo(repo, template_dir, environment)
    _write(repo, "src/auth.py", "def is_authenticated(token):\n    return bool(token)\n")
    _git(repo, "add", "--", "src/auth.py", environment=environment)
    _write(repo, "src/auth.py", "def is_authenticated(token):\n    return token is not None\n")
    _write(
        repo,
        "tests/test_auth.py",
        "def test_empty_token_is_present():\n    assert is_authenticated(\"\")\n",
    )
    _write(repo, "notes/unrelated.txt", "Unrelated evaluation note.\n")


BUILDERS = {
    "documented-ticket": _create_documented_ticket,
    "no-change": _create_no_change,
    "unborn-mixed": _create_unborn_mixed,
}


def prepare_fixtures(case_names: Iterable[str], output_root: str | Path) -> tuple[Path, dict[str, Path]]:
    names = tuple(case_names)
    if not names or any(name not in BUILDERS for name in names):
        raise FixtureError(f"Choose one or more of: {', '.join(FIXTURE_CASES)}")
    if len(names) != len(set(names)):
        raise FixtureError("Fixture case names must be unique.")

    root = Path(output_root).expanduser().resolve()
    repository_root = REPOSITORY_ROOT.resolve()
    if _is_within(root, repository_root):
        raise FixtureError("Fixture repositories must be created outside the actual repository.")
    if root.exists() and any(root.iterdir()):
        raise FixtureError("The fixture output directory must be empty.")
    root.mkdir(parents=True, exist_ok=True)

    template_dir = root / ".empty-git-template"
    template_dir.mkdir()
    global_config = root / ".empty-gitconfig"
    global_config.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": str(global_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
        }
    )

    repositories: dict[str, Path] = {}
    for name in names:
        repo = root / name
        BUILDERS[name](repo, template_dir, environment)
        repositories[name] = repo
    return root, repositories


def prepare_fixture(case_name: str, output_root: str | Path) -> Path:
    _, repositories = prepare_fixtures((case_name,), output_root)
    return repositories[case_name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("all", *FIXTURE_CASES), default="all")
    parser.add_argument("--output-dir", type=Path, help="Empty directory outside the actual repository")
    args = parser.parse_args()

    output_root = args.output_dir or Path(tempfile.mkdtemp(prefix="suggest-commit-eval-"))
    names = FIXTURE_CASES if args.case == "all" else (args.case,)
    try:
        root, repositories = prepare_fixtures(names, output_root)
    except (FixtureError, OSError, subprocess.CalledProcessError) as error:
        print(f"fixture preparation failed: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "fixture_root": str(root),
                "fixtures": {name: {"repo": str(repo), "cwd": str(repo)} for name, repo in repositories.items()},
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
