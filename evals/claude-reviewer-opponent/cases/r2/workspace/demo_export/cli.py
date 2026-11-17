"""Command line wrapper: prints the CSV report of a JSON file of rows."""

from __future__ import annotations

import json
import sys

from demo_export import export_report


def main(path: str) -> None:
    with open(path, encoding="utf-8") as source:
        rows = json.load(source)
    text = export_report(rows)
    sys.stdout.write(text)


if __name__ == "__main__":
    main(sys.argv[1])
