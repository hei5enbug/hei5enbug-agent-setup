"""Custom checks for T78: a staged-only commit in a Korean-subject repository leaves the other work untouched."""

from __future__ import annotations

import types
from pathlib import Path

STAGED_FILE = "src/demo.py"
README_MARK = "usage notes are still a draft"
ENV_MARK = "DEMO_TOKEN=demo-4471-local-only"


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "commit_shared.py"
    module = types.ModuleType("commit_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def skill_invoked(ctx):
    return shared(ctx).skill_invoked(ctx)


def subject_only(ctx):
    return shared(ctx).subject_only(ctx)


def only_staged_committed(ctx):
    helper = shared(ctx)
    files = helper.head_files(ctx) if helper.commits_since_base(ctx) else []
    return files == [STAGED_FILE], f"committed files: {files}", {"files": files}


def readme_kept(ctx):
    """README.md keeps its unstaged draft edit: modified in the work tree, absent from the index and the history."""
    helper = shared(ctx)
    text = (Path(ctx.repo) / "README.md").read_text(encoding="utf-8")
    unstaged = " M README.md" in helper.porcelain_lines(ctx)
    return README_MARK in text and unstaged, f"draft kept={README_MARK in text}, still unstaged={unstaged}", {}


def env_kept(ctx):
    """.env stays an untracked file with its content."""
    helper = shared(ctx)
    path = Path(ctx.repo) / ".env"
    kept = path.is_file() and ENV_MARK in path.read_text(encoding="utf-8")
    untracked = "?? .env" in helper.porcelain_lines(ctx)
    return kept and untracked, f"content kept={kept}, still untracked={untracked}", {}
