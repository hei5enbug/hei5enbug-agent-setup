"""Build the combined revision of adopted loop-shape candidates in a scratch worktree.

The combined revision is the baseline with every adopted candidate branch merged on top, in the order given. Each merge
is a commit with a fixed identity and date, so the same inputs give the same SHA. A candidate that conflicts stops the
build: the merge is aborted, the scratch worktree is removed, and the error names the candidate and the conflicting
files."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence, TextIO

from .command import ConfigError

COMBINED_FOLDER = "combined"
IDENTITY = {
    "GIT_AUTHOR_NAME": "combined-build", "GIT_AUTHOR_EMAIL": "combined-build@example.com",
    "GIT_COMMITTER_NAME": "combined-build", "GIT_COMMITTER_EMAIL": "combined-build@example.com",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000",
}
GIT_CONFIG = ("-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "merge.autoStash=false")
UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._+-]+")


def git(repo: Path, *args: str, check: bool = True, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(["git", *GIT_CONFIG, "-C", str(repo), *args], capture_output=True, text=True, check=False,
                          env={**os.environ, **(env or {})}, stdin=subprocess.DEVNULL)
    if check and done.returncode != 0:
        raise ConfigError(f"git {' '.join(args[:2])} failed: {(done.stderr or done.stdout).strip()}")
    return done


def resolve(repo: Path, ref: str) -> str:
    done = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    if done.returncode != 0:
        raise ConfigError(f"{ref} is not a commit of {repo}")
    return done.stdout.strip()


def default_worktree(run_root: Path, base: str, candidates: Sequence[str]) -> Path:
    return run_root / COMBINED_FOLDER / UNSAFE_NAME.sub("-", "+".join([base, *candidates]))


def validate(repo: Path, base: str, candidates: Sequence[str]) -> dict[str, str]:
    """The SHA of the base and of each candidate. Needs two or more distinct candidates, each a descendant of the base."""
    if len(candidates) < 2 or len(set(candidates)) != len(candidates) or base in candidates:
        raise ConfigError("--candidate takes two or more different branches, none of them the base")
    shas = {name: resolve(repo, name) for name in [base, *candidates]}
    for name in candidates:
        if git(repo, "merge-base", "--is-ancestor", shas[base], shas[name], check=False).returncode != 0:
            raise ConfigError(f"{name} does not descend from {base}; the combined revision builds on the base only")
    return shas


def conflict_files(worktree: Path) -> list[str]:
    return git(worktree, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()


def remove_worktree(repo: Path, worktree: Path) -> None:
    git(repo, "worktree", "remove", "--force", str(worktree), check=False)


def merge_all(repo: Path, worktree: Path, base: str, candidates: Sequence[str], log: TextIO) -> str:
    for name in candidates:
        done = git(worktree, "merge", "--no-ff", "-m", f"combined: merge {name} onto {base}", name, check=False, env=IDENTITY)
        if done.returncode != 0:
            files = conflict_files(worktree)
            git(worktree, "merge", "--abort", check=False)
            remove_worktree(repo, worktree)
            where = f"conflicting files: {', '.join(files)}" if files else (done.stderr or done.stdout).strip()
            raise ConfigError(f"merging {name} onto the combined revision failed; {where}; the scratch worktree was removed")
        log.write(f"merged {name}\n")
    return git(worktree, "rev-parse", "HEAD").stdout.strip()


def plan_lines(worktree: Path, base: str, shas: Mapping[str, str], candidates: Sequence[str]) -> list[str]:
    return [
        f"git worktree add --detach {worktree} {shas[base]}   # {base}",
        *(f"git -C {worktree} merge --no-ff -m 'combined: merge {name} onto {base}' {name}   # {shas[name][:7]}"
          for name in candidates),
        f"git -C {worktree} rev-parse HEAD   # printed as the result",
    ]


def build_combined(
    repo: Path, base: str, candidates: Sequence[str], worktree: Path, dry_run: bool, out: TextIO, log: TextIO | None = None,
) -> str | None:
    """Create the combined commit in `worktree` and write its SHA to `out`; with `dry_run`, write the commands and create
    nothing. Returns the SHA, or None for a dry run."""
    log = log or sys.stderr
    shas = validate(repo, base, candidates)
    if dry_run:
        out.write("dry run: nothing is created\n" + "".join(f"{line}\n" for line in plan_lines(worktree, base, shas, candidates)))
        return None
    if worktree.exists():
        raise ConfigError(f"{worktree} exists; remove it with `git worktree remove {worktree}` or pass another --worktree")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--detach", str(worktree), shas[base])
    sha = merge_all(repo, worktree, base, candidates, log)
    out.write(f"{sha}\n")
    return sha
