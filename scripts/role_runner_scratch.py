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


def create_scratch(name: str | None) -> Path:
    """Create the scratch folder: a new random one, or the one a session name fixes, which must not exist with content."""
    if name is None:
        return Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX)).resolve()
    scratch = Path(tempfile.gettempdir()).resolve() / f"{SCRATCH_PREFIX}{name}"
    try:
        scratch.mkdir(mode=0o700, exist_ok=True)
    except OSError as error:
        raise RunnerError(EXIT_RUN, f"Cannot create the scratch folder {scratch}: {error}") from error
    if any(scratch.iterdir()):
        raise RunnerError(EXIT_RUN, f"The scratch folder {scratch} already holds files; another run of this session may be active")
    return scratch


@contextmanager
def scratch_folder(cwd: str, add_dirs: tuple[str, ...], name: str | None = None) -> Iterator[Path]:
    """Create a scratch folder under the system temp folder, yield its resolved path, and remove it on every exit.

    A name fixes the folder's path, so a resumed session starts from the same path as the run it continues."""
    scratch = create_scratch(name)
    try:
        reject_overlap(scratch, cwd, add_dirs)
        for subpath in SCRATCH_VARIABLES.values():
            (scratch / subpath).mkdir(parents=True, exist_ok=True)
        yield scratch
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
