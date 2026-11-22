"""Write the seeded documents and the review wrapper into the repository, the scripted review beside it, and commit."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
WRAPPER = '''"""Run the project review: `python3 tools/review.py` prints one line per finding and exits 1 when there are any."""
import os
import runpy

runpy.run_path(os.path.join(os.environ["REVIEW_STATE_DIR"], "review_script.py"), run_name="__main__")
'''


def install(repo: Path, documents: dict[str, str]) -> None:
    state = repo.parent / "review-state"
    state.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "review_loop_script.py", state / "review_script.py")
    shutil.copy(HERE / "review_loop_common.py", state / "review_loop_common.py")
    for relative, text in {**documents, "tools/review.py": WRAPPER}.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for command in (["add", "-A"], ["commit", "-q", "-m", "Add the review loop documents"]):
        subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *command], cwd=repo,
                       check=True, capture_output=True)
