"""Build the fake Orca state for T79 beside the notes-cli repository, which plays demo-a's main clone.

`demo-kit` is a fictional plugin repository that declares its tracker and has no agent terminal in its workspace, so
a session that files an issue for it must start one. The work folder also holds the original session's marker and
transcript file, which the delegation rules read, a fake `orca` and a fake `gh` on `fake-bin/`, `orca-state/` with the
state file and the call log, and `gh-state/` with the seeded repositories and its call log.
"""

from __future__ import annotations

import json
import shutil
import stat
import sys
from pathlib import Path

from T21 import git, make_clone, record, with_origin

USER_MESSAGE = "demo-kit 플러그인의 release-notes 스킬이 변경 요약을 빼먹는 문제를 이슈로 등록해 줘."


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_plugin(work: Path) -> Path:
    kit = make_clone(work, "demo-kit")
    write(kit / ".claude-plugin" / "plugin.json", json.dumps({"name": "demo-kit", "version": "1.0.0"}, indent=2) + "\n")
    write(kit / "issue-target.json", json.dumps({
        "version": 1, "tracker": {"kind": "github", "location": "example-org/demo-kit"}, "language": "en",
        "body_format": "markdown", "labels": ["bug"], "public": True, "write_approval": "direct",
    }, indent=2) + "\n")
    write(kit / "skills" / "release-notes" / "SKILL.md",
          "---\nname: release-notes\ndescription: Write release notes from merged changes.\n---\n\n"
          "# Release notes\n\nList each merged change under a heading for its area.\n")
    git(kit, "add", "-A")
    git(kit, "commit", "-q", "-m", "Add the release-notes skill")
    git(kit, "push", "-q", "origin", "main")
    return kit


def main(repo_argument: str) -> None:
    repo = Path(repo_argument).resolve()
    work = repo.parent
    with_origin(repo, work / "demo-a-origin.git")
    kit = build_plugin(work)
    main_a = record("demo-a", repo, "main", "demo-a", True, None, None)
    main_kit = record("demo-kit", kit, "main", "demo-kit", True, None, None)
    state_dir = work / "orca-state"
    state_dir.mkdir()
    state = {
        "repos": [{"id": item["repoId"], "name": item["displayName"], "path": item["path"]} for item in (main_a, main_kit)],
        "worktrees": [main_a, main_kit],
        "terminals": [{"handle": "term_demo_a", "worktreeId": main_a["id"], "title": "zsh"}],
    }
    write(state_dir / "state.json", json.dumps(state, indent=2))
    write(state_dir / "baseline.json", json.dumps({
        "demo-a": git(repo, "rev-parse", "HEAD"), "demo-kit": git(kit, "rev-parse", "HEAD"),
    }, indent=2))

    transcript = work / "original-session.jsonl"
    write(transcript, json.dumps({"type": "user", "message": {"role": "user", "content": USER_MESSAGE}}) + "\n")
    write(work / "orca-user-data" / "hei5enbug-agent-setup" / "terminals" / "term_demo_a.json",
          json.dumps({"transcript_path": str(transcript)}))

    binary = work / "fake-bin"
    binary.mkdir()
    for name, source in (("orca", "fake_orca.py"), ("gh", "fake_gh.py")):
        program = binary / name
        shutil.copy(Path(__file__).with_name(source), program)
        program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    write(work / "gh-state" / "seed.json", json.dumps({"repos": {"example-org/demo-kit": {"issues": []}}}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
