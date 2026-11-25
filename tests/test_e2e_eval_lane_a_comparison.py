"""Offline proofs for the lane A blind comparison task."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "evals/e2e"
TASKS = E2E / "tasks"
sys.path.insert(0, str(E2E))

from harness import graders  # noqa: E402


@pytest.mark.parametrize(("artifact", "expected"), [
    ("unmodified", False), ("seeded-notes", False), ("reference", True),
])
def test_비교_과제는_원본_메모와_근거가_담긴_완성본을_구분한다(tmp_path, artifact, expected):
    """원본을 그대로 옮기면 빠진 측정과 검증하지 않은 제안이 걸리고 참조 보고서는 통과한다."""
    # given
    task = graders.load_task(TASKS, "T193")
    repo = tmp_path / "repo"
    base = graders.materialize_fixture(task, E2E / "fixtures", TASKS, repo)
    if artifact == "reference":
        subprocess.run([sys.executable, "-B", str(TASKS / "reference/T193/apply.py"), str(repo)],
                       env={**os.environ, "PYTHONPATH": str(TASKS / "reference")}, check=True)
    if artifact == "seeded-notes":
        (repo / "out").mkdir()
        (repo / "out/report.md").write_bytes((repo / "notes/field-notes.md").read_bytes())

    # when
    result = graders.grade_run(task, repo, base, {}, TASKS, tmp_path / "grade/work")

    # then
    assert result["success"] == expected, result["checks"]
    if artifact == "seeded-notes":
        checks = {check["id"]: check["passed"] for check in result["checks"]}
        assert checks["options-and-measures-present"]
        assert not checks["stage-titles-and-timings-present"]
        assert not checks["seeded-exclusions-absent"]
