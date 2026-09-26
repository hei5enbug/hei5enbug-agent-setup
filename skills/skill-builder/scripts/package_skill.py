#!/usr/bin/env python3
"""
Skill Packager - Creates a distributable .skill file of a skill folder

Usage:
    python -m scripts.package_skill <path/to/skill-folder> [output-directory] [--check-installed]

Example:
    python -m scripts.package_skill skills/public/my-skill
    python -m scripts.package_skill skills/public/my-skill ./dist --check-installed
"""

import argparse
import fnmatch
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.quick_validate import (
    MissingDependencyError,
    check_status,
    run_bundled_checks,
    validate_skill,
)

# Patterns to exclude when packaging skills.
EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git"}
EXCLUDE_GLOBS = {"*.pyc", "*.skill", ".env.*"}
EXCLUDE_FILES = {".DS_Store", ".env"}
# Directories excluded only at the skill root (not when nested deeper).
ROOT_EXCLUDE_DIRS = {"evals", ".eval-runs"}
ROOT_EXCLUDE_DIR_GLOBS = {"*-workspace"}


def should_exclude(rel_path: Path) -> bool:
    """Check if a path (relative to the skill's parent) should be excluded from packaging."""
    parts = rel_path.parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    # rel_path is relative to skill_path.parent, so parts[0] is the skill
    # folder name and parts[1] (if present) is the first subdir.
    if len(parts) > 1:
        first = parts[1]
        if first in ROOT_EXCLUDE_DIRS:
            return True
        if len(parts) > 2 and any(fnmatch.fnmatch(first, pat) for pat in ROOT_EXCLUDE_DIR_GLOBS):
            return True
    name = rel_path.name
    if name in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_GLOBS)


