"""Copy the static files into build/ and write a manifest. Run from the repository root."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
BUILD = ROOT / "build"


def build() -> dict[str, str]:
    BUILD.mkdir(exist_ok=True)
    manifest: dict[str, str] = {}
    for source in sorted(STATIC.iterdir()):
        target = BUILD / source.name
        shutil.copyfile(source, target)
        manifest[source.name] = hashlib.sha256(target.read_bytes()).hexdigest()[:12]
    (BUILD / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
