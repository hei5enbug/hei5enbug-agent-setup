from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath


DEFAULT_MANIFEST = Path(__file__).with_name("source-fixture.json")


def _safe_relative_path(value: str) -> Path:
    posix_path = PurePosixPath(value)
    if posix_path.is_absolute() or not posix_path.parts or ".." in posix_path.parts:
        raise ValueError(f"unsafe fixture path: {value}")
    return Path(*posix_path.parts)


def materialize(source_checkout: Path, output: Path, manifest_path: Path) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    revision = manifest["source_revision"]
    entries = manifest["files"]
    mandatory_count = manifest["mandatory_file_count"]
    conditional_count = manifest["conditional_test_count"]
    roles = [entry["role"] for entry in entries]
    if roles.count("mandatory") != mandatory_count or roles.count("conditional") != conditional_count:
        raise ValueError("fixture manifest file counts do not match its entries")

    checkout = source_checkout.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    if output == checkout or checkout in output.parents:
        raise ValueError("output must be outside the upstream checkout")
    repository_root = Path(__file__).resolve().parents[3]
    if output == repository_root or repository_root in output.parents:
        raise ValueError("output must be outside the repository")

    actual_revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual_revision != revision:
        raise ValueError(f"expected source revision {revision}, found {actual_revision}")

    paths = [_safe_relative_path(entry["path"]) for entry in entries]
    if len(paths) != len(set(paths)):
        raise ValueError("fixture manifest contains duplicate paths")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".omo-source-", dir=output.parent))
    try:
        for entry, relative_path in zip(entries, paths):
            source = checkout / relative_path
            if source.is_symlink() or not source.is_file():
                raise FileNotFoundError(f"missing regular source file: {entry['path']}")
            content = source.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != entry["sha256"]:
                raise ValueError(f"source hash mismatch: {entry['path']}")
            destination = staging / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy and verify the pinned OmO source subset into a temporary workspace."
    )
    parser.add_argument("--source-checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    output = materialize(args.source_checkout, args.output, args.manifest)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
