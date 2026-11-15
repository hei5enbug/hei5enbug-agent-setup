from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from role_runner_config import EXIT_RUN, SCRATCH_PREFIX, SCRATCH_VARIABLES, RunnerError


def scratch_environment(scratch: Path) -> dict[str, str]:
    """Return the variables that point every temp folder and tool cache of a child into its scratch folder."""
    return {name: (scratch / subpath).as_posix() for name, subpath in SCRATCH_VARIABLES.items()}


def inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def reject_overlap(scratch: Path, cwd: str, add_dirs: tuple[str, ...]) -> None:
    """Refuse a scratch folder that contains, or lies inside, the working directory or an --add-dir."""
    for directory in (cwd, *add_dirs):
        resolved = Path(directory).resolve()
        if inside(scratch, resolved) or inside(resolved, scratch):
            raise RunnerError(EXIT_RUN, f"The scratch folder {scratch} overlaps {resolved}; set TMPDIR outside the work folders")


@contextmanager
def scratch_folder(cwd: str, add_dirs: tuple[str, ...]) -> Iterator[Path]:
    """Create a new scratch folder under the system temp folder, yield its resolved path, and remove it on every exit."""
    scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX)).resolve()
    try:
        reject_overlap(scratch, cwd, add_dirs)
        for subpath in SCRATCH_VARIABLES.values():
            (scratch / subpath).mkdir(parents=True, exist_ok=True)
        yield scratch
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