def collect_files(skill_path: Path) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Return ([(arcname, absolute_path)], warnings) for everything that ships.

    Symbolic links are never followed or packaged; each one is reported.
    """
    skill_path = Path(skill_path).resolve()
    files: list[tuple[Path, Path]] = []
    warnings: list[str] = []
    for dirpath, dirnames, filenames in os.walk(skill_path, followlinks=False):
        current = Path(dirpath)
        kept_dirs = []
        for dirname in sorted(dirnames):
            candidate = current / dirname
            arcname = candidate.relative_to(skill_path.parent)
            if candidate.is_symlink():
                warnings.append(f"Skipped symbolic link: {arcname}")
                continue
            if should_exclude(arcname / "_"):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            candidate = current / filename
            arcname = candidate.relative_to(skill_path.parent)
            if candidate.is_symlink():
                warnings.append(f"Skipped symbolic link: {arcname}")
                continue
            if should_exclude(arcname):
                continue
            files.append((arcname, candidate))
    return files, warnings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_installed_copies(skill_name, source_path, files):
    """Locate other installed copies of this skill on the host.

    Roots come from SKILL_BUILDER_SKILL_ROOTS when set, so no installation
    layout is assumed. Otherwise agent-host skill directories are discovered
    by shape under the home directory rather than by product name.

    A copy is stale when any packaged file is missing or differs by SHA-256.
    """
    roots_env = os.environ.get("SKILL_BUILDER_SKILL_ROOTS", "").strip()
    candidates = []
    if roots_env:
        for root in roots_env.split(os.pathsep):
            if root.strip():
                candidates.append(Path(root.strip()).expanduser() / skill_name)
    else:
        home = Path.home()
        for pattern in (f".*/skills/{skill_name}", f".*/*/skills/{skill_name}"):
            candidates.extend(home.glob(pattern))

    source_path = Path(source_path).resolve()
    expected = {
        arcname.relative_to(arcname.parts[0]): _sha256(absolute)
        for arcname, absolute in files
    }
    copies = []
    for candidate in sorted({c.resolve() for c in candidates}):
        if candidate == source_path or not (candidate / "SKILL.md").is_file():
            continue
        stale = False
        for rel_path, digest in expected.items():
            target = candidate / rel_path
            if not target.is_file() or _sha256(target) != digest:
                stale = True
                break
        copies.append((candidate, stale))
    return copies


def package_skill(skill_path, output_dir=None, check_installed=False):
    """
    Package a skill folder into a .skill file.

    Args:
        skill_path: Path to the skill folder
        output_dir: Optional output directory for the .skill file (defaults to current directory)
        check_installed: Compare other installed copies of the skill after packaging

    Returns:
        Path to the created .skill file, or None if error
    """
    skill_path = Path(skill_path).resolve()

    # Validate skill folder exists
    if not skill_path.exists():
        print(f"❌ Error: Skill folder not found: {skill_path}")
        return None

    if not skill_path.is_dir():
        print(f"❌ Error: Path is not a directory: {skill_path}")
        return None

    # Validate SKILL.md exists
    skill_md = skill_path / "SKILL.md"
    if not skill_md.is_file() or skill_md.is_symlink():
        print(f"❌ Error: SKILL.md must be a regular, non-symlink file in {skill_path}")
        return None

    # Determine output location before doing any work
    skill_name = skill_path.name
    if output_dir:
        output_path = Path(output_dir).resolve()
    else:
        output_path = Path.cwd().resolve()
    skill_filename = output_path / f"{skill_name}.skill"
    if skill_filename.is_relative_to(skill_path):
        print(f"❌ Error: Output location {skill_filename} is inside the skill folder. Choose a directory outside {skill_path}.")
        return None

    # Run validation before packaging
    print("🔍 Validating skill...")
    try:
        valid, message = validate_skill(skill_path)
    except MissingDependencyError as exc:
        print(f"❌ Error: {exc}")
        return None
    if not valid:
        print(f"❌ Validation failed: {message}")
        print("   Please fix the validation errors before packaging.")
        return None
    print(f"✅ {message}\n")

    # Run detectors bundled with the skill
    checks_ok, results = run_bundled_checks(skill_path)
    for name, returncode, output in results:
        print(f"  [{check_status(returncode)}] {name}")
        if output:
            print(output)
    if not checks_ok:
        print("❌ Bundled checks failed. Resolve the findings before packaging.")
        return None
    if results:
        print()

    files, warnings = collect_files(skill_path)
    for warning in warnings:
        print(f"  ⚠️  {warning}")

    # Build beside the destination and publish only a verified complete archive.
    temporary_name = None
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=output_path,
            prefix=f".{skill_name}.",
            suffix=".skill.tmp",
        )
        os.close(descriptor)
        with zipfile.ZipFile(temporary_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for arcname, file_path in files:
                zipf.write(file_path, arcname)
                print(f"  Added: {arcname}")

        expected_names = [arcname.as_posix() for arcname, _ in files]
        with zipfile.ZipFile(temporary_name, 'r') as zipf:
            bad_file = zipf.testzip()
            if bad_file is not None:
                raise OSError(f"Archive CRC check failed for {bad_file}")
            if zipf.namelist() != expected_names:
                raise OSError("Archive contents differ from the collected file list")
        os.replace(temporary_name, skill_filename)
        temporary_name = None

        print(f"\n✅ Successfully packaged skill to: {skill_filename}")

        if check_installed:
            copies = find_installed_copies(skill_name, skill_path, files)
            if copies:
                print("\n📍 Other installed copies of this skill:")
                for path, stale in copies:
                    print(f"  [{'stale' if stale else 'same'}] {path}")
                if any(stale for _, stale in copies):
                    print("  Confirm with the user before syncing the stale copies.")
            else:
                print("\n📍 No other installed copies found.")

        return skill_filename

    except Exception as e:
        print(f"❌ Error creating .skill file: {e}")
        return None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def main():
    parser = argparse.ArgumentParser(description="Package a skill folder into a .skill file")
    parser.add_argument("skill_path", help="Path to the skill folder")
    parser.add_argument("output_dir", nargs="?", default=None, help="Directory for the .skill file (default: current directory)")
    parser.add_argument(
        "--check-installed",
        action="store_true",
        help="After packaging, look for other installed copies of the skill and report whether they are stale",
    )
    args = parser.parse_args()

    print(f"📦 Packaging skill: {args.skill_path}")
    if args.output_dir:
        print(f"   Output directory: {args.output_dir}")
    print()

    result = package_skill(args.skill_path, args.output_dir, check_installed=args.check_installed)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
