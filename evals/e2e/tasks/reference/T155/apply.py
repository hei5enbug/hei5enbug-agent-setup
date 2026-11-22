import json
import sys
from pathlib import Path

repo = Path(sys.argv[1])
target = repo / "release-notes-workspace/blind-1/comparison.json"
reasoning = ("Output A lists seven changes, which breaks the stated rule of at most 5 bullets. Output B keeps to five "
             "bullets, keeps the heading, and names the breaking change under Upgrade steps.")
target.write_text(json.dumps({"winner": "B", "reasoning": reasoning}, indent=2) + "\n", encoding="utf-8")
