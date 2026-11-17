"""Read the build folder and report what the build should have written and did not."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dockit.pages import load_pages  # noqa: E402

NAMESPACE = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def problems(build_dir: Path, content_dir: Path) -> list[str]:
    found = []
    for page in load_pages(content_dir):
        if not (build_dir / f"{page.slug}.html").is_file():
            found.append(f"missing {page.slug}.html")
    try:
        tree = ET.parse(build_dir / "sitemap.xml")
    except (OSError, ET.ParseError) as error:
        found.append(f"sitemap.xml is unreadable: {error}")
    else:
        for loc in tree.getroot().findall("s:url/s:loc", NAMESPACE):
            name = (loc.text or "").rsplit("/", 1)[-1]
            if not (build_dir / name).is_file():
                found.append(f"sitemap.xml lists {name}, which was not built")
    try:
        index = json.loads((build_dir / "search-index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        found.append(f"search-index.json is unreadable: {error}")
    else:
        for entry in index:
            if not (build_dir / str(entry.get("url", "")).lstrip("/")).is_file():
                found.append(f"search-index.json lists {entry.get('url')}, which was not built")
    return found


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    build_dir = Path(arguments[0]) if arguments else ROOT / "build"
    found = problems(build_dir, ROOT / "content")
    for line in found:
        print(line)
    print("site check passed" if not found else f"{len(found)} problem(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
